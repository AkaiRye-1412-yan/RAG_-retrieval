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
    "5. 先概览、后分述：复杂问题先给出结论要点，再分节展开；涉及多个产品/型号时"
    "按产品分节，最后用表格汇总差异，禁止把不同产品的操作混在一起写。\n"
    "6. 内容完整：每个产品的关键步骤、指令、参数都要写全，不要用「同理」「略」"
    "或省略号带过；回答被长度限制时优先保留各产品的操作要点。\n"
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

ROUTE_EXPLICIT_MULTI = (
    "本轮问题明确指向【{labels}】的对比，片段已按产品分别检索并合并：\n"
    "- 逐产品分节（### 产品名），每个产品按「适用场景 / 操作步骤 / 关键参数或指令 / 注意事项」"
    "组织，并在句末标注来源编号 [n]。\n"
    "- 开头先给共同点与关键差异概览，结尾用 Markdown 表格汇总对照"
    "（产品 / 关键步骤或指令 / 参数或地址 / 注意事项）。\n"
    "- 只使用属于该产品的片段（见标题里的【产品】标签）；"
    "某个被点名的产品没有检索到片段时，明确说明「知识库中未找到该产品（XXX）的相关资料」，"
    "不要用其他产品的内容替代。\n"
)

ROUTE_MULTI = (
    "本轮问题【没有点名具体产品】，属于模糊提问，必须跨产品完整覆盖：\n"
    "- 片段已按产品线分别检索并合并（{labels}）；凡是有资料的产品都要单独成节"
    "（### 产品名），逐条说明该产品的做法、指令或参数，并在句末标注来源编号 [n]。\n"
    "- 开头先用 2~4 条要点给出各产品的共同思路与关键差异概览；"
    "若做法一致，先讲共性，再逐产品指出差异。\n"
    "- 每个产品节内按「适用场景 / 操作步骤 / 关键参数或指令 / 注意事项」组织，"
    "资料里没有的部分不必强行编造。\n"
    "- 结尾用 Markdown 表格汇总对照，建议列：产品 / 关键步骤或指令 / 参数或地址 / 注意事项。\n"
    "- 只能使用与该产品对应的片段（见片段标题里的【产品】标签）；"
    "某产品没有检索到相关片段时，明确写「知识库中未找到该产品（XXX）的相关资料」，"
    "不要用其他产品的内容替代，也不要虚构。\n"
    "- 覆盖度优先：不要因为某个产品命中分数更高就只回答它。\n"
)

ROUTE_MULTI_EMPTY = (
    "本轮问题未点名产品，已对知识库中的全部产品线做了跨产品检索，但都没有找到足够相关的片段。\n"
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
    if route.products:
        template = ROUTE_EXPLICIT_MULTI if len(route.products) > 1 else ROUTE_EXPLICIT
        parts.append(template.format(labels=labels))
    elif route.multi:
        searched = "、".join(route.searched_labels) or "各产品线"
        parts.append(ROUTE_MULTI.format(labels=searched))
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
        product = h.get("product") or ""
        header = f"[{i}] 来源：《{name}》{('· ' + label) if label else ''}"
        if product:
            header += f" 【{product}】"
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
    else:
        # 模糊提问且跨产品检索后仍无命中：先说明已做过全产品检索，再走缺资料流程
        prefix = ROUTE_MULTI_EMPTY if (route and route.multi and not hits) else ""
        if tool_mode == "off":
            instr = prefix + (OFF_HIT_INSTRUCTIONS if hits else OFF_MISS_INSTRUCTIONS)
        else:
            instr = prefix + (KB_HIT_INSTRUCTIONS if hits else KB_MISS_INSTRUCTIONS)
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
