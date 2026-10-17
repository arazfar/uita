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
  return (
    <li className={selected ? 'sel' : ''} onClick={() => onSelect(f.id)}>
      <span className="time">{fmt.hms(f.t)}</span>
      <span className={`badge ${f.kind}`}>{f.kind === 'arr' ? 'ARR' : 'DEP'}</span>
      <span className="cs">{f.callsign || f.reg}</span>
      <span className="ty">{f.type}</span>
      <span className="port">
        {f.kind === 'arr' ? 'from' : 'to'} {f.port}
      </span>
      <span className="rwy">{f.runway}</span>
      <span className={`path ${f.has_track ? 'yes' : 'no'}`}>{f.has_track ? 'path' : 'no path'}</span>
    </li>
  )
})

export default function Feed({ events, fmt, selectedId, onSelect }: Props) {
  return (
    <ul className="feed">
      {events.map((f) => (
        <Row key={f.id} f={f} fmt={fmt} selected={f.id === selectedId} onSelect={onSelect} />
      ))}
    </ul>
  )
}
