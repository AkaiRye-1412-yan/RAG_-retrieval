import { defineStore } from 'pinia'
import { api } from '../api/client'

export const useLibraryStore = defineStore('library', {
  state: () => ({
    documents: [],
    stats: null,
    currentJob: null,
    pollTimer: null,
  }),
  actions: {
    async refresh() {
      const [docs, st] = await Promise.all([api.listDocuments(), api.stats()])
      this.documents = docs
      this.stats = st
    },

    async upload(fileList) {
      const fd = new FormData()
      for (const f of fileList) fd.append('files', f)
      const resp = await api.upload(fd)
      if (resp.job_id) await this.pollJob(resp.job_id)
      await this.refresh()
      return resp
    },

    async reindex() {
      const resp = await api.reindex()
      await this.pollJob(resp.job_id)
      await this.refresh()
      return resp
    },

    async remove(id) {
      await api.deleteDocument(id)
      await this.refresh()
    },

    async pollJob(jobId) {
      if (this.pollTimer) clearInterval(this.pollTimer)
      return new Promise((resolve) => {
        const tick = async () => {
          try {
            const job = await api.getJob(jobId)
            this.currentJob = job
            await this.refresh()
            if (job.status === 'done' || job.status === 'error') {
              clearInterval(this.pollTimer)
              this.pollTimer = null
              resolve(job)
            }
          } catch {
            /* 瞬时错误保留轮询 */
          }
        }
        this.pollTimer = setInterval(tick, 1200)
        tick()
      })
    },
  },
})
