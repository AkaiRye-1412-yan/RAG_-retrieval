# -*- mode: python ; coding: utf-8 -*-
"""AkaiRye 知识RAG平台 PyInstaller 打包规格（onedir 文件夹版）。

构建：scripts/build.bat（先 npm run build 前端，再 uv sync，最后 pyinstaller）
产物：dist/AkaiRyeRAG/AkaiRyeRAG.exe（.env 不在包内，首启自动在 exe 旁生成）
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

datas = []
binaries = []
hiddenimports = []

# 含数据文件/原生库/动态导入的重包
for pkg in [
    "rapidocr_onnxruntime",   # 内置 ONNX 模型 + config.yaml
    "onnxruntime",            # capi DLL
    "cv2",                    # OCR 依赖
    "shapely",
    "pymupdf",                # mupdf 原生库
    "openpyxl",
    "webview",                # pythonnet / platforms
]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# LangChain / LangGraph 动态导入与 importlib.metadata 版本探测
for pkg in [
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langchain_text_splitters",
    "langgraph",
]:
    hiddenimports += collect_submodules(pkg)
    datas += copy_metadata(pkg)

for pkg in [
    "openai",
    "tiktoken",
    "pydantic",
    "pydantic_core",
    "anyio",
    "numpy",
    "tavily",
    "rapidocr_onnxruntime",
    "python_docx",
    "xlrd",
    "pillow",
]:
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

hiddenimports += [
    "tiktoken_ext",
    "tiktoken_ext.openai_public",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "multipart",
    "pyclipper",
    "six",
    "yaml",
    "xlrd",
    "docx",
    "clr",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "bottle",
    "proxy_tools",
]

a = Analysis(
    ["launcher.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas + [("frontend/dist", "frontend")],
    hiddenimports=hiddenimports
    + [
        "akairye_rag",
        "akairye_rag.api",
        "akairye_rag.api.routes",
        "akairye_rag.agent",
        "akairye_rag.ingest",
        "akairye_rag.retrieval",
        "akairye_rag.providers",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "chromadb",
        "langchain_community",
        "langchain_classic",
        "faiss",
        "anthropic",
        "pandas",
        "matplotlib",
        "tkinter",
        "pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AkaiRyeRAG",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AkaiRyeRAG",
)
