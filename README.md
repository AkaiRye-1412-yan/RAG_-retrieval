# AkaiRye 知识RAG平台

本地优先的桌面 RAG 应用：**FastAPI + Vue3 + LangChain(LangGraph) + pywebview**，打包为 Windows exe。

- 上传 **PDF / Word(doc/docx) / Excel(xls/xlsx) / CSV / TXT / Markdown / 图片**，自动解析切分并写入本地向量库（图片与扫描版 PDF 使用内置 RapidOCR 离线识别）
- 对话**优先检索本地知识库**给出带来源引用的回答；知识库未命中时自动通过 **Tavily** 联网搜索
- 多会话上下文记忆，SQLite 持久化（会话、消息、文档、向量全部在 `data/akairye.db` 一个文件中）
- 答案为 Claude 风格 Markdown 渲染（代码高亮、表格、引用、复制按钮）
- 所有密钥与参数放在 exe 同目录的 **`.env`**（不打包），可在系统设置页热修改、随时切换模型
- 自研 SQLite 向量存储（float32 + numpy 余弦），无 Chroma 重依赖，单文件备份，断网可用

> 📖 **完整架构设计**（模块划分 / 数据模型 / 核心流程 / SSE 协议 / 安全与打包）：见 [docs/架构设计.md](docs/架构设计.md)

## 快速开始（开发模式）

需要：Python 3.12（由 uv 自动管理）、Node.js 18+、[uv](https://docs.astral.sh/uv/)。

```bash
# 1. 安装后端依赖（自动创建 .venv，Python 3.12）
uv sync

# 2. 安装前端依赖并构建（或开发热更新：cd frontend && npm run dev）
cd frontend && npm install && npm run build && cd ..

# 3. 桌面方式运行（首启自动生成 .env）
uv run akairye-rag
```

纯网页开发调试（热更新）：

```bash
scripts\dev.bat
# 或两个终端分别执行：
# uv run uvicorn akairye_rag.api.main:app --reload --port 8000
# cd frontend && npm run dev   → 打开 http://localhost:5173
```

接口文档：<http://127.0.0.1:8000/docs>

## 配置

首次运行在程序目录（开发态为项目根）生成 `.env`，参考 `.env.example`：

| 变量 | 说明 |
|---|---|
| `ARK_API_KEY` / `ARK_BASE_URL` / `ARK_MODEL` | 火山方舟对话模型（OpenAI 兼容），模型 ID 或 `ep-` 接入点 |
| `EMBEDDING_*` | 向量模型；KEY/BASE_URL 留空则回退到 ARK 配置。换模型/维度后需在「向量库」页**重建索引** |
| `TAVILY_API_KEY` / `TAVILY_ENABLED` | 联网搜索；不配置则自动禁用并在界面提示 |
| `TOOL_MODE` | `auto` 知识库优先、模型自决联网；`on` 强制使用工具；`off` 仅用知识库 |

> **401 鉴权失败？** 若你的方舟 Key 属于套餐订阅（标准 `/api/v3` 返回 401），把 `ARK_BASE_URL` 改成 `https://ark.cn-beijing.volces.com/api/plan/v3`。
> **套餐端点限流（429）？** 套餐端点嵌入接口限制约 6 次/分钟、每次最多 10 条。程序已内置自动降批、指数退避（3/6/10/12s，最多约 6 分钟）与分批提交，长文档入库较慢（数千分块可能约 1 小时），后台运行即可、进度不丢；需要更快可在方舟控制台为该模型开通按量付费后改用标准端点。
| `TOP_K` / `SIMILARITY_THRESHOLD` / `CHUNK_SIZE` / `CHUNK_OVERLAP` | 检索与切分参数 |
| `OCR_ENABLED` / `OCR_DPI` | 离线 OCR 开关与扫描 PDF 渲染精度 |
| `DATA_DIR` | 数据目录（留空为程序同级 `data/`，修改后重启生效） |
| `VECTOR_CACHE` | `on` 向量矩阵驻内存（快）；`off` 分批扫描（省内存） |

所有参数也可在应用内「系统配置」页修改保存，**下一次请求立即生效**（数据目录除外需重启）。

## 打包 exe（onedir）

```bash
scripts\build.bat
# 等价于：cd frontend && npm run build → uv sync → uv run pyinstaller akairye.spec --noconfirm --clean
```

产物：`dist/AkaiRyeRAG/AkaiRyeRAG.exe`（整个文件夹拷走即用；`.env` 不在包内，首启自动生成）。
运行环境需要 Microsoft Edge WebView2 Runtime（Win11 自带，Win10 一般已预装）。

## 数据与备份

```
程序目录/
├─ AkaiRyeRAG.exe
├─ .env                 # 密钥配置（不打包、不入库）
└─ data/
   ├─ akairye.db        # 会话/消息/文档/向量，备份只需退出程序后复制此文件
   ├─ uploads/          # 原始上传文件（重建索引需要）
   └─ logs/app.log
```

## 技术说明

- 后端：FastAPI + uvicorn(h11)，仅监听 `127.0.0.1`，带 Origin 校验防 DNS rebinding
- Agent：自研 LangGraph 状态图（预检索 → off 直接生成 / auto·on 有界工具循环），SSE 同时推送 token 与工具步骤事件
- 向量：L2 归一化向量存 SQLite BLOB，内存矩阵点积 + `argpartition` top-k（20 万分块约百毫秒级）；无缓存时分批扫描内存有界
- 桌面壳：pywebview(Edge WebView2)，守护线程内起 uvicorn，空闲端口探测、健康轮询、关窗即退出
