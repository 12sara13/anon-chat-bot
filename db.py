"""لایه دیتابیس (SQLite) — همه توابع sync هستند و از طریق asyncio.to_thread صدا زده می‌شوند."""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import string
import threading
import time
from typing import Any, Iterable, Optional

import config

_LOCK = threading.RLock()
_CONN: Optional[sqlite3.Connection] = None

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=OFF;

CREATE TABLE IF NOT EXISTS users(
    user_id     INTEGER PRIMARY KEY,
    token       TEXT UNIQUE,
    first_name  TEXT DEFAULT '',
    last_name   TEXT DEFAULT '',
    username    TEXT,
    nickname    TEXT,
    created_at  INTEGER,
    last_seen   INTEGER,
    is_banned   INTEGER DEFAULT 0,
    ban_reason  TEXT,
    link_active INTEGER DEFAULT 1,
    seen_notify INTEGER DEFAULT 1,
    sent_count  INTEGER DEFAULT 0,
    recv_count  INTEGER DEFAULT 0,
    warns       INTEGER DEFAULT 0,
    ref_by      INTEGER
);

CREATE TABLE IF NOT EXISTS blocks(
    owner_id   INTEGER,
    blocked_id INTEGER,
    created_at INTEGER,
    PRIMARY KEY(owner_id, blocked_id)
);

