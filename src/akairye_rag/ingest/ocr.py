"""RapidOCR 离线中英文识别（模型内置在 wheel 中，运行时不联网）。"""
from __future__ import annotations

import logging
import threading

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_engine = None
_lock = threading.Lock()


def get_engine():
    """懒加载单例（首次加载模型约 1~3 秒）。"""
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                from rapidocr_onnxruntime import RapidOCR

                logger.info("加载 RapidOCR 模型 ...")
                _engine = RapidOCR()
    return _engine


def ocr_bytes(data: bytes) -> str:
    """对图片字节做 OCR，返回按行拼接的文本；无文字返回空串。"""
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("图片解码失败（文件可能已损坏）")
    result, _ = get_engine()(img)
    if not result:
        return ""
    lines = []
    for item in result:
        if item and len(item) >= 2 and item[1]:
            lines.append(str(item[1]).strip())
    return "\n".join(line for line in lines if line)
