async function request(path, options = {}) {
  const res = await fetch(`/api${path}`, options)
  if (!res.ok) {
    let msg = `שגיאה ${res.status}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') msg = body.detail
    } catch { /* ignore */ }
    throw new Error(msg)
  }
  return res.json()
}

const json = (method, body) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  meta: () => request('/meta'),
  list: () => request('/applications'),
  create: (a) => request('/applications', json('POST', a)),
  update: (id, a) => request(`/applications/${id}`, json('PUT', a)),
  remove: (id) => request(`/applications/${id}`, { method: 'DELETE' }),
  events: (id) => request(`/applications/${id}/events`),
  emails: (id) => request(`/applications/${id}/emails`),
  findEmails: (id) => request(`/applications/${id}/find-emails`, { method: 'POST' }),
  reassignMail: (id, applicationId) =>
    request(`/email/suggestions/${id}/reassign`, json('POST', { application_id: applicationId })),
  addEvent: (id, e) => request(`/applications/${id}/events`, json('POST', e)),
  importCsv: (text) =>
    request('/import', { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: text }),
  extractScreenshot: (file) =>
    request('/extract-screenshot', { method: 'POST', headers: { 'Content-Type': file.type || 'application/octet-stream' }, body: file }),
  scanEmail: (days, useAi) => request(`/email/scan?days=${days}&use_ai=${useAi ? 'true' : 'false'}`, { method: 'POST' }),
  lastScan: () => request('/email/last-scan'),
  suggestions: (state = 'pending') => request(`/email/suggestions?state=${state}`),
  applySuggestion: (id, status) =>
    request(`/email/suggestions/${id}/apply${status ? `?status=${encodeURIComponent(status)}` : ''}`, { method: 'POST' }),
  createFromSuggestion: (id, data) => request(`/email/suggestions/${id}/create-application`, json('POST', data)),
  dismissSuggestion: (id) => request(`/email/suggestions/${id}/dismiss`, { method: 'POST' }),
}
