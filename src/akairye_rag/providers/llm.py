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
        # 思考型模型（如 glm-5.3-flash）默认会先进行长时间内部推理，
        # 首字可能要等 40 秒以上；low 可把这段等待压到 1~3 秒。
        reasoning_effort=s.reasoning_effort_value,
        timeout=120,
        max_retries=2,
        streaming=streaming,
    )
