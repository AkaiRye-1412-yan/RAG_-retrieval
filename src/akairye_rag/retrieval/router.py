"""检索分流：先按产品线识别问题，再做分层检索。

对应业务规则：
1. 问题里明确出现品牌（高创 / ACS / AGITO / AKRIBIS 等）→ 只检索该产品的文档，
   绝不混入其他产品内容。
2. **会话产品上下文**：同一会话里用户此前已明确点过产品（如先问“ACS 如何回零”），
   之后的模糊追问（如“具体步骤呢”）只在该产品范围内检索作答，不跨产品；
   只有当前问题重新点名其他产品（如“那高创呢”）或明确要求“其他产品”，才切换范围。
3. 问题没有点名品牌、且会话里也从未确定过产品（首次模糊提问，如“如何回零”）
   → **跨产品全覆盖检索**：按产品线分别检索并分组，把所有相关产品的资料都交给模型，
   由模型按产品分节、对比作答。
4. 指令类问题（如 PTP、MST、CDHD 参数等）→ 每个产品范围内只保留“指令词精确命中”
   的候选；某产品没有精确命中时回退该产品的语义结果。
5. 模糊提问额外做轻量同义词扩展（回零/回原点/Homing…），提升多维度召回。

产品目录按文件名 + 片段正文采样做归类。内置目录见下方 `PRODUCTS`；
新增品牌建议在 `data/product_catalog.json`（或 `PRODUCT_CATALOG` 指定的文件）的
`products` 数组里追加一项，同名 key 覆盖内置项、新 key 追加；修改后无需重启，
下一轮问答自动生效。
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from akairye_rag.core import paths

if TYPE_CHECKING:
    from akairye_rag.core.app_context import AppContext
    from akairye_rag.core.settings import Settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 产品目录
# ---------------------------------------------------------------------------
# aliases：品牌/系列名，问题或文件名里出现即强判定（大小写不敏感，英文按整词匹配）。
# model_prefixes：型号前缀，仅在文件名/正文中作为弱信号；问题里出现则视为该产品。
# 注意：前缀按“词首”匹配，因此 "UDMmc" 能命中 "udm"。


@dataclass(frozen=True)
class Product:
    key: str
    label: str
    aliases: tuple[str, ...] = ()
    model_prefixes: tuple[str, ...] = ()


PRODUCTS: tuple[Product, ...] = (
    Product(
        "acs",
        "ACS",
        aliases=("acs motion control", "acs motion", "acspl", "acsp", "spiiplus", "acs"),
    ),
    Product(
        "gaochuang",
        "高创（Servotronix）",
        aliases=("高创传动", "高创", "servotronix", "cdhd", "ddhd"),
        model_prefixes=("cdhd", "ddhd"),
    ),
    Product(
        "agito",
        "AGITO",
        aliases=("agito",),
        model_prefixes=("agd", "agm"),
    ),
    Product(
        "akribis",
        "AKRIBIS（雅科贝思）",
        aliases=("akribis", "雅科贝思"),
        model_prefixes=("akm", "akd", "akh", "aks", "axt", "ath", "awm", "acw", "udm"),
    ),
)

_PRODUCTS_LOCK = threading.RLock()
_PRODUCTS_CACHE: tuple[Product, ...] = PRODUCTS
_PRODUCTS_SIG: tuple[str, float, int] = ("", 0.0, 0)


def _catalog_candidates() -> list[Path]:
    """候选目录文件：PRODUCT_CATALOG > DATA_DIR/data > 程序目录/data > 打包资源。"""
    out: list[Path] = []
    env_path = os.environ.get("PRODUCT_CATALOG", "").strip()
    if env_path:
        p = Path(env_path).expanduser()
        out.append(p if p.is_absolute() else paths.APP_DIR / p)
    out.append(paths.data_dir(os.environ.get("DATA_DIR", "")) / "product_catalog.json")
    out.append(paths.APP_DIR / "data" / "product_catalog.json")
    if paths.RES_DIR != paths.APP_DIR:
        out.append(paths.RES_DIR / "data" / "product_catalog.json")
    return out


def _catalog_path() -> Path | None:
    for p in _catalog_candidates():
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def _str_tuple(item: dict[str, Any], key: str) -> tuple[str, ...]:
    vals = item.get(key) or []
    if isinstance(vals, str):
        vals = [vals]
    if not isinstance(vals, list):
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for v in vals:
        s = str(v).strip()
        if not s or s.lower() in seen:
            continue
        seen.add(s.lower())
        out.append(s)
    return tuple(out)


def _product_from_json(item: dict[str, Any]) -> Product | None:
    key = str(item.get("key") or "").strip().lower()
    if not key:
        return None
    label = str(item.get("label") or key).strip() or key
    aliases = _str_tuple(item, "aliases") + _str_tuple(item, "english")
    # aliases / english 可能重复，合并后再去重
    dedup: list[str] = []
    seen: set[str] = set()
    for a in aliases:
        if a.lower() in seen:
            continue
        seen.add(a.lower())
        dedup.append(a)
    return Product(
        key=key,
        label=label,
        aliases=tuple(dedup),
        model_prefixes=_str_tuple(item, "model_prefixes"),
    )


def _load_catalog(path: Path) -> list[Product] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("产品目录读取失败（%s），继续使用内置目录：%s", path, e)
        return None
    items = data.get("products") if isinstance(data, dict) else data
    if not isinstance(items, list):
        logger.warning("产品目录格式不正确（缺少 products 数组）：%s", path)
        return None
    loaded = [_product_from_json(it) for it in items if isinstance(it, dict)]
    return [p for p in loaded if p is not None]


def products() -> tuple[Product, ...]:
    """当前产品目录：内置 + 外部 JSON（同名覆盖、新 key 追加）。

    每轮问答只做一次 stat；文件未变化直接复用缓存，编辑 JSON 后下一轮即生效。
    """
    global _PRODUCTS_CACHE, _PRODUCTS_SIG
    path = _catalog_path()
    sig: tuple[str, float, int] = ("", 0.0, 0)
    if path is not None:
        try:
            st = path.stat()
            sig = (str(path), st.st_mtime, st.st_size)
        except OSError:
            path = None
    with _PRODUCTS_LOCK:
        if _PRODUCTS_SIG == sig:
            return _PRODUCTS_CACHE
        merged: dict[str, Product] = {p.key: p for p in PRODUCTS}
        if path is not None:
            loaded = _load_catalog(path)
            if loaded:
                for p in loaded:
                    merged[p.key] = p  # dict 覆盖保序：已有产品位置不变，新 key 追加末尾
                logger.info("已加载产品目录 %s：%d 个产品", path, len(merged))
        _PRODUCTS_CACHE = tuple(merged.values())
        _PRODUCTS_SIG = sig
        return _PRODUCTS_CACHE


def catalog_signature() -> tuple[str, float, int]:
    """产品目录指纹，用于让文档归类缓存随目录修改一起失效。"""
    products()
    with _PRODUCTS_LOCK:
        return _PRODUCTS_SIG


def refresh_catalog() -> tuple[Product, ...]:
    """强制忽略 mtime 缓存重读（设置页保存后调用）。"""
    global _PRODUCTS_SIG
    with _PRODUCTS_LOCK:
        _PRODUCTS_SIG = ("", 0.0, 0)
    return products()


def _product_by_key() -> dict[str, Product]:
    return {p.key: p for p in products()}


_CJK_RE = re.compile(r"[一-鿿]")
_ASCII_ALIAS_RE = r"(?<![a-z0-9]){}(?![a-z0-9])"
_ASCII_PREFIX_RE = r"(?<![a-z0-9]){}[a-z0-9_-]*"


def product_label(key: str) -> str:
    p = _product_by_key().get(key)
    return p.label if p else key


def product_labels(keys: Iterable[str]) -> list[str]:
    return [product_label(k) for k in keys]


def _match_alias(text_lower: str, alias: str) -> bool:
    if _CJK_RE.search(alias):
        return alias in text_lower
    return re.search(_ASCII_ALIAS_RE.format(re.escape(alias)), text_lower) is not None


def _match_prefix(text_lower: str, prefix: str) -> bool:
    return re.search(_ASCII_PREFIX_RE.format(re.escape(prefix)), text_lower) is not None


# ---------------------------------------------------------------------------
# 文档归类
# ---------------------------------------------------------------------------

def classify_document(filename: str, sample_text: str = "") -> str:
    """按文件名 + 正文采样把文档归到一个产品；无法确定时返回 ""（不猜）。"""
    name_low = (filename or "").lower()
    body_low = (sample_text or "").lower()
    scores: dict[str, int] = {}
    for p in products():
        score = 0
        for alias in p.aliases:
            if _match_alias(name_low, alias):
                score += 6
            if body_low and _match_alias(body_low, alias):
                score += 3
        for prefix in p.model_prefixes:
            if _match_prefix(name_low, prefix):
                score += 2
            if body_low and _match_prefix(body_low, prefix):
                score += 1
        if score:
            scores[p.key] = score
    if not scores:
        return ""
    best = max(scores.values())
    winners = [k for k, v in scores.items() if v == best]
    # 多个产品同分（如正文同时提到两家）→ 不归类，避免错误锁定
    return winners[0] if len(winners) == 1 else ""


def document_product_map(ctx: "AppContext") -> dict[str, str]:
    """{doc_id: product_key}，按 documents 表当前状态缓存；改名/增删文档后自动重算。"""
    with ctx.db.lock:
        rows = ctx.db.conn.execute(
            "SELECT id, filename, chunk_count FROM documents"
        ).fetchall()
    # 产品目录改动后归类结果可能变化，一并纳入缓存指纹
    signature = (
        tuple((r["id"], r["filename"], r["chunk_count"]) for r in rows),
        catalog_signature(),
    )
    with ctx._product_map_lock:
        if ctx._product_map_signature == signature:
            return dict(ctx._product_map)

    mapping: dict[str, str] = {}
    for r in rows:
        product = classify_document(r["filename"])
        if not product:
            sample = _sample_document_text(ctx, r["id"])
            product = classify_document(r["filename"], sample)
        mapping[r["id"]] = product

    with ctx._product_map_lock:
        ctx._product_map = mapping
        ctx._product_map_signature = signature
        return dict(mapping)


def _sample_document_text(ctx: "AppContext", doc_id: str) -> str:
    """取该文档前几段正文用于品牌识别（文件名看不出来时）。"""
    try:
        with ctx.db.lock:
            rows = ctx.db.conn.execute(
                "SELECT content FROM chunks WHERE doc_id=? ORDER BY seq LIMIT 3",
                (doc_id,),
            ).fetchall()
        return "\n".join(r["content"] for r in rows)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 问题识别
# ---------------------------------------------------------------------------

_INSTRUCTION_HINT_RE = re.compile(
    r"指令|命令|参数|寄存器|关键字|语句|command|instruction|opcode|keyword", re.I
)
_ASCII_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9_]{1,19}")
# CANopen/寄存器地址这类指令参数，如 0x607A、0x60
_HEX_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])0x[0-9A-Fa-f]{2,16}")
# 常见英文缩写，避免被当成指令词做精确过滤
_COMMON_CAPS = {
    "PDF", "DOC", "DOCX", "XLS", "XLSX", "CSV", "TXT", "MD", "API", "CPU", "USB",
    "HTTP", "HTTPS", "URL", "URI", "FAQ", "OK", "ID", "IO", "PLC", "RAG", "SSE",
    "AI", "CN", "EN", "JSON", "XML", "HTML", "GUI", "SDK", "CLI", "PNG", "JPG",
    "JPEG", "BMP", "TIFF", "ZIP", "AKAI", "RYE",
}
_COMMON_WORDS = {
    "the", "and", "for", "with", "how", "what", "why", "use", "using", "set",
    "get", "can", "does", "are", "is", "to", "of", "in", "on", "a", "an",
    # 问题里描述“指令”本身的词，不是指令名
    "command", "commands", "instruction", "instructions", "opcode", "keyword",
    "parameter", "parameters", "option", "value",
}
_OTHERS_RE = re.compile(
    r"其他产品|其他品牌|其它产品|其它品牌|别的品牌|别家|其他厂家|其他型号|其他系列"
    r"|所有产品|全部产品|各家产品|全部品牌|各家品牌"
)

# 常见功能词的同义/英文表达：模糊提问时追加检索，避免“回零 / 回原点 / Homing”
# 在不同厂商手册里写法不同导致漏召回。只做轻量扩展（每词最多 2 个变体）。
_TERM_VARIANTS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("回零", "回原点", "寻零", "找零"),
        ("回原点", "原点回归", "homing", "home"),
    ),
    (
        ("使能", "上电"),
        ("伺服使能", "servo on", "enable"),
    ),
    (
        ("报警", "故障", "报错"),
        ("报警", "故障", "alarm", "错误码"),
    ),
    (
        ("点动", "手动移动"),
        ("点动", "jog", "手动运行"),
    ),
    (
        ("限位",),
        ("限位", "正限位", "负限位", "limit"),
    ),
    (
        ("急停",),
        ("急停", "emergency stop", "estop"),
    ),
    (
        ("增益", "调参", "整定"),
        ("增益", "gain", "pid", "参数整定"),
    ),
)
_MAX_QUERY_VARIANTS = 2   # 控制额外嵌入调用次数（套餐端点限流约 6 次/分钟）


def query_variants(query: str) -> tuple[str, ...]:
    """模糊提问 → 追加的同义词检索语句（去掉原问题里已有的词）。"""
    text = query or ""
    low = text.lower()
    extras: list[str] = []
    for triggers, variants in _TERM_VARIANTS:
        if not any(t in text for t in triggers):
            continue
        for v in variants:
            if v.lower() in low or v in extras:
                continue
            extras.append(v)
    return tuple(extras[:_MAX_QUERY_VARIANTS])


# 多主题问题分隔符：只切明显并列的连词/标点，不对「和/或」这类高频字误切
_QUERY_SPLIT_RE = re.compile(r"、|；|;|\n|以及|还有|并且|同时")


def decompose_query(query: str, max_parts: int = 3) -> tuple[str, ...]:
    """把「回零、报警、点动」这类多主题问题拆成子查询（用于补充关键词召回）。

    只在 2~3 个子问题、且至少一个子问题足够长时拆分；拆不出有意义的部分时返回空。
    """
    text = (query or "").strip()
    if len(text) < 8:
        return ()
    parts = [p.strip(" \t，,。.？?！!") for p in _QUERY_SPLIT_RE.split(text)]
    parts = [p for p in parts if len(p) >= 4]
    if not (2 <= len(parts) <= max_parts):
        return ()
    if not any(len(p) >= 5 for p in parts):
        return ()
    return tuple(parts[:max_parts])


_FOLLOWUP_HINTS = (
    "具体", "详细", "步骤", "展开", "再", "还有", "然后", "接着",
    "为什么", "怎么", "如何", "呢", "上面", "上述", "刚才", "前面", "这个", "那个",
)


def contextualize_query(
    query: str, previous_texts: list[str], route: "Route | None"
) -> str:
    """把省略式追问补全成可检索的查询。

    「ACS 如何回零？」→「具体步骤呢」时，只用后一句做 embedding 会丢失主题；
    这里只把上一轮有实质内容的问题拼到检索语句里（不改变展示给模型的原问题）。
    """
    q = (query or "").strip()
    if route is None or not route.context or not previous_texts:
        return q
    if len(q) > 40:
        return q
    # 没有明显追问特征、本身又是完整问题时，不做改写，避免污染正常查询
    if len(q) > 12 and not any(h in q for h in _FOLLOWUP_HINTS):
        return q
    prev = next(
        (t.strip() for t in reversed(previous_texts) if len(t.strip()) >= 6),
        "",
    )
    if not prev or prev == q:
        return q
    return f"{prev} {q}"[:160]


def detect_product_keys(text: str) -> list[str]:
    """识别文本中明确提到的产品；强别名优先于型号前缀，按匹配强度排序。"""
    low = (text or "").lower()
    strong: list[tuple[str, int]] = []
    weak: list[tuple[str, int]] = []
    for p in products():
        best_alias = max((len(a) for a in p.aliases if _match_alias(low, a)), default=0)
        if best_alias:
            strong.append((p.key, 100 + best_alias))
            continue
        best_prefix = max((len(x) for x in p.model_prefixes if _match_prefix(low, x)), default=0)
        if best_prefix:
            weak.append((p.key, best_prefix))
    return [k for k, _ in sorted(strong, key=lambda kv: kv[1], reverse=True)] + [
        k for k, _ in sorted(weak, key=lambda kv: kv[1], reverse=True)
    ]


def extract_instruction_tokens(query: str) -> tuple[str, ...]:
    """提取疑似指令/命令词（PTP、MST、HOME…）。

    规则：全大写词、含数字的英文词，或在“指令/命令”语境下的英文词；
    产品名（ACS、CDHD、UDM 等）不算指令词，否则会因片段前缀而误命中整篇文档。
    """
    hint = bool(_INSTRUCTION_HINT_RE.search(query or ""))
    tokens: list[str] = [m.group(0) for m in _HEX_TOKEN_RE.finditer(query or "")]
    for m in _ASCII_TOKEN_RE.finditer(query or ""):
        raw = m.group(0).strip("_")
        if len(raw) < 2:
            continue
        up = raw.upper()
        if up in _COMMON_CAPS:
            continue
        if detect_product_keys(raw):  # 品牌 / 型号
            continue
        if raw.isupper() or any(ch.isdigit() for ch in raw) or (
            hint and raw.lower() not in _COMMON_WORDS
        ):
            tokens.append(raw)
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        k = t.upper()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return tuple(out)


def content_has_any_token(content: str, tokens: Iterable[str]) -> bool:
    tokens = tuple(tokens)
    if not tokens:
        return False
    body = _chunk_body(content)
    return any(_token_in_text(body, t) for t in tokens)


def _chunk_body(content: str) -> str:
    """去掉切分器加的《文件名》溯源前缀，只在正文里找指令词。"""
    if content.startswith("《") and "\n" in content:
        return content.split("\n", 1)[1]
    return content


def _token_in_text(text: str, token: str) -> bool:
    return re.search(_ASCII_ALIAS_RE.format(re.escape(token)), text, re.I) is not None


def previous_user_texts(messages: list[Any], query: str) -> list[str]:
    from langchain_core.messages import HumanMessage

    users = [str(m.content) for m in messages if isinstance(m, HumanMessage)]
    if users and users[-1].strip() == (query or "").strip():
        users = users[:-1]
    return users[-6:]


def session_products(previous_texts: list[str]) -> list[str]:
    """会话产品上下文：从本会话的历史用户消息里，取最近一次的产品范围表态。

    倒序扫描（previous_texts 按时间从旧到新）：
    - 最近一条明确“点名品牌/型号”的消息 → 返回这些 key（可能多个，表示此前在做对比）；
    - 最近一条明确要求“其他/全部产品”的消息 → 返回空列表（会话范围已解除）；
    - 都没提到 → 空列表（会话尚未确定产品，走跨产品覆盖）。
    """
    for text in reversed(previous_texts or []):
        if _OTHERS_RE.search(text or ""):
            return []
        keys = detect_product_keys(text)
        if keys:
            return keys
    return []


def _is_repeat_question(tokens: Iterable[str], previous_texts: list[str]) -> bool:
    tokens = tuple(tokens)
    if not tokens or not previous_texts:
        return False
    prev = "\n".join(previous_texts)
    return any(_token_in_text(prev, t) for t in tokens)


# ---------------------------------------------------------------------------
# 路由决策
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Route:
    products: tuple[str, ...] = ()          # 问题明确指定的产品（explicit / context）
    source: str = "none"                    # explicit / context / multi / none
    tokens: tuple[str, ...] = ()            # 指令/命令词
    exact: bool = False                     # 片段是否已按指令词精确过滤
    relaxed: bool = False                   # 用户明确要求看其他产品
    doc_ids: tuple[str, ...] | None = None  # None=不限制；空元组=限定但无文档
    searched: tuple[str, ...] = ()          # 模糊提问时实际参与检索的产品线
    note: str = ""

    @property
    def labels(self) -> list[str]:
        return product_labels(self.products)

    @property
    def searched_labels(self) -> list[str]:
        return product_labels(self.searched)

    @property
    def scoped(self) -> bool:
        return self.doc_ids is not None

    @property
    def multi(self) -> bool:
        """本会话首次模糊提问：跨产品全覆盖检索，不锁定单一主导产品。"""
        return self.source == "multi"

    @property
    def context(self) -> bool:
        """本轮未点名产品，但沿用了本会话此前确定的产品范围。"""
        return self.source == "context"


def docs_for_products(
    keys: Iterable[str], product_map: dict[str, str]
) -> list[str]:
    want = set(keys)
    return [doc_id for doc_id, product in product_map.items() if product in want]


def grouped_docs(
    product_map: dict[str, str],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """按产品目录顺序，返回知识库中实际有文档的产品及其 doc_ids。"""
    groups: list[tuple[str, tuple[str, ...]]] = []
    for p in products():
        ids = docs_for_products((p.key,), product_map)
        if ids:
            groups.append((p.key, tuple(ids)))
    return tuple(groups)


def unclassified_docs(product_map: dict[str, str]) -> tuple[str, ...]:
    """未能归入任何产品的文档（文件名/正文都看不出品牌）。"""
    return tuple(doc_id for doc_id, key in product_map.items() if not key)


def retrieval_scopes(
    product_map: dict[str, str],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """跨产品检索范围：先各产品线，再未归类文档（tag 为空串，最后合并）。"""
    scopes: list[tuple[str, tuple[str, ...]]] = list(grouped_docs(product_map))
    others = unclassified_docs(product_map)
    if others:
        scopes.append(("", others))
    return tuple(scopes)


def product_scopes(
    keys: Iterable[str],
    product_map: dict[str, str],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """只对问题点名的多个产品做分产品检索（对比类问题也要逐产品配额）。"""
    want = set(keys)
    scopes: list[tuple[str, tuple[str, ...]]] = []
    for p in products():
        if p.key not in want:
            continue
        ids = docs_for_products((p.key,), product_map)
        if ids:
            scopes.append((p.key, tuple(ids)))
    return tuple(scopes)


def analyze_query(
    query: str,
    previous_texts: list[str],
    product_map: dict[str, str],
) -> Route:
    """问题 → 路由决策（检索前调用；不发起任何模型请求）。

    优先级：
    1. 当前问题点名产品 → explicit（同时刷新会话产品范围）；
    2. 当前问题明确要求“其他产品/全部产品” → 解除范围，走 multi；
    3. 当前问题模糊，但本会话此前点过产品 → context，只在该产品范围内检索；
    4. 本会话从未确定过产品（首次模糊提问）→ multi，全产品覆盖。
    """
    explicit = detect_product_keys(query)
    tokens = extract_instruction_tokens(query)
    wants_others = bool(_OTHERS_RE.search(query or ""))
    relaxed = _is_repeat_question(tokens, previous_texts or []) or wants_others

    # 用户本轮明确要求看其他/全部产品：既解除当前问题里的产品指向，也不沿用会话范围
    if wants_others:
        explicit = []

    # 1) 当前问题点名产品：本轮以当前问题为准，同时成为新的会话范围。
    if explicit:
        doc_ids = docs_for_products(explicit, product_map)
        return Route(
            products=tuple(explicit),
            source="explicit",
            tokens=tokens,
            exact=False,
            relaxed=relaxed,
            doc_ids=tuple(doc_ids),
            note="问题明确指定了产品",
        )

    # 2) 本轮模糊，但本会话此前明确过产品 → 沿用该产品范围，只检索该产品资料。
    context = [] if wants_others else session_products(previous_texts)
    if context:
        doc_ids = docs_for_products(context, product_map)
        return Route(
            products=tuple(context),
            source="context",
            tokens=tokens,
            exact=False,
            relaxed=relaxed,
            doc_ids=tuple(doc_ids),
            note="问题未点名产品：沿用本会话已确定的产品范围",
        )

    # 3) 本会话首次模糊提问（从未点过产品）→ 全产品覆盖检索。
    return Route(
        products=(),
        source="multi",
        tokens=tokens,
        exact=False,
        relaxed=relaxed,
        doc_ids=None,
        note="问题未点名产品：跨产品全覆盖检索",
    )
