<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  UploadCloud,
  FileText,
  Boxes,
  HardDrive,
  RefreshCw,
  Trash2,
  Loader2,
  AlertTriangle,
  Clock,
  ScanText,
} from 'lucide-vue-next'
import { useLibraryStore } from '../stores/library'
import StatusIcon from '../components/StatusIcon.vue'

const lib = useLibraryStore()
const fileInput = ref(null)
const dragOver = ref(false)
const busy = ref(false)
const notice = ref(null)

const ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.md,.log,.png,.jpg,.jpeg,.bmp,.webp,.tif,.tiff'

onMounted(() => lib.refresh())

const stageText = {
  waiting: '等待中',
  parsing: '解析中',
  splitting: '切分中',
  embedding: '嵌入入库中',
  done: '完成',
  error: '失败',
}
const docStatusText = {
  pending: '等待中',
  parsing: '解析中',
  splitting: '切分中',
  embedding: '嵌入中',
  done: '已完成',
  error: '失败',
}

const running = computed(() => {
  const j = lib.currentJob
  return j && j.status === 'running'
})

async function handleFiles(list) {
  const files = [...(list || [])]
  if (!files.length) return
  busy.value = true
  notice.value = null
  try {
    const resp = await lib.upload(files)
    if (resp.skipped?.length) {
      notice.value = {
        type: 'warn',
        text: resp.skipped.map((x) => `${x.filename}：${x.reason}`).join('；'),
      }
    }
  } catch (e) {
    notice.value = { type: 'error', text: e.message }
  } finally {
    busy.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

function onDrop(e) {
  dragOver.value = false
  handleFiles(e.dataTransfer.files)
}

async function doReindex() {
  busy.value = true
  notice.value = null
  try {
    await lib.reindex()
  } catch (e) {
    notice.value = { type: 'error', text: e.message }
  } finally {
    busy.value = false
  }
}

async function remove(id, name) {
  if (!confirm(`确定删除文档「${name}」及其全部向量吗？`)) return
  await lib.remove(id)
}

function fmtSize(n) {
  if (!n && n !== 0) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(i ? 1 : 0)} ${units[i]}`
}
</script>

<template>
  <div class="lib">
    <div class="lib-inner">
      <div class="page-head">
        <div>
          <h2>向量库</h2>
          <p class="muted">上传文档自动解析、切分并写入本地向量库，支持 PDF / Word / Excel / TXT / 图片（OCR）</p>
        </div>
        <button class="btn" :disabled="running || busy || !lib.documents.length" @click="doReindex">
          <RefreshCw :size="14" :class="{ spin: running }" /> 重建索引
        </button>
      </div>

      <!-- 统计 -->
      <div class="stat-row">
        <div class="stat-card card">
          <FileText :size="18" />
          <div>
            <div class="num">{{ lib.stats?.document_count ?? 0 }}</div>
            <div class="lbl">文档数</div>
          </div>
        </div>
        <div class="stat-card card">
          <Boxes :size="18" />
          <div>
            <div class="num">{{ lib.stats?.chunk_count ?? 0 }}</div>
            <div class="lbl">分块向量数</div>
          </div>
        </div>
        <div class="stat-card card">
          <HardDrive :size="18" />
          <div>
            <div class="num">{{ lib.stats?.db_size_human ?? '0 B' }}</div>
            <div class="lbl">数据库占用</div>
          </div>
        </div>
        <div class="stat-card card">
          <ScanText :size="18" />
          <div>
            <div class="num">{{ lib.stats?.embedding_dim ?? '-' }}</div>
            <div class="lbl">向量维度</div>
          </div>
        </div>
      </div>

      <!-- 上传区 -->
      <div
        class="dropzone"
        :class="{ over: dragOver }"
        @click="fileInput?.click()"
        @dragover.prevent="dragOver = true"
        @dragleave.prevent="dragOver = false"
        @drop.prevent="onDrop"
      >
        <input
          ref="fileInput"
          type="file"
          multiple
          :accept="ACCEPT"
          hidden
          @change="handleFiles($event.target.files)"
        />
        <UploadCloud :size="34" class="up-ico" />
        <div class="up-title">拖拽文件到此处，或点击选择文件</div>
        <div class="up-sub muted">
          pdf / doc / docx / xls / xlsx / csv / txt / md / png / jpg / bmp / webp / tiff，单文件 ≤ 100MB
        </div>
        <div v-if="busy" class="up-busy"><Loader2 :size="14" class="spin" /> 正在上传…</div>
      </div>

      <div v-if="notice" class="notice" :class="notice.type">
        <AlertTriangle :size="14" /> {{ notice.text }}
      </div>

      <!-- 任务进度 -->
      <div v-if="lib.currentJob" class="card job-card">
        <div class="job-head">
          <span class="section-title"><span class="bar"></span>入库任务</span>
          <span class="badge" :class="running ? 'badge-warn' : 'badge-ok'">
            <StatusIcon :status="running ? 'running' : 'done'" :size="12" />
            {{ running ? `${lib.currentJob.done}/${lib.currentJob.total}` : '已完成' }}
          </span>
        </div>
        <div class="job-list">
          <div v-for="f in lib.currentJob.files" :key="f.doc_id" class="job-file">
            <span class="jf-name">{{ f.filename }}</span>
            <span class="jf-state" :class="f.stage">
              <StatusIcon :status="f.stage === 'done' ? 'done' : f.stage === 'error' ? 'error' : 'running'" :size="12" />
              {{ stageText[f.stage] }}
              <template v-if="f.stage === 'done'"> · {{ f.chunk_count }} 块</template>
              <template v-if="f.stage === 'error'"> · {{ f.error }}</template>
            </span>
          </div>
        </div>
      </div>

      <!-- 文档表 -->
      <div class="card doc-card">
        <div class="job-head">
          <span class="section-title"><span class="bar"></span>文档列表</span>
          <span class="muted">{{ lib.documents.length }} 个文件</span>
        </div>
        <div v-if="!lib.documents.length" class="empty-lib muted">
          <Clock :size="20" /> 知识库还是空的，先上传几份文档吧
        </div>
        <table v-else class="doc-table">
          <thead>
            <tr>
              <th>文件名</th>
              <th style="width: 90px">大小</th>
              <th style="width: 90px">分块数</th>
              <th style="width: 70px">OCR</th>
              <th style="width: 110px">状态</th>
              <th style="width: 60px"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in lib.documents" :key="d.id">
              <td class="fname">
                <FileText :size="14" class="f-ico" />
                <span :title="d.filename">{{ d.filename }}</span>
              </td>
              <td class="muted">{{ fmtSize(d.size_bytes) }}</td>
              <td>{{ d.chunk_count }}</td>
              <td>
                <span v-if="d.ocr_used" class="badge badge-ok">OCR</span>
                <span v-else class="muted">-</span>
              </td>
              <td>
                <span class="status" :class="d.status">
                  <StatusIcon
                    :status="['pending','parsing','splitting','embedding'].includes(d.status) ? 'running' : d.status === 'done' ? 'done' : 'error'"
                    :size="11"
                  />
                  {{ docStatusText[d.status] || d.status }}
                </span>
                <div v-if="d.status === 'error'" class="err-tip" :title="d.error">{{ d.error }}</div>
              </td>
              <td>
                <button class="del" title="删除文档与向量" @click="remove(d.id, d.filename)">
                  <Trash2 :size="14" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lib {
  height: 100%;
  overflow-y: auto;
}
.lib-inner {
  max-width: 1040px;
  margin: 0 auto;
  padding: 18px 26px 30px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
}
.page-head h2 {
  font-size: 20px;
  color: var(--text-strong);
  margin-bottom: 4px;
}
.page-head p {
  font-size: 12.5px;
}
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.stat-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  color: var(--cyan);
}
.stat-card .num {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-strong);
}
.stat-card .lbl {
  font-size: 12px;
  color: var(--muted);
}
.dropzone {
  border: 1.5px dashed var(--line-strong);
  border-radius: var(--radius);
  padding: 34px 20px;
  text-align: center;
  cursor: pointer;
  transition: all 0.18s;
  background: rgba(15, 33, 56, 0.45);
}
.dropzone:hover,
.dropzone.over {
  border-color: var(--cyan);
  background: rgba(34, 211, 238, 0.07);
  box-shadow: inset 0 0 30px rgba(34, 211, 238, 0.06);
}
.up-ico {
  color: var(--cyan);
  margin-bottom: 8px;
}
.up-title {
  font-size: 14px;
  color: var(--text-strong);
  margin-bottom: 5px;
}
.up-sub {
  font-size: 12px;
}
.up-busy {
  margin-top: 10px;
  color: var(--cyan);
  font-size: 12.5px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.notice {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  border-radius: 8px;
  font-size: 12.5px;
}
.notice.warn {
  color: #fcd9a0;
  background: var(--warn-bg);
  border: 1px solid rgba(245, 158, 11, 0.35);
}
.notice.error {
  color: var(--danger);
  background: var(--danger-bg);
  border: 1px solid rgba(248, 113, 113, 0.35);
}
.job-card,
.doc-card {
  padding: 15px 18px;
}
.job-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.job-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.job-file {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  padding: 7px 10px;
  border-radius: 7px;
  background: rgba(8, 17, 32, 0.4);
}
.jf-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.jf-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  font-size: 12px;
  color: var(--muted);
}
.jf-state.done {
  color: var(--ok);
}
.jf-state.error {
  color: var(--danger);
  max-width: 55%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.empty-lib {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 30px 0;
  font-size: 13px;
}
.doc-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.doc-table th {
  text-align: left;
  font-weight: 500;
  color: var(--muted);
  font-size: 12px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--line);
}
.doc-table td {
  padding: 9px 10px;
  border-bottom: 1px solid rgba(34, 211, 238, 0.07);
}
.doc-table tr:hover td {
  background: rgba(34, 211, 238, 0.04);
}
.fname {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}
.fname span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.f-ico {
  color: var(--cyan-dim);
  flex-shrink: 0;
}
.status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
}
.status.done {
  color: var(--ok);
}
.status.error {
  color: var(--danger);
}
.err-tip {
  font-size: 11px;
  color: var(--danger);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 150px;
}
.del {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
}
.del:hover {
  color: var(--danger);
  background: rgba(248, 113, 113, 0.1);
}
</style>
