"""对话模型：OpenAI 兼容客户端，指向火山方舟 Ark 端点。"""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from akairye_rag.core.settings import Settings


def build_chat_model(s: Settings, *, streaming: bool = True) -> ChatOpenAI:
    return ChatOpenAI(
        model=s.ark_model,
        base_url=s.ark_base_url,
        api_key=s.ark_api_key.get_secret_value(),
        temperature=s.temperature,
        max_tokens=s.max_tokens,
        timeout=120,
        max_retries=2,
        streaming=streaming,
    )
