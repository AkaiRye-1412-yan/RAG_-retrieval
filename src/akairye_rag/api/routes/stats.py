"""知识库与运行统计。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from akairye_rag.api.deps import get_ctx
from akairye_rag.db import repos

router = APIRouter(prefix="/api", tags=["stats"])


def _human_size(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


@router.get("/health")
async def health():
    return {"ok": True}


@router.get("/stats")
async def stats(request: Request):
    ctx = get_ctx(request)
    s = ctx.settings_store.get()
    data = repos.documents_stats(ctx.db)
    db_file = s.db_path
    total_bytes = 0
    if db_file.exists():
        total_bytes += db_file.stat().st_size
        for suffix in ("-wal", "-shm"):
            p = db_file.with_name(db_file.name + suffix)
            if p.exists():
                total_bytes += p.stat().st_size
    upload_dir = ctx.uploads_dir()
    upload_bytes = (
        sum(f.stat().st_size for f in upload_dir.rglob("*") if f.is_file())
        if upload_dir.exists()
        else 0
    )
    cache_bytes = ctx.vector_store.cache_memory_bytes()
    return {
        **data,
        "embedding_dim": ctx.vector_store.dim,
        "db_size_bytes": total_bytes,
        "db_size_human": _human_size(total_bytes),
        "uploads_size_bytes": upload_bytes,
        "uploads_size_human": _human_size(upload_bytes),
        "vector_cache_on": s.vector_cache_on,
        "vector_cache_bytes": cache_bytes,
        "vector_cache_human": _human_size(cache_bytes),
        "ocr_enabled": s.ocr_enabled,
    }
