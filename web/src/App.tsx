import { useCallback, useEffect, useMemo, useState } from 'react'
import Controls from './components/Controls'
import Feed from './components/Feed'
import Kpis from './components/Kpis'
import Inspector from './components/Inspector'
import MapView from './components/Map'
import { SimClock } from './data/clock'
import { activeTracks, buildDataset, countKinds, recentEvents, type Dataset } from './data/dataset'
import { loadFlights, loadKpis, loadRunways, loadTracks, type RunwayCollection } from './data/loaders'
import { makeTimeFormat } from './data/time'
import { sampleTrack } from './data/interpolate'
import type { Flight, KpisFile } from './data/types'

const FEED_MAX = 200
const UI_HZ_MS = 250

interface Loaded {
  ds: Dataset
  runways: RunwayCollection
  kpis: KpisFile
}

interface Snap {
  t: number
  playing: boolean
  speed: number
  events: Flight[]
  airborne: number
  arrToday: number
  depToday: number
  hourArr: number
  hourDep: number
}

function Live({ ds, runways, kpis }: Loaded) {
  const fmt = useMemo(() => makeTimeFormat(ds.week.tz), [ds])
  const clock = useMemo(() => {
    const c = new SimClock(ds.week.start, ds.week.end - 1, fmt.dayStart(ds.week.start + 12 * 3600) + 7 * 3600)
    c.speed = 60
    return c
  }, [ds, fmt])
  const [selected, setSelected] = useState<string | null>(null)

  const compute = useCallback((): Snap => {
    const t = clock.now()
    const day = fmt.dayStart(t)
    const today = countKinds(ds, day - 1, t)
    const hour = countKinds(ds, t - 3600, t)
    return {
      t,
      playing: clock.playing,
      speed: clock.speed,
      events: recentEvents(ds, t, FEED_MAX),
      airborne: activeTracks(ds, t).filter((track) => sampleTrack(track, t) !== null).length,
      arrToday: today.arr,
      depToday: today.dep,
      hourArr: hour.arr,
      hourDep: hour.dep,
    }
  }, [ds, clock, fmt])

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
          <div><span className="instrument-label">02 / Operations</span><h2>Traffic & evidence</h2></div>
          <a href="#operations-feed" className="feed-link">View feed <span aria-hidden="true">↓</span></a>
        </div>
        <div className="side-scroll">
          {selected && <Inspector ds={ds} id={selected} t={snap.t} fmt={fmt} onClose={() => setSelected(null)} />}
          <div className="stats">
            <div><b>{snap.airborne}</b><span>on map now</span></div>
            <div><b>{snap.arrToday}</b><span>arr today</span></div>
            <div><b>{snap.depToday}</b><span>dep today</span></div>
            <div><b>{snap.hourArr + snap.hourDep}</b><span>last hr ({snap.hourArr}a/{snap.hourDep}d)</span></div>
          </div>
          <Kpis ds={ds} kpis={kpis} t={snap.t} fmt={fmt} onSelect={setSelected} />
          <section className="feed-section" id="operations-feed" tabIndex={-1} aria-label="Operations feed">
            <h2>Operations feed</h2>
            <p className="feed-caption">Latest {FEED_MAX} roster operations at replay time</p>
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
    Promise.all([loadFlights(`${p}flights.json`), loadTracks(`${p}tracks.json`), loadRunways('/data/runways.geojson'), loadKpis(`${p}kpis.json`)])
      .then(([ff, tf, runways, kpis]) => setData({ ds: buildDataset(ff, tf), runways, kpis }))
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
        <span><span className="footer-label">Source</span> DataSF / SFO Museum{data?.kpis.coverage.adsb_paths !== undefined && ' / ADSB.lol'}</span>
        <span>Full roster in feed and throughput. Map shows available tracks; gaps over 2 minutes stay empty.</span>
        <span className="research-label">Research use only</span>
      </footer>
    </div>
  )
}
