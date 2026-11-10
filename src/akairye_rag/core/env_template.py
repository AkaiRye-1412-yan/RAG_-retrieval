"""首次运行时自动生成的 .env 模板（带中文注释）。

.env 永远位于 exe 同目录（开发态位于项目根），不参与打包，可随时用记事本编辑，
保存后在"系统设置"中点保存或重启程序即可生效。
"""
from __future__ import annotations

ENV_TEMPLATE = """\
# ============================================================
#  AkaiRye 知识RAG平台 配置文件
#  修改本文件后：可在程序内"系统设置"页保存使其立即生效，或重启程序。
#  等号两边不要加引号；留空表示使用默认值/回退值。
# ============================================================

# ===== 火山方舟 对话模型（OpenAI 兼容接口）=====
# 申请：火山方舟控制台 → API Key 管理 → 创建 API Key
ARK_API_KEY=
# 标准端点 /api/v3；若你的 Key 是套餐订阅类型（标准端点返回 401），请改用 /api/plan/v3
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
# 模型 ID（如 doubao-seed-... ）或在线推理接入点 ID（ep- 开头）
ARK_MODEL=doubao-seed-1-6-250615
TEMPERATURE=0.7
# 跨产品回答（分产品小节 + 对比表）较长，建议 8192
MAX_TOKENS=8192
# 推理强度：low=缩短模型“思考”阶段，首字更快（推荐）；medium/high=更慢更细；留空=不发送该参数
# 若切换的模型不支持该参数并报 InvalidParameter，请把本项留空
REASONING_EFFORT=low
# 工具调用模式：auto=模型自决（知识库优先） / on=强制使用工具 / off=仅用知识库、不联网
TOOL_MODE=auto

# ===== 向量模型（KEY / BASE_URL 留空则自动回退到上面的 ARK 配置）=====
EMBEDDING_MODEL=doubao-embedding-text-240715
EMBEDDING_BASE_URL=
EMBEDDING_API_KEY=
# 向量维度（豆包文本向量支持 2048/1024/512 降维）；更换向量模型后需要在知识库页"重建索引"
EMBEDDING_DIM=2048
# 单次嵌入批大小（套餐端点 /api/plan/v3 上限为 10；标准端点可调到 32/64；程序遇批量上限会自动降批）
EMBEDDING_BATCH=10

# ===== Tavily 联网搜索（配置 Key 即可用；是否联网由上面的 TOOL_MODE 决定）=====
# 申请：https://app.tavily.com/
TAVILY_API_KEY=

# ===== 检索与切分 =====
TOP_K=6
# 相似度阈值 0~1，低于该值视为知识库未命中（值越小越宽松）
SIMILARITY_THRESHOLD=0.30
# 文本分块大小 / 重叠（按中文字符计）
CHUNK_SIZE=500
CHUNK_OVERLAP=80
# 每轮对话携带的历史消息条数
HISTORY_LIMIT=12

# ===== 图片 / 扫描版 PDF 离线 OCR（RapidOCR，首次调用加载模型约 1~3 秒）=====
OCR_ENABLED=true
OCR_DPI=200

# ===== 路径与性能 =====
# 数据目录留空 = exe 同级 data 目录；可改到其他磁盘，改后重启程序生效（历史数据请手动迁移）
DATA_DIR=
# 向量矩阵缓存：on=启动后首次检索载入内存（快，占用约 分块数×维度×4 字节）；off=分批扫描（省内存）
VECTOR_CACHE=on
"""
