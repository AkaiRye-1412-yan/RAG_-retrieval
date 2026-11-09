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
