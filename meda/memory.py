"""Long-term memory for the crew, stored in one SQLite file.

Everything the agents remember lives here: facts about you, tasks and the
academic schedule, job applications, mood check-ins, token usage, and each
agent's conversation room.
"""

import json
import sqlite3
import threading
import time
from datetime import datetime

from . import config

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY, text TEXT NOT NULL, topic TEXT DEFAULT 'general',
    saved_by TEXT, created TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, kind TEXT DEFAULT 'task',
    due TEXT, done INTEGER DEFAULT 0, created TEXT
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY, company TEXT NOT NULL, role TEXT, status TEXT DEFAULT 'planned',
    link TEXT, notes TEXT, updated TEXT
);
CREATE TABLE IF NOT EXISTS moods (
    id INTEGER PRIMARY KEY, mood TEXT NOT NULL, score INTEGER, note TEXT, created TEXT
);
CREATE TABLE IF NOT EXISTS rooms (
    agent TEXT PRIMARY KEY, messages TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY, agent TEXT, ts REAL, input_tokens INTEGER,
    output_tokens INTEGER, cost REAL
);
CREATE TABLE IF NOT EXISTS cooldowns (
    agent TEXT PRIMARY KEY, until REAL, reason TEXT
);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="minutes")


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


_conn = None


def db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = connect()
    return _conn


def _run(sql: str, args: tuple = ()) -> list[dict]:
    with _lock:
        cur = db().execute(sql, args)
        db().commit()
        return [dict(r) for r in cur.fetchall()]


def _change(sql: str, args: tuple) -> int:
    """Run an UPDATE or DELETE and return how many rows it touched."""
    with _lock:
        cur = db().execute(sql, args)
        db().commit()
        return cur.rowcount


def _insert(sql: str, args: tuple) -> int:
    with _lock:
        cur = db().execute(sql, args)
        db().commit()
        return cur.lastrowid


# ---------- facts ----------

def remember(text: str, topic: str = "general", saved_by: str = "") -> int:
    return _insert("INSERT INTO facts (text, topic, saved_by, created) VALUES (?, ?, ?, ?)",
                   (text, topic, saved_by, _now()))


def recall(query: str = "", limit: int = 20) -> list[dict]:
    if not query:
        return _run("SELECT * FROM facts ORDER BY id DESC LIMIT ?", (limit,))
    words = [w for w in query.lower().split() if len(w) > 2] or [query.lower()]
    clause = " OR ".join("lower(text) LIKE ? OR lower(topic) LIKE ?" for _ in words)
    args = tuple(a for w in words for a in (f"%{w}%", f"%{w}%"))
    return _run(f"SELECT * FROM facts WHERE {clause} ORDER BY id DESC LIMIT ?", args + (limit,))


def forget(fact_id: int) -> bool:
    return _change("DELETE FROM facts WHERE id = ?", (fact_id,)) > 0


# ---------- tasks and schedule ----------

def add_task(title: str, kind: str = "task", due: str = "") -> int:
    return _insert("INSERT INTO tasks (title, kind, due, created) VALUES (?, ?, ?, ?)",
                   (title, kind, due, _now()))


def list_tasks(include_done: bool = False) -> list[dict]:
    where = "" if include_done else "WHERE done = 0"
    return _run(f"SELECT * FROM tasks {where} ORDER BY due IS NULL OR due = '', due, id")


def complete_task(task_id: int) -> bool:
    return _change("UPDATE tasks SET done = 1 WHERE id = ?", (task_id,)) > 0


# ---------- job applications ----------

def save_application(company: str, role: str = "", status: str = "planned",
                     link: str = "", notes: str = "", app_id: int | None = None) -> int:
    if app_id:
        _run("UPDATE applications SET company=?, role=?, status=?, link=?, notes=?, updated=? WHERE id=?",
             (company, role, status, link, notes, _now(), app_id))
        return app_id
    return _insert("INSERT INTO applications (company, role, status, link, notes, updated) VALUES (?, ?, ?, ?, ?, ?)",
                   (company, role, status, link, notes, _now()))


def list_applications() -> list[dict]:
    return _run("SELECT * FROM applications ORDER BY updated DESC")


# ---------- moods ----------

def log_mood(mood: str, score: int | None = None, note: str = "") -> int:
    return _insert("INSERT INTO moods (mood, score, note, created) VALUES (?, ?, ?, ?)",
                   (mood, score, note, _now()))


def mood_history(limit: int = 14) -> list[dict]:
    return _run("SELECT * FROM moods ORDER BY id DESC LIMIT ?", (limit,))


# ---------- conversation rooms ----------

def load_room(agent: str) -> list[dict]:
    rows = _run("SELECT messages FROM rooms WHERE agent = ?", (agent,))
    return json.loads(rows[0]["messages"]) if rows else []


def save_room(agent: str, messages: list[dict]) -> None:
    _run("INSERT INTO rooms (agent, messages) VALUES (?, ?) "
         "ON CONFLICT(agent) DO UPDATE SET messages = excluded.messages",
         (agent, json.dumps(messages)))


def clear_room(agent: str) -> None:
    _run("DELETE FROM rooms WHERE agent = ?", (agent,))


# ---------- usage and cooldowns (Jyothi's books) ----------

def record_usage(agent: str, input_tokens: int, output_tokens: int, cost: float) -> None:
    _insert("INSERT INTO usage (agent, ts, input_tokens, output_tokens, cost) VALUES (?, ?, ?, ?, ?)",
            (agent, time.time(), input_tokens, output_tokens, cost))


def usage_since(seconds: float, agent: str | None = None) -> dict:
    since = time.time() - seconds
    if agent:
        rows = _run("SELECT COALESCE(SUM(input_tokens),0) i, COALESCE(SUM(output_tokens),0) o, "
                    "COALESCE(SUM(cost),0) c, COUNT(*) n FROM usage WHERE ts >= ? AND agent = ?", (since, agent))
    else:
        rows = _run("SELECT COALESCE(SUM(input_tokens),0) i, COALESCE(SUM(output_tokens),0) o, "
                    "COALESCE(SUM(cost),0) c, COUNT(*) n FROM usage WHERE ts >= ?", (since,))
    r = rows[0]
    return {"input_tokens": r["i"], "output_tokens": r["o"], "cost_usd": round(r["c"], 4), "calls": r["n"]}


def usage_today(agent: str | None = None) -> dict:
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    return usage_since(time.time() - midnight, agent)


def set_cooldown(agent: str, until: float, reason: str) -> None:
    _run("INSERT INTO cooldowns (agent, until, reason) VALUES (?, ?, ?) "
         "ON CONFLICT(agent) DO UPDATE SET until = excluded.until, reason = excluded.reason",
         (agent, until, reason))


def get_cooldown(agent: str) -> dict | None:
    rows = _run("SELECT * FROM cooldowns WHERE agent = ? AND until > ?", (agent, time.time()))
    return rows[0] if rows else None


def clear_cooldown(agent: str) -> None:
    _run("DELETE FROM cooldowns WHERE agent = ?", (agent,))
