"""自建 LangGraph 状态图：预检索 →（off: 直接生成 / auto,on: 有界 agent 循环）。"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Any

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.config import get_stream_writer
from langgraph.graph.message import MessagesState

from akairye_rag.agent.prompts import build_system_prompt
from akairye_rag.agent.tools import _kb_items, _tool_end, _tool_start, EVENT_ERROR_MAX, make_agent_tools
from akairye_rag.providers.llm import build_chat_model

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 3


class ChatState(MessagesState):
    query: str
    hits: list[dict[str, Any]]
    route: Any  # retrieval.router.Route
    product_map: dict[str, str]


def _route_event(route) -> dict[str, Any]:
    """给前端工具步骤追加的分流信息（不影响现有渲染，未知字段会被忽略）。"""
    extra: dict[str, Any] = {}
    if route is not None:
        labels = route.labels or route.searched_labels
        if labels:
            extra["product"] = labels
        if route.multi:
            extra["multi"] = True
        if route.tokens:
            extra["tokens"] = list(route.tokens)
        if route.scoped:
            extra["scoped"] = True
    return extra


def build_chat_graph(ctx, s):
    """每次问答构建一次（读取当前 settings 快照）。"""
    mode = s.tool_mode_value
    tavily_ok = s.tavily_usable
    # 客户端构造一次复用：settings 快照在本请求内固定，无需每轮重建连接/对象
    llm = build_chat_model(s)

    async def retrieve(state: ChatState):
        writer = get_stream_writer()
        query = state["query"]
        writer(_tool_start("knowledge_search", query))
        hits: list[dict[str, Any]] = []
        err = None
        route = None
        product_map: dict[str, str] = {}
        try:
            from akairye_rag.retrieval import router as routing

            # 1) 先分层：识别产品 / 指令词 / 是否再次追问
            product_map = await asyncio.to_thread(routing.document_product_map, ctx)
            previous = routing.previous_user_texts(state["messages"], query)
            route = routing.analyze_query(query, previous, product_map)

            # 2) 再检索，分三条路径：
            #    multi（模糊提问）→ 全部产品线分别检索并合并；
            #    明确点名多个产品 → 只对这些产品分别检索并合并（对比类问题也要全覆盖）；
            #    明确点名单个产品 → 文档级硬过滤，只用该产品资料。
            scopes: tuple[tuple[str, tuple[str, ...]], ...] = ()
            if route.multi:
                scopes = routing.retrieval_scopes(product_map)
            elif len(route.products) > 1:
                scopes = routing.product_scopes(route.products, product_map)

            if route.multi or len(route.products) > 1:
                if len(scopes) > 1:
                    raw = await ctx.kb_search_multi(
                        query,
                        s,
                        scopes,
                        exact_tokens=route.tokens,
                        # 同义词扩展只用于模糊提问；点名产品时按用户原话检索
                        variants=(
                            routing.query_variants(query)
                            if route.multi and not route.tokens
                            else ()
                        ),
                    )
                else:
                    # 知识库无法按产品归类（或只有一类）：退化为普通检索
                    limit = max(s.top_k, 24) if route.tokens else s.top_k
                    raw = await ctx.kb_search(
                        query,
                        s,
                        doc_ids=route.doc_ids,
                        exact_tokens=route.tokens,
                        limit=limit,
                    )
                route = replace(
                    route,
                    searched=tuple(k for k, _ in scopes),
                    exact=bool(route.tokens)
                    and any(
                        routing.content_has_any_token(h["content"], route.tokens)
                        for h in raw
                    ),
                )
            else:
                limit = max(s.top_k, 24) if route.tokens else s.top_k
                raw = await ctx.kb_search(
                    query, s, doc_ids=route.doc_ids, exact_tokens=route.tokens, limit=limit
                )
                if route.tokens:
                    matched = [
                        h for h in raw
                        if routing.content_has_any_token(h["content"], route.tokens)
                    ]
                    route = replace(route, exact=bool(matched))
                    if matched:
                        raw = matched
                raw = raw[: s.top_k]
            hits = await asyncio.to_thread(_kb_items, ctx, raw, product_map)
        except Exception as e:
            err = str(e)[:EVENT_ERROR_MAX]
            logger.warning("预检索失败: %s", e)
        writer(
            _tool_end(
                "knowledge_search", hits,
                top_score=hits[0]["score"] if hits else None,
                error=err,
                extra=_route_event(route),
            )
        )
        return {"hits": hits, "route": route, "product_map": product_map}

    async def generate_direct(state: ChatState):
        """off 模式：纯 RAG 链，不绑工具，按资料说话。"""
        system = build_system_prompt(
            state["hits"], tool_mode="off", tavily_usable=False, route=state.get("route")
        )
        ai: AIMessage = await llm.ainvoke(
            [SystemMessage(content=system), *state["messages"]]
        )
        return {"messages": [ai]}

    async def agent_node(state: ChatState):
        route = state.get("route")
        # 明确点名（或已锁定）产品时，业务规则要求只用该产品知识库作答。
        # 此时直接基于预检索片段生成：不给模型联网/二次检索工具，
        # 既避免混入其他产品内容，也省掉 2~3 轮模型往返与联网等待。
        if mode == "auto" and route is not None and route.products:
            system = build_system_prompt(
                state["hits"], tool_mode="off", tavily_usable=False, route=route
            )
            ai: AIMessage = await llm.ainvoke(
                [SystemMessage(content=system), *state["messages"]]
            )
            return {"messages": [ai]}

        # 工具二次检索沿用产品范围，防止模型自己绕回全库
        tools = make_agent_tools(
            ctx, s, base_ref=len(state["hits"]),
            doc_ids=route.doc_ids if route is not None else None,
            product_map=state.get("product_map") or None,
        )
        system_text = build_system_prompt(
            state["hits"], tool_mode=mode, tavily_usable=tavily_ok, route=route
        )
        messages: list = [SystemMessage(content=system_text), *state["messages"]]

        choice: str = "required" if mode == "on" else "auto"
        forced = mode == "on"

        for _ in range(MAX_TOOL_ROUNDS):
            bound = llm.bind_tools(tools, tool_choice=choice)  # type: ignore[arg-type]
            try:
                ai = await bound.ainvoke(messages)
            except Exception:
                if forced:
                    # 个别 Ark 模型不支持 tool_choice=required → 回退 auto 并加强约束
                    logger.info("tool_choice=required 被拒绝，回退 auto", exc_info=True)
                    forced = False
                    choice = "auto"
                    messages[0] = SystemMessage(
                        content=system_text + "\n注意：你必须先调用一个可用工具再作答。"
                    )
                    continue
                raise
            messages.append(ai)
            tool_calls = getattr(ai, "tool_calls", None)
            if not tool_calls:
                return {"messages": [ai]}

            tool_map = {t.name: t for t in tools}
            tool_messages: list[ToolMessage] = []
            for call in tool_calls:
                t = tool_map.get(call["name"])
                content = (
                    await _invoke_tool(t, call["args"])
                    if t is not None
                    else "工具不可用"
                )
                tool_messages.append(
                    ToolMessage(
                        content=str(content),
                        tool_call_id=call.get("id", ""),
                        name=call["name"],
                    )
                )
            messages.extend(tool_messages)
            choice = "auto"
            forced = False

        # 工具轮次用尽：直接要求成稿
        final = await llm.ainvoke(
            messages
            + [HumanMessage(content="请基于以上检索到的资料，直接给出完整的最终回答。")]
        )
        return {"messages": [final]}

    graph = StateGraph(ChatState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("generate_direct", generate_direct)
    graph.add_node("agent", agent_node)
    graph.add_edge(START, "retrieve")
    graph.add_conditional_edges(
        "retrieve",
        lambda state: "direct" if s.tool_mode_value == "off" else "agent",
        {"direct": "generate_direct", "agent": "agent"},
    )
    graph.add_edge("generate_direct", END)
    graph.add_edge("agent", END)
    return graph.compile()


async def _invoke_tool(tool, args: dict) -> str:
    try:
        return await tool.ainvoke(args)
    except Exception as e:
        return f"工具执行出错：{e}"
