"""集中管理所有路径：frozen（PyInstaller）与开发态两套规则。

- APP_DIR：exe 同目录 / 开发态项目根。.env、data/ 默认都在这里。
- RES_DIR：打包资源目录（sys._MEIPASS），前端构建产物与随包数据在此。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _compute_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # 本文件位于 src/akairye_rag/core/paths.py，向上 4 层即项目根
    return Path(__file__).resolve().parents[3]


def _compute_res_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        return Path(meipass)
    return APP_DIR


APP_DIR: Path = _compute_app_dir()
RES_DIR: Path = _compute_res_dir()


def chdir_to_app_dir() -> None:
    """让 cwd 确定，相对路径与 dotenv 行为统一。"""
    try:
        os.chdir(APP_DIR)
    except OSError:
        pass


def env_file() -> Path:
    return APP_DIR / ".env"


def frontend_dist() -> Path:
    if getattr(sys, "frozen", False):
        return RES_DIR / "frontend"          # PyInstaller datas 解包目录
    return APP_DIR / "frontend" / "dist"     # 开发态 vite 构建产物


def data_dir(configured: str | None = None) -> Path:
    if configured and configured.strip():
        p = Path(configured.strip()).expanduser()
        if not p.is_absolute():
            p = APP_DIR / p
        return p
    return APP_DIR / "data"


def db_path(configured: str | None = None) -> Path:
    return data_dir(configured) / "akairye.db"


def uploads_dir(configured: str | None = None) -> Path:
    return data_dir(configured) / "uploads"


def logs_dir(configured: str | None = None) -> Path:
    return data_dir(configured) / "logs"


def ensure_runtime_dirs(configured_data_dir: str | None = None) -> None:
    for d in (data_dir(configured_data_dir), uploads_dir(configured_data_dir), logs_dir(configured_data_dir)):
        d.mkdir(parents=True, exist_ok=True)
