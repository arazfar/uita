import type { Dataset } from '../data/dataset'
import { sampleTrack } from '../data/interpolate'
import type { TimeFormat } from '../data/time'

interface Props {
  ds: Dataset
  id: string
  t: number
  fmt: TimeFormat
  onClose: () => void
}

export default function Inspector({ ds, id, t, fmt, onClose }: Props) {
  const f = ds.byId.get(id)
  if (!f) return null
  const tr = ds.tracks.get(id)
  const s = tr ? sampleTrack(tr, t) : null
  const rows: [string, string][] = [
    ['Callsign', f.callsign],
    ['Reg', f.reg],
    ['Type', f.type],
    ['Airline', f.airline],
    [f.kind === 'arr' ? 'Origin' : 'Destination', f.port],
    ['Runway', f.runway],
    [f.kind === 'arr' ? 'Landed' : 'Departed', `${fmt.day(f.t)} ${fmt.hms(f.t)}`],
    ['Track points', tr ? String(tr.n) : 'no path'],
    ['Altitude now', s && !Number.isNaN(s.alt) ? `${Math.round(s.alt)} ft` : '-'],
    ['Speed now', s && !Number.isNaN(s.spd) ? `${Math.round(s.spd)} kt` : '-'],
  ]
  return (
    <div className="inspector">
      <div className="ih">
        <b>
          {f.callsign || f.reg} <span className={`badge ${f.kind}`}>{f.kind === 'arr' ? 'ARR' : 'DEP'}</span>
        </b>
        <button onClick={onClose}>Close</button>
      </div>
      <dl>
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
