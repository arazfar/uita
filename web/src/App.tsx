import { useCallback, useEffect, useMemo, useState } from 'react'
import Controls from './components/Controls'
import Feed from './components/Feed'
import Inspector from './components/Inspector'
import MapView from './components/Map'
import { SimClock } from './data/clock'
import { activeTracks, buildDataset, countKinds, recentEvents, type Dataset } from './data/dataset'
import { loadFlights, loadRunways, loadTracks, type RunwayCollection } from './data/loaders'
import { makeTimeFormat } from './data/time'
import type { Flight } from './data/types'

const FEED_MAX = 200
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
  arrToday: number
  depToday: number
  hourArr: number
  hourDep: number
}

function Live({ ds, runways }: Loaded) {
  const fmt = useMemo(() => makeTimeFormat(ds.week.tz), [ds])
  const clock = useMemo(() => {
    const c = new SimClock(ds.week.start, ds.week.end, fmt.dayStart(ds.week.start + 12 * 3600) + 7 * 3600)
    c.speed = 60
    return c
  }, [ds, fmt])
  const [selected, setSelected] = useState<string | null>(null)

  const compute = useCallback((): Snap => {
    const t = clock.now()
    const day = fmt.dayStart(t)
    const today = countKinds(ds, day, t)
    const hour = countKinds(ds, t - 3600, t)
    return {
      t,
      playing: clock.playing,
      speed: clock.speed,
      events: recentEvents(ds, t, FEED_MAX),
      airborne: activeTracks(ds, t).length,
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
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === 'TEXTAREA' || tag === 'SELECT') return
      e.preventDefault()
      ;(document.activeElement as HTMLElement | null)?.blur()
      act((c) => c.toggle())
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [act])

  return (
    <div className="body">
      <div className="left">
        <MapView ds={ds} clock={clock} runways={runways} selectedId={selected} onSelect={setSelected} />
        <Controls week={ds.week} fmt={fmt} t={snap.t} playing={snap.playing} speed={snap.speed} act={act} />
      </div>
      <aside className="side">
        <div className="stats">
          <div><b>{snap.airborne}</b><span>airborne</span></div>
          <div><b>{snap.arrToday}</b><span>arr today</span></div>
          <div><b>{snap.depToday}</b><span>dep today</span></div>
          <div><b>{snap.hourArr + snap.hourDep}</b><span>last hr ({snap.hourArr}a/{snap.hourDep}d)</span></div>
        </div>
        {selected && <Inspector ds={ds} id={selected} t={snap.t} fmt={fmt} onClose={() => setSelected(null)} />}
        <h2>Live feed</h2>
        <Feed events={snap.events} fmt={fmt} selectedId={selected} onSelect={setSelected} />
      </aside>
    </div>
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
      <header>
        <h1>Up in the Air - SFO week replay</h1>
        <div className="attr">
          DataSF SFO Flight Operations (PDDL) · SFO Museum flight paths (CDLA-Permissive-1.0). Positions are observed
          paths; gaps are not filled.
        </div>
      </header>
      {error && <div className="msg err">Failed to load data: {error}</div>}
      {!data && !error && <div className="msg">Loading flights and tracks...</div>}
      {data && <Live {...data} />}
    </div>
  )
}
