"""向量模型：OpenAI 兼容 Embeddings，缺省回退到 ARK 的 base_url / key。"""
from __future__ import annotations

from langchain_openai import OpenAIEmbeddings

from akairye_rag.core.settings import Settings


def build_embeddings(s: Settings) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=s.embedding_model,
        base_url=s.effective_embedding_base_url,
        api_key=s.effective_embedding_key,
        dimensions=s.embedding_dim,
        check_embedding_ctx_length=False,  # 避免未知模型名触发 tiktoken 首次联网下载词表
        chunk_size=max(1, s.embedding_batch),
        # 关闭 SDK 内部重试：429 由 SQLiteVectorStore 的限速器统一退避，避免多层重试叠加撞限流窗
        max_retries=0,
    )
