import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api.js'
import ApplicationForm from './components/ApplicationForm.jsx'
import Detail from './components/Detail.jsx'
import EmailInbox from './components/EmailInbox.jsx'
import ScreenshotImport from './components/ScreenshotImport.jsx'
import MailSync from './components/MailSync.jsx'
import Stats from './components/Stats.jsx'
import { daysSince, fmtDate, normalizeUrl, statusClass } from './util.js'

const CLOSED = ['התקבלתי', 'נדחיתי', 'ביטלתי']

export default function App() {
  const [meta, setMeta] = useState({ statuses: [], email_configured: false, category_labels: {} })
  const [apps, setApps] = useState([])
  const [tab, setTab] = useState('apps')
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [form, setForm] = useState(null) // null | {} (new) | an application object (edit)
  const [detailId, setDetailId] = useState(null)
  const [error, setError] = useState('')
  const [shot, setShot] = useState(null) // null = the screenshot dialog is closed; {file} = open (file may be empty)

  // pasting a screenshot (Ctrl+V) anywhere on the page
  useEffect(() => {
    const onPaste = (e) => {
      const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith('image/'))
      if (item) setShot((open) => open || { file: item.getAsFile() }) // when the dialog is already open it handles the paste itself
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [])

  const reload = useCallback(async () => {
    try {
      setApps(await api.list())
      setError('')
    } catch (e) {
      setError(`לא ניתן להתחבר לשרת: ${e.message}`)
    }
  }, [])

  useEffect(() => {
    api.meta().then(setMeta).catch(() => {})
    reload()
  }, [reload])

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    return apps.filter(
      (a) =>
        (!statusFilter || a.status === statusFilter) &&
        (!q || [a.company, a.position, a.location, a.source, a.notes].join(' ').toLowerCase().includes(q)),
    )
  }, [apps, search, statusFilter])

  const pendingEmails = apps.reduce((n, a) => n + Number(a.pending_emails || 0), 0)
  const detail = apps.find((a) => a.id === detailId)

  const save = async (data) => {
    if (data.id) await api.update(data.id, data)
    else await api.create(data)
    setForm(null)
    reload()
  }

  const importFile = async (file) => {
    if (!file) return
    const { imported } = await api.importCsv(await file.text())
    alert(`יובאו ${imported} הגשות`)
    reload()
  }

  return (
    <div className="page">
      <header>
        <h1>מעקב הגשות</h1>
        <nav>
          <button className={tab === 'apps' ? 'tab active' : 'tab'} onClick={() => setTab('apps')}>
            הגשות ({apps.length})
          </button>
          <button className={tab === 'email' ? 'tab active' : 'tab'} onClick={() => setTab('email')}>
            תשובות במייל {pendingEmails > 0 && <span className="badge">{pendingEmails}</span>}
          </button>
        </nav>
      </header>

      {error && <div className="error">{error}</div>}

      {tab === 'email' ? (
        <EmailInbox meta={meta} onChange={reload} />
      ) : (
        <>
          <Stats apps={apps} />
          <MailSync meta={meta} onDone={reload} />
          <div className="toolbar">
            <button className="primary" onClick={() => setForm({})}>+ הגשה חדשה</button>
            <input placeholder="חיפוש חברה, תפקיד, הערות…" value={search} onChange={(e) => setSearch(e.target.value)} />
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">כל הסטטוסים</option>
              {meta.statuses.map((s) => <option key={s}>{s}</option>)}
            </select>
            <button onClick={() => setShot({ file: null })} title="אפשר גם להדביק צילום מסך עם Ctrl+V בכל מקום בעמוד">
              📷 מצילום מסך
            </button>
            <span className="spacer" />
            <a className="btn" href="/api/export.csv">ייצוא CSV</a>
            <label className="btn">
              ייבוא CSV
              <input type="file" accept=".csv" hidden onChange={(e) => { importFile(e.target.files[0]); e.target.value = '' }} />
            </label>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>חברה</th><th>תפקיד</th><th>מקור</th><th>הוגשה</th><th>סטטוס</th><th>מעקב</th><th /></tr>
              </thead>
              <tbody>
                {visible.map((a) => {
                  const open = !CLOSED.includes(a.status)
                  const idle = open ? daysSince(a.last_activity) : 0
                  const due = open && a.follow_up_date && a.follow_up_date <= new Date().toISOString().slice(0, 10)
                  return (
                    <tr key={a.id} onClick={() => setDetailId(a.id)}>
                      <td><strong>{a.company}</strong>{a.pending_emails > 0 && <span className="badge" title="מייל ממתין לאישור">✉ {a.pending_emails}</span>}</td>
                      <td>{a.position}</td>
                      <td>{a.source}</td>
                      <td>{fmtDate(a.applied_date)}</td>
                      <td><span className={`pill ${statusClass(a.status)}`}>{a.status}</span></td>
                      <td>
                        {due ? <span className="warn">לחזור אליהם! ({fmtDate(a.follow_up_date)})</span>
                          : open && idle >= 7 ? <span className="muted">{idle} ימים בלי עדכון</span> : fmtDate(a.follow_up_date)}
                      </td>
                      <td className="row-actions" onClick={(e) => e.stopPropagation()}>
                        {a.url && <a className="btn" href={normalizeUrl(a.url)} target="_blank" rel="noreferrer" title="פתח את המשרה">🔗</a>}
                        <button onClick={() => setForm(a)}>עריכה</button>
                      </td>
                    </tr>
                  )
                })}
                {visible.length === 0 && (
                  <tr><td colSpan="7" className="empty">{apps.length ? 'אין תוצאות לסינון הזה' : 'עוד לא הוספת הגשות. לחץ על "הגשה חדשה" כדי להתחיל.'}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {shot && (
        <ScreenshotImport
          initialFile={shot.file}
          statuses={meta.statuses}
          onClose={() => setShot(null)}
          onSaved={(n) => { setShot(null); setTab('apps'); reload(); alert(`נוספו ${n} הגשות`) }}
        />
      )}
      {form && <ApplicationForm initial={form} statuses={meta.statuses} onSave={save} onClose={() => setForm(null)} />}
      {detail && (
        <Detail
          app={detail}
          statuses={meta.statuses}
          meta={meta}
          siblings={apps.filter((a) => a.id !== detail.id && a.company.trim().toLowerCase() === detail.company.trim().toLowerCase())}
          onClose={() => setDetailId(null)}
          onEdit={() => { setForm(detail); setDetailId(null) }}
          onChange={reload}
          onDelete={async () => {
            if (confirm(`למחוק את ההגשה ל-${detail.company}?`)) {
              await api.remove(detail.id)
              setDetailId(null)
              reload()
            }
          }}
        />
      )}
    </div>
  )
}
