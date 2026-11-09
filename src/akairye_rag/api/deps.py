"""路由公共依赖：应用上下文与 404 守卫。"""
from __future__ import annotations

from fastapi import HTTPException, Request

from akairye_rag.core.app_context import AppContext


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def get_or_404(getter, detail: str):
    """取对象，缺失时抛 404；getter 应为延迟执行的零参调用（如 lambda）。"""
    obj = getter()
    if obj is None:
        raise HTTPException(status_code=404, detail=detail)
    return obj
