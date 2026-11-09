"""应用级装配：配置存储、数据库、向量库、任务管理器在启动时组装一次。"""
from __future__ import annotations

import asyncio
import logging
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
        self.jobs = JobManager(self)

    def uploads_dir(self) -> Path:
        return paths.uploads_dir(self.settings_store.get().data_dir)

    def upload_path(self, doc_id: str, ext: str) -> Path:
        return self.uploads_dir() / f"{doc_id}.{ext}"

    async def kb_search(self, query: str, s: "Settings") -> list[dict[str, Any]]:
        """知识库检索（线程池执行，避免阻塞事件循环），按 settings 快照取 top_k/阈值。"""
        return await asyncio.to_thread(
            self.vector_store.search,
            query,
            k=s.top_k,
            threshold=s.similarity_threshold,
        )

    def shutdown(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass
