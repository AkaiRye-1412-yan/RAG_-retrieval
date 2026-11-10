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

产品目录（`PRODUCTS`）按文件名 + 片段正文采样做归类；新增品牌只需在此追加一项。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from akairye_rag.core.app_context import AppContext
    from akairye_rag.core.settings import Settings

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

_PRODUCT_BY_KEY = {p.key: p for p in PRODUCTS}

_CJK_RE = re.compile(r"[一-鿿]")
_ASCII_ALIAS_RE = r"(?<![a-z0-9]){}(?![a-z0-9])"
_ASCII_PREFIX_RE = r"(?<![a-z0-9]){}[a-z0-9_-]*"


def product_label(key: str) -> str:
    p = _PRODUCT_BY_KEY.get(key)
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
    for p in PRODUCTS:
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
    signature = tuple((r["id"], r["filename"], r["chunk_count"]) for r in rows)
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


def detect_product_keys(text: str) -> list[str]:
    """识别文本中明确提到的产品；强别名优先于型号前缀，按匹配强度排序。"""
    low = (text or "").lower()
    strong: list[tuple[str, int]] = []
    weak: list[tuple[str, int]] = []
    for p in PRODUCTS:
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
    for p in PRODUCTS:
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
    for p in PRODUCTS:
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
