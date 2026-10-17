import { useEffect, useRef } from 'react'
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
  const panel = useRef<HTMLElement>(null)
  useEffect(() => {
    panel.current?.focus({ preventScroll: true })
    panel.current?.scrollIntoView({ block: 'nearest' })
  }, [id])
  const flight = ds.byId.get(id)
  if (!flight) return null
  const track = ds.tracks.get(id)
  const sample = track ? sampleTrack(track, t) : null
  const name = flight.callsign || flight.reg || flight.id
  const rows: [string, string][] = [
    ['Callsign', flight.callsign || 'Unknown'],
    ['Registration', flight.reg || 'Unknown'],
    ['Aircraft', flight.type || 'Unknown'],
    ['Airline', flight.airline || 'Unknown'],
    [flight.kind === 'arr' ? 'Origin' : 'Destination', flight.port || 'Unknown'],
    ['Runway', flight.runway || 'Unknown'],
    [flight.kind === 'arr' ? 'Arrival' : 'Departure', `${fmt.day(flight.t)} ${fmt.hms(flight.t)}`],
    ['Track points', track ? track.n.toLocaleString() : 'No map path'],
    ['Path source', flight.track_source || (track ? 'SFO Museum' : 'No matched path')],
    ['ICAO address', flight.icao24 || 'Not recorded'],
    ['Reported altitude now', sample && Number.isFinite(sample.alt) ? `${Math.round(sample.alt).toLocaleString()} ft` : '—'],
    ['Derived speed now', sample && Number.isFinite(sample.spd) ? `${Math.round(sample.spd)} kt` : '—'],
  ]
  if (flight.kind === 'arr' && typeof flight.sched === 'number' && Number.isFinite(flight.sched)) {
    rows.push(['Scheduled arrival', `${fmt.day(flight.sched)} ${fmt.hm(flight.sched)}`])
  }
  return (
    <section ref={panel} tabIndex={-1} className="inspector" aria-label={`Flight details for ${name}`}>
      <span className="instrument-label">Selected operation / Flight strip</span>
      <div className="ih">
        <b>{name} <span className={`badge ${flight.kind}`}>{flight.kind === 'arr' ? 'ARR' : 'DEP'}</span></b>
        <button onClick={onClose} aria-label="Close flight details">Close</button>
      </div>
      <p className="inspector-status">{!track ? 'This roster operation has no map path.' : sample ? 'Observed path at the replay time.' : 'Path available outside the current replay time.'}</p>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
        ))}
      </dl>
      <p className="inspector-zone">Times in {fmt.tzName(t)}</p>
    </section>
  )
}
