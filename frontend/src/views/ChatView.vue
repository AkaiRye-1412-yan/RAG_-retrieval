<script setup>
import { nextTick, onActivated, onDeactivated, onMounted, ref, watch } from 'vue'
import {
  Plus,
  SquarePen,
  Trash2,
  Eraser,
  Send,
  Square,
  Pencil,
  Sparkles,
  Globe,
} from 'lucide-vue-next'
import { useChatStore } from '../stores/chat'
import { useAppStore } from '../stores/app'
import { api } from '../api/client'
import MarkdownView from '../components/MarkdownView.vue'
import ToolSteps from '../components/ToolSteps.vue'
import SourceChips from '../components/SourceChips.vue'

const chat = useChatStore()
const app = useAppStore()

const scrollEl = ref(null)
const input = ref('')
const editingId = ref(null)
const editingTitle = ref('')

// 记录滚动位置：切走页面再切回时恢复到原位置（浏览器隐藏元素时会清空 scrollTop）
let savedScroll = 0
function onScroll() {
  if (scrollEl.value) savedScroll = scrollEl.value.scrollTop
  if (ctxMenu.value) ctxMenu.value = null
}
onActivated(() => {
  nextTick(() => {
    if (scrollEl.value) scrollEl.value.scrollTop = savedScroll
  })
})

// 自定义右键菜单：实现「复制选中 / 复制本条消息」。打包版 pywebview 禁用了原生右键菜单，
// 这里在消息区自行接管 contextmenu，提供可靠的复制入口（dev 与打包版通用）。
const ctxMenu = ref(null)

function onContextMenu(e) {
  const items = []
  const sel = window.getSelection()?.toString().trim() || ''
  if (sel) items.push({ label: '复制选中的内容', text: sel })
  const bubble = e.target?.closest?.('.bubble') || null
  if (bubble) {
    const md = bubble.querySelector('.md-body')
    const text = (md ? md.innerText : bubble.innerText)?.trim() || ''
    if (text && text !== sel) items.push({ label: '复制本条消息', text })
  }
  if (!items.length) return
  e.preventDefault()
  ctxMenu.value = { x: e.clientX, y: e.clientY, items }
}

async function copyAndClose(text) {
  ctxMenu.value = null
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    ta.remove()
  }
}

function onDocMouseDown(e) {
  if (ctxMenu.value && !e.target.closest('.ctx-menu')) ctxMenu.value = null
}
onActivated(() => document.addEventListener('mousedown', onDocMouseDown))
onDeactivated(() => document.removeEventListener('mousedown', onDocMouseDown))

onMounted(async () => {
  if (!chat.sessions.length) await chat.loadSessions(true)
  else if (!chat.currentId && chat.sessions[0]) await chat.selectSession(chat.sessions[0].id)
})

async function scrollBottom() {
  await nextTick()
  const el = scrollEl.value
  if (el) {
    el.scrollTop = el.scrollHeight
    savedScroll = el.scrollTop
  }
}
watch(
  () => chat.messages.map((m) => m.content.length).join(','),
  scrollBottom
)
watch(() => chat.currentId, scrollBottom)

async function doSend() {
  const q = input.value
  if (!q.trim() || chat.sending) return
  input.value = ''
  await chat.send(q)
  scrollBottom()
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    doSend()
  }
}

function startEdit(s) {
  editingId.value = s.id
  editingTitle.value = s.title
}
async function commitEdit() {
  const id = editingId.value
  if (!id) return
  const t = editingTitle.value.trim()
  if (t) await api.renameSession(id, t).catch(() => {})
  editingId.value = null
  await chat.loadSessions(false)
}
</script>

