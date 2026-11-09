// 后端 REST 调用封装
async function request(path, options = {}) {
  const resp = await fetch(path, {
    headers: options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`
    try {
      const data = await resp.json()
      if (data.detail) detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return resp.json()
}

const json = (body) => ({ body: JSON.stringify(body) })

export const api = {
  // 配置
  status: () => request('/api/config/status'),
  getSettings: () => request('/api/settings'),
  saveSettings: (data) => request('/api/settings', { method: 'PUT', ...json(data) }),
  testChat: () => request('/api/settings/test-chat', { method: 'POST' }),
  testEmbedding: () => request('/api/settings/test-embedding', { method: 'POST' }),

  // 会话
  listSessions: () => request('/api/sessions'),
  createSession: (title) => request('/api/sessions', { method: 'POST', ...json({ title }) }),
  renameSession: (id, title) => request(`/api/sessions/${id}`, { method: 'PATCH', ...json({ title }) }),
  deleteSession: (id) => request(`/api/sessions/${id}`, { method: 'DELETE' }),
  clearSession: (id) => request(`/api/sessions/${id}/clear`, { method: 'POST' }),
  getMessages: (id) => request(`/api/sessions/${id}/messages`),

  // 文档
  upload: (formData) =>
    request('/api/documents/upload', { method: 'POST', body: formData }),
  listDocuments: () => request('/api/documents'),
  deleteDocument: (id) => request(`/api/documents/${id}`, { method: 'DELETE' }),
  reindex: () => request('/api/documents/reindex', { method: 'POST' }),
  getJob: (id) => request(`/api/jobs/${id}`),

  // 统计
  stats: () => request('/api/stats'),
}
