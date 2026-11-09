import { defineStore } from 'pinia'
import { api } from '../api/client'
import { streamChat } from '../api/sse'

export const useChatStore = defineStore('chat', {
  state: () => ({
    sessions: [],
    currentId: null,
    messages: [],
    sending: false,
    abortCtrl: null,
  }),
  getters: {
    currentSession: (s) => s.sessions.find((x) => x.id === s.currentId) || null,
  },
  actions: {
    async loadSessions(selectFirst = true) {
      this.sessions = await api.listSessions()
      if (selectFirst && !this.currentId && this.sessions.length) {
        await this.selectSession(this.sessions[0].id)
      }
    },

    async newSession() {
      const s = await api.createSession()
      this.sessions.unshift(s)
      await this.selectSession(s.id)
      return s
    },

    async selectSession(id) {
      if (this.sending) this.stop()
      this.currentId = id
      this.messages = await api.getMessages(id)
    },

    async removeSession(id) {
      await api.deleteSession(id)
      this.sessions = this.sessions.filter((x) => x.id !== id)
      if (this.currentId === id) {
        this.currentId = null
        this.messages = []
        if (this.sessions.length) await this.selectSession(this.sessions[0].id)
      }
    },

    async clearCurrent() {
      if (!this.currentId) return
      await api.clearSession(this.currentId)
      this.messages = []
      await this.loadSessions(false)
    },

    stop() {
      if (this.abortCtrl) this.abortCtrl.abort()
      this.abortCtrl = null
      this.sending = false
      const last = this.messages[this.messages.length - 1]
      if (last && last.role === 'assistant' && last.streaming) {
        last.streaming = false
        if (!last.content) last.content = '_（已停止生成）_'
      }
    },

    async send(query) {
      query = (query || '').trim()
      if (!query || this.sending) return
      if (!this.currentId) await this.newSession()

      // 首条消息自动以问题前 12 个字作为会话标题
      if (this.messages.length === 0) {
        const title = query.slice(0, 12)
        api.renameSession(this.currentId, title).catch(() => {})
        const s = this.sessions.find((x) => x.id === this.currentId)
        if (s) s.title = title
      }

      this.messages.push({ role: 'user', content: query })
      const answer = {
        role: 'assistant',
        content: '',
        sources: [],
        tool_steps: [],
        streaming: true,
        error: null,
      }
      this.messages.push(answer)
      this.sending = true
      this.abortCtrl = new AbortController()

      const upsertStep = (ev) => {
        const running = [...answer.tool_steps].reverse().find(
          (x) => x.name === ev.name && x.status === 'running'
        )
        if (running) {
          running.status = ev.error ? 'error' : 'done'
          running.hits = ev.hits
          running.top_score = ev.top_score
          running.error = ev.error
        } else {
          answer.tool_steps.push({
            name: ev.name,
            status: ev.status === 'start' ? 'running' : ev.error ? 'error' : 'done',
            hits: ev.hits,
            top_score: ev.top_score,
            error: ev.error,
          })
        }
      }

      try {
        await streamChat({
          sessionId: this.currentId,
          query,
          signal: this.abortCtrl.signal,
          onEvent: (ev) => {
            if (ev.type === 'tool') {
              upsertStep(ev)
            } else if (ev.type === 'token') {
              answer.content += ev.content
            } else if (ev.type === 'sources') {
              answer.sources = ev.items || []
            } else if (ev.type === 'error') {
              answer.error = ev.message
            }
          },
        })
      } catch (e) {
        if (e.name !== 'AbortError') {
          answer.error = answer.error || e.message || String(e)
        }
      } finally {
        answer.streaming = false
        if (!answer.content && answer.error) {
          answer.content = `> ⚠️ ${answer.error}`
        }
        this.sending = false
        this.abortCtrl = null
        this.loadSessions(false).catch(() => {})
      }
    },
  },
})
