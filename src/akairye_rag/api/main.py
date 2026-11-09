"""FastAPI 应用工厂：仅监听回环、Origin 校验、API 路由 + 前端 SPA 静态托管。"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from akairye_rag import APP_NAME, __version__
from akairye_rag.api.routes import chat, config, documents, sessions, stats
from akairye_rag.core import paths
from akairye_rag.core.app_context import AppContext

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def create_app(ctx: AppContext | None = None) -> FastAPI:
    ctx = ctx or AppContext()
    app = FastAPI(title=APP_NAME, version=__version__)
    app.state.ctx = ctx

    @app.middleware("http")
    async def loopback_guard(request: Request, call_next):
        # 防 DNS rebinding：带 Origin/Referer 的跨来请求必须来自本机回环
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin:
            try:
                host = urlparse(origin).hostname or ""
            except ValueError:
                host = ""
            if host.lower() not in ALLOWED_HOSTS:
                return JSONResponse({"detail": "Forbidden"}, status_code=403)
        return await call_next(request)

    for router in (config.router, sessions.router, chat.router, documents.router, stats.router):
        app.include_router(router)

    dist = paths.frontend_dist()
    index_html = dist / "index.html"
    assets_dir = dist / "assets"

    if index_html.exists():
        if assets_dir.exists():
            app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir)),
                name="assets",
            )

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str, request: Request):
            # API 路径未命中时不回退到 index.html
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            target = dist / full_path
            if full_path and target.is_file():
                return FileResponse(str(target))
            return FileResponse(str(index_html))

        logger.info("前端静态资源: %s", dist)
    else:
        @app.get("/")
        async def dev_placeholder():
            return {
                "name": f"{APP_NAME} API",
                "version": __version__,
                "frontend": "未构建（开发模式请运行 npm run dev）",
                "docs": "/docs",
            }

    return app


# 供 `uvicorn akairye_rag.api.main:app --reload` 开发使用
app = create_app()
