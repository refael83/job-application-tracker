import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtDateTime, gmailLink, normalizeUrl } from '../util.js'
import MailSync from './MailSync.jsx'
import UrlField from './UrlField.jsx'

function MailInfo({ s, account }) {
  const link = gmailLink(s.message_id, account)
  if (!s.summary && !link) return null
  return (
    <p className="snippet" dir="auto">
      {s.summary}
      {link && <> <a href={link} target="_blank" rel="noreferrer">פתח את המייל ב-Gmail</a></>}
    </p>
  )
}

function Discovered({ s, meta, onDone }) {
  const [company, setCompany] = useState(s.guessed_company || '')
  const [position, setPosition] = useState(s.guessed_position || '')
  const [status, setStatus] = useState(s.suggested_status || 'הוגשה')
  const [url, setUrl] = useState(s.job_url || '')
  return (
    <div className="mail">
      <div className="mail-head">
        <span className="pill progress">משרה שזוהתה</span>
        <span className="spacer" />
        <span className="muted">{fmtDateTime(s.received_at)}</span>
      </div>
      <div className="mail-subject">{s.subject}</div>
      <div className="muted" dir="auto">{s.sender}</div>
      <MailInfo s={s} account={meta.mail_account} />
      <div className="mail-actions">
        <input placeholder="חברה" value={company} onChange={(e) => setCompany(e.target.value)} />
        <input placeholder="תפקיד" value={position} onChange={(e) => setPosition(e.target.value)} />
        <UrlField placeholder="קישור למשרה" value={url} onChange={setUrl} />
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          {meta.statuses.map((st) => <option key={st}>{st}</option>)}
        </select>
        <button className="primary" disabled={!company.trim()}
          onClick={() => onDone(() => api.createFromSuggestion(s.id, { company, position, status, url: normalizeUrl(url) }))}>
          הוסף למעקב
        </button>
        <button onClick={() => onDone(() => api.dismissSuggestion(s.id))}>זה לא משרה</button>
      </div>
      <div className="muted">זוהה כ: {meta.category_labels[s.category] || s.category}</div>
    </div>
  )
}

export default function EmailInbox({ meta, onChange }) {
  const [items, setItems] = useState([])

  const load = useCallback(() => api.suggestions().then(setItems), [])
  useEffect(() => { load() }, [load])

  const act = async (fn) => {
    await fn()
    await load()
    onChange()
  }

  return (
    <div>
      <MailSync meta={meta} onDone={() => { load(); onChange() }} />

      <p className="muted">
        הסריקה קוראת מיילים בלבד, לא משנה ולא מוחקת כלום בתיבה. מייל שמתאים למשרה מקושר אליה אוטומטית, ושינוי סטטוס
        דורש את אישורך.
        {meta.ai_configured && ' הסריקה עוברת דרך Claude: השולח, הנושא ותחילת הטקסט של מיילים שעברו סינון נשלחים ל-Anthropic.'}
      </p>

      {items.length === 0 && meta.email_configured && <div className="empty">אין מיילים שממתינים לאישור.</div>}

      {items.some((s) => !s.application_id) && (
        <h3>משרות שזוהו במייל ועוד לא במעקב</h3>
      )}
      {items.filter((s) => !s.application_id).map((s) => (
        <Discovered key={s.id} s={s} meta={meta} onDone={act} />
      ))}
      {items.some((s) => s.application_id) && <h3>תשובות להגשות שכבר במעקב</h3>}

      {items.filter((s) => s.application_id).map((s) => (
        <div className="mail" key={s.id}>
          <div className="mail-head">
            <strong>{s.company}</strong>
            <span className="muted">{s.position}</span>
            {s.match_confidence === 'low' && <span className="warn">יש כמה משרות באותה חברה: בדוק שזו המשרה הנכונה</span>}
            <span className="spacer" />
            <span className="muted">{fmtDateTime(s.received_at)}</span>
          </div>
          <div className="mail-subject">{s.subject}</div>
          <div className="muted" dir="auto">{s.sender}</div>
          <MailInfo s={s} account={meta.mail_account} />
          <div className="mail-actions">
            <span className="muted">זוהה כ: <strong>{meta.category_labels[s.category] || s.category}</strong></span>
            {s.suggested_status
              ? <button className="primary" onClick={() => act(() => api.applySuggestion(s.id))}>
                  עדכן סטטוס ל"{s.suggested_status}"
                </button>
              : <button onClick={() => act(() => api.applySuggestion(s.id))}>הוסף להיסטוריה</button>}
            <select defaultValue="" onChange={(e) => e.target.value && act(() => api.applySuggestion(s.id, e.target.value))}>
              <option value="">סטטוס אחר…</option>
              {meta.statuses.map((st) => <option key={st}>{st}</option>)}
            </select>
            <button onClick={() => act(() => api.dismissSuggestion(s.id))}>התעלם</button>
          </div>
        </div>
      ))}
    </div>
  )
}
