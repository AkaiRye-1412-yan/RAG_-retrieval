"""问答 SSE：token 流与工具状态事件交织输出。"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from akairye_rag.agent.graph import build_chat_graph
from akairye_rag.api.deps import get_ctx
from akairye_rag.api.schemas import ChatRequest
from akairye_rag.db import repos

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _error_stream(message: str) -> StreamingResponse:
    async def gen():
        yield _sse({"type": "error", "message": message})

    return StreamingResponse(gen(), media_type="text/event-stream")


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content or "")


@router.post("/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    ctx = get_ctx(request)
    db = ctx.db
    s = ctx.settings_store.get()

    if not repos.get_session(db, payload.session_id):
        return _error_stream("会话不存在，请新建对话后重试。")

    if not s.has_ark_key:
        return _error_stream("尚未配置 ARK_API_KEY，请到「系统配置」中填写火山方舟 API Key。")

    # 1) 用户消息落库 + 取上下文
    repos.add_message(db, payload.session_id, "user", payload.query)
    history_rows = repos.recent_messages(db, payload.session_id, s.history_limit)
    history = [
        HumanMessage(content=row["content"])
        if row["role"] == "user"
        else AIMessage(content=row["content"])
        for row in history_rows
    ]

    graph = build_chat_graph(ctx, s)
    message_id = repos.new_id()

    async def event_gen():
        tool_events: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        used_web = False
        answer_parts: list[str] = []

        yield _sse(
            {
                "type": "meta",
                "session_id": payload.session_id,
                "message_id": message_id,
                "tool_mode": s.tool_mode_value,
                "tavily": s.tavily_usable,
            }
        )

        def collect_items(ev: dict[str, Any]) -> None:
            nonlocal used_web
            if ev.get("name") == "tavily_web_search" and ev.get("status") == "end" and ev.get("hits"):
                used_web = True
            for item in ev.get("items") or []:
                key = ("kb:" + str(item.get("id"))) if item.get("kind") == "kb" else (
                    "web:" + str(item.get("url"))
                )
                if key in seen:
                    continue
                seen.add(key)
                ref = len(sources) + 1
                if item.get("kind") == "kb":
                    sources.append(
                        {
                            "ref": ref,
                            "kind": "kb",
                            "doc_id": item.get("doc_id"),
                            "doc_name": item.get("doc_name"),
                            "label": item.get("label", ""),
                            "score": item.get("score"),
                            "snippet": item.get("snippet", ""),
                        }
                    )
                else:
                    sources.append(
                        {
                            "ref": ref,
                            "kind": "web",
                            "title": item.get("title", ""),
                            "url": item.get("url", ""),
                            "snippet": item.get("snippet", ""),
                        }
                    )

        try:
            aiter = graph.astream(
                {"messages": history, "query": payload.query},
                stream_mode=["messages", "custom"],
            )
            while True:
                if await request.is_disconnected():
                    break
                # 用 shield 包裹：keep-alive 超时只放弃等待，不取消底层图流
                task = asyncio.ensure_future(aiter.__anext__())
                while not task.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(task), timeout=20)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        if await request.is_disconnected():
                            task.cancel()
                            break
                    except StopAsyncIteration:
                        # 流在 wait_for 等待期间自然结束（异常会穿透 shield）
                        break
                if task.cancelled():
                    break
                try:
                    mode, chunk = task.result()
                except StopAsyncIteration:
                    break

                if mode == "custom":
                    ev = dict(chunk)
                    tool_events.append(ev)
                    if ev.get("status") == "end":
                        collect_items(ev)
                    yield _sse(ev)
                elif mode == "messages":
                    msg, _meta = chunk
                    if getattr(msg, "tool_call_chunks", None):
                        continue
                    text = _content_to_text(getattr(msg, "content", ""))
                    if text:
                        answer_parts.append(text)
                        yield _sse({"type": "token", "content": text})
        except Exception as e:
            logger.exception("问答流异常")
            yield _sse({"type": "error", "message": f"生成失败：{e}"})

        answer = "".join(answer_parts).strip()
        if answer:
            repos.add_message(
                db,
                payload.session_id,
                "assistant",
                answer,
                sources=sources,
                tool_events=tool_events,
                used_web=used_web,
            )
            yield _sse({"type": "sources", "items": sources})
            yield _sse(
                {
                    "type": "done",
                    "message_id": message_id,
                    "used_web": used_web,
                }
            )

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
