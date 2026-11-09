"""系统提示词与知识库片段格式化。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from akairye_rag.retrieval.router import Route

BASE_INSTRUCTIONS = (
    "你是 AkaiRye 知识RAG平台 的智能助手，服务于中文用户。要求：\n"
    "1. 使用与用户提问相同的语言作答，使用规范、排版精美的 Markdown 格式。\n"
    "2. 回答务必结构清晰：合理使用标题、列表、表格；代码用代码块并注明语言。\n"
    "3. 引用本地知识库内容时，在句末用方括号标注来源编号，如 [1]、[2]。\n"
    "4. 不要编造。知识库与联网结果都无法支撑答案时，明确告知用户你不知道或缺少相关资料。\n"
)

KB_HIT_INSTRUCTIONS = (
    "以下是从用户【本地知识库】检索到的相关片段，是回答的首要依据。"
    "检索已在提问前完成，片段就在下方；不要为了重复同一问题再次调用 knowledge_search，"
    "只有确实需要换关键词补充资料时才调用一次。"
    "只有当这些片段明显不足以回答、或问题涉及时效性/外部信息时，才可调用联网搜索工具。\n"
)

KB_MISS_INSTRUCTIONS = (
    "本地知识库【未检索到】与该问题足够相关的内容。"
    "如果该问题需要外部或最新信息，请调用 tavily_web_search 工具联网搜索后再作答；"
    "若联网工具不可用或搜索结果也无法回答，请直接、如实地告知用户，不要根据常识臆造。\n"
)

OFF_HIT_INSTRUCTIONS = (
    "以下是从用户【本地知识库】检索到的相关片段。你只能依据这些片段回答，"
    "并在引用处标注 [n]；片段不足以回答的部分要明确指出资料不足。\n"
)

OFF_MISS_INSTRUCTIONS = (
    "本地知识库中未检索到与该问题相关的内容；当前为「仅知识库」模式（工具调用已关闭），无法联网。"
    "请直接、礼貌地告知用户：知识库中暂无相关资料，可上传相关文档，"
    "或在系统设置中把工具调用模式改为 auto 并开启 Tavily 联网搜索。"
    "不要根据自身常识编造答案。\n"
)


# ---- 产品分流（retrieval/router.py）----

ROUTE_EXPLICIT = (
    "本轮问题明确指向【{labels}】。你只能依据【{labels}】的知识库片段回答：\n"
    "- 即使其他产品有同名指令或相似功能，本轮也不要提及、不要引用。\n"
    "- 若片段不足以回答，请如实说明该产品资料中未找到，不要用其他产品资料补答。\n"
)

ROUTE_IMPLIED = (
    "本轮问题未点名产品，但检索已按指令/内容匹配锁定为【{labels}】。\n"
    "- 首轮回答只使用【{labels}】的片段；其他产品虽有相似功能，本轮不要展开。\n"
    "- 若用户再次追问，才可以补充其他产品的内容。\n"
)

ROUTE_RELAXED = (
    "用户本轮属于再次追问（或明确要求看其他产品），可以补充其他产品的相近/同名功能；\n"
    "- 但必须逐条注明内容来自哪个产品，不要混为一谈。\n"
)

ROUTE_EXACT_HIT = "- 指令关键词：{tokens}（当前片段已优先按该关键词精确筛选）。\n"
ROUTE_EXACT_MISS = (
    "- 指令关键词：{tokens}（未找到精确命中的片段，以下为语义相近结果；回答前需说明这一点）。\n"
)

ROUTE_SCOPE_MISS = (
    "本地知识库【没有检索到】与【{labels}】相关的片段。请如实告知用户：知识库中暂缺该产品资料，"
    "可上传对应文档；不要用其他产品的资料替代，也不要臆造。\n"
)


def format_route(route: "Route | None") -> str:
    """把路由决策渲染成给模型看的约束段；无分流信息时返回 ""。"""
    if route is None:
        return ""
    labels = "、".join(route.labels)
    parts: list[str] = []
    if route.products and route.source == "implied":
        parts.append(ROUTE_IMPLIED.format(labels=labels))
    elif route.products:
        parts.append(ROUTE_EXPLICIT.format(labels=labels))
    if route.relaxed and not route.products:
        parts.append(ROUTE_RELAXED)
    if route.tokens:
        tokens = "、".join(route.tokens)
        parts.append((ROUTE_EXACT_HIT if route.exact else ROUTE_EXACT_MISS).format(tokens=tokens))
    if not parts:
        return ""
    return "===== 检索分层（必须遵守）=====\n" + "".join(parts)


def format_kb_hits(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return ""
    blocks = []
    for i, h in enumerate(hits, start=1):
        name = h.get("doc_name") or "未知文档"
        label = (h.get("locator") or {}).get("label", "")
        header = f"[{i}] 来源：《{name}》{('· ' + label) if label else ''}"
        snippet = h["content"].strip()
        blocks.append(f"{header}\n{snippet}")
    return "===== 本地知识库检索片段 =====\n" + "\n\n".join(blocks) + "\n===== 片段结束 ====="


def build_system_prompt(
    hits: list[dict[str, Any]],
    *,
    tool_mode: str,
    tavily_usable: bool,
    route: "Route | None" = None,
) -> str:
    context = format_kb_hits(hits)  # 空输入时返回 ""
    scoped_labels = "、".join(route.labels) if route and route.labels else ""
    if route and route.products and not hits:
        # 已锁定某产品但该产品没有资料：不能说“知识库没有”，更不能拿别家资料顶替
        instr = ROUTE_SCOPE_MISS.format(labels=scoped_labels)
        if tool_mode != "off" and tavily_usable:
            instr += "（如调用 tavily_web_search，也只能围绕该产品检索，不能用其他产品替代。）\n"
    elif tool_mode == "off":
        instr = OFF_HIT_INSTRUCTIONS if hits else OFF_MISS_INSTRUCTIONS
    else:
        instr = KB_HIT_INSTRUCTIONS if hits else KB_MISS_INSTRUCTIONS
        if not tavily_usable:
            instr += "（当前未配置/未启用联网搜索，无法调用 tavily_web_search。）\n"
    parts = [BASE_INSTRUCTIONS, instr]
    route_text = format_route(route)
    if route_text:
        parts.append(route_text)
    if context:
        parts.append(context)
    return "\n\n".join(parts)


def format_tool_results(payload: list[dict[str, Any]], base_ref: int) -> str:
    """工具结果给模型看的编号文本（编号顺延预检索片段之后）。"""
    blocks = []
    for i, item in enumerate(payload, start=base_ref + 1):
        content = (item.get("content") or "")[:1200]
        if item.get("url"):
            blocks.append(
                f"[{i}] 网络来源：{item.get('title','')}\nURL: {item['url']}\n{content}"
            )
        else:
            name = item.get("doc_name") or "未知文档"
            blocks.append(f"[{i}] 来源：《{name}》\n{content}")
    return "\n\n".join(blocks)
