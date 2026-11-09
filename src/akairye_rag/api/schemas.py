"""API 请求模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str
    query: str = Field(min_length=1)


class SessionCreate(BaseModel):
    title: str | None = None


class SessionRename(BaseModel):
    title: str


class SettingsIn(BaseModel):
    # Key 类：None/"" 表示不修改
    ark_api_key: str | None = None
    ark_base_url: str | None = None
    ark_model: str | None = None

    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    embedding_batch: int | None = None

    tavily_api_key: str | None = None

    temperature: float | None = None
    max_tokens: int | None = None
    tool_mode: Literal["auto", "on", "off"] | None = None

    top_k: int | None = None
    similarity_threshold: float | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    history_limit: int | None = None

    ocr_enabled: bool | None = None
    ocr_dpi: int | None = None

    data_dir: str | None = None
    vector_cache: Literal["on", "off"] | None = None