<template>
  <div class="chat-layout">
    <!-- 会话栏 -->
    <div class="rail">
      <div class="rail-head">
        <span>对话列表</span>
        <button class="icon-btn" title="新建对话" @click="chat.newSession()">
          <Plus :size="16" />
        </button>
      </div>
      <div class="rail-list">
        <div
          v-for="s in chat.sessions"
          :key="s.id"
          class="rail-item"
          :class="{ active: s.id === chat.currentId }"
          @click="chat.selectSession(s.id)"
        >
          <template v-if="editingId === s.id">
            <input
              v-model="editingTitle"
              class="rename-input"
              @keyup.enter="commitEdit"
              @blur="commitEdit"
              @click.stop
              autofocus
            />
          </template>
          <template v-else>
            <div class="rail-title">{{ s.title }}</div>
            <div class="rail-actions" @click.stop>
              <button title="重命名" @click="startEdit(s)"><Pencil :size="12" /></button>
              <button
                title="删除会话"
                @click="chat.removeSession(s.id)"
              >
                <Trash2 :size="12" />
              </button>
            </div>
          </template>
        </div>
        <div v-if="!chat.sessions.length" class="rail-empty muted">暂无对话，点击 + 新建</div>
      </div>
    </div>

    <!-- 主聊天区 -->
    <div class="chat-main">
      <div class="chat-toolbar">
        <div class="t-title">
          <SquarePen :size="15" />
          <span>{{ chat.currentSession?.title || '新对话' }}</span>
        </div>
        <button
          class="btn"
          :disabled="!chat.currentId || chat.sending"
          title="清除当前对话"
          @click="chat.clearCurrent()"
        >
          <Eraser :size="14" /> 清除当前对话
        </button>
      </div>

      <div ref="scrollEl" class="messages" @scroll="onScroll" @contextmenu="onContextMenu">
        <div v-if="!chat.messages.length" class="empty">
          <div class="empty-logo">A</div>
          <h2>AkaiRye 知识RAG平台</h2>
          <p>基于本地知识库优先作答；工具模式为 auto 且已配置 Tavily Key 时，未命中可联网检索。</p>
          <div class="tips">
            <div class="tip" @click="input = '总结一下知识库中的主要内容'; doSend()">
              <Sparkles :size="14" /> 总结知识库中的主要内容
            </div>
            <div class="tip" @click="app.setView('library')">
              <Plus :size="14" /> 上传文档构建向量库
            </div>
          </div>
        </div>

        <div v-for="(m, i) in chat.messages" :key="i" class="msg-row" :class="m.role">
          <div v-if="m.role === 'assistant'" class="avatar">A</div>
          <div class="bubble">
            <ToolSteps v-if="m.tool_steps && m.tool_steps.length" :steps="m.tool_steps" />
            <MarkdownView :content="m.content || ''" />
            <span v-if="m.streaming && !m.tool_steps?.some((x) => x.status === 'running')" class="cursor"></span>
            <SourceChips v-if="m.sources && m.sources.length" :items="m.sources" />
          </div>
        </div>

        <div v-if="ctxMenu" class="ctx-menu" :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }">
          <button v-for="it in ctxMenu.items" :key="it.label" type="button" @mousedown.stop.prevent="copyAndClose(it.text)">
            {{ it.label }}
          </button>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="composer-wrap">
        <div class="composer">
          <textarea
            v-model="input"
            rows="1"
            placeholder="输入你的问题，Enter 发送，Shift+Enter 换行…"
            @keydown="onKeydown"
            @input="$event.target.style.height = 'auto'; $event.target.style.height = Math.min($event.target.scrollHeight, 160) + 'px'"
          ></textarea>
          <button
            v-if="!chat.sending"
            class="send btn-primary"
            :disabled="!input.trim()"
            @click="doSend()"
          >
            <Send :size="15" />
          </button>
          <button v-else class="send stop" title="停止生成" @click="chat.stop()">
            <Square :size="14" />
          </button>
        </div>
        <div class="composer-hint">
          <span><Globe :size="11" /> 联网搜索：
            <b :class="app.tavilyEffective ? 'on' : 'off'">
              {{ app.tavilyEffective
                ? 'Tavily 可用'
                : app.tavilyUsable
                  ? '已配置 Key，但工具模式为 off，本轮不会联网'
                  : '未配置 Key' }}
            </b>
          </span>
          <span class="muted">回答由 AI 生成，请核对关键信息</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  height: 100%;
  min-height: 0;
}
.rail {
  width: 236px;
  flex-shrink: 0;
  border-right: 1px solid var(--line);
  background: rgba(12, 28, 51, 0.5);
  display: flex;
  flex-direction: column;
  padding: 12px;
}
.rail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--muted);
  padding: 4px 6px 10px;
}
.icon-btn {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--cyan);
  border: 1px solid var(--line);
}
.icon-btn:hover {
  background: rgba(34, 211, 238, 0.12);
}
.rail-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.rail-item {
  position: relative;
  padding: 9px 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  color: var(--muted);
  transition: all 0.12s;
}
.rail-item:hover {
  background: rgba(34, 211, 238, 0.07);
  color: var(--text);
}
.rail-item.active {
  background: linear-gradient(90deg, rgba(34, 211, 238, 0.16), rgba(34, 211, 238, 0.03));
  color: var(--cyan);
}
.rail-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding-right: 46px;
}
.rail-actions {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  display: none;
  gap: 2px;
}
.rail-item:hover .rail-actions {
  display: flex;
}
.rail-actions button {
  width: 22px;
  height: 22px;
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
}
.rail-actions button:hover {
  color: var(--danger);
  background: rgba(248, 113, 113, 0.1);
}
.rename-input {
  width: 100%;
  background: var(--bg-deep);
  border: 1px solid var(--cyan-dim);
  border-radius: 6px;
  color: var(--text);
  padding: 4px 8px;
  font-size: 13px;
}
.rail-empty {
  font-size: 12.5px;
  padding: 16px 8px;
}

