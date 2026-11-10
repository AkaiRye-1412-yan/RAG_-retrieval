"""配置模型与热加载：所有可配置项来自 .env（环境变量），保存后下次请求即生效。"""
from __future__ import annotations

import re
import threading
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from akairye_rag.core import paths
from akairye_rag.core.env_template import ENV_TEMPLATE

ToolMode = Literal["auto", "on", "off"]

# 已知向量模型支持的输出维度；未知模型不校验（保存时维度任意，风险由用户自负）
EMBEDDING_DIMS_BY_MODEL: dict[str, tuple[int, ...]] = {
    "doubao-embedding-vision": (2048,),          # 多模态向量：仅支持 2048，其它维度接口直接 400
    "doubao-embedding-text-240715": (2048, 1024, 512),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # 对话模型
    ark_api_key: SecretStr = SecretStr("")
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    ark_model: str = "doubao-seed-1-6-250615"
    temperature: float = 0.7
    # 跨产品回答（高创/ACS/AGITO 分节 + 对比表）通常较长，默认给足输出预算
    max_tokens: int = 8192
    # 推理强度：low 可显著缩短“思考”阶段（首字从数十秒降到 1~3 秒）；
    # 留空则不发送该参数（个别模型不支持时会报 InvalidParameter）。
    reasoning_effort: str = "low"
    tool_mode: str = "auto"

    # 向量模型
    embedding_model: str = "doubao-embedding-text-240715"
    embedding_base_url: str = ""
    embedding_api_key: SecretStr = SecretStr("")
    embedding_dim: int = 2048
    embedding_batch: int = 10

    # Tavily（配置了 Key 即可用；是否真正联网由 TOOL_MODE 决定）
    tavily_api_key: SecretStr = SecretStr("")

    # 检索与切分
    top_k: int = 6
    similarity_threshold: float = 0.30
    chunk_size: int = 500
    chunk_overlap: int = 80
    history_limit: int = 12

    # OCR
    ocr_enabled: bool = True
    ocr_dpi: int = 200

    # 路径 / 性能
    data_dir: str = ""
    vector_cache: str = "on"

    @field_validator("tool_mode")
    @classmethod
    def _clamp_tool_mode(cls, v: str) -> str:
        v = (v or "auto").strip().lower()
        return v if v in ("auto", "on", "off") else "auto"

    @property
    def tool_mode_value(self) -> ToolMode:
        return self.tool_mode if self.tool_mode in ("auto", "on", "off") else "auto"

    @property
    def reasoning_effort_value(self) -> str | None:
        v = (self.reasoning_effort or "").strip().lower()
        return v if v in ("minimal", "low", "medium", "high") else None

    @property
    def vector_cache_on(self) -> bool:
        return self.vector_cache.strip().lower() in ("on", "true", "1", "yes")

    @property
    def embedding_dim_options(self) -> tuple[int, ...] | None:
        """当前向量模型支持的维度；未知模型返回 None（保存时不校验）。"""
        return EMBEDDING_DIMS_BY_MODEL.get(self.embedding_model.strip())

    @property
    def effective_embedding_base_url(self) -> str:
        return self.embedding_base_url.strip() or self.ark_base_url.strip().rstrip("/")

    @property
    def effective_embedding_key(self) -> str:
        k = self.embedding_api_key.get_secret_value().strip()
        return k or self.ark_api_key.get_secret_value().strip()

    @property
    def has_ark_key(self) -> bool:
        return bool(self.ark_api_key.get_secret_value().strip())

    @property
    def has_tavily_key(self) -> bool:
        return bool(self.tavily_api_key.get_secret_value().strip())

    @property
    def tavily_usable(self) -> bool:
        # TAVILY_ENABLED 已取消：有 Key 即可用，是否联网由工具模式（TOOL_MODE）决定
        return self.has_tavily_key

    @property
    def data_dir_path(self):
        return paths.data_dir(self.data_dir)

    @property
    def db_path(self):
        return paths.db_path(self.data_dir)


def ensure_env_file() -> None:
    p = paths.env_file()
    if not p.exists() or p.stat().st_size == 0:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(ENV_TEMPLATE, encoding="utf-8")


def _mask_last4(secret: str) -> str:
    secret = secret.strip()
    if not secret:
        return ""
    return ("*" * max(0, len(secret) - 4)) + secret[-4:]


class SettingsStore:
    """持有当前 Settings 快照；.env 更新后 reload，下一次 get 即新值。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._settings: Settings | None = None
        self.reload()

    def reload(self) -> Settings:
        with self._lock:
            ensure_env_file()
            load_dotenv(paths.env_file(), override=True)
            self._settings = Settings()
            return self._settings

    def get(self) -> Settings:
        assert self._settings is not None
        return self._settings

    # ---- .env 读改写（保留注释与未知键）----
    @staticmethod
    def write_updates(updates: dict[str, str]) -> None:
        ensure_env_file()
        path = paths.env_file()
        lines = path.read_text(encoding="utf-8").splitlines()
        remaining = dict(updates)
        out: list[str] = []
        for line in lines:
            m = re.match(r"^([A-Z0-9_]+)\s*=", line)
            if m and m.group(1) in remaining:
                out.append(f"{m.group(1)}={remaining.pop(m.group(1))}")
            else:
                out.append(line)
        if remaining:
            if out and out[-1].strip():
                out.append("")
            out.append("# ---- 以下由系统设置页写入 ----")
            for k, v in remaining.items():
                out.append(f"{k}={v}")
        path.write_text("\n".join(out) + "\n", encoding="utf-8")

    def apply_updates(self, updates: dict[str, str]) -> Settings:
        with self._lock:
            self.write_updates(updates)
            return self.reload()

    def masked_view(self) -> dict[str, Any]:
        s = self.get()
        return {
            "ark_api_key_configured": s.has_ark_key,
            "ark_api_key_hint": _mask_last4(s.ark_api_key.get_secret_value()),
            "ark_base_url": s.ark_base_url,
            "ark_model": s.ark_model,
            "temperature": s.temperature,
            "max_tokens": s.max_tokens,
            "tool_mode": s.tool_mode_value,
            "embedding_model": s.embedding_model,
            "embedding_base_url": s.embedding_base_url,
            "embedding_api_key_configured": bool(s.effective_embedding_key),
            "embedding_api_key_hint": _mask_last4(s.effective_embedding_key),
            "embedding_dim": s.embedding_dim,
            "embedding_dim_options": list(s.embedding_dim_options) if s.embedding_dim_options else None,
            "embedding_batch": s.embedding_batch,
            "tavily_api_key_configured": s.has_tavily_key,
            "tavily_api_key_hint": _mask_last4(s.tavily_api_key.get_secret_value()),
            "tavily_usable": s.tavily_usable,
            "top_k": s.top_k,
            "similarity_threshold": s.similarity_threshold,
            "chunk_size": s.chunk_size,
            "chunk_overlap": s.chunk_overlap,
            "history_limit": s.history_limit,
            "ocr_enabled": s.ocr_enabled,
            "ocr_dpi": s.ocr_dpi,
            "data_dir": s.data_dir,
            "vector_cache": s.vector_cache,
            "paths": {
                "env": str(paths.env_file()),
                "data": str(s.data_dir_path),
                "db": str(s.db_path),
                "uploads": str(paths.uploads_dir(s.data_dir)),
            },
        }
