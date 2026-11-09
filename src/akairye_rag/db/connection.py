"""单个 SQLite 连接的封装：WAL、外键、行工厂、统一锁。"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from akairye_rag.db.schema import SCHEMA_SQL


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        with self.lock:
            self.conn.executescript(SCHEMA_SQL)
            self.conn.commit()

    def close(self) -> None:
        with self.lock:
            self.conn.close()
