"""仓库层：会话 / 消息 / 文档 / KV 的 CRUD（chunks 表由向量存储模块直接操作）。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from akairye_rag.db.connection import Database


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def json_loads(s: str | None, default: Any = None) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default


def _one(row) -> dict[str, Any] | None:
    return dict(row) if row else None


def _all(rows) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


# ---------------- sessions ----------------

def list_sessions(db: Database) -> list[dict[str, Any]]:
    with db.lock:
        rows = db.conn.execute(
            """SELECT s.id, s.title, s.created_at, s.updated_at,
                      (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count
               FROM sessions s ORDER BY s.updated_at DESC"""
        ).fetchall()
    return _all(rows)


def create_session(db: Database, title: str | None = None) -> dict[str, Any]:
    sid = new_id()
    ts = now_iso()
    title = (title or "").strip() or "新对话"
    with db.lock:
        db.conn.execute(
            "INSERT INTO sessions(id, title, created_at, updated_at) VALUES (?,?,?,?)",
            (sid, title, ts, ts),
        )
        db.conn.commit()
    return {"id": sid, "title": title, "created_at": ts, "updated_at": ts}


def get_session(db: Database, session_id: str) -> dict[str, Any] | None:
    with db.lock:
        row = db.conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    return _one(row)


def rename_session(db: Database, session_id: str, title: str) -> bool:
    title = (title or "").strip() or "新对话"
    with db.lock:
        cur = db.conn.execute("UPDATE sessions SET title=? WHERE id=?", (title, session_id))
        db.conn.commit()
        return cur.rowcount > 0


def delete_session(db: Database, session_id: str) -> bool:
    with db.lock:
        cur = db.conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        db.conn.commit()
        return cur.rowcount > 0


def clear_messages(db: Database, session_id: str) -> None:
    with db.lock:
        db.conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        db.conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now_iso(), session_id))
        db.conn.commit()


# ---------------- messages ----------------

def add_message(
    db: Database,
    session_id: str,
    role: str,
    content: str,
    sources: list[dict[str, Any]] | None = None,
    tool_events: list[dict[str, Any]] | None = None,
    used_web: bool = False,
) -> dict[str, Any]:
    mid = new_id()
    ts = now_iso()
    with db.lock:
        seq_row = db.conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM messages WHERE session_id=?",
            (session_id,),
        ).fetchone()
        seq = seq_row["next_seq"]
        db.conn.execute(
            """INSERT INTO messages(id, session_id, seq, role, content, sources, tool_events, used_web, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                mid,
                session_id,
                seq,
                role,
                content,
                json_dumps(sources or []),
                json_dumps(tool_events or []),
                1 if used_web else 0,
                ts,
            ),
        )
        db.conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (ts, session_id))
        db.conn.commit()
    return {
        "id": mid,
        "session_id": session_id,
        "seq": seq,
        "role": role,
        "content": content,
        "sources": sources or [],
        "tool_events": tool_events or [],
        "used_web": used_web,
        "created_at": ts,
    }


def _message_row(r) -> dict[str, Any]:
    d = dict(r)
    d["sources"] = json_loads(d.get("sources"), [])
    d["tool_events"] = json_loads(d.get("tool_events"), [])
    d["used_web"] = bool(d.get("used_web"))
    return d


def list_messages(db: Database, session_id: str) -> list[dict[str, Any]]:
    with db.lock:
        rows = db.conn.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY seq ASC", (session_id,)
        ).fetchall()
    return [_message_row(r) for r in rows]


def recent_messages(db: Database, session_id: str, limit: int) -> list[dict[str, Any]]:
    with db.lock:
        rows = db.conn.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY seq DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [_message_row(r) for r in reversed(rows)]


def recent_user_texts(db: Database, session_id: str, limit: int = 40) -> list[str]:
    """本会话最近的用户提问文本（旧→新），供检索分流识别会话级产品范围。

    与 `recent_messages` 不同：只取 user 消息、且不受 HISTORY_LIMIT 限制，
    保证「ACS 如何回零」这类早期明确产品在后续多轮追问后仍能被记住。
    """
    with db.lock:
        rows = db.conn.execute(
            "SELECT content FROM messages WHERE session_id=? AND role='user'"
            " ORDER BY seq DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [r["content"] for r in reversed(rows)]


# ---------------- documents ----------------

def create_document(
    db: Database, doc_id: str, filename: str, ext: str, size_bytes: int, sha256: str
) -> None:
    ts = now_iso()
    with db.lock:
        db.conn.execute(
            """INSERT INTO documents(id, filename, ext, size_bytes, sha256, status, created_at)
               VALUES (?,?,?,?,?,'pending',?)""",
            (doc_id, filename, ext, size_bytes, sha256, ts),
        )
        db.conn.commit()


def update_document(
    db: Database,
    doc_id: str,
    status: str | None = None,
    chunk_count: int | None = None,
    ocr_used: bool | None = None,
    error: str | None = None,
) -> None:
    fields: list[str] = []
    params: list[Any] = []
    if status is not None:
        fields.append("status=?")
        params.append(status)
    if chunk_count is not None:
        fields.append("chunk_count=?")
        params.append(chunk_count)
    if ocr_used is not None:
        fields.append("ocr_used=?")
        params.append(1 if ocr_used else 0)
    if error is not None:
        fields.append("error=?")
        params.append(error)
    if not fields:
        return
    params.append(doc_id)
    with db.lock:
        db.conn.execute(f"UPDATE documents SET {', '.join(fields)} WHERE id=?", params)
        db.conn.commit()


def get_document(db: Database, doc_id: str) -> dict[str, Any] | None:
    with db.lock:
        row = db.conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    return _one(row)


def list_documents(db: Database) -> list[dict[str, Any]]:
    with db.lock:
        rows = db.conn.execute(
            "SELECT * FROM documents ORDER BY created_at DESC"
        ).fetchall()
    return _all(rows)


def delete_document(db: Database, doc_id: str) -> dict[str, Any] | None:
    doc = get_document(db, doc_id)
    if not doc:
        return None
    with db.lock:
        db.conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))  # chunks 级联删除
        db.conn.commit()
    return doc


def reset_documents_for_reindex(db: Database) -> None:
    with db.lock:
        db.conn.execute("UPDATE documents SET status='pending', chunk_count=0, ocr_used=0, error=NULL")
        db.conn.commit()


def documents_stats(db: Database) -> dict[str, Any]:
    with db.lock:
        doc_count = db.conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
        chunk_count = db.conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"]
        done = db.conn.execute("SELECT COUNT(*) AS c FROM documents WHERE status='done'").fetchone()["c"]
        error = db.conn.execute("SELECT COUNT(*) AS c FROM documents WHERE status='error'").fetchone()["c"]
        pending = doc_count - done - error
    return {
        "document_count": doc_count,
        "chunk_count": chunk_count,
        "done_count": done,
        "pending_count": pending,
        "error_count": error,
    }


# ---------------- kv ----------------

def kv_get(db: Database, key: str) -> str | None:
    with db.lock:
        row = db.conn.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return row["v"] if row else None


def kv_set(db: Database, key: str, value: str) -> None:
    with db.lock:
        db.conn.execute(
            "INSERT INTO kv(k, v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (key, value),
        )
        db.conn.commit()


def kv_delete(db: Database, key: str) -> None:
    with db.lock:
        db.conn.execute("DELETE FROM kv WHERE k=?", (key,))
        db.conn.commit()
