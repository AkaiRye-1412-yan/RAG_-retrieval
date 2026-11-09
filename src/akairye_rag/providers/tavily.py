"""Tavily 联网搜索（直接用 tavily-python 异步客户端，不引入 langchain-community）。"""
from __future__ import annotations

from typing import Any

import httpx
from tavily import AsyncTavilyClient

from akairye_rag.core.settings import Settings


async def tavily_search(s: Settings, query: str, max_results: int = 5) -> list[dict[str, Any]]:
    if not s.tavily_usable:
        raise RuntimeError("未配置 TAVILY_API_KEY，无法联网搜索")
    # trust_env=False：Tavily SDK 默认读取系统代理。Steam++ / Clash 等加速器会把
    # 注册表代理指向 127.0.0.1，其自签 CA 会让 Python 报 CERTIFICATE_VERIFY_FAILED；
    # 而且失败前要等约 9 秒，直接拖慢整轮回答。这里显式直连（实测可直连 Tavily）。
    async with httpx.AsyncClient(
        trust_env=False,
        timeout=httpx.Timeout(20.0, connect=8.0),
    ) as http_client:
        client = AsyncTavilyClient(
            api_key=s.tavily_api_key.get_secret_value(),
            client=http_client,
        )
        resp = await client.search(
            query=query,
            max_results=max_results,
            search_depth="basic",
        )
    results = []
    for item in resp.get("results", []):
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
                "score": item.get("score"),
            }
        )
    return results
