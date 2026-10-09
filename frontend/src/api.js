async function request(url, options = {}) {
  const res = await fetch(url, options)
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') msg = body.detail
      else if (Array.isArray(body.detail)) msg = body.detail.map((d) => d.msg).join('；')
    } catch {}
    throw new Error(msg)
  }
  return res.json()
}

export const api = {
  health: () => request('/api/health'),
  upload(files) {
    const form = new FormData()
    for (const f of files) form.append('files', f)
    return request('/api/uploads', { method: 'POST', body: form })
  },
  createBatch: (payload) =>
    request('/api/batches', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  listBatches: () => request('/api/batches'),
  retry: (taskId) => request(`/api/tasks/${taskId}/retry`, { method: 'POST' }),
}
