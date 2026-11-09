"""系统配置：状态查询、热保存、连接测试。"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from akairye_rag.api.deps import get_ctx
from akairye_rag.api.schemas import SettingsIn
from akairye_rag.core.settings import EMBEDDING_DIMS_BY_MODEL
from akairye_rag.providers.embeddings import build_embeddings
from akairye_rag.providers.llm import build_chat_model

router = APIRouter(prefix="/api", tags=["config"])


async def _timed_check(awaitable: Any, *, detail: str) -> tuple[Any, int]:
    """执行异步探测，失败时抛 502；成功返回 (result, latency_ms)。"""
    started = time.perf_counter()
    try:
        result = await awaitable
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"{detail}：{e}") from e
    latency = round((time.perf_counter() - started) * 1000)
    return result, latency


@router.get("/config/status")
async def config_status(request: Request) -> dict:
    s = get_ctx(request).settings_store.get()
    return {
        "ark_configured": s.has_ark_key,
        "embedding_configured": bool(s.effective_embedding_key),
        "tavily_configured": s.has_tavily_key,
        "tavily_enabled": s.tavily_enabled,
        "tavily_usable": s.tavily_usable,
        "ark_model": s.ark_model,
        "embedding_model": s.embedding_model,
        "tool_mode": s.tool_mode_value,
    }


@router.get("/settings")
async def get_settings(request: Request) -> dict:
    return get_ctx(request).settings_store.masked_view()


def _updates_from_payload(payload: SettingsIn) -> dict[str, str]:
    data = payload.model_dump(exclude_unset=True)
    updates: dict[str, str] = {}
    # 密钥：仅当传入非空字符串时覆盖
    for key_field, env_name in (
        ("ark_api_key", "ARK_API_KEY"),
        ("embedding_api_key", "EMBEDDING_API_KEY"),
        ("tavily_api_key", "TAVILY_API_KEY"),
    ):
        v = data.get(key_field)
        if isinstance(v, str) and v.strip():
            updates[env_name] = v.strip()

    str_map = {
        "ark_base_url": "ARK_BASE_URL",
        "ark_model": "ARK_MODEL",
        "embedding_base_url": "EMBEDDING_BASE_URL",
        "embedding_model": "EMBEDDING_MODEL",
        "tool_mode": "TOOL_MODE",
        "vector_cache": "VECTOR_CACHE",
        "data_dir": "DATA_DIR",
    }
    for f, env in str_map.items():
        if f in data and data[f] is not None:
            updates[env] = str(data[f]).strip()

    num_map = {
        "temperature": "TEMPERATURE",
        "max_tokens": "MAX_TOKENS",
        "embedding_dim": "EMBEDDING_DIM",
        "embedding_batch": "EMBEDDING_BATCH",
        "top_k": "TOP_K",
        "similarity_threshold": "SIMILARITY_THRESHOLD",
        "chunk_size": "CHUNK_SIZE",
        "chunk_overlap": "CHUNK_OVERLAP",
        "history_limit": "HISTORY_LIMIT",
        "ocr_dpi": "OCR_DPI",
    }
    for f, env in num_map.items():
        if f in data and data[f] is not None:
            updates[env] = str(data[f])

    bool_map = {
        "tavily_enabled": "TAVILY_ENABLED",
        "ocr_enabled": "OCR_ENABLED",
    }
    for f, env in bool_map.items():
        if f in data and data[f] is not None:
            updates[env] = "true" if data[f] else "false"
    return updates


@router.put("/settings")
async def save_settings(payload: SettingsIn, request: Request) -> dict:
    ctx = get_ctx(request)
    data = payload.model_dump(exclude_unset=True)
    updates = _updates_from_payload(payload)

    # 向量维度校验：改成模型不支持的维度（如 vision 模型填 512）会让上传/检索全部 400
    if data.get("embedding_dim") is not None:
        new_model = data.get("embedding_model") or ctx.settings_store.get().embedding_model
        options = EMBEDDING_DIMS_BY_MODEL.get((new_model or "").strip())
        if options and data["embedding_dim"] not in options:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"向量维度 {data['embedding_dim']} 不受向量模型 {new_model} 支持"
                    f"（该模型仅支持 {' / '.join(str(o) for o in options)}）。"
                    "请改为模型支持的维度，或先更换向量模型。"
                ),
            )

    if updates:
        ctx.settings_store.apply_updates(updates)

    s = ctx.settings_store.get()
    # 维度与现有向量库不一致时提示重建索引，否则新文档入库会因维度冲突而失败
    warn = None
    existing = ctx.vector_store.dim
    if existing and s.embedding_dim != existing and ctx.vector_store.count() > 0:
        warn = (
            f"向量维度已改为 {s.embedding_dim}，现有知识库向量为 {existing} 维。"
            "新文档上传前请在「向量库」页执行「重建索引」，否则会因维度不一致而失败。"
        )
    return {"ok": True, "warn": warn, "settings": ctx.settings_store.masked_view()}


@router.post("/settings/test-chat")
async def test_chat(request: Request) -> dict:
    ctx = get_ctx(request)
    s = ctx.settings_store.get()
    if not s.has_ark_key:
        raise HTTPException(status_code=400, detail="尚未配置 ARK_API_KEY")
    llm = build_chat_model(s, streaming=False)
    resp, latency = await _timed_check(
        llm.ainvoke("请只回复两个字：你好"), detail="连接失败"
    )
    return {"ok": True, "latency_ms": latency, "reply": str(resp.content)[:200]}


@router.post("/settings/test-embedding")
async def test_embedding(request: Request) -> dict:
    ctx = get_ctx(request)
    s = ctx.settings_store.get()
    if not s.effective_embedding_key:
        raise HTTPException(status_code=400, detail="尚未配置向量模型 API Key")
    emb = build_embeddings(s)
    vec, latency = await _timed_check(
        emb.aembed_query("AkaiRye 知识RAG平台"), detail="向量接口连接失败"
    )
    return {"ok": True, "latency_ms": latency, "dim": len(vec)}
