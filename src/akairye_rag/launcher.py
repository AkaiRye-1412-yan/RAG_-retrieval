"""桌面启动：空闲端口起 uvicorn 守护线程 → 健康轮询 → pywebview 窗口。"""
from __future__ import annotations

import ctypes
import logging
import os
import socket
import sys
import threading
import time

import uvicorn

from akairye_rag import APP_NAME
from akairye_rag.api.main import create_app
from akairye_rag.core.app_context import AppContext

logger = logging.getLogger(__name__)

WINDOW_W = 1440
WINDOW_H = 900


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_health(port: int, timeout: float = 20.0) -> bool:
    import httpx

    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code == 200:
                return True
        except Exception:
            time.sleep(0.25)
    return False


def _fatal_box(title: str, text: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)  # MB_ICONERROR
    except Exception:
        pass


def run() -> None:
    dev = os.environ.get("AKAIR_DEV") == "1"
    ctx = None
    port = 0

    if not dev:
        ctx = AppContext()
        port = _free_port()
        config = uvicorn.Config(
            create_app(ctx),
            host="127.0.0.1",
            port=port,
            loop="asyncio",
            http="h11",
            log_config=None,
        )
        server = uvicorn.Server(config)
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()

        if not _wait_health(port):
            _fatal_box(APP_NAME, "本地服务启动失败，请查看 data/logs/app.log 后重试。")
            sys.exit(1)

    url = "http://localhost:5173" if dev else f"http://127.0.0.1:{port}/"
    logger.info("打开窗口: %s", url)

    try:
        import webview

        webview.settings["SHOW_DEFAULT_MENUS"] = True  # 允许右键系统菜单（复制等）
        webview.create_window(
            APP_NAME,
            url,
            width=WINDOW_W,
            height=WINDOW_H,
            min_size=(1100, 700),
            background_color="#0A1628",
            text_select=True,  # 允许鼠标划选文本（pywebview 默认禁用）
        )
        webview.start(gui="edgechromium")
    except Exception as e:
        logger.exception("pywebview 启动失败")
        _fatal_box(
            APP_NAME,
            "无法启动桌面窗口（需要 WebView2 运行时）。\n"
            "请安装 Microsoft Edge WebView2 Runtime 后重试。\n\n"
            f"错误信息：{e}",
        )
    finally:
        if not dev:
            server.should_exit = True
            if ctx:
                ctx.shutdown()


if __name__ == "__main__":
    run()
