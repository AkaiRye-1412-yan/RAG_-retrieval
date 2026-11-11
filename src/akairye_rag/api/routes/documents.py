"""向量库文档：上传、列表、删除、重建索引、任务进度。"""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile

from akairye_rag.api.deps import get_ctx, get_or_404
from akairye_rag.db import repos
from akairye_rag.ingest.parsers import SUPPORTED_EXTS, ext_of

router = APIRouter(prefix="/api", tags=["documents"])

MAX_FILE_BYTES = 100 * 1024 * 1024  # 单文件 100MB 保护


@router.post("/documents/upload")
async def upload_documents(request: Request, files: list[UploadFile]):
    ctx = get_ctx(request)
    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")

    upload_dir: Path = ctx.uploads_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)

    doc_ids: list[str] = []
    saved: list[tuple[str, str]] = []  # (doc_id, path)，失败时回滚
    skipped: list[dict] = []

    try:
        for up in files:
            filename = Path(up.filename or "").name
            ext = ext_of(filename)
            if ext not in SUPPORTED_EXTS:
                skipped.append({"filename": filename, "reason": f"不支持的类型 .{ext}"})
                continue

            doc_id = repos.new_id()
            dest = ctx.upload_path(doc_id, ext)
            digest = hashlib.sha256()
            size = 0
            oversize = False
            with dest.open("wb") as fh:
                while True:
                    chunk = await up.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        oversize = True
                        break
                    digest.update(chunk)
                    fh.write(chunk)
            if oversize:
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"{filename} 超过 100MB 限制")

            repos.create_document(
                ctx.db,
                doc_id=doc_id,
                filename=filename,
                ext=ext,
                size_bytes=size,
                sha256=digest.hexdigest(),
            )
            doc_ids.append(doc_id)
            saved.append((doc_id, str(dest)))
    except HTTPException:
        # 回滚已写入的记录与文件
        for did, p in saved:
            repos.delete_document(ctx.db, did)
            Path(p).unlink(missing_ok=True)
        raise

    if not doc_ids:
        return {"job_id": None, "accepted": 0, "skipped": skipped}

    job_id = ctx.jobs.start_ingest(doc_ids)
    return {"job_id": job_id, "accepted": len(doc_ids), "skipped": skipped}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    ctx = get_ctx(request)
    return get_or_404(lambda: ctx.jobs.get(job_id), "任务不存在或已过期")


@router.get("/documents")
async def list_documents(request: Request):
    return repos.list_documents(get_ctx(request).db)


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, request: Request):
    ctx = get_ctx(request)
    doc = get_or_404(lambda: repos.get_document(ctx.db, doc_id), "文档不存在")
    # 先通过向量库删除 chunks 并同步清理 FTS5 关键词索引，再删 documents 行
    ctx.vector_store.delete_for_doc(doc_id)
    repos.delete_document(ctx.db, doc_id)
    ctx.vector_store._invalidate()
    ctx.upload_path(doc_id, doc["ext"]).unlink(missing_ok=True)
    return {"ok": True}


@router.post("/documents/reindex")
async def reindex(request: Request):
    ctx = get_ctx(request)
    docs = repos.list_documents(ctx.db)
    if not docs:
        raise HTTPException(status_code=400, detail="知识库为空，请先上传文档")
    job_id = ctx.jobs.start_reindex(docs)
    return {"job_id": job_id, "total": len(docs)}
