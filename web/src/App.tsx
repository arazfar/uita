import { useCallback, useEffect, useMemo, useState } from 'react'
import Controls from './components/Controls'
import Feed from './components/Feed'
import Inspector from './components/Inspector'
import MapView from './components/Map'
import { SimClock } from './data/clock'
import { activeTracks, buildDataset, recentTracked, type Dataset } from './data/dataset'
import { loadFlights, loadRunways, loadTracks, type RunwayCollection } from './data/loaders'
import { makeTimeFormat } from './data/time'
import { sampleTrack, upperBound } from './data/interpolate'
import type { Flight } from './data/types'

const FEED_MAX = 100
const HOUR = 3600
const UI_HZ_MS = 250

interface Loaded {
  ds: Dataset
  runways: RunwayCollection
}

interface Snap {
  t: number
  playing: boolean
  speed: number
  events: Flight[]
  airborne: number
  hourArr: number
  hourDep: number
  /** last-hour operations on 28L, 28R */
  runways: [number, number]
}

function Live({ ds, runways }: Loaded) {
  const fmt = useMemo(() => makeTimeFormat(ds.week.tz), [ds])
  const clock = useMemo(() => {
    const c = new SimClock(ds.week.start, ds.week.end - 1, fmt.dayStart(ds.week.start + 12 * 3600) + 7 * 3600)
    c.speed = 60
    return c
  }, [ds, fmt])
  const [selected, setSelected] = useState<string | null>(null)

  const compute = useCallback((): Snap => {
    const t = clock.now()
    const hour = ds.flights.slice(upperBound(ds.times, t - HOUR), upperBound(ds.times, t))
    const hourArr = hour.filter((f) => f.kind === 'arr').length
    return {
      t,
      playing: clock.playing,
      speed: clock.speed,
      events: recentTracked(ds, t, FEED_MAX),
      airborne: activeTracks(ds, t).filter((track) => sampleTrack(track, t) !== null).length,
      hourArr,
      hourDep: hour.length - hourArr,
      runways: [hour.filter((f) => f.runway === '28L').length, hour.filter((f) => f.runway === '28R').length],
    }
  }, [ds, clock])

  const [snap, setSnap] = useState<Snap>(compute)

  const refresh = useCallback(() => {
    setSnap(compute())
  }, [compute])

  useEffect(() => {
    const id = setInterval(refresh, UI_HZ_MS)
    return () => clearInterval(id)
  }, [refresh])

  const act = useCallback(
    (fn: (c: SimClock) => void) => {
      fn(clock)
      refresh()
    },
    [clock, refresh],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== 'Space') return
      const target = e.target as HTMLElement | null
      if (e.repeat || target?.closest('button, input, textarea, select, a, [contenteditable="true"]')) return
      e.preventDefault()
      act((c) => c.toggle())
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [act])

  return (
    <main className="body" id="replay-workspace" tabIndex={-1}>
      <div className="left">
        <MapView ds={ds} clock={clock} runways={runways} selectedId={selected} onSelect={setSelected} />
        <Controls week={ds.week} fmt={fmt} t={snap.t} playing={snap.playing} speed={snap.speed} act={act} />
      </div>
      <aside className="side" aria-label="Traffic and evidence">
        <div className="instrument-heading side-heading">
          <div><span className="instrument-label">02 / Operations</span><h2>Traffic</h2></div>
          <a href="#operations-feed" className="feed-link">View flights <span aria-hidden="true">↓</span></a>
        </div>
        <div className="side-scroll">
          {selected && <Inspector ds={ds} id={selected} t={snap.t} fmt={fmt} onClose={() => setSelected(null)} />}
          <div className="stats">
            <div><b>{snap.airborne}</b><span>on map now</span></div>
            <div><b>{snap.hourArr}</b><span>arrivals, last hr</span></div>
            <div><b>{snap.hourDep}</b><span>departures, last hr</span></div>
            <div><b>{snap.runways[0]}/{snap.runways[1]}</b><span>28L / 28R, last hr</span></div>
          </div>
          <section className="feed-section" id="operations-feed" tabIndex={-1} aria-label="Tracked flights">
            <h2>Tracked flights</h2>
            <p className="feed-caption">Latest {FEED_MAX} flights with a recorded path. Hourly counts include all {ds.flights.length.toLocaleString()} roster operations.</p>
            <Feed events={snap.events} fmt={fmt} selectedId={selected} onSelect={setSelected} />
          </section>
        </div>
      </aside>
    </main>
  )
}

export default function App() {
  const [data, setData] = useState<Loaded | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const p = '/data/'
    Promise.all([loadFlights(`${p}flights.json`), loadTracks(`${p}tracks.json`), loadRunways('/data/runways.geojson')])
      .then(([ff, tf, runways]) => setData({ ds: buildDataset(ff, tf), runways }))
      .catch((e) => setError(String(e)))
  }, [])

  return (
    <div className="app">
      <a className="skip-link" href="#replay-workspace">Skip to replay</a>
      <header className="app-header">
        <div className="identity">
          <span className="station-mark" aria-hidden="true">SFO</span>
          <div><span className="instrument-label">Uita / Traffic archive</span><h1>Up in the Air · SFO</h1></div>
        </div>
        <div className="attr">
          <span className="mode-label"><span className="status-lamp" aria-hidden="true" />Recorded replay</span>
          <span className="archive-date">Aug 3–9, 2026 <span className="header-separator">/</span> Research prototype</span>
        </div>
      </header>
      {error && <div className="msg err" role="alert">Failed to load replay data: {error}. Run <code>bun run data</code> in the web folder, then reload.</div>}
      {!data && !error && <div className="msg" role="status">Loading flights and tracks...</div>}
      {data && <Live {...data} />}
      <footer className="app-footer">
        <span><span className="footer-label">Source</span> DataSF / SFO Museum</span>
        <span>{data ? `Map shows the ${data.ds.tracks.size.toLocaleString()} of ${data.ds.flights.length.toLocaleString()} operations with a recorded path` : 'Map shows flights with a recorded path'}; gaps over 2 minutes stay empty.</span>
        <span className="research-label">Research use only</span>
      </footer>
    </div>
  )
}
