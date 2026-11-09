"""自建 LangGraph 状态图：预检索 →（off: 直接生成 / auto,on: 有界 agent 循环）。"""
from __future__ import annotations

import asyncio
import logging
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
        try:
            raw = await ctx.kb_search(query, s)
            hits = await asyncio.to_thread(_kb_items, ctx, raw)
        except Exception as e:
            err = str(e)[:EVENT_ERROR_MAX]
            logger.warning("预检索失败: %s", e)
        writer(
            _tool_end(
                "knowledge_search", hits,
                top_score=hits[0]["score"] if hits else None,
                error=err,
            )
        )
        return {"hits": hits}

    async def generate_direct(state: ChatState):
        """off 模式：纯 RAG 链，不绑工具，按资料说话。"""
        system = build_system_prompt(state["hits"], tool_mode="off", tavily_usable=False)
        ai: AIMessage = await llm.ainvoke(
            [SystemMessage(content=system), *state["messages"]]
        )
        return {"messages": [ai]}

    async def agent_node(state: ChatState):
        tools = make_agent_tools(ctx, s, base_ref=len(state["hits"]))
        system_text = build_system_prompt(state["hits"], tool_mode=mode, tavily_usable=tavily_ok)
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
