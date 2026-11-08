import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtDateTime } from '../util.js'

// [days, label in the dropdown, short label for the "last scan" line]
const RANGES = [
  [1, 'יום אחרון', 'יום'], [3, '3 ימים אחרונים', '3 ימים'], [7, 'שבוע אחרון', 'שבוע'],
  [14, 'שבועיים אחרונים', 'שבועיים'], [30, 'חודש אחרון', 'חודש'], [90, '3 חודשים אחרונים', '3 חודשים'],
]
const rangeLabel = (days) => (RANGES.find(([d]) => d === days) || [days, '', `${days} ימים`])[2]

// "Update from email": scans the chosen time range, links every email that matches a job to that job,
// and shows when the scan was last run.
export default function MailSync({ meta, onDone }) {
  const [days, setDays] = useState(7)
  const [busy, setBusy] = useState(false)
  const [last, setLast] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => { api.lastScan().then(setLast).catch(() => {}) }, [])

  const run = async () => {
    setBusy(true)
    setError('')
    setResult(null)
    try {
      const r = await api.scanEmail(days, meta.ai_configured)
      setResult(r)
      setLast({ ran_at: r.ran_at, days: r.days })
      onDone && onDone()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="sync-card">
      <div className="toolbar">
        <button className="primary" onClick={run} disabled={busy || !meta.email_configured}>
          {busy ? 'סורק מיילים…' : '📬 עדכן ממיילים'}
        </button>
        <label className="inline">
          טווח:
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} disabled={busy}>
            {RANGES.map(([d, label]) => <option key={d} value={d}>{label}</option>)}
          </select>
        </label>
        <span className="muted">
          {last
            ? `סריקה אחרונה: ${fmtDateTime(last.ran_at)} (טווח: ${rangeLabel(last.days)})`
            : 'עוד לא בוצעה סריקה'}
        </span>
      </div>
      {busy && (
        <div className="muted">
          {meta.ai_configured ? 'Claude בודק את המיילים, זה יכול לקחת כמה דקות.' : 'סורק לפי מילות מפתח…'}
        </div>
      )}
      {!meta.email_configured && (
        <div className="muted">הגדרות המייל חסרות: מלא IMAP_USER ו-IMAP_PASSWORD בקובץ backend/.env והפעל מחדש את השרת.</div>
      )}
      {error && <div className="error">{error}</div>}
      {result && (
        <div className="sync-result">
          {result.new === 0 ? (
            <div>לא נמצאו מיילים חדשים בטווח הזה.</div>
          ) : (
            <>
              <div>
                נמצאו {result.new} מיילים חדשים: {result.linked} עודכנו במשרות
                {result.needs_review > 0 && `, ${result.needs_review} מציעים שינוי סטטוס וממתינים לאישור`}
                {result.discovered > 0 && `, ${result.discovered} על משרות חדשות שעוד לא במעקב`}.
              </div>
              {result.updated.length > 0 && (
                <div className="muted">
                  עודכנו: {result.updated.map((u) => `${u.company}${u.position ? ` (${u.position})` : ''} ×${u.count}`).join(' · ')}
                </div>
              )}
              {(result.needs_review > 0 || result.discovered > 0) && (
                <div className="muted">את ההצעות לאישור אפשר לראות בלשונית "תשובות במייל".</div>
              )}
            </>
          )}
          {result.ai_errors > 0 && <div className="warn">סיווג ה-AI נכשל ב-{result.ai_errors} מיילים, ולהם הופעלו מילות מפתח.</div>}
        </div>
      )}
    </div>
  )
}
