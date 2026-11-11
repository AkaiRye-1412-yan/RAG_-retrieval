"""应用级装配：配置存储、数据库、向量库、任务管理器在启动时组装一次。"""
from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from akairye_rag.core import paths
from akairye_rag.core.logging import setup_logging
from akairye_rag.core.settings import SettingsStore
from akairye_rag.db import repos
from akairye_rag.db.connection import Database
from akairye_rag.ingest.service import JobManager
from akairye_rag.providers.embeddings import build_embeddings
from akairye_rag.retrieval.sqlite_store import SQLiteVectorStore

if TYPE_CHECKING:
    from akairye_rag.core.settings import Settings

logger = logging.getLogger(__name__)

# 跨产品全覆盖检索：每个产品线/未归类文档至少/至多取多少条片段。
# 默认 TOP_K=6 → 每产品 6 条；产品数一般 ≤4，总片段量可控。
MULTI_MIN_PER_SCOPE = 3
MULTI_MAX_PER_SCOPE = 8
MULTI_VARIANT_HITS = 2   # 同义词变体查询每个产品最多补充 2 条

# 混合检索融合参数
RRF_K = 60               # Reciprocal Rank Fusion 常数
MIN_SEMANTIC_CUTOFF = 0.20  # 自适应阈值下限，避免模型分数分布偏低时全灭
KEYWORD_KEEP_RANK = 5    # 关键词排名前 N 的片段允许略低余弦分入选
NEIGHBOR_MAX_EXTRA = 4   # 命中片段后最多追加的前后相邻片段数


