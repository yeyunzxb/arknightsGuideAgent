export async function api(path, body, signal) {
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body), signal,
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === 'string' ? data.detail : '请求失败，请检查输入内容和后端服务。')
  }
  return response
}

// fetch + ReadableStream：POST 携带临时密钥，解析跨网络分片的 SSE。
export async function streamChat(body, onEvent, signal) {
  const response = await api('/chat', body, signal)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = '', finished = false
  try {
    while (true) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
      let boundary
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const name = frame.split('\n').find(line => line.startsWith('event:'))?.slice(6).trim()
        const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n')
        if (name && data) {
          onEvent(name, JSON.parse(data))
          if (name === 'done' || name === 'error') finished = true
        }
      }
      if (done) break
    }
    if (!finished) throw new Error('连接提前结束，请重试。')
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