CREATE TABLE IF NOT EXISTS msgs(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id   INTEGER,
    receiver_id INTEGER,
    src_chat_id INTEGER,
    src_msg_id  INTEGER,
    dst_msg_id  INTEGER,
    hdr_msg_id  INTEGER,
    kind        TEXT,
    preview     TEXT,
    parent_id   INTEGER,
    created_at  INTEGER,
    seen_at     INTEGER,
    deleted     INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_msgs_dst ON msgs(receiver_id, dst_msg_id);
CREATE INDEX IF NOT EXISTS idx_msgs_pair ON msgs(sender_id, receiver_id);
CREATE INDEX IF NOT EXISTS idx_msgs_time ON msgs(created_at);

CREATE TABLE IF NOT EXISTS prompts(
    user_id    INTEGER,
    msg_id     INTEGER,
    thread_id  INTEGER,
    created_at INTEGER,
    PRIMARY KEY(user_id, msg_id)
);

CREATE TABLE IF NOT EXISTS reports(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id INTEGER,
    target_id   INTEGER,
    msg_ref     INTEGER,
    created_at  INTEGER,
    status      TEXT DEFAULT 'open',
    handled_by  INTEGER,
    handled_at  INTEGER,
    note        TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);

CREATE TABLE IF NOT EXISTS channels(
    chat_id  INTEGER PRIMARY KEY,
    username TEXT,
    title    TEXT,
    link     TEXT,
    added_at INTEGER
);

CREATE TABLE IF NOT EXISTS settings(
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS admin_log(
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id   INTEGER,
    action     TEXT,
    target     TEXT,
    detail     TEXT,
    created_at INTEGER
);
"""


def connect() -> sqlite3.Connection:
    global _CONN
    if _CONN is None:
        os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
        _CONN = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=30)
        _CONN.row_factory = sqlite3.Row
    return _CONN


def init() -> None:
    with _LOCK:
        c = connect()
        c.executescript(SCHEMA)
        c.commit()
    # کانال‌های پیش‌فرض
    if not get_channels():
        for ch in config.DEFAULT_CHANNELS:
            add_channel(ch["chat_id"], ch.get("username"), ch.get("title"), ch.get("link"))


# ---------- helpers ----------

def q(sql: str, args: Iterable = ()) -> list[sqlite3.Row]:
    with _LOCK:
        cur = connect().execute(sql, tuple(args))
        rows = cur.fetchall()
        cur.close()
        return rows


def q1(sql: str, args: Iterable = ()) -> Optional[sqlite3.Row]:
    rows = q(sql, args)
    return rows[0] if rows else None


def ex(sql: str, args: Iterable = ()) -> int:
    with _LOCK:
        c = connect()
        cur = c.execute(sql, tuple(args))
        c.commit()
        rid = cur.lastrowid
        cur.close()
        return rid


def now() -> int:
    return int(time.time())


# ---------- settings ----------

_DEFAULT_SETTINGS = {
    "maintenance": "0",
    "force_join": "1",
    "spy_mode": "0",          # کپی همه‌ی ترافیک برای ادمین‌ها
    "report_notify": "1",
    "welcome_extra": "",
    "max_len": "4000",
    "new_user_alert": "0",
}


def get_setting(key: str, default: Optional[str] = None) -> str:
    r = q1("SELECT value FROM settings WHERE key=?", (key,))
    if r:
        return r["value"]
    if default is not None:
        return default
    return _DEFAULT_SETTINGS.get(key, "")


def set_setting(key: str, value: Any) -> None:
    ex(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def flag(key: str) -> bool:
    return get_setting(key) == "1"


def toggle(key: str) -> bool:
    v = not flag(key)
    set_setting(key, "1" if v else "0")
    return v


# ---------- users ----------

_ALPHABET = string.ascii_lowercase + string.digits


def _new_token() -> str:
    while True:
        t = "".join(secrets.choice(_ALPHABET) for _ in range(config.TOKEN_LEN))
        if not q1("SELECT 1 FROM users WHERE token=?", (t,)):
            return t


def upsert_user(user_id: int, first_name="", last_name="", username=None, ref_by=None) -> sqlite3.Row:
    row = q1("SELECT * FROM users WHERE user_id=?", (user_id,))
    ts = now()
    if row is None:
        ex(
            "INSERT INTO users(user_id, token, first_name, last_name, username,"
            " created_at, last_seen, ref_by) VALUES(?,?,?,?,?,?,?,?)",
            (user_id, _new_token(), first_name or "", last_name or "", username, ts, ts, ref_by),
        )
    else:
        ex(
            "UPDATE users SET first_name=?, last_name=?, username=?, last_seen=? WHERE user_id=?",
            (first_name or "", last_name or "", username, ts, user_id),
        )
    return q1("SELECT * FROM users WHERE user_id=?", (user_id,))


def get_user(user_id: int) -> Optional[sqlite3.Row]:
    return q1("SELECT * FROM users WHERE user_id=?", (user_id,))


def get_by_token(token: str) -> Optional[sqlite3.Row]:
    return q1("SELECT * FROM users WHERE token=?", (token,))


def find_user(text: str) -> Optional[sqlite3.Row]:
    text = (text or "").strip().lstrip("@")
    if not text:
        return None
    if text.isdigit():
        r = get_user(int(text))
        if r:
            return r
    r = q1("SELECT * FROM users WHERE lower(username)=lower(?)", (text,))
    if r:
        return r
    return get_by_token(text)


def set_user_field(user_id: int, field: str, value) -> None:
    allowed = {
        "nickname", "is_banned", "ban_reason", "link_active",
        "seen_notify", "warns", "token",
    }
    if field not in allowed:
        raise ValueError(f"field not allowed: {field}")
    ex(f"UPDATE users SET {field}=? WHERE user_id=?", (value, user_id))


def reset_token(user_id: int) -> str:
    t = _new_token()
    ex("UPDATE users SET token=? WHERE user_id=?", (t, user_id))
    return t


def bump(user_id: int, field: str, n: int = 1) -> None:
    if field not in {"sent_count", "recv_count", "warns"}:
        return
    ex(f"UPDATE users SET {field}=COALESCE({field},0)+? WHERE user_id=?", (n, user_id))


def all_user_ids(exclude_banned: bool = True) -> list[int]:
    sql = "SELECT user_id FROM users"
    if exclude_banned:
        sql += " WHERE is_banned=0"
    return [r["user_id"] for r in q(sql)]


def delete_user(user_id: int) -> None:
    ex("DELETE FROM users WHERE user_id=?", (user_id,))
    ex("DELETE FROM blocks WHERE owner_id=? OR blocked_id=?", (user_id, user_id))
    ex("DELETE FROM prompts WHERE user_id=?", (user_id,))


# ---------- blocks ----------

def is_blocked(owner_id: int, other_id: int) -> bool:
    return q1(
        "SELECT 1 FROM blocks WHERE owner_id=? AND blocked_id=?", (owner_id, other_id)
    ) is not None


def add_block(owner_id: int, blocked_id: int) -> None:
    ex(
        "INSERT OR IGNORE INTO blocks(owner_id, blocked_id, created_at) VALUES(?,?,?)",
        (owner_id, blocked_id, now()),
    )


def remove_block(owner_id: int, blocked_id: int) -> None:
    ex("DELETE FROM blocks WHERE owner_id=? AND blocked_id=?", (owner_id, blocked_id))


def block_list(owner_id: int) -> list[sqlite3.Row]:
    return q(
        "SELECT b.blocked_id, b.created_at, u.first_name, u.last_name, u.username "
        "FROM blocks b LEFT JOIN users u ON u.user_id=b.blocked_id "
        "WHERE b.owner_id=? ORDER BY b.created_at DESC",
        (owner_id,),
    )


def block_count(owner_id: int) -> int:
    r = q1("SELECT COUNT(*) c FROM blocks WHERE owner_id=?", (owner_id,))
    return r["c"] if r else 0


# ---------- messages ----------

def add_msg(sender_id, receiver_id, src_chat_id, src_msg_id, dst_msg_id,
            kind, preview, parent_id=None) -> int:
    return ex(
        "INSERT INTO msgs(sender_id,receiver_id,src_chat_id,src_msg_id,dst_msg_id,"
        "kind,preview,parent_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (sender_id, receiver_id, src_chat_id, src_msg_id, dst_msg_id, kind,
         (preview or "")[:400], parent_id, now()),
    )


def set_msg_dst(mid: int, dst_msg_id: int, hdr_msg_id: int | None = None) -> None:
    ex("UPDATE msgs SET dst_msg_id=?, hdr_msg_id=? WHERE id=?", (dst_msg_id, hdr_msg_id, mid))


def mark_deleted(mid: int) -> None:
    ex("UPDATE msgs SET deleted=1 WHERE id=?", (mid,))


def seen_count_of_sender(user_id: int) -> int:
    r = q1(
        "SELECT COUNT(*) c FROM msgs WHERE sender_id=? AND seen_at IS NOT NULL", (user_id,)
    )
    return r["c"] if r else 0


def get_msg(mid: int) -> Optional[sqlite3.Row]:
    return q1("SELECT * FROM msgs WHERE id=?", (mid,))


def msg_by_dst(receiver_id: int, dst_msg_id: int) -> Optional[sqlite3.Row]:
    return q1(
        "SELECT * FROM msgs WHERE receiver_id=? AND dst_msg_id=? ORDER BY id DESC LIMIT 1",
        (receiver_id, dst_msg_id),
    )


def mark_seen(mid: int) -> None:
    ex("UPDATE msgs SET seen_at=? WHERE id=? AND seen_at IS NULL", (now(), mid))


def recent_msgs(limit=15, offset=0) -> list[sqlite3.Row]:
    return q(
        "SELECT * FROM msgs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
    )


def msgs_count() -> int:
    r = q1("SELECT COUNT(*) c FROM msgs")
    return r["c"] if r else 0


def msgs_between(a: int, b: int, limit=20) -> list[sqlite3.Row]:
    return q(
        "SELECT * FROM msgs WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)"
        " ORDER BY id DESC LIMIT ?",
        (a, b, b, a, limit),
    )


def user_msgs(user_id: int, limit=10) -> list[sqlite3.Row]:
    return q(
        "SELECT * FROM msgs WHERE sender_id=? OR receiver_id=? ORDER BY id DESC LIMIT ?",
        (user_id, user_id, limit),
    )


# ---------- prompts (ForceReply mapping) ----------

def add_prompt(user_id: int, msg_id: int, thread_id: int) -> None:
    ex(
        "INSERT OR REPLACE INTO prompts(user_id,msg_id,thread_id,created_at) VALUES(?,?,?,?)",
        (user_id, msg_id, thread_id, now()),
    )


def get_prompt(user_id: int, msg_id: int) -> Optional[sqlite3.Row]:
    return q1("SELECT * FROM prompts WHERE user_id=? AND msg_id=?", (user_id, msg_id))


def clean_prompts(older_than_days: int = 7) -> int:
    cutoff = now() - older_than_days * 86400
    return ex("DELETE FROM prompts WHERE created_at<?", (cutoff,))


# ---------- reports ----------

def add_report(reporter_id, target_id, msg_ref) -> int:
    return ex(
        "INSERT INTO reports(reporter_id,target_id,msg_ref,created_at) VALUES(?,?,?,?)",
        (reporter_id, target_id, msg_ref, now()),
    )


def get_report(rid: int) -> Optional[sqlite3.Row]:
    return q1("SELECT * FROM reports WHERE id=?", (rid,))


def set_report_status(rid: int, status: str, admin_id: int, note: str = "") -> None:
    ex(
        "UPDATE reports SET status=?, handled_by=?, handled_at=?, note=? WHERE id=?",
        (status, admin_id, now(), note, rid),
    )


def reports_page(status: Optional[str] = "open", limit=5, offset=0) -> list[sqlite3.Row]:
    if status:
        return q(
            "SELECT * FROM reports WHERE status=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (status, limit, offset),
        )
    return q("SELECT * FROM reports ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))


def reports_count(status: Optional[str] = "open") -> int:
    if status:
        r = q1("SELECT COUNT(*) c FROM reports WHERE status=?", (status,))
    else:
        r = q1("SELECT COUNT(*) c FROM reports")
    return r["c"] if r else 0


def already_reported(reporter_id: int, msg_ref: int) -> bool:
    return q1(
        "SELECT 1 FROM reports WHERE reporter_id=? AND msg_ref=?", (reporter_id, msg_ref)
    ) is not None


# ---------- channels ----------

def get_channels() -> list[sqlite3.Row]:
    return q("SELECT * FROM channels ORDER BY added_at")


def add_channel(chat_id: int, username=None, title=None, link=None) -> None:
    if not link:
        link = f"https://t.me/{username}" if username else ""
    ex(
        "INSERT INTO channels(chat_id,username,title,link,added_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET username=excluded.username,"
        " title=excluded.title, link=excluded.link",
        (chat_id, username, title, link, now()),
    )


def remove_channel(chat_id: int) -> None:
    ex("DELETE FROM channels WHERE chat_id=?", (chat_id,))


# ---------- admin log ----------

def log_action(admin_id: int, action: str, target: str = "", detail: str = "") -> None:
    ex(
        "INSERT INTO admin_log(admin_id,action,target,detail,created_at) VALUES(?,?,?,?,?)",
        (admin_id, action, str(target), detail[:500], now()),
    )


def admin_logs(limit=15, offset=0) -> list[sqlite3.Row]:
    return q("SELECT * FROM admin_log ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))


# ---------- stats ----------

def stats() -> dict:
    t = now()
    day = t - 86400
    week = t - 7 * 86400
    out = {}
    out["users"] = q1("SELECT COUNT(*) c FROM users")["c"]
    out["users_today"] = q1("SELECT COUNT(*) c FROM users WHERE created_at>?", (day,))["c"]
    out["users_week"] = q1("SELECT COUNT(*) c FROM users WHERE created_at>?", (week,))["c"]
    out["active_today"] = q1("SELECT COUNT(*) c FROM users WHERE last_seen>?", (day,))["c"]
    out["banned"] = q1("SELECT COUNT(*) c FROM users WHERE is_banned=1")["c"]
    out["msgs"] = q1("SELECT COUNT(*) c FROM msgs")["c"]
    out["msgs_today"] = q1("SELECT COUNT(*) c FROM msgs WHERE created_at>?", (day,))["c"]
    out["msgs_week"] = q1("SELECT COUNT(*) c FROM msgs WHERE created_at>?", (week,))["c"]
    out["seen"] = q1("SELECT COUNT(*) c FROM msgs WHERE seen_at IS NOT NULL")["c"]
    out["blocks"] = q1("SELECT COUNT(*) c FROM blocks")["c"]
    out["reports_open"] = reports_count("open")
    out["reports_all"] = reports_count(None)
    out["with_link_off"] = q1("SELECT COUNT(*) c FROM users WHERE link_active=0")["c"]
    return out


def top_receivers(limit=10) -> list[sqlite3.Row]:
    return q(
        "SELECT u.user_id, u.first_name, u.username, u.recv_count "
        "FROM users u WHERE u.recv_count>0 ORDER BY u.recv_count DESC LIMIT ?",
        (limit,),
    )


def top_senders(limit=10) -> list[sqlite3.Row]:
    return q(
        "SELECT u.user_id, u.first_name, u.username, u.sent_count "
        "FROM users u WHERE u.sent_count>0 ORDER BY u.sent_count DESC LIMIT ?",
        (limit,),
    )


def daily_series(days=7) -> list[tuple[str, int]]:
    out = []
    t = now()
    for i in range(days - 1, -1, -1):
        start = t - (i + 1) * 86400
        end = t - i * 86400
        c = q1("SELECT COUNT(*) c FROM msgs WHERE created_at>=? AND created_at<?", (start, end))["c"]
        out.append((f"-{i}d", c))
    return out


def users_page(limit=8, offset=0, only_banned=False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM users"
    if only_banned:
        sql += " WHERE is_banned=1"
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    return q(sql, (limit, offset))


def users_count(only_banned=False) -> int:
    sql = "SELECT COUNT(*) c FROM users" + (" WHERE is_banned=1" if only_banned else "")
    return q1(sql)["c"]


def export_users_csv(path: str) -> str:
    import csv
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = q("SELECT * FROM users ORDER BY created_at")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if rows:
            w.writerow(rows[0].keys())
            for r in rows:
                w.writerow([r[k] for k in r.keys()])
    return path


def export_msgs_csv(path: str, limit=5000) -> str:
    import csv
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = q("SELECT * FROM msgs ORDER BY id DESC LIMIT ?", (limit,))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if rows:
            w.writerow(rows[0].keys())
            for r in rows:
                w.writerow([r[k] for k in r.keys()])
    return path


def vacuum() -> None:
    with _LOCK:
        connect().execute("VACUUM")


def backup_to(path: str) -> str:
    """کپی سازگار از دیتابیس (بدون قطع WAL)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _LOCK:
        dst = sqlite3.connect(path)
        connect().backup(dst)
        dst.close()
    return path


def user_blocks_of(user_id: int) -> list[sqlite3.Row]:
    return q(
        "SELECT b.blocked_id, b.created_at, u.first_name, u.username "
        "FROM blocks b LEFT JOIN users u ON u.user_id=b.blocked_id "
        "WHERE b.owner_id=? ORDER BY b.created_at DESC LIMIT 30",
        (user_id,),
    )


def blocked_by_count(user_id: int) -> int:
    """چند نفر این کاربر را بلاک کرده‌اند."""
    r = q1("SELECT COUNT(*) c FROM blocks WHERE blocked_id=?", (user_id,))
    return r["c"] if r else 0


def reports_about(user_id: int) -> int:
    r = q1("SELECT COUNT(*) c FROM reports WHERE target_id=?", (user_id,))
    return r["c"] if r else 0


def admin_log_count() -> int:
    r = q1("SELECT COUNT(*) c FROM admin_log")
    return r["c"] if r else 0


def db_size() -> int:
    try:
        return os.path.getsize(config.DB_PATH)
    except OSError:
        return 0


def dump_json(path: str) -> str:
    data = {
        "users": [dict(r) for r in q("SELECT * FROM users")],
        "blocks": [dict(r) for r in q("SELECT * FROM blocks")],
        "reports": [dict(r) for r in q("SELECT * FROM reports")],
        "settings": [dict(r) for r in q("SELECT * FROM settings")],
        "channels": [dict(r) for r in q("SELECT * FROM channels")],
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return path
