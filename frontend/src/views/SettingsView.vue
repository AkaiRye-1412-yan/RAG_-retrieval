<script setup>
import { onMounted, reactive, ref } from 'vue'
import {
  Bot,
  AudioLines,
  Globe,
  FolderCog,
  Info,
  Eye,
  EyeOff,
  PlugZap,
  Minus,
  Plus,
  Database,
  RefreshCw,
  CheckCircle2,
  Loader2,
  SlidersHorizontal,
} from 'lucide-vue-next'
import { api } from '../api/client'
import { useAppStore } from '../stores/app'
import { useLibraryStore } from '../stores/library'
import SaveButton from '../components/SaveButton.vue'

const app = useAppStore()
const lib = useLibraryStore()

const loaded = ref(false)
const loadError = ref('')
const toast = ref(null)
let toastTimer = null
function showToast(text, ok = true) {
  toast.value = { text, ok }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = null), 3000)
}

const form = reactive({
  ark_base_url: '',
  ark_model: '',
  temperature: 0.7,
  max_tokens: 4096,
  tool_mode: 'auto',
  embedding_model: '',
  embedding_base_url: '',
  embedding_dim: 2048,
  embedding_batch: 32,
  tavily_enabled: true,
  top_k: 6,
  similarity_threshold: 0.35,
  chunk_size: 500,
  chunk_overlap: 80,
  history_limit: 12,
  ocr_enabled: true,
  ocr_dpi: 200,
  data_dir: '',
  vector_cache: 'on',
})
const keys = reactive({ ark: '', embedding: '', tavily: '' })
const showKey = reactive({ ark: false, embedding: false, tavily: false })
const paths = ref({ env: '', data: '', db: '', uploads: '' })
const dimOptions = ref([])
const masks = reactive({ ark: false, emb: false, tav: false, arkHint: '', embHint: '' })

const testing = reactive({ chat: false, emb: false })
const testResult = reactive({ chat: null, emb: null })
const saving = ref(false)
const reindexing = ref(false)

onMounted(load)

async function load() {
  loadError.value = ''
  let s
  try {
    s = await api.getSettings()
  } catch (e) {
    loadError.value =
      e.name === 'TypeError' || e.message === 'Failed to fetch'
        ? '无法连接后端服务（127.0.0.1:8000）。\n请确认已启动后端：uv run uvicorn akairye_rag.api.main:app --reload --port 8000'
        : e.message || String(e)
    return
  }
  Object.assign(form, {
    ark_base_url: s.ark_base_url,
    ark_model: s.ark_model,
    temperature: s.temperature,
    max_tokens: s.max_tokens,
    tool_mode: s.tool_mode,
    embedding_model: s.embedding_model,
    embedding_base_url: s.embedding_base_url,
    embedding_dim: s.embedding_dim,
    embedding_batch: s.embedding_batch,
    tavily_enabled: s.tavily_enabled,
    top_k: s.top_k,
    similarity_threshold: s.similarity_threshold,
    chunk_size: s.chunk_size,
    chunk_overlap: s.chunk_overlap,
    history_limit: s.history_limit,
    ocr_enabled: s.ocr_enabled,
    ocr_dpi: s.ocr_dpi,
    data_dir: s.data_dir || '',
    vector_cache: s.vector_cache,
  })
  paths.value = s.paths
  dimOptions.value = s.embedding_dim_options || []
  masks.ark = s.ark_api_key_configured
  masks.emb = s.embedding_api_key_configured
  masks.tav = s.tavily_api_key_configured
  masks.arkHint = s.ark_api_key_hint
  masks.embHint = s.embedding_api_key_hint
  loaded.value = true
  lib.stats || lib.refresh()
}

function payload() {
  const p = { ...form }
  if (keys.ark.trim()) p.ark_api_key = keys.ark.trim()
  if (keys.embedding.trim()) p.embedding_api_key = keys.embedding.trim()
  if (keys.tavily.trim()) p.tavily_api_key = keys.tavily.trim()
  return p
}