class AppContext:
    def __init__(self) -> None:
        paths.chdir_to_app_dir()
        self.settings_store = SettingsStore()  # 首启时生成 .env 模板并加载
        s = self.settings_store.get()
        setup_logging(s.data_dir)
        paths.ensure_runtime_dirs(s.data_dir)
        logger.info("数据目录: %s", s.data_dir_path)

        self.db = Database(s.db_path)
        # 上次异常退出时，任务线程随进程消失：把卡在中间态的文档标记为中断
        self.db.conn.execute(
            """UPDATE documents
               SET status='error', error='程序重启导致中断，请在向量库页执行「重建索引」'
               WHERE status IN ('pending','parsing','splitting','embedding')"""
        )
        self.db.conn.commit()
        self.vector_store = SQLiteVectorStore(
            self.db,
            embeddings_factory=lambda: build_embeddings(self.settings_store.get()),
            cache_on=s.vector_cache_on,
        )
        # 文档 → 产品线 归类缓存（由 retrieval.router.document_product_map 维护）
        self._product_map: dict[str, str] = {}
        self._product_map_signature: tuple | None = None
        self._product_map_lock = threading.RLock()
        self.jobs = JobManager(self)

    def uploads_dir(self) -> Path:
        return paths.uploads_dir(self.settings_store.get().data_dir)

    def upload_path(self, doc_id: str, ext: str) -> Path:
        return self.uploads_dir() / f"{doc_id}.{ext}"

    async def kb_search(
        self,
        query: str,
        s: "Settings",
        *,
        doc_ids: tuple[str, ...] | None = None,
        exact_tokens: tuple[str, ...] = (),
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """知识库检索（线程池执行，避免阻塞事件循环）。

        doc_ids：产品分流后的文档范围（None=全库；空元组=该产品无文档，直接无命中）。
        exact_tokens：指令/命令词，命中片段优先；没有任何精确命中时回退语义结果。
        """
        return await asyncio.to_thread(
            self._kb_search_sync, query, s, doc_ids, exact_tokens, limit
        )

    async def kb_search_multi(
        self,
        query: str,
        s: "Settings",
        scopes: tuple[tuple[str, tuple[str, ...]], ...],
        *,
        exact_tokens: tuple[str, ...] = (),
        variants: tuple[str, ...] = (),
        per_limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """跨产品全覆盖检索：每个 scope（产品线/未归类文档）各取一批片段。

        模糊提问（未点名品牌）用它，保证高创、ACS、AGITO 等每个产品的相关资料
        都进入上下文，而不是被全库 top-k 的单一产品挤掉。返回片段带 product_key。
        查询向量只算一次（变体查询各算一次），避免多路检索重复请求嵌入接口。
        """
        return await asyncio.to_thread(
            self._kb_search_multi_sync, query, s, scopes, exact_tokens, variants, per_limit
        )

    # ---- 混合检索：向量召回 + FTS5 关键词召回 → RRF 融合 ----

    @staticmethod
    def _rrf(rank: int) -> float:
        return 1.0 / (RRF_K + rank + 1)

    def _fuse_hits(
        self,
        query_vec,
        vector_hits: list[dict[str, Any]],
        keyword_hits: list[tuple[str, float]],
    ) -> list[dict[str, Any]]:
        """按 Reciprocal Rank Fusion 合并两路结果；关键词独有的片段补算余弦分。"""
        fused: dict[str, dict[str, Any]] = {}
        for rank, h in enumerate(vector_hits):
            item = dict(h)
            item["_rrf"] = self._rrf(rank)
            item["kw_rank"] = None
            fused[item["id"]] = item

        kw_ids: list[str] = []
        seen: set[str] = set()
        for cid, _bm in keyword_hits:
            if cid in seen:
                continue
            seen.add(cid)
            kw_ids.append(cid)

        missing = [cid for cid in kw_ids if cid not in fused]
        if missing:
            for h in self.vector_store.chunks_by_ids(missing, query_vec=query_vec):
                item = dict(h)
                item["_rrf"] = 0.0
                item["kw_rank"] = None
                fused[item["id"]] = item

        for rank, cid in enumerate(kw_ids):
            item = fused.get(cid)
            if item is None:
                continue
            item["_rrf"] += self._rrf(rank)
            if item["kw_rank"] is None or rank < item["kw_rank"]:
                item["kw_rank"] = rank
        return sorted(
            fused.values(), key=lambda h: float(h.get("_rrf") or 0.0), reverse=True
        )

    @staticmethod
    def _apply_cutoff(
        hits: list[dict[str, Any]], threshold: float
    ) -> list[dict[str, Any]]:
        """自适应语义阈值：不低于「配置阈值」与「最高分-0.10」中较松者（且有下限）。"""
        if not hits:
            return []
        # 阈值配成 0 表示“不过滤”，尊重用户显式设置
        if threshold <= 0:
            return hits
        top = max(float(h.get("score") or 0.0) for h in hits)
        cut = max(MIN_SEMANTIC_CUTOFF, min(float(threshold), top - 0.10))
        out: list[dict[str, Any]] = []
        for h in hits:
            score = h.get("score")
            if score is None:
                continue
            score = float(score)
            kw_rank = h.get("kw_rank")
            if score >= cut:
                out.append(h)
            elif (
                kw_rank is not None
                and kw_rank < KEYWORD_KEEP_RANK
                and score >= max(0.15, cut - 0.10)
            ):
                # 关键词排名靠前但余弦分略低的片段也保留（专有名词/缩写常见）
                out.append(h)
        return out

    def _keyword_hits(
        self,
        s: "Settings",
        query: str,
        doc_ids: tuple[str, ...] | None,
        exact_tokens: tuple[str, ...],
        *,
        extra_k: int = 24,
    ) -> list[tuple[str, float]]:
        if not getattr(s, "hybrid_search", True):
            return []
        out = list(self.vector_store.search_keyword(query, k=extra_k, doc_ids=doc_ids))
        if getattr(s, "query_decompose", True):
            from akairye_rag.retrieval.router import decompose_query

            for part in decompose_query(query):
                out.extend(
                    self.vector_store.search_keyword(part, k=16, doc_ids=doc_ids)
                )
        if exact_tokens:
            # 指令词单独走一次关键词检索，确保不被语义候选排名截断
            out.extend(
                self.vector_store.search_keyword(
                    " ".join(exact_tokens), k=24, doc_ids=doc_ids
                )
            )
        return out

    def _expand_neighbors(
        self, hits: list[dict[str, Any]], max_extra: int = NEIGHBOR_MAX_EXTRA
    ) -> list[dict[str, Any]]:
        """给命中片段补上同文档的前后相邻块，避免步骤被 500 字切分边界截断。"""
        if not hits or max_extra <= 0:
            return hits
        ids = {h.get("id") for h in hits}
        extras: list[dict[str, Any]] = []
        for h in hits:
            if len(extras) >= max_extra:
                break
            doc_id, seq = h.get("doc_id"), h.get("seq")
            if not doc_id or seq is None:
                continue
            try:
                with self.db.lock:
                    rows = self.db.conn.execute(
                        "SELECT id, doc_id, seq, content, locator FROM chunks"
                        " WHERE doc_id=? AND seq IN (?,?)",
                        (doc_id, int(seq) + 1, int(seq) - 1),
                    ).fetchall()
            except Exception:
                continue
            # 下一块优先于上一块
            rows = sorted(rows, key=lambda r: (0 if r["seq"] == int(seq) + 1 else 1))
            for r in rows:
                if r["id"] in ids:
                    continue
                ids.add(r["id"])
                item = {
                    "id": r["id"],
                    "doc_id": r["doc_id"],
                    "seq": r["seq"],
                    "content": r["content"],
                    "locator": repos.json_loads(r["locator"]),
                    "score": h.get("score"),
                    "neighbor": True,
                }
                if h.get("product_key"):
                    item["product_key"] = h["product_key"]
                extras.append(item)
                if len(extras) >= max_extra:
                    break
        return hits + extras

    def _kb_search_multi_sync(
        self,
        query: str,
        s: "Settings",
        scopes: tuple[tuple[str, tuple[str, ...]], ...],
        exact_tokens: tuple[str, ...],
        variants: tuple[str, ...],
        per_limit: int | None,
    ) -> list[dict[str, Any]]:
        if not scopes:
            return []
        per = per_limit or max(
            MULTI_MIN_PER_SCOPE, min(MULTI_MAX_PER_SCOPE, int(s.top_k or 6))
        )
        # 产品线变多时，单产品配额自动下调，保证总片段量有界（每产品至少 2 条）
        total_cap = max(16, int(getattr(s, "multi_max_total", 24) or 24))
        if per * len(scopes) > total_cap:
            per = max(2, total_cap // len(scopes))
        threshold = float(s.similarity_threshold)
        if exact_tokens and threshold > 0.25:
            threshold = 0.25
        from akairye_rag.retrieval.router import content_has_any_token

        # 1) 主查询：每个产品线各取一批（向量 + 关键词宽召回后融合），查询向量只算一次
        qvec = self.vector_store.embed_query(query)
        candidate: dict[str, list[dict[str, Any]]] = {}
        for tag, doc_ids in scopes:
            fetch_k = max(per * 4, 24)
            vec_hits = self.vector_store.search(
                query,
                k=fetch_k,
                threshold=None,
                filter={"doc_ids": tuple(doc_ids)},
                query_vec=qvec,
            )
            kw_hits = self._keyword_hits(
                s, query, tuple(doc_ids), exact_tokens, extra_k=max(24, fetch_k)
            )
            hits = self._fuse_hits(qvec, vec_hits, kw_hits)
            exact_ok = False
            if exact_tokens:
                matched = [
                    h for h in hits if content_has_any_token(h["content"], exact_tokens)
                ]
                if matched:  # 精确命中优先；该产品全无命中时保留融合结果
                    hits = matched
                    exact_ok = True
            if not exact_ok:
                hits = self._apply_cutoff(hits, threshold)
            candidate[tag] = list(hits)

        # 2) 同义词补充：只给“主查询召回不足 per 条”的产品补，且每产品只补少量。
        #    所有产品都取满时完全跳过，避免额外嵌入调用触发套餐端点限流。
        scope_map = dict(scopes)

        def distinct_count(tag: str) -> int:
            return len({h.get("id") for h in candidate[tag]})

        short = [tag for tag in candidate if distinct_count(tag) < per]
        for v in (variants if not exact_tokens else ()):
            if v == query or not short:
                continue
            vvec = self.vector_store.embed_query(v)
            for tag in short:
                doc_ids = scope_map[tag]
                extra = self.vector_store.search(
                    v,
                    k=MULTI_VARIANT_HITS * 2,
                    threshold=None,
                    filter={"doc_ids": tuple(doc_ids)},
                    query_vec=vvec,
                )
                for h in extra:
                    item = dict(h)
                    item["_rrf"] = 0.0  # 变体补充排在主查询结果之后
                    item["kw_rank"] = None
                    candidate[tag].append(item)
            short = [tag for tag in short if distinct_count(tag) < per]

        # 3) 合并去重：按产品目录顺序输出，产品内按融合排名降序，每产品截断 per 条
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for tag, _doc_ids in scopes:
            hits = sorted(
                candidate.get(tag, []),
                key=lambda h: (
                    float(h.get("_rrf") or 0.0),
                    float(h.get("score") or 0.0),
                ),
                reverse=True,
            )
            picked = 0
            for h in hits:
                if picked >= per:
                    break
                cid = h.get("id")
                if cid in seen:
                    continue
                seen.add(cid)
                item = dict(h)
                item["product_key"] = tag
                merged.append(item)
                picked += 1
        if getattr(s, "neighbor_expand", True):
            merged = self._expand_neighbors(merged)
        return merged

    def _kb_search_sync(
        self,
        query: str,
        s: "Settings",
        doc_ids: tuple[str, ...] | None,
        exact_tokens: tuple[str, ...],
        limit: int | None,
    ) -> list[dict[str, Any]]:
        cap = int(limit or s.top_k)
        # 指令问题放宽语义阈值，给“命令词精确命中但语义分数一般”的片段一个机会；
        # 后面的精确过滤会把噪声去掉。
        threshold = float(s.similarity_threshold)
        if exact_tokens and threshold > 0.25:
            threshold = 0.25
        fetch_k = max(cap * 4, 24)

        # 向量宽召回（不先卡阈值，留给融合后的自适应阈值统一裁剪）
        qvec = self.vector_store.embed_query(query)
        vec_hits = self.vector_store.search(
            query,
            k=fetch_k,
            threshold=None,
            filter={"doc_ids": doc_ids} if doc_ids is not None else None,
            query_vec=qvec,
        )
        kw_hits = self._keyword_hits(s, query, doc_ids, exact_tokens, extra_k=max(24, fetch_k))
        hits = self._fuse_hits(qvec, vec_hits, kw_hits)

        exact_ok = False
        if exact_tokens:
            from akairye_rag.retrieval.router import content_has_any_token

            matched = [h for h in hits if content_has_any_token(h["content"], exact_tokens)]
            if matched:  # 精确指令命中优先；全都没有时回退，避免误伤正常问答
                hits = matched
                exact_ok = True
        if not exact_ok:
            hits = self._apply_cutoff(hits, threshold)
        hits = hits[:cap]
        if getattr(s, "neighbor_expand", True):
            hits = self._expand_neighbors(hits)
        return hits

    def shutdown(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass
