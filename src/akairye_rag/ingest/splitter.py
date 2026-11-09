"""把解析后的 Block 切成带溯源前缀的片段 [(text, locator), ...]。"""
from __future__ import annotations

from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from akairye_rag.ingest.parsers import ParseResult

CN_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "!", "?", ";", "：", ":", "，", ",", " ", ""]


def _locator_kind(locator: dict) -> tuple[str, str]:
    """按 locator 类型返回 (溯源前缀片段, 展示标签)；前缀片段自带前导空格。"""
    t = locator.get("type")
    if t == "page":
        return f" 第{locator.get('page')}页", f"第{locator.get('page')}页"
    if t == "sheet":
        return f" 工作表「{locator.get('sheet')}」", f"工作表「{locator.get('sheet')}」"
    if t == "image":
        return " 图片OCR内容", "图片OCR"
    if locator.get("table"):
        return " 表格", "表格"
    return "", "正文"


def _source_prefix(filename: str, locator: dict) -> str:
    suffix, _ = _locator_kind(locator)
    return f"《{filename}》{suffix}\n"


def _locator_label(locator: dict) -> str:
    _, label = _locator_kind(locator)
    return label


def split_blocks(
    parsed: ParseResult,
    filename: str,
    chunk_size: int = 500,
    chunk_overlap: int = 80,
) -> list[tuple[str, dict]]:
    """返回 [(chunk_text, locator), ...]，chunk_text 自带《文件名》溯源前缀。"""
    splitter = RecursiveCharacterTextSplitter(
        separators=CN_SEPARATORS,
        keep_separator=True,
        chunk_size=max(100, chunk_size),
        chunk_overlap=max(0, min(chunk_overlap, chunk_size // 2)),
        length_function=len,
    )
    fragments: list[tuple[str, dict]] = []
    name = Path(filename).name

    for block in parsed.blocks:
        text = block.text.strip()
        if not text:
            continue
        prefix = _source_prefix(name, block.locator)
        base_label = _locator_label(block.locator)

        is_tabular = block.locator.get("type") == "sheet" or block.locator.get("table")
        if is_tabular:
            pieces = _split_table(text, max(100, chunk_size))
        else:
            pieces = splitter.split_text(text)

        for i, piece in enumerate(pieces, start=1):
            piece = piece.strip()
            if not piece:
                continue
            locator = dict(block.locator)
            locator["chunk"] = i
            locator["label"] = (
                f"{base_label}·片段{i}" if len(pieces) > 1 else base_label
            )
            fragments.append((prefix + piece, locator))
    return fragments


def _split_table(text: str, max_chars: int) -> list[str]:
    """表格：按行累积成块；若有表头则每个后续块都带上表头。"""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    header = lines[0] if "|" in lines[0] else ""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    budget = max_chars - (len(header) + 1 if header else 0)
    for line in lines:
        if current and current_len + len(line) + 1 > budget:
            body = "\n".join(current)
            chunks.append((header + "\n" + body) if header else body)
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        body = "\n".join(current)
        chunks.append((header + "\n" + body) if (header and current[0] != header) else body)
    return chunks
