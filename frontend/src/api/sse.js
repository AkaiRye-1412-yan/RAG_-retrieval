// 用 fetch + ReadableStream 读取 POST SSE（EventSource 不支持 POST body）
// onEvent(解析后的 JSON 对象)；controller.signal 可中止。
export async function streamChat({ sessionId, query, signal, onEvent }) {
  const resp = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, query }),
    signal,
  })
  if (!resp.ok || !resp.body) {
    throw new Error(`流式请求失败：${resp.status}`)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop()
    for (const frame of frames) {
      for (const line of frame.split('\n')) {
        if (!line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        if (!payload) continue
        try {
          onEvent(JSON.parse(payload))
        } catch {
          /* 忽略 keep-alive 注释等非 JSON */
        }
      }
    }
  }
}
