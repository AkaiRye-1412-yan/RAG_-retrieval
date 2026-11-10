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
        threshold = s.similarity_threshold
        if exact_tokens and threshold > 0.25:
            threshold = 0.25
        from akairye_rag.retrieval.router import content_has_any_token

        # 1) 主查询：每个产品线各取一批，查询向量只算一次
        qvec = self.vector_store.embed_query(query)
        candidate: dict[str, list[dict[str, Any]]] = {}
        for tag, doc_ids in scopes:
            fetch_k = max(per, s.top_k * 4) if exact_tokens else per
            hits = self.vector_store.search(
                query,
                k=fetch_k,
                threshold=threshold,
                filter={"doc_ids": tuple(doc_ids)},
                query_vec=qvec,
            )
            if exact_tokens:
                matched = [h for h in hits if content_has_any_token(h["content"], exact_tokens)]
                if matched:  # 精确命中优先；该产品全无命中时保留语义结果
                    hits = matched
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
                candidate[tag].extend(
                    self.vector_store.search(
                        v,
                        k=MULTI_VARIANT_HITS,
                        threshold=threshold,
                        filter={"doc_ids": tuple(doc_ids)},
                        query_vec=vvec,
                    )
                )
            short = [tag for tag in short if distinct_count(tag) < per]

        # 3) 合并去重：按产品目录顺序输出，产品内按相关度降序，每产品截断 per 条
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for tag, _doc_ids in scopes:
            hits = sorted(
                candidate.get(tag, []),
                key=lambda h: float(h.get("score") or 0.0),
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
        return merged

    def _kb_search_sync(
        self,
        query: str,
        s: "Settings",
        doc_ids: tuple[str, ...] | None,
        exact_tokens: tuple[str, ...],
        limit: int | None,
    ) -> list[dict[str, Any]]:
        cap = limit or s.top_k
        fetch_k = max(cap, s.top_k * 4) if exact_tokens else cap
        # 指令问题放宽语义阈值，给“命令词精确命中但语义分数一般”的片段一个机会；
        # 后面的精确过滤会把噪声去掉。
        threshold = s.similarity_threshold
        if exact_tokens and threshold > 0.25:
            threshold = 0.25
        hits = self.vector_store.search(
            query,
            k=fetch_k,
            threshold=threshold,
            filter={"doc_ids": doc_ids} if doc_ids is not None else None,
        )
        if exact_tokens:
            from akairye_rag.retrieval.router import content_has_any_token

            matched = [h for h in hits if content_has_any_token(h["content"], exact_tokens)]
            if matched:  # 精确指令命中优先；全都没有时回退，避免误伤正常问答
                hits = matched
        return hits[:cap]

    def shutdown(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass
