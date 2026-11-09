import { defineStore } from 'pinia'
import { api } from '../api/client'

export const useAppStore = defineStore('app', {
  state: () => ({
    view: 'chat',
    status: null,
  }),
  getters: {
    arkConfigured: (s) => !!s.status?.ark_configured,
    tavilyUsable: (s) => !!s.status?.tavily_usable,
    // 联网是否真正生效：除 Key 之外，工具模式为 off 时 Tavily 不会被调用
    tavilyEffective: (s) => !!s.status?.tavily_usable && s.status?.tool_mode !== 'off',
  },
  actions: {
    setView(v) {
      this.view = v
    },
    async refreshStatus() {
      try {
        this.status = await api.status()
      } catch {
        this.status = null
      }
    },
  },
})
