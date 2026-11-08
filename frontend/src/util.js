export const fmtDate = (d) => (d ? new Date(d).toLocaleDateString('he-IL') : '')

export const fmtDateTime = (d) =>
  d ? new Date(d).toLocaleString('he-IL', { dateStyle: 'short', timeStyle: 'short' }) : ''

export const daysSince = (d) => (d ? Math.floor((Date.now() - new Date(d).getTime()) / 86400000) : 0)

export function statusClass(status) {
  if (['הצעה', 'התקבלתי'].includes(status)) return 'good'
  if (['נדחיתי', 'ביטלתי'].includes(status)) return 'bad'
  if (status === 'ללא מענה') return 'muted'
  if (status === 'הוגשה') return 'neutral'
  return 'progress'
}

// A link that opens the original email in Gmail by Message-ID. Empty if impossible (not Gmail, or no real Message-ID)
export function gmailLink(messageId, account) {
  if (!account || !messageId || !messageId.startsWith('<')) return ''
  const id = messageId.replace(/^<|>$/g, '')
  return `https://mail.google.com/mail/?authuser=${encodeURIComponent(account)}#search/${encodeURIComponent(`rfc822msgid:${id}`)}`
}

// A link without http(s):// gets https:// (so it is clickable); empty stays empty.
// Chrome hides "www." in the address bar, so a link read from a screenshot lacks it. These job boards redirect
// the bare domain to www. and DROP the query string (the job id), so the link must start with www.
export const normalizeUrl = (u) => {
  let url = (u || '').trim()
  if (!url) return url
  if (!/^https?:\/\//i.test(url)) url = `https://${url}`
  return url.replace(/^(https?:\/\/)(alljobs\.co\.il|drushim\.co\.il|jobmaster\.co\.il)(?=[/?#]|$)/i, '$1www.$2')
}
