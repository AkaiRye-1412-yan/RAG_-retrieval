"""多格式文件解析：pdf / docx / doc / xlsx / xls / csv / txt / md / 图片。

统一输出 ParsedBlock(text, locator, ocr_used)，locator 形如：
  {"type": "page", "page": 3} / {"type": "sheet", "sheet": "Sheet1"} /
  {"type": "doc", "index": 12} / {"type": "image"} / {"type": "section"}
"""
from __future__ import annotations

import csv
import io
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from akairye_rag.ingest import ocr

logger = logging.getLogger(__name__)

SUPPORTED_EXTS = {
    "pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "md", "log",
    "png", "jpg", "jpeg", "bmp", "webp", "tif", "tiff",
}
IMAGE_EXTS = {"png", "jpg", "jpeg", "bmp", "webp", "tif", "tiff"}
SCAN_PAGE_MIN_CHARS = 10


def ext_of(name: str) -> str:
    """从文件名提取小写扩展名（无点）；无扩展名返回空串。"""
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


@dataclass
class ParsedBlock:
    text: str
    locator: dict
    ocr_used: bool = False


@dataclass
class ParseResult:
    blocks: list[ParsedBlock] = field(default_factory=list)
    ocr_used: bool = False

    def mark_ocr(self) -> None:
        self.ocr_used = True


def _decode_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


# ---------------- PDF ----------------

def parse_pdf(path: Path, ocr_enabled: bool, dpi: int) -> ParseResult:
    import pymupdf

    result = ParseResult()
    doc = pymupdf.open(path)
    try:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            used = False
            if len(text) < SCAN_PAGE_MIN_CHARS and ocr_enabled:
                try:
                    pix = page.get_pixmap(dpi=dpi)
                    ocr_text = ocr.ocr_bytes(pix.tobytes("png")).strip()
                    if ocr_text:
                        text = ocr_text
                        used = True
                        result.mark_ocr()
                except Exception as e:  # 单页 OCR 失败不拖垮整份文档
                    logger.warning("PDF 第 %d 页 OCR 失败: %s", i, e)
            if text:
                result.blocks.append(
                    ParsedBlock(text=text, locator={"type": "page", "page": i}, ocr_used=used)
                )
    finally:
        doc.close()
    return result


# ---------------- Word ----------------

def _docx_table_text(table) -> str:
    lines = []
    for row in table.rows:
        cells = [c.text.strip().replace("\n", " ") for c in row.cells]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def parse_docx(path: Path) -> ParseResult:
    import docx

    result = ParseResult()
    doc = docx.Document(str(path))

    # 按文档顺序遍历段落与表格
    from docx.oxml.ns import qn

    body = doc.element.body
    para_iter = iter(doc.paragraphs)
    table_iter = iter(doc.tables)
    index = 0
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            p = next(para_iter)
            text = p.text.strip()
            if text:
                index += 1
                result.blocks.append(
                    ParsedBlock(text=text, locator={"type": "doc", "index": index})
                )
        elif child.tag == qn("w:tbl"):
            table = next(table_iter)
            text = _docx_table_text(table)
            if text.strip():
                index += 1
                result.blocks.append(
                    ParsedBlock(text=text, locator={"type": "doc", "index": index, "table": True})
                )
    return result


def parse_doc(path: Path) -> ParseResult:
    """旧版 .doc：若系统装有 LibreOffice 则先转 docx，否则给出明确引导。"""
    soffice = shutil.which("soffice") or shutil.which("soffice.exe")
    if not soffice:
        raise ValueError(
            "旧版 .doc 格式不被直接支持，请用 Word/WPS 将文件另存为 .docx 后重新上传"
            "（或安装 LibreOffice 后重试）。"
        )
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "docx", "--outdir", tmp, str(path)],
            check=True,
            capture_output=True,
            timeout=300,
        )
        converted = Path(tmp) / (path.stem + ".docx")
        if not converted.exists():
            raise ValueError("LibreOffice 转换 .doc 失败，请另存为 .docx 后上传。")
        return parse_docx(converted)


# ---------------- Excel ----------------

def _format_cell(value, is_date: bool = False) -> str:
    if value is None:
        return ""
    if is_date:
        try:
            return value.isoformat(sep=" ")[:19]
        except Exception:
            return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _sheet_to_block(sheet_name: str, rows: list[list[str]]) -> ParsedBlock | None:
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return None
    lines = [" | ".join(c for c in row) for row in rows]
    return ParsedBlock(
        text="\n".join(lines), locator={"type": "sheet", "sheet": sheet_name}
    )


def parse_xlsx(path: Path) -> ParseResult:
    import openpyxl

    result = ParseResult()
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            rows: list[list[str]] = []
            for row in ws.iter_rows():
                rows.append([_format_cell(c.value, getattr(c, "is_date", False)) for c in row])
            block = _sheet_to_block(ws.title, rows)
            if block:
                result.blocks.append(block)
    finally:
        wb.close()
    return result


def parse_xls(path: Path) -> ParseResult:
    import xlrd

    result = ParseResult()
    book = xlrd.open_workbook(str(path))
    for sheet in book.sheets():
        rows: list[list[str]] = []
        for r in range(sheet.nrows):
            values = []
            for c in range(sheet.ncols):
                cell = sheet.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        dt = xlrd.xldate_as_datetime(cell.value, book.datemode)
                        values.append(dt.isoformat(sep=" ")[:19])
                        continue
                    except Exception:
                        pass
                values.append(_format_cell(cell.value))
            rows.append(values)
        block = _sheet_to_block(sheet.name, rows)
        if block:
            result.blocks.append(block)
    return result


# ---------------- 纯文本 / CSV ----------------

def parse_text(path: Path) -> ParseResult:
    text = _decode_bytes(path.read_bytes())
    result = ParseResult()
    if text.strip():
        result.blocks.append(
            ParsedBlock(text=text.strip(), locator={"type": "section"})
        )
    return result


def parse_csv(path: Path) -> ParseResult:
    text = _decode_bytes(path.read_bytes())
    result = ParseResult()
    reader = csv.reader(io.StringIO(text))
    rows = [[cell.strip() for cell in row] for row in reader]
    block = _sheet_to_block("CSV", rows)
    if block:
        result.blocks.append(block)
    return result


# ---------------- 图片 ----------------

def parse_image(path: Path, ocr_enabled: bool) -> ParseResult:
    result = ParseResult()
    if not ocr_enabled:
        logger.info("OCR 已关闭，图片 %s 不提取文本", path.name)
        return result
    text = ocr.ocr_bytes(path.read_bytes()).strip()
    if text:
        result.mark_ocr()
        result.blocks.append(ParsedBlock(text=text, locator={"type": "image"}))
    return result


# ---------------- 统一入口 ----------------

def parse_file(path: str | Path, *, ocr_enabled: bool = True, ocr_dpi: int = 200) -> ParseResult:
    path = Path(path)
    ext = ext_of(path.name)
    if ext not in SUPPORTED_EXTS:
        raise ValueError(f"不支持的文件类型：.{ext}")

    if ext == "pdf":
        return parse_pdf(path, ocr_enabled, ocr_dpi)
    if ext == "docx":
        return parse_docx(path)
    if ext == "doc":
        return parse_doc(path)
    if ext == "xlsx":
        return parse_xlsx(path)
    if ext == "xls":
        return parse_xls(path)
    if ext == "csv":
        return parse_csv(path)
    if ext in IMAGE_EXTS:
        return parse_image(path, ocr_enabled)
    return parse_text(path)
