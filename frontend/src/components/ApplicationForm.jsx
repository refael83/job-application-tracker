import { useState } from 'react'
import { normalizeUrl } from '../util.js'
import UrlField from './UrlField.jsx'

const SOURCES = ['AllJobs', 'דרושים', 'JobMaster', 'LinkedIn', 'אתר החברה', 'חבר/המלצה', 'אחר']
const today = () => new Date().toISOString().slice(0, 10)

export default function ApplicationForm({ initial, statuses, onSave, onClose }) {
  const [f, setF] = useState({
    company: '', position: '', url: '', source: '', location: '', status: 'הוגשה',
    resume_version: '', contact: '', salary: '', notes: '',
    applied_date: today(), follow_up_date: '',
    ...Object.fromEntries(Object.entries(initial).map(([k, v]) => [k, v ?? ''])),
  })
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      await onSave({ ...f, url: normalizeUrl(f.url) })
    } catch (err) {
      alert(err.message)
      setBusy(false)
    }
  }

  return (
    <div className="overlay" onMouseDown={onClose}>
      <form className="modal" onMouseDown={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>{f.id ? 'עריכת הגשה' : 'הגשה חדשה'}</h2>
        <div className="grid">
          <label>חברה *<input required autoFocus value={f.company} onChange={set('company')} /></label>
          <label>תפקיד<input value={f.position} onChange={set('position')} /></label>
          <label className="wide-field">קישור למשרה
            <UrlField value={f.url} onChange={(v) => setF({ ...f, url: v })} />
          </label>
          <label>מקור
            <input list="sources" value={f.source} onChange={set('source')} />
            <datalist id="sources">{SOURCES.map((s) => <option key={s} value={s} />)}</datalist>
          </label>
          <label>מיקום<input value={f.location} onChange={set('location')} /></label>
          <label>תאריך הגשה<input type="date" value={f.applied_date} onChange={set('applied_date')} /></label>
          <label>סטטוס
            <select value={f.status} onChange={set('status')}>{statuses.map((s) => <option key={s}>{s}</option>)}</select>
          </label>
          <label>גרסת קורות חיים<input placeholder="עברית / אנגלית" value={f.resume_version} onChange={set('resume_version')} /></label>
          <label>איש קשר<input value={f.contact} onChange={set('contact')} /></label>
          <label>שכר<input value={f.salary} onChange={set('salary')} /></label>
          <label>תאריך מעקב<input type="date" value={f.follow_up_date} onChange={set('follow_up_date')} /></label>
        </div>
        <label>הערות<textarea rows="3" value={f.notes} onChange={set('notes')} /></label>
        <div className="actions">
          <button type="button" onClick={onClose}>ביטול</button>
          <button className="primary" disabled={busy}>שמירה</button>
        </div>
      </form>
    </div>
  )
}
