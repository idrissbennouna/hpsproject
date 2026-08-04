# backend/app/services/conversation_history.py
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

_DB_PATH = Path(__file__).resolve().parent.parent / "storage" / "conversations.db"
_LOCK = threading.Lock()

def _get_conn():
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _init_db():
    with _LOCK:
        conn = _get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id            TEXT PRIMARY KEY,
                    agent_type    TEXT NOT NULL DEFAULT 'logs',
                    title         TEXT NOT NULL DEFAULT 'Conversation sans titre',
                    last_activity TEXT NOT NULL,
                    messages_json TEXT NOT NULL DEFAULT '[]',
                    result_json   TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_conv_agent_activity
                ON conversations (agent_type, last_activity DESC)
            """)
            conn.commit()
        finally:
            conn.close()

_init_db()

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def create_conversation(agent_type, title, messages=None, result=None, conv_id=None):
    conv_id = conv_id or str(uuid.uuid4())
    now = _now_iso()
    messages_json = json.dumps(messages or [], ensure_ascii=False)
    result_json = json.dumps(result, ensure_ascii=False) if result is not None else None
    with _LOCK:
        conn = _get_conn()
        try:
            conn.execute(
                "INSERT INTO conversations (id, agent_type, title, last_activity, messages_json, result_json) VALUES (?, ?, ?, ?, ?, ?)",
                (conv_id, agent_type, title, now, messages_json, result_json),
            )
            conn.commit()
        finally:
            conn.close()
    return get_conversation(conv_id)

def get_conversations(agent_type, limit=10):
    with _LOCK:
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT id, agent_type, title, last_activity FROM conversations WHERE agent_type = ? ORDER BY last_activity DESC LIMIT ?",
                (agent_type, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

def get_conversation(conv_id):
    with _LOCK:
        conn = _get_conn()
        try:
            row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
            if row is None:
                return None
            d = dict(row)
            d["messages"] = json.loads(d.pop("messages_json", "[]") or "[]")
            raw_result = d.pop("result_json", None)
            d["result"] = json.loads(raw_result) if raw_result else None
            return d
        finally:
            conn.close()

def update_conversation(conv_id, title=None, messages=None, result=None):
    now = _now_iso()
    with _LOCK:
        conn = _get_conn()
        try:
            existing = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
            if existing is None:
                return None
            new_title = title if title is not None else existing["title"]
            new_messages_json = json.dumps(messages, ensure_ascii=False) if messages is not None else existing["messages_json"]
            new_result_json = json.dumps(result, ensure_ascii=False) if result is not None else existing["result_json"]
            conn.execute(
                "UPDATE conversations SET title = ?, last_activity = ?, messages_json = ?, result_json = ? WHERE id = ?",
                (new_title, now, new_messages_json, new_result_json, conv_id),
            )
            conn.commit()
        finally:
            conn.close()
    return get_conversation(conv_id)

def delete_conversation(conv_id):
    with _LOCK:
        conn = _get_conn()
        try:
            cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
