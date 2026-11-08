import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtDate, fmtDateTime, gmailLink, normalizeUrl, statusClass } from '../util.js'

export default function Detail({ app, statuses, meta, siblings = [], onClose, onEdit, onDelete, onChange }) {
  const [events, setEvents] = useState([])
  const [mails, setMails] = useState([])
  const [searching, setSearching] = useState(false)
  const [mailMsg, setMailMsg] = useState('')
  const [status, setStatus] = useState('')
  const [note, setNote] = useState('')
  const [editingUrl, setEditingUrl] = useState(false)
  const [urlDraft, setUrlDraft] = useState('')
  const [urlError, setUrlError] = useState('')

  // Save the job link straight from the details panel, without opening the full edit form
  const saveUrl = async () => {
    try {
      const { company, position, source, location, applied_date, status, resume_version, contact, salary,
        follow_up_date, notes } = app
      await api.update(app.id, {
        company, position, source, location, applied_date, status, resume_version, contact, salary,
        follow_up_date, notes, url: normalizeUrl(urlDraft),
      })
      setEditingUrl(false)
      setUrlError('')
      onChange()
    } catch (e) {
      setUrlError(e.message)
    }
  }

  const load = useCallback(() => api.events(app.id).then(setEvents), [app.id])
  useEffect(() => { load() }, [load])

  const loadMails = useCallback(() => api.emails(app.id).then(setMails).catch(() => {}), [app.id])
  useEffect(() => { loadMails() }, [loadMails])

  const reassign = async (mailId, appId) => {
    if (!appId) return
    await api.reassignMail(mailId, Number(appId))
    loadMails()
    onChange()
  }

  const findMails = async () => {
    setSearching(true)
    setMailMsg('')
    try {
      const { found, relevant, mine, added, errors } = await api.findEmails(app.id)
      setMailMsg(found
        ? `Claude בדק ${found} מיילים: ${relevant} קשורים להגשות בחברה, ${mine} מהם למשרה הזאת (${added} חדשים)` +
          (errors ? `. ${errors} מיילים לא נבדקו בגלל תקלה, אפשר לנסות שוב` : '')
        : 'לא נמצאו מיילים חדשים של החברה')
      loadMails()
      onChange()
    } catch (e) {
      setMailMsg(e.message)
    } finally {
      setSearching(false)
    }
  }

  const add = async (e) => {
    e.preventDefault()
    if (!status && !note.trim()) return
    await api.addEvent(app.id, { status, note })
    setStatus('')
    setNote('')
    load()
    onChange()
  }

  return (
    <div className="overlay" onMouseDown={onClose}>
      <aside className="drawer" onMouseDown={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <h2>{app.company}</h2>
            <div className="muted">{app.position}</div>
          </div>
          <span className={`pill ${statusClass(app.status)}`}>{app.status}</span>
        </div>

        <dl>
          {[['מקור', app.source], ['מיקום', app.location], ['הוגשה', fmtDate(app.applied_date)],
            ['קו"ח', app.resume_version], ['איש קשר', app.contact], ['שכר', app.salary],
            ['תאריך מעקב', fmtDate(app.follow_up_date)]]
            .filter(([, v]) => v).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
        </dl>

        <div className="link-field">
          <div className="muted">קישור למשרה</div>
          {editingUrl ? (
            <div className="mail-actions">
              <input dir="ltr" autoFocus placeholder="https://…" value={urlDraft}
                onChange={(e) => setUrlDraft(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') saveUrl() }} />
              <button className="primary" onClick={saveUrl}>שמירה</button>
              <button onClick={() => { setEditingUrl(false); setUrlError('') }}>ביטול</button>
            </div>
          ) : (
            <div className="mail-actions">
              {app.url
                ? <a href={normalizeUrl(app.url)} target="_blank" rel="noreferrer" dir="ltr" className="url-text">{app.url}</a>
                : <span className="muted">עוד לא נוסף קישור</span>}
              <button onClick={() => { setUrlDraft(app.url || ''); setEditingUrl(true) }}>
                {app.url ? 'עריכת קישור' : 'הוספת קישור'}
              </button>
            </div>
          )}
          {urlError && <div className="error">{urlError}</div>}
        </div>
        {app.notes && <p className="notes">{app.notes}</p>}

        <h3>עדכון חדש</h3>
        <form className="event-form" onSubmit={add}>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">(בלי שינוי סטטוס)</option>
            {statuses.map((s) => <option key={s}>{s}</option>)}
          </select>
          <input placeholder="הערה (למשל: דיברתי עם דנה, ביקשו מטלה)" value={note} onChange={(e) => setNote(e.target.value)} />
          <button className="primary">הוספה</button>
        </form>

        <h3>מיילים ({mails.length})</h3>
        <div className="mail-actions">
          <button onClick={findMails} disabled={searching || !meta.email_configured || !meta.ai_configured}
            title={meta.ai_configured ? '' : 'החיפוש עובד דרך Claude: צריך Claude Code מותקן או ANTHROPIC_API_KEY'}>
            {searching ? 'Claude בודק מיילים… (עד כמה דקות)' : `חפש מיילים של המשרה הזאת (דרך Claude)`}
          </button>
          {mailMsg && <span className="muted">{mailMsg}</span>}
        </div>
        <ul className="mail-list">
          {mails.map((m) => {
            const link = gmailLink(m.message_id, meta.mail_account)
            return (
              <li key={m.id}>
                <div className="muted">
                  {fmtDateTime(m.received_at)} · {meta.category_labels?.[m.category] || m.category}
                  {m.state === 'pending' && ' · ממתין לאישור'}
                </div>
                <div dir="auto">
                  {link ? <a href={link} target="_blank" rel="noreferrer">{m.subject || '(בלי נושא)'}</a> : (m.subject || '(בלי נושא)')}
                </div>
                {m.summary && <div className="muted" dir="auto">{m.summary}</div>}
                {siblings.length > 0 && (
                  <div className="mail-actions">
                    {m.match_confidence === 'low' && <span className="warn">לא בטוח שהמייל שייך למשרה הזאת</span>}
                    <select value="" onChange={(e) => reassign(m.id, e.target.value)}>
                      <option value="">העבר להגשה אחרת באותה חברה…</option>
                      {siblings.map((s) => (
                        <option key={s.id} value={s.id}>{s.position || s.company} ({fmtDate(s.applied_date)})</option>
                      ))}
                    </select>
                  </div>
                )}
              </li>
            )
          })}
          {mails.length === 0 && <li className="muted">עוד לא קושרו מיילים להגשה הזאת.</li>}
        </ul>

        <h3>היסטוריה</h3>
        <ul className="timeline">
          {events.map((ev) => (
            <li key={ev.id}>
              <div className="muted">{fmtDateTime(ev.ts)}</div>
              {ev.status && <span className={`pill ${statusClass(ev.status)}`}>{ev.status}</span>} {ev.note}
            </li>
          ))}
        </ul>

        <div className="actions">
          <button className="danger" onClick={onDelete}>מחיקה</button>
          <span className="spacer" />
          <button onClick={onEdit}>עריכה</button>
          <button onClick={onClose}>סגירה</button>
        </div>
      </aside>
    </div>
  )
}
