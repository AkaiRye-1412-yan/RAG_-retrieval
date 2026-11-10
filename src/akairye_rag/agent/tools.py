"""Agent 工具工厂：knowledge_search（本地知识库）与 tavily_web_search（联网）。"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from akairye_rag.agent.prompts import format_tool_results
from akairye_rag.providers import tavily as tavily_provider

if TYPE_CHECKING:
    from akairye_rag.core.app_context import AppContext
    from akairye_rag.core.settings import Settings

logger = logging.getLogger(__name__)

SNIPPET_LEN = 280        # 来源摘要与工具结果截断长度
EVENT_ERROR_MAX = 200    # SSE 事件里错误信息截断长度


def _tool_start(name: str, query: str, **extra: Any) -> dict[str, Any]:
    return {"type": "tool", "name": name, "status": "start", "input": query, **extra}


def _tool_error(name: str, e: Exception) -> dict[str, Any]:
    return {
        "type": "tool", "name": name, "status": "end",
        "hits": 0, "error": str(e)[:EVENT_ERROR_MAX], "items": [],
    }


def _tool_end(
    name: str,
    items: list[dict[str, Any]],
    *,
    top_score: float | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "type": "tool", "name": name, "status": "end",
        "hits": len(items), "items": items,
    }
    if top_score is not None:
        ev["top_score"] = top_score
    if error is not None:
        ev["error"] = error
    if extra:
        ev.update(extra)
    return ev


def number(items: list[dict[str, Any]], counter: dict[str, int]) -> list[dict[str, Any]]:
    """顺延编号（counter 为共享的 {"ref": int}）。"""
    numbered = []
    for it in items:
        counter["ref"] += 1
        numbered.append({**it, "ref": counter["ref"]})
    return numbered


def _kb_items(
    ctx: "AppContext",
    hits: list[dict[str, Any]],
    product_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if not hits:
        return []
    placeholders = ",".join("?" for _ in {h["doc_id"] for h in hits})
    rows = ctx.db.conn.execute(
        f"SELECT id, filename FROM documents WHERE id IN ({placeholders})",
        list({h["doc_id"] for h in hits}),
    ).fetchall()
    names = {r["id"]: r["filename"] for r in rows}
    if product_map is None:
        from akairye_rag.retrieval.router import document_product_map

        product_map = document_product_map(ctx)
    from akairye_rag.retrieval.router import product_label

    items = []
    for h in hits:
        loc = h.get("locator") or {}
        key = h.get("product_key") or product_map.get(h["doc_id"], "")
        items.append(
            {
                "kind": "kb",
                "id": h["id"],
                "doc_id": h["doc_id"],
                "doc_name": names.get(h["doc_id"], "未知文档"),
                "label": loc.get("label", ""),
                "product_key": key,
                "product": product_label(key) if key else "",
                "score": h.get("score"),
                "snippet": h["content"][:SNIPPET_LEN],
                "content": h["content"],
            }
        )
    return items


def make_agent_tools(
    ctx: "AppContext",
    s: "Settings",
    base_ref: int,
    *,
    doc_ids: tuple[str, ...] | None = None,
    product_map: dict[str, str] | None = None,
):
    """按请求构建工具；编号在预检索片段之后顺延。

    doc_ids：产品分流锁定的文档范围，工具二次检索必须沿用，避免模型自己
    绕回全库把其他产品的内容捞进来。
    """
    counter = {"ref": base_ref}

    @tool
    async def knowledge_search(query: str) -> str:
        """在本地知识库中检索文档片段。当需要补充或核对知识库资料时调用，参数为简短的检索问题或关键词。"""
        writer = get_stream_writer()
        writer(_tool_start("knowledge_search", query))
        try:
            hits = await ctx.kb_search(query, s, doc_ids=doc_ids)
        except Exception as e:
            logger.warning("知识库工具检索失败: %s", e)
            writer(_tool_error("knowledge_search", e))
            return f"知识库检索失败：{e}"
        items = _kb_items(ctx, hits, product_map)
        numbered = number(items, counter)
        writer(
            _tool_end(
                "knowledge_search", numbered,
                top_score=items[0]["score"] if items else None,
            )
        )
        if not numbered:
            return "知识库中未检索到更多相关片段。"
        return format_tool_results(numbered, base_ref=counter["ref"] - len(numbered))

    @tool
    async def tavily_web_search(query: str) -> str:
        """联网搜索外部/最新信息（网页结果）。仅当本地知识库无法回答用户问题时使用。"""
        writer = get_stream_writer()
        writer(_tool_start("tavily_web_search", query, reason="below_threshold"))
        try:
            results = await tavily_provider.tavily_search(s, query)
        except Exception as e:
            logger.warning("Tavily 搜索失败: %s", e)
            writer(_tool_error("tavily_web_search", e))
            return f"联网搜索失败：{e}"
        numbered = number(
            [
                {
                    "kind": "web",
                    "title": r["title"],
                    "url": r["url"],
                    "snippet": (r["content"] or "")[:SNIPPET_LEN],
                    "content": r["content"] or "",
                }
                for r in results
            ],
            counter,
        )
        writer(_tool_end("tavily_web_search", numbered))
        if not numbered:
            return "联网搜索没有返回可用结果。"
        return format_tool_results(numbered, base_ref=counter["ref"] - len(numbered))

    tools = [knowledge_search]
    if s.tavily_usable:
        tools.append(tavily_web_search)
    return tools
