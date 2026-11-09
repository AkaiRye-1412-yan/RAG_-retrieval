"""系统提示词与知识库片段格式化。"""
from __future__ import annotations

from typing import Any

BASE_INSTRUCTIONS = (
    "你是 AkaiRye 知识RAG平台 的智能助手，服务于中文用户。要求：\n"
    "1. 使用与用户提问相同的语言作答，使用规范、排版精美的 Markdown 格式。\n"
    "2. 回答务必结构清晰：合理使用标题、列表、表格；代码用代码块并注明语言。\n"
    "3. 引用本地知识库内容时，在句末用方括号标注来源编号，如 [1]、[2]。\n"
    "4. 不要编造。知识库与联网结果都无法支撑答案时，明确告知用户你不知道或缺少相关资料。\n"
)

KB_HIT_INSTRUCTIONS = (
    "以下是从用户【本地知识库】检索到的相关片段，是回答的首要依据。"
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
    "本地知识库中未检索到与该问题相关的内容，且当前已关闭联网搜索。"
    "请直接、礼貌地告知用户：知识库中暂无相关资料，可上传相关文档或在系统设置中开启联网。"
    "不要根据自身常识编造答案。\n"
)


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


def build_system_prompt(hits: list[dict[str, Any]], *, tool_mode: str, tavily_usable: bool) -> str:
    context = format_kb_hits(hits)  # 空输入时返回 ""
    if tool_mode == "off":
        instr = OFF_HIT_INSTRUCTIONS if hits else OFF_MISS_INSTRUCTIONS
    else:
        instr = KB_HIT_INSTRUCTIONS if hits else KB_MISS_INSTRUCTIONS
        if not tavily_usable:
            instr += "（当前未配置/未启用联网搜索，无法调用 tavily_web_search。）\n"
    parts = [BASE_INSTRUCTIONS, instr]
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
