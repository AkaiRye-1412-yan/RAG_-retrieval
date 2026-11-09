"""会话管理：新建 / 列表 / 重命名 / 删除 / 清空 / 历史消息。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from akairye_rag.api.deps import get_ctx, get_or_404
from akairye_rag.api.schemas import SessionCreate, SessionRename
from akairye_rag.db import repos

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _require_session(db, sid: str):
    return get_or_404(lambda: repos.get_session(db, sid), "会话不存在")


@router.get("")
async def list_sessions(request: Request) -> list[dict]:
    return repos.list_sessions(get_ctx(request).db)


@router.post("")
async def create_session(payload: SessionCreate, request: Request) -> dict:
    return repos.create_session(get_ctx(request).db, payload.title)


@router.patch("/{session_id}")
async def rename_session(session_id: str, payload: SessionRename, request: Request) -> dict:
    db = get_ctx(request).db
    _require_session(db, session_id)
    repos.rename_session(db, session_id, payload.title)
    return {"ok": True}


@router.delete("/{session_id}")
async def delete_session(session_id: str, request: Request) -> dict:
    db = get_ctx(request).db
    _require_session(db, session_id)
    repos.delete_session(db, session_id)
    return {"ok": True}


@router.post("/{session_id}/clear")
async def clear_session(session_id: str, request: Request) -> dict:
    db = get_ctx(request).db
    _require_session(db, session_id)
    repos.clear_messages(db, session_id)
    return {"ok": True}


@router.get("/{session_id}/messages")
async def get_messages(session_id: str, request: Request) -> list[dict]:
    db = get_ctx(request).db
    _require_session(db, session_id)
    return repos.list_messages(db, session_id)