async function save() {
  saving.value = true
  try {
    const r = await api.saveSettings(payload())
    keys.ark = keys.embedding = keys.tavily = ''
    await Promise.all([load(), app.refreshStatus()])
    if (r && r.warn) {
      showToast('⚠️ ' + r.warn, true)
    } else {
      showToast('配置已保存，新设置立即生效')
    }
  } catch (e) {
    showToast(e.message, false)
  } finally {
    saving.value = false
  }
}

async function testChat() {
  testing.chat = true
  testResult.chat = null
  try {
    const r = await api.testChat()
    testResult.chat = { ok: true, text: `连接成功 · ${r.latency_ms} ms · ${r.reply || ''}` }
  } catch (e) {
    testResult.chat = { ok: false, text: e.message }
  } finally {
    testing.chat = false
  }
}

async function testEmbedding() {
  testing.emb = true
  testResult.emb = null
  try {
    const r = await api.testEmbedding()
    testResult.emb = { ok: true, text: `嵌入成功 · 维度 ${r.dim} · ${r.latency_ms} ms` }
  } catch (e) {
    testResult.emb = { ok: false, text: e.message }
  } finally {
    testing.emb = false
  }
}

async function doReindex() {
  if (!confirm('将清空全部向量并按当前向量模型重新嵌入，确定继续吗？')) return
  reindexing.value = true
  try {
    await lib.reindex()
    showToast('索引重建完成')
  } catch (e) {
    showToast(e.message, false)
  } finally {
    reindexing.value = false
  }
}
</script>

