import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { normalizeUrl } from '../util.js'
import UrlField from './UrlField.jsx'

const SOURCES = ['AllJobs', 'דרושים', 'JobMaster', 'LinkedIn', 'אתר החברה', 'חבר/המלצה', 'אחר']
const TYPES = ['image/png', 'image/jpeg', 'image/webp']
const MAX_BYTES = 8 * 1024 * 1024

export default function ScreenshotImport({ initialFile, statuses, onClose, onSaved }) {
  const [file, setFile] = useState(initialFile || null)
  const [preview, setPreview] = useState('')
  const [phase, setPhase] = useState('pick') // pick -> loading -> review
  const [rows, setRows] = useState([])
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [link, setLink] = useState('')
  const inputRef = useRef(null)

  const choose = (f) => {
    if (!f) return
    if (!TYPES.includes(f.type)) return setError('פורמט לא נתמך. יש להעלות PNG, JPG או WEBP')
    if (f.size > MAX_BYTES) return setError('התמונה גדולה מדי (עד 8MB)')
    setError('')
    setFile(f)
  }

  // preview of the selected image
  useEffect(() => {
    if (!file) return setPreview('')
    const url = URL.createObjectURL(file)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  // paste (Ctrl+V) while the dialog is open
  useEffect(() => {
    const onPaste = (e) => {
      if (phase !== 'pick') return
      const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith('image/'))
      if (item) choose(item.getAsFile())
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [phase])

  // the screenshot is sent for parsing only after the user clicks Confirm
  const confirm = async () => {
    setPhase('loading')
    setError('')
    try {
      const { jobs } = await api.extractScreenshot(file)
      const today = new Date().toISOString().slice(0, 10)
      setRows(jobs.map((j) => ({
        ...j, applied_date: j.applied_date || today, include: true,
        urlFromImage: !!j.url, // the link was read from the image, so it may contain misread characters
        url: normalizeUrl(j.url || (jobs.length === 1 ? link.trim() : '')), // a manually entered link applies when exactly one job was detected
      })))
      setPhase('review')
    } catch (e) {
      setError(e.message)
      setPhase('pick')
    }
  }

  const set = (i, k, v) => setRows(rows.map((r, idx) => (idx === i ? { ...r, [k]: v } : r)))
  const chosen = rows.filter((r) => r.include && r.company.trim())

  const save = async () => {
    setSaving(true)
    try {
      for (const r of chosen) {
        await api.create({
          company: r.company, position: r.position, url: normalizeUrl(r.url), source: r.source, location: r.location,
          applied_date: r.applied_date || null, status: r.status, notes: r.notes,
        })
      }
      onSaved(chosen.length)
    } catch (e) {
      setError(e.message)
      setSaving(false)
    }
  }

  return (
    <div className="overlay" onMouseDown={phase === 'loading' ? undefined : onClose}>
      <div className="modal wide" onMouseDown={(e) => e.stopPropagation()}>
        <h2>הוספה מצילום מסך</h2>

        {phase !== 'review' && (
          <>
            <div
              className={`dropzone${dragging ? ' dragging' : ''}`}
              onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => { e.preventDefault(); setDragging(false); choose(e.dataTransfer.files[0]) }}
            >
              {preview ? (
                <img className="shot" src={preview} alt="הצילום שנבחר" />
              ) : (
                <div className="muted">הדבק צילום מסך כאן (Ctrl+V), גרור לכאן קובץ, או בחר תמונה מהמחשב</div>
              )}
              <button type="button" disabled={phase === 'loading'} onClick={() => inputRef.current.click()}>
                {file ? 'בחירת תמונה אחרת' : 'בחירת תמונה'}
              </button>
              <input ref={inputRef} type="file" accept={TYPES.join(',')} hidden
                onChange={(e) => { choose(e.target.files[0]); e.target.value = '' }} />
            </div>
            <label className="wide-label">
              קישור למשרה (לא חובה)
              <UrlField value={link} onChange={setLink} />
            </label>
            <p className="muted">
              לחיצה על "אישור" שולחת את התמונה ל-Anthropic לחילוץ המידע. התמונה לא נשמרת. אחרי החילוץ תוכל לבדוק ולתקן
              הכל לפני ההוספה למעקב.
            </p>
          </>
        )}

        {error && <div className="error">{error}</div>}
        {phase === 'loading' && <div className="empty">קורא את התמונה… (בדרך כלל 10–30 שניות)</div>}

        {phase === 'review' && (
          <>
            {preview && <img className="shot" src={preview} alt="הצילום שנשלח" />}
            {rows.length === 0 && (
              <div className="empty">לא זוהתה משרה בתמונה. נסה צילום שמראה את כותרת המשרה ושם החברה.</div>
            )}
            {rows.map((r, i) => (
              <div className="mail" key={i}>
                <label className="inline">
                  <input type="checkbox" checked={r.include} onChange={(e) => set(i, 'include', e.target.checked)} />
                  להוסיף למעקב
                </label>
                <div className="grid">
                  <label>חברה<input value={r.company} onChange={(e) => set(i, 'company', e.target.value)} /></label>
                  <label>תפקיד<input value={r.position} onChange={(e) => set(i, 'position', e.target.value)} /></label>
                  <label>תאריך הגשה<input type="date" value={r.applied_date} onChange={(e) => set(i, 'applied_date', e.target.value)} /></label>
                  <label>סטטוס
                    <select value={r.status} onChange={(e) => set(i, 'status', e.target.value)}>
                      {statuses.map((s) => <option key={s}>{s}</option>)}
                    </select>
                  </label>
                  <label>מקור
                    <input list="shot-sources" value={r.source} onChange={(e) => set(i, 'source', e.target.value)} />
                  </label>
                  <label>קישור למשרה<UrlField value={r.url} onChange={(v) => set(i, 'url', v)} />
                    {r.urlFromImage && <span className="muted">הקישור נקרא מהתמונה: לחץ על "פתח" כדי לוודא שהוא נכון לפני ההוספה</span>}
                  </label>
                  <label>הערות<input value={r.notes} onChange={(e) => set(i, 'notes', e.target.value)} /></label>
                </div>
              </div>
            ))}
            <datalist id="shot-sources">{SOURCES.map((s) => <option key={s} value={s} />)}</datalist>
          </>
        )}

        <div className="actions">
          <button onClick={onClose} disabled={phase === 'loading' || saving}>ביטול</button>
          {phase === 'review' && <button onClick={() => { setPhase('pick'); setRows([]) }}>חזרה לבחירת תמונה</button>}
          <span className="spacer" />
          {phase !== 'review' ? (
            <button className="primary" disabled={!file || phase === 'loading'} onClick={confirm}>אישור</button>
          ) : (
            <button className="primary" disabled={saving || chosen.length === 0} onClick={save}>
              הוסף {chosen.length || ''} למעקב
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
