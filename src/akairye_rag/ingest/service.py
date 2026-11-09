"""入库任务编排：上传后后台线程执行 解析→切分→嵌入→入库，进度供前端轮询。"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from akairye_rag.db import repos
from akairye_rag.ingest.parsers import parse_file
from akairye_rag.ingest.splitter import split_blocks

if TYPE_CHECKING:
    from akairye_rag.core.app_context import AppContext

logger = logging.getLogger(__name__)


@dataclass
class JobFile:
    doc_id: str
    filename: str
    stage: str = "waiting"   # waiting/parsing/splitting/embedding/done/error
    chunk_count: int = 0
    error: str | None = None


@dataclass
class Job:
    job_id: str
    kind: str                # ingest / reindex
    total: int
    done: int = 0
    status: str = "running"  # running/done/error
    current_file: str = ""
    files: list[JobFile] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None


class JobManager:
    def __init__(self, ctx: "AppContext") -> None:
        self.ctx = ctx
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()

    def _set(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
        return self._dump(job) if job else None

    @staticmethod
    def _dump(job: Job) -> dict[str, Any]:
        return {
            "job_id": job.job_id,
            "kind": job.kind,
            "status": job.status,
            "total": job.total,
            "done": job.done,
            "current_file": job.current_file,
            "files": [vars(f) for f in job.files],
            "created_at": job.created_at,
            "finished_at": job.finished_at,
        }

    # ---- 新建任务 ----
    def start_ingest(self, doc_ids: list[str]) -> str:
        job = Job(job_id=repos.new_id(), kind="ingest", total=len(doc_ids))
        for did in doc_ids:
            doc = repos.get_document(self.ctx.db, did)
            job.files.append(JobFile(doc_id=did, filename=doc["filename"] if doc else did))
        self._set(job)
        t = threading.Thread(target=self._run, args=(job.job_id, doc_ids), daemon=True)
        t.start()
        return job.job_id

    def start_reindex(self, docs: list[dict[str, Any]] | None = None) -> str:
        if docs is None:
            docs = repos.list_documents(self.ctx.db)
        job = Job(job_id=repos.new_id(), kind="reindex", total=len(docs))
        for d in docs:
            job.files.append(JobFile(doc_id=d["id"], filename=d["filename"]))
        self._set(job)
        doc_ids = [d["id"] for d in docs]
        t = threading.Thread(target=self._run, args=(job.job_id, doc_ids, True), daemon=True)
        t.start()
        return job.job_id

    # ---- 后台执行 ----
    def _run(self, job_id: str, doc_ids: list[str], reindex: bool = False) -> None:
        job = self._jobs[job_id]
        db = self.ctx.db
        try:
            if reindex:
                logger.info("重建索引：清空 chunks")
                self.ctx.vector_store.clear_all()
                repos.reset_documents_for_reindex(db)

            for jf in job.files:
                job.current_file = jf.filename
                doc = repos.get_document(db, jf.doc_id)
                if not doc:
                    jf.stage, jf.error = "error", "数据库记录不存在"
                    continue
                try:
                    self._process_one(job, jf, doc)
                except Exception as e:
                    logger.exception("文档处理失败: %s", jf.filename)
                    err = str(e)[:500]
                    jf.stage = "error"
                    jf.error = err
                    repos.update_document(db, jf.doc_id, status="error", error=err)
                finally:
                    job.done += 1
                    self._set(job)
            job.status = "error" if any(f.stage == "error" for f in job.files) else "done"
        except Exception as e:
            logger.exception("任务异常终止: %s", e)
            job.status = "error"
            for jf in job.files:
                if jf.stage not in ("done", "error"):
                    jf.stage = "error"
                    jf.error = str(e)[:500]
        finally:
            job.current_file = ""
            job.finished_at = time.time()
            self._set(job)

    def _process_one(self, job: Job, jf: JobFile, doc: dict) -> None:
        ctx = self.ctx
        s = ctx.settings_store.get()
        path = ctx.upload_path(jf.doc_id, doc["ext"])
        if not path.exists():
            raise FileNotFoundError(f"原始文件丢失：{path.name}")
        if not s.effective_embedding_key:
            raise ValueError(
                "尚未配置向量模型密钥（ARK_API_KEY 或 EMBEDDING_API_KEY），"
                "请到「系统配置」填写后重试。"
            )

        jf.stage = "parsing"
        repos.update_document(ctx.db, jf.doc_id, status="parsing", error="")
        self._set(job)
        parsed = parse_file(path, ocr_enabled=s.ocr_enabled, ocr_dpi=s.ocr_dpi)

        jf.stage = "splitting"
        repos.update_document(ctx.db, jf.doc_id, status="splitting")
        self._set(job)
        fragments = split_blocks(
            parsed, doc["filename"], chunk_size=s.chunk_size, chunk_overlap=s.chunk_overlap
        )
        if not fragments:
            raise ValueError("未能从文件中提取到任何文本（若是扫描件/图片，请确认 OCR 已开启）")

        jf.stage = "embedding"
        repos.update_document(ctx.db, jf.doc_id, status="embedding")
        self._set(job)
        if job.kind == "reindex":
            ctx.vector_store.delete_for_doc(jf.doc_id)

        def on_progress(done: int) -> None:
            jf.chunk_count = done
            # 长文档限流时可能跑数十分钟，每批落库并回写进度，中断也不丢已完成部分
            repos.update_document(ctx.db, jf.doc_id, chunk_count=done)
            self._set(job)

        n = ctx.vector_store.add_fragments(
            jf.doc_id,
            fragments,
            batch_size=max(1, s.embedding_batch),
            on_progress=on_progress,
        )

        jf.chunk_count = n
        jf.stage = "done"
        repos.update_document(
            ctx.db, jf.doc_id, status="done", chunk_count=n,
            ocr_used=parsed.ocr_used, error="",
        )
        self._set(job)