<template>
  <div class="settings">
    <div class="st-inner">
      <div class="page-head">
        <h2>系统设置</h2>
        <span class="muted">配置保存在程序目录的 <code>.env</code> 文件，修改后立即生效（数据目录变更需重启）</span>
      </div>

      <div v-if="!loaded">
        <div v-if="loadError" class="load-error">
          <div class="load-error-title">⚠️ 配置加载失败</div>
          <div class="load-error-msg">{{ loadError }}</div>
          <button class="btn" @click="load">重试</button>
        </div>
        <div v-else class="loading muted"><Loader2 :size="16" class="spin" /> 加载中…</div>
      </div>

      <div v-else class="grid">
        <!-- ========== AI 模型配置 ========== -->
        <section class="card set-card">
          <header>
            <span class="section-title"><span class="bar"></span><Bot :size="15" /> AI 模型配置</span>
            <span class="badge" :class="masks.ark ? 'badge-ok' : 'badge-warn'">
              <span class="dot" :class="masks.ark ? 'dot-ok' : 'dot-live'"></span>
              {{ masks.ark ? `已配置 ${masks.arkHint}` : '尚未配置 API Key' }}
            </span>
          </header>

          <label class="field">
            <span class="lbl">ARK_API_KEY</span>
            <div class="pwd">
              <input
                :type="showKey.ark ? 'text' : 'password'"
                class="input"
                v-model="keys.ark"
                :placeholder="masks.ark ? '留空表示不修改；粘贴新的 Key 才会覆盖' : '请输入火山方舟 API Key'"
              />
              <button class="eye" type="button" @click="showKey.ark = !showKey.ark">
                <component :is="showKey.ark ? EyeOff : Eye" :size="15" />
              </button>
            </div>
          </label>

          <label class="field">
            <span class="lbl">ARK_BASE_URL</span>
            <input class="input" v-model="form.ark_base_url" />
          </label>

          <label class="field">
            <span class="lbl">ARK_MODEL</span>
            <input class="input" v-model="form.ark_model" placeholder="模型 ID 或 ep- 接入点 ID" />
          </label>

          <div class="row-2">
            <label class="field">
              <span class="lbl">temperature（{{ form.temperature.toFixed(1) }}）</span>
              <input type="range" min="0" max="2" step="0.1" v-model.number="form.temperature" class="slider" />
            </label>
            <label class="field" style="max-width: 190px">
              <span class="lbl">max_tokens</span>
              <div class="num-box">
                <button type="button" @click="form.max_tokens = Math.max(256, form.max_tokens - 256)"><Minus :size="13" /></button>
                <input class="input num" type="number" min="256" step="256" v-model.number="form.max_tokens" />
                <button type="button" @click="form.max_tokens += 256"><Plus :size="13" /></button>
              </div>
            </label>
          </div>

          <div class="field">
            <span class="lbl">工具调用模式</span>
            <div class="segmented">
              <button
                v-for="m in [{k:'auto',t:'auto（自动探测）'},{k:'on',t:'on（强制启用）'},{k:'off',t:'off（关闭）'}]"
                :key="m.k"
                type="button"
                :class="{ active: form.tool_mode === m.k }"
                @click="form.tool_mode = m.k"
              >{{ m.t }}</button>
            </div>
            <p class="hint">
              auto = 优先本地知识库，未命中时模型可调用联网搜索；on = 强制先使用工具；off = 仅依据知识库回答、不联网。
            </p>
          </div>

          <div class="actions">
            <SaveButton :saving="saving" @click="save" />
            <button class="btn" :disabled="testing.chat" @click="testChat">
              <component :is="testing.chat ? Loader2 : PlugZap" :size="14" :class="{ spin: testing.chat }" />
              测试连接
            </button>
            <span v-if="testResult.chat" class="test-res" :class="{ bad: !testResult.chat.ok }">
              <CheckCircle2 v-if="testResult.chat.ok" :size="13" /> {{ testResult.chat.text }}
            </span>
          </div>
        </section>

        <!-- ========== 向量模型配置 ========== -->
        <section class="card set-card">
          <header>
            <span class="section-title"><span class="bar"></span><AudioLines :size="15" /> 向量模型配置</span>
            <span class="badge" :class="masks.emb ? 'badge-ok' : 'badge-warn'">
              <span class="dot" :class="masks.emb ? 'dot-ok' : 'dot-live'"></span>
              {{ masks.emb ? `已配置 ${masks.embHint}` : '回退使用 ARK Key' }}
            </span>
          </header>

          <label class="field">
            <span class="lbl">EMBEDDING_MODEL</span>
            <input class="input" v-model="form.embedding_model" />
          </label>
          <label class="field">
            <span class="lbl">EMBEDDING_BASE_URL<span class="hint-inline">（留空回退 ARK_BASE_URL）</span></span>
            <input class="input" v-model="form.embedding_base_url" placeholder="留空则使用 ARK_BASE_URL" />
          </label>
          <label class="field">
            <span class="lbl">EMBEDDING_API_KEY<span class="hint-inline">（留空回退 ARK_API_KEY）</span></span>
            <div class="pwd">
              <input
                :type="showKey.embedding ? 'text' : 'password'"
                class="input"
                v-model="keys.embedding"
                placeholder="留空则使用 ARK_API_KEY"
              />
              <button class="eye" type="button" @click="showKey.embedding = !showKey.embedding">
                <component :is="showKey.embedding ? EyeOff : Eye" :size="15" />
              </button>
            </div>
          </label>
          <div class="row-2">
            <label class="field">
              <span class="lbl">向量维度 EMBEDDING_DIM</span>
              <input class="input" type="number" min="128" step="128" v-model.number="form.embedding_dim" />
              <p v-if="dimOptions.length" class="hint">
                当前模型 {{ form.embedding_model }} 支持维度：{{ dimOptions.join(' / ') }}
              </p>
            </label>
            <label class="field">
              <span class="lbl">嵌入批大小</span>
              <input class="input" type="number" min="1" max="128" v-model.number="form.embedding_batch" />
            </label>
          </div>
          <p class="hint">更换向量模型或维度后，需到「向量库」页执行重建索引，否则新文档会因维度不一致而入库失败。</p>
          <div class="actions">
            <SaveButton :saving="saving" @click="save" />
            <button class="btn" :disabled="testing.emb" @click="testEmbedding">
              <component :is="testing.emb ? Loader2 : PlugZap" :size="14" :class="{ spin: testing.emb }" />
              测试嵌入
            </button>
            <span v-if="testResult.emb" class="test-res" :class="{ bad: !testResult.emb.ok }">
              <CheckCircle2 v-if="testResult.emb.ok" :size="13" /> {{ testResult.emb.text }}
            </span>
          </div>
        </section>

        <!-- ========== Tavily 联网搜索 ========== -->
        <section class="card set-card">
          <header>
            <span class="section-title"><span class="bar"></span><Globe :size="15" /> Tavily 联网搜索</span>
            <span class="badge" :class="masks.tav && form.tavily_enabled ? 'badge-ok' : 'badge-warn'">
              <span class="dot" :class="masks.tav && form.tavily_enabled ? 'dot-ok' : 'dot-live'"></span>
              {{ masks.tav ? (form.tavily_enabled ? '可用' : '已手动关闭') : '未配置 Key' }}
            </span>
          </header>
          <label class="field">
            <span class="lbl">TAVILY_API_KEY</span>
            <div class="pwd">
              <input
                :type="showKey.tavily ? 'text' : 'password'"
                class="input"
                v-model="keys.tavily"
                :placeholder="masks.tav ? '留空表示不修改；粘贴新的 Key 才会覆盖' : 'https://app.tavily.com 申请'"
              />
              <button class="eye" type="button" @click="showKey.tavily = !showKey.tavily">
                <component :is="showKey.tavily ? EyeOff : Eye" :size="15" />
              </button>
            </div>
          </label>
          <div class="field">
            <span class="lbl">启用联网搜索</span>
            <div class="switch-row">
              <button class="switch" :class="{ on: form.tavily_enabled }" @click="form.tavily_enabled = !form.tavily_enabled">
                <span class="knob"></span>
              </button>
              <span class="muted">{{ form.tavily_enabled ? '知识库未命中时允许联网搜索' : '已关闭，仅使用本地知识库' }}</span>
            </div>
          </div>
          <div class="actions">
            <SaveButton :saving="saving" @click="save" />
          </div>
        </section>

        <!-- ========== 检索与切分 ========== -->
        <section class="card set-card">
          <header>
            <span class="section-title"><span class="bar"></span><SlidersHorizontal :size="15" /> 检索与切分参数</span>
          </header>
          <div class="row-2">
            <label class="field"><span class="lbl">检索条数 TOP_K</span>
              <input class="input" type="number" min="1" max="20" v-model.number="form.top_k" /></label>
            <label class="field"><span class="lbl">相似度阈值（0~1）</span>
              <input class="input" type="number" min="0" max="1" step="0.05" v-model.number="form.similarity_threshold" /></label>
            <label class="field"><span class="lbl">分块大小</span>
              <input class="input" type="number" min="200" max="2000" step="50" v-model.number="form.chunk_size" /></label>
            <label class="field"><span class="lbl">分块重叠</span>
              <input class="input" type="number" min="0" max="300" step="10" v-model.number="form.chunk_overlap" /></label>
            <label class="field"><span class="lbl">上下文历史消息数</span>
              <input class="input" type="number" min="2" max="40" v-model.number="form.history_limit" /></label>
            <label class="field"><span class="lbl">OCR DPI</span>
              <input class="input" type="number" min="100" max="400" step="50" v-model.number="form.ocr_dpi" /></label>
          </div>
          <div class="field">
            <div class="switch-row">
              <button class="switch" :class="{ on: form.ocr_enabled }" @click="form.ocr_enabled = !form.ocr_enabled">
                <span class="knob"></span>
              </button>
              <span class="muted">启用离线 OCR（扫描版 PDF 与图片中的文字识别，低配电脑可关闭）</span>
            </div>
          </div>
          <div class="field">
            <div class="switch-row">
              <button class="switch" :class="{ on: form.vector_cache === 'on' }" @click="form.vector_cache = form.vector_cache === 'on' ? 'off' : 'on'">
                <span class="knob"></span>
              </button>
              <span class="muted">向量矩阵内存缓存（关闭后检索省内存但变慢，重启后生效）</span>
            </div>
          </div>
          <div class="actions">
            <SaveButton :saving="saving" @click="save" />
          </div>
        </section>

        <!-- ========== 数据与路径 ========== -->
        <section class="card set-card">
          <header>
            <span class="section-title"><span class="bar"></span><FolderCog :size="15" /> 数据与路径</span>
          </header>
          <div class="paths">
            <div class="path-row"><span>配置文件 .env</span><code>{{ paths.env }}</code></div>
            <div class="path-row"><span>数据目录</span><code>{{ paths.data }}</code></div>
            <div class="path-row"><span>数据库</span><code>{{ paths.db }}</code></div>
            <div class="path-row"><span>原始上传文件</span><code>{{ paths.uploads }}</code></div>
          </div>
          <label class="field" style="margin-top: 12px">
            <span class="lbl">自定义数据目录 DATA_DIR<span class="hint-inline">（留空为程序同级 data，改后重启生效）</span></span>
            <input class="input" v-model="form.data_dir" placeholder="例如 D:\AkaiRyeData" />
          </label>
          <div class="tip-box">
            <Info :size="14" />
            <span>备份只需复制 data 目录下的 <b>akairye.db</b>（建议退出程序后复制）；也可直接用记事本编辑 .env，保存后在本页点保存或重启生效。</span>
          </div>
          <div class="actions">
            <SaveButton :saving="saving" @click="save" />
          </div>
        </section>

        <!-- ========== 知识库统计 ========== -->
        <section class="card set-card">
          <header>
            <span class="section-title"><span class="bar"></span><Database :size="15" /> 知识库维护</span>
          </header>
          <div class="kb-stats">
            <div><b>{{ lib.stats?.document_count ?? 0 }}</b><span>文档</span></div>
            <div><b>{{ lib.stats?.chunk_count ?? 0 }}</b><span>分块向量</span></div>
            <div><b>{{ lib.stats?.db_size_human ?? '0 B' }}</b><span>占用空间</span></div>
            <div><b>{{ lib.stats?.embedding_dim ?? '-' }}</b><span>向量维度</span></div>
          </div>
          <div class="actions">
            <button class="btn" :disabled="reindexing || !lib.documents?.length" @click="doReindex">
              <RefreshCw :size="14" :class="{ spin: reindexing }" /> {{ reindexing ? '重建中…' : '重建索引' }}
            </button>
            <span class="muted" style="font-size:12px">更换向量模型后需要重建；进度请到「向量库」页查看。</span>
          </div>
        </section>

        <!-- ========== 使用说明 ========== -->
        <section class="card set-card instructions">
          <header>
            <span class="section-title"><span class="bar"></span><Info :size="15" /> 使用说明</span>
          </header>
          <ol>
            <li><b>配置密钥</b>：在上方填写火山方舟 ARK_API_KEY 并选择模型，点「测试连接」通过后即可对话；不配置密钥也能管理文档，但 AI 问答不可用。</li>
            <li><b>上传文档</b>：到「向量库」页上传 PDF、Word、Excel、TXT 或图片，等待 解析→切分→嵌入 全部完成（扫描件与图片自动 OCR）。</li>
            <li><b>开始提问</b>：系统优先检索本地知识库作答并标注 [1] 来源；知识库未命中且配置了 Tavily 时自动联网搜索。</li>
            <li><b>切换模型只改一行</b>：修改 ARK_MODEL（换成新的豆包模型或 ep- 接入点）即可，其余配置无需变动；换向量模型记得重建索引。</li>
            <li><b>数据安全</b>：.env 与 akairye.db 都在程序目录，可随时备份；所有网络服务仅监听本机 127.0.0.1。</li>
          </ol>
        </section>
      </div>
    </div>

    <transition name="toast">
      <div v-if="toast" class="toast" :class="{ bad: !toast.ok }">
        <CheckCircle2 :size="15" /> {{ toast.text }}
      </div>
    </transition>
  </div>
