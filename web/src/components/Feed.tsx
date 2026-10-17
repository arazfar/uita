import { memo } from 'react'
import type { TimeFormat } from '../data/time'
import type { Flight } from '../data/types'

interface Props {
  events: Flight[]
  fmt: TimeFormat
  selectedId: string | null
  onSelect: (id: string) => void
}

const Row = memo(function Row({ f, fmt, selected, onSelect }: { f: Flight; fmt: TimeFormat; selected: boolean; onSelect: (id: string) => void }) {
  const name = f.callsign || f.reg || f.id
  return (
    <li>
      <button className={`feed-row ${selected ? 'sel' : ''}`} onClick={() => onSelect(f.id)} aria-pressed={selected} aria-label={`${name}, ${f.kind === 'arr' ? 'arrival' : 'departure'} at ${fmt.hms(f.t)}, ${f.has_track ? 'path available' : 'no map path'}`}>
        <span className="time">{fmt.hms(f.t)}</span>
        <span className={`badge ${f.kind}`}>{f.kind === 'arr' ? 'ARR' : 'DEP'}</span>
        <span className="cs">{name}</span>
        <span className="ty">{f.type || '—'}</span>
        <span className="port">{f.kind === 'arr' ? 'from' : 'to'} {f.port || 'unknown'}</span>
        <span className="rwy">{f.runway || '—'}</span>
        <span className={`path ${f.has_track ? 'yes' : 'no'}`}>{f.has_track ? 'path' : 'no path'}</span>
      </button>
    </li>
  )
})

export default function Feed({ events, fmt, selectedId, onSelect }: Props) {
  return (
    <ul className="feed" aria-label="Recent roster operations, newest first">
      {events.length ? events.map((f) => (
        <Row key={f.id} f={f} fmt={fmt} selected={f.id === selectedId} onSelect={onSelect} />
      )) : <li className="feed-empty">No operations yet. Select a day to jump to 07:00.</li>}
    </ul>
  )
}
