import { useMemo } from 'react'
import type { Dataset } from '../data/dataset'
import { lowerBound, upperBound } from '../data/interpolate'
import type { TimeFormat } from '../data/time'
import type { KpisFile, SepEvent } from '../data/types'

interface Props {
  ds: Dataset
  kpis: KpisFile
  t: number
  fmt: TimeFormat
  onSelect: (id: string) => void
}

const ARRIVAL_REFERENCE = 54
const HOUR = 3600

function median(values: number[]) {
  if (!values.length) return null
  const sorted = values.slice().sort((a, b) => a - b)
  const middle = sorted.length >> 1
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

function minutes(value: number | null, signed = false) {
  if (value === null) return '—'
  const rounded = Math.round(value)
  return `${signed && rounded > 0 ? '+' : ''}${rounded} min`
}

export default function Kpis({ ds, kpis, t, fmt, onSelect }: Props) {
  const index = useMemo(
    () => ({
      separationTimes: Float64Array.from(kpis.sep_events, (event) => event.t_start),
      goAroundTimes: Float64Array.from(kpis.go_arounds, (event) => event.t),
      longestEvent: kpis.sep_events.reduce((max, event) => Math.max(max, event.t_end - event.t_start), 0),
    }),
    [kpis],
  )
  const weekTracked = useMemo(() => ds.flights.filter((flight) => ds.tracks.has(flight.id)).length, [ds])
  const name = (id: string) => {
    const flight = ds.byId.get(id)
    return flight?.callsign || flight?.reg || id
  }

  const separationCount = upperBound(index.separationTimes, t)
  const separationsLastHour = separationCount - upperBound(index.separationTimes, t - HOUR)
  const goAroundCount = upperBound(index.goAroundTimes, t)
  const separationEvaluable = kpis.coverage?.separation_evaluable_tracks ?? 0
  const goAroundEvaluable = kpis.coverage?.go_around_evaluable_arrivals ?? 0
  const active: SepEvent[] = []
  for (let i = separationCount - 1; i >= lowerBound(index.separationTimes, t - index.longestEvent); i--) {
    if (kpis.sep_events[i].t_end >= t) active.push(kpis.sep_events[i])
  }

  const hourFlights = ds.flights.slice(upperBound(ds.times, t - HOUR), upperBound(ds.times, t))
  const arrivals = hourFlights.filter((flight) => flight.kind === 'arr')
  const departures = hourFlights.length - arrivals.length
  const runwayCounts = ['28L', '28R'].map((runway) => hourFlights.filter((flight) => flight.runway === runway).length)
  const runwayTotal = runwayCounts[0] + runwayCounts[1]
  const runwayShare = (count: number) => runwayTotal ? `${Math.round(100 * count / runwayTotal)}%` : '—'
  const otherRunways = hourFlights.length - runwayTotal

  const offsets: number[] = []
  for (let i = upperBound(ds.times, t - 3 * HOUR), end = upperBound(ds.times, t); i < end; i++) {
    const flight = ds.flights[i]
    if (flight.kind === 'arr' && ds.tracks.has(flight.id) && typeof flight.sched === 'number' && Number.isFinite(flight.sched)) {
      offsets.push((flight.t - flight.sched) / 60)
    }
  }
  const medianOffset = median(offsets)
  const within15 = offsets.length ? Math.round(100 * offsets.filter((offset) => offset <= 15).length / offsets.length) : null
  const spacing = ['28L', '28R'].map((runway) => {
    const runwayArrivals = arrivals.filter((flight) => flight.runway === runway)
    const gaps = runwayArrivals.slice(1).map((flight, i) => (flight.t - runwayArrivals[i].t) / 60)
    return { runway, gap: median(gaps), count: gaps.length }
  })

  const dayFlights = ds.flights.slice(lowerBound(ds.times, fmt.dayStart(t)), upperBound(ds.times, t))
  const dayTracked = dayFlights.filter((flight) => ds.tracks.has(flight.id)).length
  const coverage = dayFlights.length ? Math.round(100 * dayTracked / dayFlights.length) : null

  return (
    <section className="kpis" aria-labelledby="kpi-title">
      <div className="kpi-heading">
        <h2 id="kpi-title">ATC performance</h2>
        <span>At replay time</span>
      </div>
      <div className="kgrid">
        <div className={`kpi-card safety ${active.length ? 'has-alert' : ''}`}>
          <h3>Safety candidates <span>Week so far · limited altitude coverage</span></h3>
          <div className="metric-pair">
            <div><b className={separationEvaluable ? '' : 'unavailable'}>{separationEvaluable ? separationCount : 'Unavailable'}</b><span>separation candidates</span></div>
            <div><b className={goAroundEvaluable ? '' : 'unavailable'}>{goAroundEvaluable ? goAroundCount : 'Unavailable'}</b><span>go-around candidates</span></div>
          </div>
          <p>{separationEvaluable ? `${separationsLastHour} separation candidates in the last hour. Sparse reported-altitude coverage.` : 'No usable reported-altitude track segments for separation checks.'}</p>
          {!goAroundEvaluable && <p>No usable low-altitude arrival observations for go-around detection.</p>}
          {active.map((event) => (
            <div key={`${event.a}-${event.b}-${event.t_start}`} className="alert">
              <strong>Active candidate</strong> · minimum {event.min_nm.toFixed(1)} NM / {Math.round(event.min_ft).toLocaleString()} ft
              <div>
                <button onClick={() => onSelect(event.a)}>{name(event.a)}</button>
                <span> / </span>
                <button onClick={() => onSelect(event.b)}>{name(event.b)}</button>
              </div>
            </div>
          ))}
        </div>

        <div className="kpi-card">
          <h3>Throughput <span>Last 60 min</span></h3>
          <div className="metric-value"><b>{arrivals.length}</b><span>arrivals /h</span></div>
          <div className="throughput-track" aria-hidden="true"><span style={{ width: `${Math.min(100, 100 * arrivals.length / ARRIVAL_REFERENCE)}%` }} /></div>
          <p>{ARRIVAL_REFERENCE} /h demo reference (visual conditions) · {departures} departures</p>
          <p className="metric-scope">All roster operations, including those without paths</p>
        </div>

        <div className="kpi-card">
          <h3>Arrival schedule offset <span>Last 3 h</span></h3>
          <div className="metric-value"><b>{minutes(medianOffset, true)}</b><span>median</span></div>
          <p>{within15 === null ? '—' : `${within15}%`} at most 15 min late · {offsets.length} tracked, scheduled arrivals</p>
          <p className="metric-scope">Recorded operation vs scheduled arrival; approximate</p>
        </div>

        <div className="kpi-card">
          <h3>Runway use <span>Last 60 min</span></h3>
          <div className="runway-metrics">
            {['28L', '28R'].map((runway, i) => (
              <div key={runway}><span>{runway}</span><b>{runwayShare(runwayCounts[i])}</b><small>{runwayCounts[i]} ops</small></div>
            ))}
          </div>
          <p>{runwayTotal} roster ops on the 28s{otherRunways > 0 ? ` · ${otherRunways} on other runways` : ''}</p>
        </div>

        <div className="kpi-card">
          <h3>Arrival spacing <span>Last 60 min</span></h3>
          <div className="runway-metrics">
            {spacing.map(({ runway, gap, count }) => (
              <div key={runway}><span>{runway}</span><b>{gap === null ? '—' : `${gap.toFixed(1)} min`}</b><small>{count} gaps</small></div>
            ))}
          </div>
          <p>Median gap between roster arrivals on each runway</p>
        </div>

        <div className="kpi-card">
          <h3>Path coverage <span>Today so far</span></h3>
          <div className="metric-value"><b>{coverage === null ? '—' : `${coverage}%`}</b><span>of roster operations</span></div>
          <p>{dayTracked.toLocaleString()} of {dayFlights.length.toLocaleString()} operations have a path</p>
          <p className="metric-scope">Full week: {weekTracked.toLocaleString()} / {ds.flights.length.toLocaleString()} operations</p>
        </div>
      </div>
      <details className="kpi-methods">
        <summary>How to read these metrics</summary>
        <p>Safety counts are track-derived candidates, not verified incidents. Missing paths cannot contribute to safety counts.</p>
        <p>Separation candidates are under 3 NM horizontally and under 1,000 ft vertically. Checks use reported beacon altitude, sampled every 10 seconds. Assigned altitude is excluded. Observation gaps over 120 seconds are excluded.</p>
        <p>The paired-approach exclusion is a demo heuristic: opposite 28L/28R arrivals, below 3,000 ft, up to 8 NM before their thresholds, within 0.5 NM of their centerlines, heading inbound within 20°. It does not establish visual separation.</p>
        <p>Go-around candidates descend below 1,500 ft within 6 NM, then climb at least 1,000 ft. These rules cannot establish controller clearance.</p>
        <p>Across the full week, {separationEvaluable.toLocaleString()} tracks have usable altitude segments for separation checks; {goAroundEvaluable.toLocaleString()} arrivals have usable low-altitude observations for go-around checks. Zero candidates does not establish safe separation.</p>
        <p>The 54 arrivals per hour figure is a demo reference, not measured capacity for this week.</p>
        <p>Throughput, runway use, and spacing include the full roster. Schedule offsets include tracked arrivals with a schedule. Departure schedules are unavailable.</p>
        <p>Windows end at the replay clock. Safety totals start at the beginning of the week. Coverage starts at local midnight.</p>
        <p>Sources: <a href="https://data.sf.gov/d/43zc-xw3x" target="_blank" rel="noreferrer">DataSF SFO operations</a> (PDDL); <a href="https://github.com/sfomuseum-data/sfomuseum-data-flights-2026-08" target="_blank" rel="noreferrer">SFO Museum flight paths</a> (CDLA-Permissive-1.0).</p>
      </details>
    </section>
  )
}