.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.chat-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 22px;
  border-bottom: 1px solid var(--line);
}
.t-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong);
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 22px clamp(20px, 6%, 80px);
  user-select: text;
  -webkit-user-select: text;
}
.ctx-menu {
  position: fixed;
  z-index: 300;
  min-width: 150px;
  padding: 4px;
  background: linear-gradient(180deg, #12263f, #0e1d33);
  border: 1px solid var(--line-strong);
  border-radius: 9px;
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.5);
}
.ctx-menu button {
  display: block;
  width: 100%;
  text-align: left;
  padding: 7px 12px;
  font-size: 12.5px;
  color: var(--text);
  border-radius: 6px;
}
.ctx-menu button:hover {
  background: rgba(34, 211, 238, 0.12);
  color: var(--cyan-soft);
}
.empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  text-align: center;
}
.empty-logo {
  width: 56px;
  height: 56px;
  border-radius: 15px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 30px;
  font-weight: 800;
  color: #04222b;
  background: linear-gradient(135deg, #67e8f9, #06b6d4);
  box-shadow: 0 0 34px rgba(34, 211, 238, 0.4);
  margin-bottom: 6px;
}
.empty h2 {
  font-size: 22px;
  color: var(--text-strong);
}
.empty p {
  color: var(--muted);
  font-size: 13.5px;
}
.tips {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}
.tip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 999px;
  border: 1px solid var(--line);
  color: var(--muted);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}
.tip:hover {
  color: var(--cyan);
  border-color: var(--line-strong);
}

.msg-row {
  display: flex;
  gap: 12px;
  margin-bottom: 26px;
}
.msg-row.user {
  justify-content: flex-end;
}
.avatar {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  color: #04222b;
  background: linear-gradient(135deg, #67e8f9, #06b6d4);
}
.bubble {
  min-width: 0;
  max-width: 100%;
}
.msg-row.user .bubble {
  max-width: 76%;
  background: linear-gradient(135deg, rgba(6, 182, 212, 0.22), rgba(8, 145, 178, 0.14));
  border: 1px solid rgba(34, 211, 238, 0.25);
  border-radius: 12px 12px 3px 12px;
  padding: 10px 15px;
  white-space: pre-wrap;
  line-height: 1.7;
}
.msg-row.assistant .bubble {
  flex: 1;
  padding-top: 4px;
}
.cursor {
  display: inline-block;
  width: 7px;
  height: 15px;
  margin-left: 3px;
  background: var(--cyan);
  border-radius: 2px;
  vertical-align: text-bottom;
  animation: blink 1s steps(2) infinite;
  box-shadow: 0 0 8px var(--cyan-glow);
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}

.composer-wrap {
  padding: 8px clamp(20px, 6%, 80px) 14px;
}
.composer {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  background: var(--panel);
  border: 1px solid var(--line-strong);
  border-radius: 14px;
  padding: 10px 12px;
  transition: box-shadow 0.15s;
}
.composer:focus-within {
  box-shadow: 0 0 0 2px rgba(34, 211, 238, 0.18), 0 0 24px rgba(34, 211, 238, 0.12);
}
.composer textarea {
  flex: 1;
  resize: none;
  background: transparent;
  border: none;
  color: var(--text);
  font-size: 14px;
  line-height: 1.6;
  max-height: 160px;
  padding: 4px 2px;
}
.composer textarea::placeholder {
  color: var(--muted-2);
}
.send {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.send.stop {
  background: rgba(248, 113, 113, 0.14);
  border: 1px solid rgba(248, 113, 113, 0.4);
  color: var(--danger);
}
.composer-hint {
  display: flex;
  justify-content: space-between;
  margin-top: 7px;
  font-size: 11.5px;
  color: var(--muted);
  padding: 0 4px;
}
.composer-hint b.on {
  color: var(--ok);
}
.composer-hint b.off {
  color: var(--warn);
}
</style>
