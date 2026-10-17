import { useEffect, useRef } from 'react'
import * as maplibregl from 'maplibre-gl'
import { MapboxOverlay } from '@deck.gl/mapbox'
import { IconLayer, PathLayer, PolygonLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers'
import { TripsLayer } from '@deck.gl/geo-layers'
import type { SimClock } from '../data/clock'
import { activeTracks, recentNoTrack, type Dataset } from '../data/dataset'
import { SFO, destination, ring, runwayThresholds, thresholdFor } from '../data/geo'
import { sampleTrack } from '../data/interpolate'
import type { RunwayCollection } from '../data/loaders'
import type { CompiledTrack, Kind } from '../data/types'

const STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
const COLOR: Record<Kind, [number, number, number]> = { arr: [34, 211, 238], dep: [251, 191, 36] }
const TRAIL_SEC = 240
const PULSE_SEC = 120
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

/** Binary trip data (one layer per kind) with timestamps relative to week start. */
function tripData(ds: Dataset, kind: Kind) {
  const tracks = ds.trackList.filter((t) => ds.byId.get(t.id)!.kind === kind && t.n >= 2)
  const startIndices = new Uint32Array(tracks.length + 1)
  let total = 0
  tracks.forEach((t, i) => {
    startIndices[i] = total
    total += t.n
  })
  startIndices[tracks.length] = total
  const path = new Float32Array(total * 2)
  const time = new Float32Array(total)
  tracks.forEach((t, i) => {
    const o = startIndices[i]
    for (let k = 0; k < t.n; k++) {
      path[(o + k) * 2] = t.lon[k]
      path[(o + k) * 2 + 1] = t.lat[k]
      time[o + k] = t.ts[k] - ds.week.start
    }
  })
  return {
    length: tracks.length,
    startIndices,
    attributes: { getPath: { value: path, size: 2 }, getTimestamps: { value: time, size: 1 } },
  }
}

function fmtAlt(ft: number): string {
  if (Number.isNaN(ft)) return ''
  return ft >= 18000 ? `FL${Math.round(ft / 100)}` : `${Math.round(ft / 100) * 100}ft`
}

export default function MapView({ ds, clock, runways, selectedId, onSelect }: Props) {
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
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')

    const overlay = new MapboxOverlay({
      interleaved: false,
      onClick: (info) => {
        if (!info.layer) selectRef.current(null)
      },
    })
    map.addControl(overlay as unknown as maplibregl.IControl)

    // static data, built once
    const thresholds = runwayThresholds(runways)
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
    const frame = () => {
      raf = requestAnimationFrame(frame)
      const t = clock.now()
      const sel = selRef.current

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
      const pulses = recentNoTrack(ds, t, PULSE_SEC).map((f) => ({
        kind: f.kind,
        position: thresholdFor(thresholds, f.runway),
        age: (t - f.t) / PULSE_SEC,
      }))
      const selTrack: CompiledTrack | undefined = sel ? ds.tracks.get(sel) : undefined
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
            data: selTrack ? [selTrack] : [],
            getPath: (d: CompiledTrack) => Array.from(d.lon, (lon, i) => [lon, d.lat[i]] as [number, number]),
            getColor: [255, 255, 255, 230],
            getWidth: 2,
            widthUnits: 'pixels',
          }),
          new ScatterplotLayer({
            id: 'pulses',
            data: pulses,
            getPosition: (d) => d.position,
            stroked: true,
            filled: false,
            radiusUnits: 'pixels',
            lineWidthUnits: 'pixels',
            getRadius: (d) => 6 + 34 * d.age,
            getLineWidth: 2,
            getLineColor: (d) => [...COLOR[d.kind as Kind], Math.round(255 * (1 - d.age))],
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
      map.remove()
    }
  }, [ds, clock, runways])

  return <div ref={el} className="map" />
}
