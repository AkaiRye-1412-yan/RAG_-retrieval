"""自研向量存储：向量以 float32 BLOB 存于 SQLite，numpy 做归一化点积（=余弦）。

- 写入：embedding L2 归一化后 numpy.tobytes()，与分块文本同事务存入 chunks 表。
- 检索：缓存模式把全量矩阵载入内存做一次矩阵乘 + argpartition；
  VECTOR_CACHE=off 时分批流式扫描，内存有界。
- 实现 langchain_core VectorStore 接口，同时提供业务层 helper。
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
from openai import BadRequestError, RateLimitError
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore

from akairye_rag.db import repos
from akairye_rag.db.connection import Database

logger = logging.getLogger(__name__)

EMBED_BATCH = 32
SCAN_BATCH = 10_000
_CHUNK_INSERT_SQL = (
    "INSERT OR REPLACE INTO chunks(id, doc_id, seq, content, locator, dim, embedding, created_at)"
    " VALUES (?,?,?,?,?,?,?,?)"
)
MAX_429_RETRIES = 30          # 单批最多退避次数（足以跨越数分钟的严格限流窗）
BASE_PACE_SECONDS = 1.0       # 未遇限流时的批间间隔
MAX_PACE_SECONDS = 12.0       # 学到的最大批间间隔（套餐端点约 6~10s 放行一次大请求）
_BACKOFF_STEPS = (3, 6, 10, 12)  # 连续 429 的退避序列，之后稳定 12s


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    norm = float(np.linalg.norm(v))
    return v / norm if norm > 0 else v


class SQLiteVectorStore(VectorStore):
    def __init__(
        self,
        db: Database,
        embeddings_factory: Callable[[], Embeddings],
        *,
        cache_on: bool = True,
    ) -> None:
        self.db = db
        self._embeddings_factory = embeddings_factory
        self.cache_on = cache_on
        self._lock = threading.RLock()
        self._loaded = False
        self._ids: np.ndarray | None = None       # (n,) object
        self._doc_ids: np.ndarray | None = None   # (n,) object
        self._V: np.ndarray | None = None         # (n, dim) float32
        self._last_rowid: int | None = None       # 已并入内存矩阵的最大 chunks.rowid（增量加载水印）
        self._embed_limit: int | None = None      # 端点返回的每批上限（如套餐端点 10）
        self._embed_gap = BASE_PACE_SECONDS       # 批间节流间隔，遇 429 后自适应拉大

    # ---- LangChain 契约 ----
    @property
    def embeddings(self) -> Embeddings:  # type: ignore[override]
        return self._embeddings_factory()

    @classmethod
    def from_texts(
        cls,
        texts: Sequence[str],
        embedding: Embeddings,
        metadatas: Sequence[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> "SQLiteVectorStore":
        # 仅用于满足 ABC；业务入库走 add_fragments
        raise NotImplementedError("from_texts 未实现，请使用 add_fragments 入库。")

    def similarity_search(self, query: str, k: int = 4, filter: dict | None = None, **kwargs: Any):
        results = self.search(query, k=k, filter=filter)
        return [
            Document(
                page_content=r["content"],
                metadata={"doc_id": r["doc_id"], "seq": r["seq"], "locator": r["locator"]},
            )
            for r in results
        ]

    # ---- 业务 helper ----
    @property
    def dim(self) -> int | None:
        v = repos.kv_get(self.db, "embedding_dim")
        return int(v) if v else None

    def count(self) -> int:
        with self.db.lock:
            return self.db.conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"]

    def cache_memory_bytes(self) -> int:
        with self._lock:
            return 0 if self._V is None else int(self._V.nbytes)

    def add_fragments(
        self,
        doc_id: str,
        fragments: Sequence[tuple[str, dict[str, Any]]],
        *,
        batch_size: int = EMBED_BATCH,
        on_progress: Callable[[int], None] | None = None,
    ) -> int:
        """每批嵌入成功即提交入库（长文档遭遇限流也不丢进度），并回调累计已入库条数。"""
        if not fragments:
            return 0
        now = repos.now_iso()
        dim_checked = False

        def persist(batch_vecs: list[np.ndarray], start: int) -> None:
            nonlocal dim_checked
            if not dim_checked:
                self._check_or_set_dim(batch_vecs[0].shape[0])
                dim_checked = True
            part = fragments[start : start + len(batch_vecs)]
            params: list[tuple[Any, ...]] = []
            for offset, ((text, locator), vec) in enumerate(zip(part, batch_vecs)):
                seq = start + offset + 1
                params.append(
                    (
                        f"{doc_id}-{seq}",
                        doc_id,
                        seq,
                        text,
                        repos.json_dumps(locator) if locator is not None else None,
                        int(vec.shape[0]),
                        vec.tobytes(),
                        now,
                    )
                )
            with self.db.lock:
                self.db.conn.executemany(_CHUNK_INSERT_SQL, params)
                self.db.conn.commit()
            # 纯追加写：不失效缓存，由 rowid 水印把新块增量并入内存矩阵（见 _merge_new_rows），
            # 避免长文档入库期间每次查询都全量重载。
            if on_progress:
                on_progress(start + len(batch_vecs))

        texts = [t for t, _ in fragments]
        self._embed(texts, batch_size=batch_size, on_batch=persist)
        return len(fragments)

    def embed_query(self, query: str) -> np.ndarray:
        """查询向量（已 L2 归一化）；多路检索时先算一次再传给 search，避免重复请求嵌入接口。"""
        emb = self.embeddings
        qraw = self._call_with_rate_guard(lambda: emb.embed_query(query))
        return _l2_normalize(np.asarray(qraw, dtype=np.float32))

    def search(
        self,
        query: str,
        *,
        k: int = 6,
        threshold: float | None = None,
        filter: dict | None = None,
        query_vec: np.ndarray | None = None,
    ) -> list[dict[str, Any]]:
        """返回 [{id, doc_id, seq, content, locator, score}]，按相关度降序，已按阈值过滤。"""
        qvec = query_vec if query_vec is not None else self.embed_query(query)
        cond = filter or {}
        doc_filter = cond.get("doc_id")
        # doc_ids：产品分流后限定在一批文档内检索（None=不限制；空集合=无可用文档）
        doc_ids = cond.get("doc_ids")
        if doc_ids is not None:
            doc_ids = tuple(doc_ids)
        with self._lock:
            if self.cache_on:
                hits = self._search_cached(qvec, k, doc_filter, doc_ids)
            else:
                hits = self._search_stream(qvec, k, doc_filter, doc_ids)
        if threshold is not None:
            hits = [h for h in hits if h[1] >= threshold]
        if not hits:
            return []
        # 取文本
        placeholders = ",".join("?" for _ in hits)
        with self.db.lock:
            rows = self.db.conn.execute(
                f"SELECT id, doc_id, seq, content, locator FROM chunks WHERE id IN ({placeholders})",
                [h[0] for h in hits],
            ).fetchall()
        text_map = {
            r["id"]: (r["doc_id"], r["seq"], r["content"], r["locator"]) for r in rows
        }
        out: list[dict[str, Any]] = []
        for cid, score in hits:
            if cid not in text_map:
                continue
            doc_id, seq, content, locator_raw = text_map[cid]
            locator = repos.json_loads(locator_raw)
            out.append(
                {
                    "id": cid,
                    "doc_id": doc_id,
                    "seq": seq,
                    "content": content,
                    "locator": locator,
                    "score": round(float(score), 4),
                }
            )
        return out

    def delete_for_doc(self, doc_id: str) -> None:
        with self.db.lock:
            self.db.conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            self.db.conn.commit()
        self._invalidate()

    def clear_all(self) -> None:
        with self.db.lock:
            self.db.conn.execute("DELETE FROM chunks")
            self.db.conn.commit()
        repos.kv_delete(self.db, "embedding_dim")
        self._invalidate()

    # ---- 内部实现 ----
    def _call_with_rate_guard(self, fn: Callable[[], Any]) -> Any:
        """单次嵌入调用 + 429 统一退避（SDK 内部重试已关闭，节奏完全由这里控制）。"""
        for attempt in range(MAX_429_RETRIES + 1):
            try:
                return fn()
            except RateLimitError as e:
                if attempt >= MAX_429_RETRIES:
                    raise
                wait = 0.0
                response = getattr(e, "response", None)
                if response is not None:
                    ra = response.headers.get("retry-after")
                    if ra and ra.replace(".", "", 1).isdigit():
                        wait = float(ra)
                if wait <= 0:
                    wait = _BACKOFF_STEPS[min(attempt, len(_BACKOFF_STEPS) - 1)]
                # 撞过限流就永久拉大后续批间隔（保守，不回弹），避免反复撞窗
                self._embed_gap = min(
                    MAX_PACE_SECONDS, max(self._embed_gap, min(wait, MAX_PACE_SECONDS))
                )
                logger.warning(
                    "嵌入接口限流(429)，%.0f 秒后重试（第 %d/%d 次）",
                    wait, attempt + 1, MAX_429_RETRIES,
                )
                time.sleep(wait)
        raise RuntimeError("unreachable")

    def _embed(
        self,
        texts: list[str],
        batch_size: int = EMBED_BATCH,
        on_batch: Callable[[list[np.ndarray], int], None] | None = None,
    ) -> list[np.ndarray]:
        if not texts:
            return []
        emb = self.embeddings
        vectors: list[np.ndarray] = []
        size = max(1, min(batch_size, self._embed_limit or batch_size))
        i = 0
        while i < len(texts):
            batch = texts[i : i + size]
            try:
                raw = self._call_with_rate_guard(lambda: emb.embed_documents(batch))
            except BadRequestError as e:
                msg = str(e)
                if "dimensions" in msg and "max" not in msg:
                    # 向量模型不接受当前维度（如 vision 模型只支持 2048），给出明确中文提示
                    raise ValueError(
                        "向量模型不支持当前 EMBEDDING_DIM 维度。"
                        "请在「系统配置」→向量模型配置中，将维度改为该模型支持的取值"
                        "（更换维度后需在「向量库」页重建索引）。"
                    ) from e
                # 不同端点批量上限不同（火山方舟套餐 /api/plan/v3 上限 10，标准端点更宽），
                # 从报错解析 "max N" 后自动降批重试，无需用户手工调参。
                m = re.search(r"max\s+(\d+)", msg)
                limit = int(m.group(1)) if m else 0
                if 0 < limit < size:
                    self._embed_limit = limit
                    size = limit
                    logger.info("嵌入接口批量上限为 %d，自动降批重试", size)
                    continue
                raise
            batch_vecs = [_l2_normalize(np.asarray(v, dtype=np.float32)) for v in raw]
            vectors.extend(batch_vecs)
            i += len(batch)
            if on_batch:
                on_batch(batch_vecs, i - len(batch))
            if i < len(texts):
                time.sleep(self._embed_gap)  # 批间节流，规避套餐端点限流
        return vectors

    def _check_or_set_dim(self, dim: int) -> None:
        existing = self.dim
        if existing is None:
            repos.kv_set(self.db, "embedding_dim", str(dim))
        elif existing != dim:
            raise ValueError(
                f"向量维度冲突：知识库现有维度 {existing}，当前向量模型输出 {dim}。"
                "请在向量库页执行「重建索引」后重试。"
            )

    def _invalidate(self) -> None:
        # 仅删除/清空等结构性变更时调用：下次检索整表重建矩阵。
        with self._lock:
            self._loaded = False
            self._ids = None
            self._doc_ids = None
            self._V = None
            self._last_rowid = None

    def _ensure_matrix(self) -> None:
        if self._loaded and self._V is not None:
            # 已载入：把水印之后新增的分块增量并入，避免每次检索重载全量矩阵
            self._merge_new_rows()
            return
        self._load_full()

    @staticmethod
    def _build_matrix(rows) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """将 (rowid?, id, doc_id, embedding) 行集转为与 _V/_ids/_doc_ids 对齐的并行数组。"""
        nrows = len(rows)
        if nrows == 0:
            return (
                np.empty((0, 0), dtype=np.float32),
                np.empty(0, dtype=object),
                np.empty(0, dtype=object),
            )
        dim = len(np.frombuffer(rows[0]["embedding"], dtype=np.float32))
        V = np.empty((nrows, dim), dtype=np.float32)
        ids = np.empty(nrows, dtype=object)
        doc_ids = np.empty(nrows, dtype=object)
        for i, r in enumerate(rows):
            V[i] = np.frombuffer(r["embedding"], dtype=np.float32)
            ids[i] = r["id"]
            doc_ids[i] = r["doc_id"]
        return V, ids, doc_ids

    def _load_full(self) -> None:
        dim = self.dim
        with self.db.lock:
            n = self.db.conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"]
            if n == 0 or dim is None:
                self._ids = np.empty(0, dtype=object)
                self._doc_ids = np.empty(0, dtype=object)
                self._V = np.empty((0, dim or 0), dtype=np.float32)
                self._last_rowid = 0
                self._loaded = True
                return
            rows = self.db.conn.execute(
                "SELECT rowid, id, doc_id, embedding FROM chunks ORDER BY rowid"
            ).fetchall()
        V, ids, doc_ids = self._build_matrix(rows)
        self._ids, self._doc_ids, self._V = ids, doc_ids, V
        self._last_rowid = rows[-1]["rowid"]
        self._loaded = True
        logger.info("向量矩阵已载入内存：%d 行 × %d 维，约 %.1f MB", n, dim, V.nbytes / 1048576)

    def _merge_new_rows(self) -> None:
        """把 rowid 水印之后新增的分块追加到内存矩阵；维度不一致时整表重建。"""
        assert self._V is not None and self._last_rowid is not None
        dim = self.dim
        if dim is None or self._V.shape[1] != dim:
            if self._V.shape[0] > 0:
                self._loaded = False
                self._load_full()
            return
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT rowid, id, doc_id, embedding FROM chunks WHERE rowid>? ORDER BY rowid",
                (self._last_rowid,),
            ).fetchall()
        if not rows:
            return
        V, ids, doc_ids = self._build_matrix(rows)
        with self._lock:
            self._V = np.concatenate([self._V, V], axis=0)
            self._ids = np.concatenate([self._ids, ids])
            self._doc_ids = np.concatenate([self._doc_ids, doc_ids])
            self._last_rowid = rows[-1]["rowid"]
        logger.info(
            "向量矩阵增量并入 %d 行，当前共 %d 行 × %d 维",
            len(rows), self._V.shape[0], self._V.shape[1],
        )

    def _search_cached(
        self,
        qvec: np.ndarray,
        k: int,
        doc_filter: str | None,
        doc_ids: tuple[str, ...] | None = None,
    ) -> list[tuple[str, float]]:
        self._ensure_matrix()
        assert self._V is not None and self._ids is not None and self._doc_ids is not None
        n = self._V.shape[0]
        if n == 0:
            return []
        scores = self._V @ qvec
        if doc_filter is not None:
            mask = self._doc_ids == doc_filter
            if not mask.any():
                return []
            scores = np.where(mask, scores, -np.inf)
        if doc_ids is not None:
            if not doc_ids:
                return []
            mask = np.isin(self._doc_ids, np.asarray(doc_ids, dtype=object))
            if not mask.any():
                return []
            scores = np.where(mask, scores, -np.inf)
        kk = min(k, n)
        idx = np.argpartition(scores, -kk)[-kk:]
        idx = idx[np.argsort(scores[idx])[::-1]]
        return [(str(self._ids[i]), float(scores[i])) for i in idx if np.isfinite(scores[i])]

    def _search_stream(
        self,
        qvec: np.ndarray,
        k: int,
        doc_filter: str | None,
        doc_ids: tuple[str, ...] | None = None,
    ) -> list[tuple[str, float]]:
        """分批加载、维护大小为 k 的 top-k 堆，内存有界。"""
        import heapq

        if doc_ids is not None and not doc_ids:
            return []
        allowed = set(doc_ids) if doc_ids is not None else None
        heap: list[tuple[float, str]] = []
        offset = 0
        with self.db.lock:
            total = self.db.conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"]
        while offset < total:
            with self.db.lock:
                rows = self.db.conn.execute(
                    "SELECT id, doc_id, embedding FROM chunks ORDER BY id LIMIT ? OFFSET ?",
                    (SCAN_BATCH, offset),
                ).fetchall()
            if not rows:
                break
            mat = np.empty((len(rows), qvec.shape[0]), dtype=np.float32)
            for i, r in enumerate(rows):
                mat[i] = np.frombuffer(r["embedding"], dtype=np.float32)
            scores = mat @ qvec
            for r, score in zip(rows, scores):
                if doc_filter is not None and r["doc_id"] != doc_filter:
                    continue
                if allowed is not None and r["doc_id"] not in allowed:
                    continue
                item = (float(score), str(r["id"]))
                if len(heap) < k:
                    heapq.heappush(heap, item)
                elif item[0] > heap[0][0]:
                    heapq.heapreplace(heap, item)
            offset += len(rows)
        return [(cid, score) for score, cid in sorted(heap, reverse=True)]
