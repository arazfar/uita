import { useEffect, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import { MapboxOverlay } from '@deck.gl/mapbox'
import { IconLayer, PathLayer, PolygonLayer, TextLayer } from '@deck.gl/layers'
import { TripsLayer } from '@deck.gl/geo-layers'
import type { SimClock } from '../data/clock'
import { activeTracks, type Dataset } from '../data/dataset'
import { SFO, destination, ring } from '../data/geo'
import { MAX_TRACK_GAP_SEC, sampleTrack } from '../data/interpolate'
import type { RunwayCollection } from '../data/loaders'
import type { CompiledTrack, Kind } from '../data/types'

const STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
const COLOR: Record<Kind, [number, number, number]> = { arr: [34, 211, 238], dep: [251, 191, 36] }
const TRAIL_SEC = 240
const RING_NM = [10, 40, 80]

interface Props {
  ds: Dataset
  clock: SimClock
  runways: RunwayCollection
  selectedId: string | null
  onSelect: (id: string | null) => void
}

interface Active {
  id: string
  kind: Kind
  position: [number, number]
  heading: number
  label: string
}

function planeIcon(): string {
  const c = document.createElement('canvas')
  c.width = c.height = 64
  const g = c.getContext('2d')!
  g.fillStyle = '#fff'
  g.beginPath() // nose up
  g.moveTo(32, 4)
  g.lineTo(37, 24)
  g.lineTo(60, 40)
  g.lineTo(60, 46)
  g.lineTo(37, 38)
  g.lineTo(35, 54)
  g.lineTo(44, 60)
  g.lineTo(44, 62)
  g.lineTo(32, 59)
  g.lineTo(20, 62)
  g.lineTo(20, 60)
  g.lineTo(29, 54)
  g.lineTo(27, 38)
  g.lineTo(4, 46)
  g.lineTo(4, 40)
  g.lineTo(27, 24)
  g.closePath()
  g.fill()
  return c.toDataURL()
}

/** Split long observation gaps so trails never imply an observed path across them. */
function trackSegments(track: CompiledTrack) {
  const segments: { track: CompiledTrack; start: number; end: number }[] = []
  let start = 0
  for (let i = 1; i <= track.n; i++) {
    if (i === track.n || track.ts[i] - track.ts[i - 1] > MAX_TRACK_GAP_SEC) {
      if (i - start >= 2) segments.push({ track, start, end: i })
      start = i
    }
  }
  return segments
}

/** Binary trip data with timestamps relative to week start. */
function tripData(ds: Dataset, kind: Kind) {
  const segments = ds.trackList.filter((t) => ds.byId.get(t.id)!.kind === kind).flatMap(trackSegments)
  const startIndices = new Uint32Array(segments.length + 1)
  let total = 0
  segments.forEach(({ start, end }, i) => {
    startIndices[i] = total
    total += end - start
  })
  startIndices[segments.length] = total
  const path = new Float32Array(total * 2)
  const time = new Float32Array(total)
  segments.forEach(({ track: t, start, end }, i) => {
    const o = startIndices[i]
    for (let k = start; k < end; k++) {
      path[(o + k - start) * 2] = t.lon[k]
      path[(o + k - start) * 2 + 1] = t.lat[k]
      time[o + k - start] = t.ts[k] - ds.week.start
    }
  })
  return {
    length: segments.length,
    startIndices,
    attributes: { getPath: { value: path, size: 2 }, getTimestamps: { value: time, size: 1 } },
  }
}

function fmtAlt(ft: number): string {
  if (Number.isNaN(ft)) return ''
  return ft >= 18000 ? `FL${Math.round(ft / 100)}` : `${Math.round(ft / 100) * 100}ft`
}

export default function MapView({ ds, clock, runways, selectedId, onSelect }: Props) {
  const [basemap, setBasemap] = useState<'loading' | 'ready' | 'unavailable'>('loading')
  const el = useRef<HTMLDivElement>(null)
  const selRef = useRef(selectedId)
  const selectRef = useRef(onSelect)
  selRef.current = selectedId
  selectRef.current = onSelect

  useEffect(() => {
    const map = new maplibregl.Map({
      container: el.current!,
      style: STYLE,
      center: SFO,
      zoom: 7.4,
      attributionControl: { compact: true },
    })
    const basemapTimeout = window.setTimeout(() => setBasemap((state) => state === 'loading' ? 'unavailable' : state), 15000)
    map.on('style.load', () => {
      window.clearTimeout(basemapTimeout)
      setBasemap('ready')
    })
    map.on('error', () => setBasemap('unavailable'))
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')

    const overlay = new MapboxOverlay({
      interleaved: false,
      onClick: (info) => {
        if (!info.layer) selectRef.current(null)
      },
    })
    map.addControl(overlay as unknown as maplibregl.IControl)

    // static data, built once
    const icon = planeIcon()
    const iconMapping = { plane: { x: 0, y: 0, width: 64, height: 64, mask: true } }
    const arrTrips = tripData(ds, 'arr')
    const depTrips = tripData(ds, 'dep')
    const rings = RING_NM.map((nm) => ({ nm, path: ring(SFO, nm) }))
    const ringLabels = RING_NM.map((nm) => ({ text: `${nm} NM`, position: destination(SFO, nm, 0) }))
    const polys = runways.features.map((f) => f.geometry.coordinates)

    const staticLayers = [
      new PathLayer({
        id: 'rings',
        data: rings,
        getPath: (d) => d.path,
        getColor: (d) => (d.nm === 80 ? [148, 163, 184, 150] : [148, 163, 184, 70]),
        getWidth: (d) => (d.nm === 80 ? 1.5 : 1),
        widthUnits: 'pixels',
      }),
      new TextLayer({
        id: 'ring-labels',
        data: ringLabels,
        getPosition: (d) => d.position,
        getText: (d) => d.text,
        getSize: 11,
        getColor: [148, 163, 184, 200],
        getPixelOffset: [0, -8],
        fontFamily: 'ui-monospace, monospace',
      }),
      new PolygonLayer({
        id: 'runways',
        data: polys,
        getPolygon: (d) => d,
        getFillColor: [226, 232, 240, 230],
        getLineColor: [226, 232, 240, 255],
        lineWidthMinPixels: 1,
      }),
    ]

    let raf = 0
    let lastTime = NaN
    let lastSelected: string | null | undefined
    let selectedPaths: [number, number][][] = []
    const frame = () => {
      raf = requestAnimationFrame(frame)
      const t = clock.now()
      const sel = selRef.current
      if (t === lastTime && sel === lastSelected) return
      if (sel !== lastSelected) {
        const track = sel ? ds.tracks.get(sel) : undefined
        selectedPaths = track ? trackSegments(track).map(({ start, end }) =>
          Array.from(track.lon.slice(start, end), (lon, i) => [lon, track.lat[start + i]] as [number, number])) : []
      }
      lastTime = t
      lastSelected = sel

      const active: Active[] = []
      for (const tr of activeTracks(ds, t)) {
        const s = sampleTrack(tr, t)
        if (!s) continue
        const f = ds.byId.get(tr.id)!
        const alt = fmtAlt(s.alt)
        active.push({
          id: tr.id,
          kind: f.kind,
          position: [s.lon, s.lat],
          heading: s.heading,
          label: alt ? `${f.callsign} ${alt}` : f.callsign,
        })
      }
      const rel = t - ds.week.start

      overlay.setProps({
        layers: [
          ...staticLayers,
          new TripsLayer({
            id: 'trips-arr',
            data: arrTrips,
            _pathType: 'open',
            getColor: COLOR.arr,
            currentTime: rel,
            trailLength: TRAIL_SEC,
            fadeTrail: true,
            widthMinPixels: 2,
          }),
          new TripsLayer({
            id: 'trips-dep',
            data: depTrips,
            _pathType: 'open',
            getColor: COLOR.dep,
            currentTime: rel,
            trailLength: TRAIL_SEC,
            fadeTrail: true,
            widthMinPixels: 2,
          }),
          new PathLayer({
            id: 'selected-path',
            data: selectedPaths,
            getPath: (path) => path,
            getColor: [255, 255, 255, 230],
            getWidth: 2,
            widthUnits: 'pixels',
          }),
          new IconLayer<Active>({
            id: 'aircraft',
            data: active,
            pickable: true,
            iconAtlas: icon,
            iconMapping,
            getIcon: () => 'plane',
            getPosition: (d) => d.position,
            getAngle: (d) => -d.heading,
            getSize: (d) => (d.id === sel ? 30 : 20),
            getColor: (d) => (d.id === sel ? [255, 255, 255] : COLOR[d.kind]),
            sizeUnits: 'pixels',
            billboard: false,
            onClick: (info) => {
              if (info.object) selectRef.current(info.object.id)
              return true
            },
            updateTriggers: { getSize: sel, getColor: sel },
          }),
          new TextLayer<Active>({
            id: 'labels',
            data: active,
            getPosition: (d) => d.position,
            getText: (d) => d.label,
            getSize: 11,
            getColor: (d) => [...COLOR[d.kind], 255],
            getTextAnchor: 'start',
            getPixelOffset: [14, 0],
            fontFamily: 'ui-monospace, monospace',
            fontSettings: { sdf: true },
            outlineWidth: 3,
            outlineColor: [8, 12, 18, 230],
          }),
        ],
      })
    }
    frame()

    return () => {
      cancelAnimationFrame(raf)
      window.clearTimeout(basemapTimeout)
      map.remove()
    }
  }, [ds, clock, runways])

  return (
    <div className="map-shell">
      <div ref={el} className="map" role="region" aria-label="SFO tracked flight map" />
      {basemap !== 'ready' && <div className="map-status" role="status">{basemap === 'loading' ? 'Loading basemap…' : 'Basemap is slow or unavailable. Aircraft paths remain available.'}</div>}
      <div className="map-legend"><span className="legend-arr">● Arrivals</span><span className="legend-dep">● Departures</span><span>Available paths</span></div>
    </div>
  )
}
