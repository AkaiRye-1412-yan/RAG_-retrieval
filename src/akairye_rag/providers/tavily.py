"""Tavily 联网搜索（直接用 tavily-python 异步客户端，不引入 langchain-community）。"""
from __future__ import annotations

from typing import Any

from tavily import AsyncTavilyClient

from akairye_rag.core.settings import Settings


async def tavily_search(s: Settings, query: str, max_results: int = 5) -> list[dict[str, Any]]:
    if not s.has_tavily_key:
        raise RuntimeError("未配置 TAVILY_API_KEY")
    client = AsyncTavilyClient(api_key=s.tavily_api_key.get_secret_value())
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
