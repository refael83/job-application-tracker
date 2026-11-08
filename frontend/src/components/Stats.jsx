export default function Stats({ apps }) {
  const total = apps.length
  const count = (...statuses) => apps.filter((a) => statuses.includes(a.status)).length
  const responded = apps.filter((a) => !['הוגשה', 'ללא מענה'].includes(a.status)).length
  const rate = total ? Math.round((responded / total) * 100) : 0

  const cards = [
    ['סה"כ הגשות', total],
    ['בתהליך', total - count('התקבלתי', 'נדחיתי', 'ביטלתי', 'ללא מענה')],
    ['ראיונות ומטלות', count('שיחת טלפון', 'ראיון ראשון', 'מטלת בית', 'ראיון טכני', 'ראיון סופי')],
    ['הצעות', count('הצעה', 'התקבלתי')],
    ['נדחיתי', count('נדחיתי')],
    ['אחוז תגובה', `${rate}%`],
  ]
  return (
    <div className="stats">
      {cards.map(([label, value]) => (
        <div className="stat" key={label}>
          <div className="stat-value">{value}</div>
          <div className="stat-label">{label}</div>
        </div>
      ))}
    </div>
  )
}
