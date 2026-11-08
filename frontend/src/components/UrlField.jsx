import { normalizeUrl } from '../util.js'

// A text input for a job link with an "open" button next to it that opens the job page in a new tab
export default function UrlField({ value, onChange, placeholder = 'https://…' }) {
  const href = normalizeUrl(value)
  return (
    <span className="url-field">
      <input dir="ltr" placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />
      {href ? (
        <a className="btn" href={href} target="_blank" rel="noreferrer" title="פתח את עמוד המשרה">🔗 פתח</a>
      ) : (
        <span className="btn disabled" aria-disabled="true">🔗 פתח</span>
      )}
    </span>
  )
}