</template>

<style scoped>
.settings {
  height: 100%;
  overflow-y: auto;
  position: relative;
}
.st-inner {
  max-width: 1120px;
  margin: 0 auto;
  padding: 18px 26px 40px;
}
.page-head {
  margin-bottom: 16px;
}
.page-head h2 {
  font-size: 20px;
  color: var(--text-strong);
  margin-bottom: 4px;
}
.loading {
  display: flex;
  align-items: center;
  gap: 8px;
}
.load-error {
  background: rgba(248, 113, 113, 0.07);
  border: 1px solid rgba(248, 113, 113, 0.35);
  border-radius: 10px;
  padding: 18px 20px;
  max-width: 640px;
}
.load-error-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--danger);
  margin-bottom: 8px;
}
.load-error-msg {
  font-size: 12.5px;
  color: var(--muted);
  white-space: pre-line;
  line-height: 1.7;
  margin-bottom: 12px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  align-items: start;
}
.set-card {
  padding: 18px 20px;
}
.set-card header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.field {
  display: block;
  margin-bottom: 13px;
}
.lbl {
  display: block;
  font-size: 12.5px;
  color: var(--muted);
  margin-bottom: 6px;
}
.hint-inline {
  color: var(--muted-2);
  font-size: 11.5px;
  margin-left: 6px;
}
.pwd {
  position: relative;
}
.pwd .input {
  padding-right: 38px;
}
.eye {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--muted);
  display: flex;
  padding: 4px;
}
.eye:hover {
  color: var(--cyan);
}
.row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 14px;
}
.slider {
  width: 100%;
  accent-color: var(--cyan);
  height: 4px;
}
.num-box {
  display: flex;
  align-items: center;
  gap: 4px;
}
.num-box button {
  width: 34px;
  height: 36px;
  border-radius: 7px;
  border: 1px solid var(--line);
  color: var(--muted);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.num-box button:hover {
  color: var(--cyan);
  border-color: var(--line-strong);
}
.num-box .num {
  text-align: center;
}
.segmented {
  display: inline-flex;
  border: 1px solid var(--line-strong);
  border-radius: 9px;
  overflow: hidden;
}
.segmented button {
  padding: 7px 16px;
  font-size: 12.5px;
  color: var(--muted);
  background: rgba(8, 17, 32, 0.4);
  transition: all 0.15s;
}
.segmented button + button {
  border-left: 1px solid var(--line);
}
.segmented button.active {
  color: #04222b;
  font-weight: 600;
  background: linear-gradient(135deg, #22d3ee, #06b6d4);
  box-shadow: 0 0 14px rgba(34, 211, 238, 0.35);
}
.hint {
  font-size: 12px;
  color: var(--muted-2);
  margin-top: 6px;
  line-height: 1.6;
}
.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
  flex-wrap: wrap;
}
.test-res {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--ok);
}
.test-res.bad {
  color: var(--danger);
}
.switch-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
}
.switch {
  width: 40px;
  height: 22px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.25);
  position: relative;
  transition: background 0.18s;
  flex-shrink: 0;
}
.switch .knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #e2e8f0;
  transition: all 0.18s;
}
.switch.on {
  background: linear-gradient(135deg, #06b6d4, #0891b2);
  box-shadow: 0 0 10px rgba(34, 211, 238, 0.35);
}
.switch.on .knob {
  left: 21px;
}
.paths {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.path-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
  font-size: 12.5px;
}
.path-row span {
  color: var(--muted);
  width: 96px;
  flex-shrink: 0;
}
.path-row code {
  font-family: 'Cascadia Code', Consolas, monospace;
  font-size: 12px;
  color: #7dd3fc;
  background: rgba(34, 211, 238, 0.08);
  padding: 3px 9px;
  border-radius: 6px;
  word-break: break-all;
}
.tip-box {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  padding: 11px 13px;
  border-radius: 9px;
  border: 1px solid rgba(34, 211, 238, 0.2);
  background: rgba(34, 211, 238, 0.05);
  color: var(--muted);
  font-size: 12.5px;
  line-height: 1.7;
  margin: 6px 0 4px;
}
.tip-box b {
  color: var(--cyan-soft);
}
.kb-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-bottom: 14px;
}
.kb-stats > div {
  background: rgba(8, 17, 32, 0.45);
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 12px;
  text-align: center;
}
.kb-stats b {
  display: block;
  font-size: 19px;
  color: var(--text-strong);
}
.kb-stats span {
  font-size: 11.5px;
  color: var(--muted);
}
.instructions {
  grid-column: 1 / -1;
}
.instructions ol {
  padding-left: 20px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.9;
}
.instructions b {
  color: var(--text-strong);
}
.toast {
  position: fixed;
  bottom: 26px;
  right: 26px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 18px;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(6, 182, 212, 0.25), rgba(8, 17, 32, 0.95));
  border: 1px solid var(--line-strong);
  color: var(--cyan-soft);
  font-size: 13px;
  box-shadow: var(--shadow);
  z-index: 100;
}
.toast.bad {
  color: var(--danger);
  border-color: rgba(248, 113, 113, 0.4);
  background: rgba(40, 12, 12, 0.95);
}
.toast-enter-active,
.toast-leave-active {
  transition: all 0.25s;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(10px);
}
@media (max-width: 1100px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
