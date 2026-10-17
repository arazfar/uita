import type { SimClock } from '../data/clock'
import type { TimeFormat } from '../data/time'
import type { Week } from '../data/types'

export const SPEEDS = [1, 10, 60, 300, 1800]

interface Props {
  week: Week
  fmt: TimeFormat
  t: number
  playing: boolean
  speed: number
  /** apply a clock change and refresh UI state immediately */
  act: (fn: (c: SimClock) => void) => void
}

export default function Controls({ week, fmt, t, playing, speed, act }: Props) {
  const days = Array.from({ length: 7 }, (_, i) => fmt.dayStart(week.start + i * 86400 + 12 * 3600))
  const span = week.end - week.start
  return (
    <div className="controls">
      <div className="row">
        <button className="play" onClick={() => act((c) => c.toggle())} title="Space">
          {playing ? 'Pause' : 'Play'}
        </button>
        <div className="speeds">
          {SPEEDS.map((s) => (
            <button key={s} className={s === speed ? 'on' : ''} onClick={() => act((c) => c.setSpeed(s))}>
              {s}x
            </button>
          ))}
        </div>
        <div className="clock">
          {fmt.day(t)} <b>{fmt.hms(t)}</b> {fmt.tzName(t)}
        </div>
        <div className="days">
          {days.map((d) => (
            <button key={d} onClick={() => act((c) => c.seek(d + 7 * 3600))} title="Jump to 07:00">
              {fmt.dow(d + 43200)}
            </button>
          ))}
        </div>
      </div>
      <div className="scrub">
        <input
          type="range"
          min={week.start}
          max={week.end}
          step={1}
          value={t}
          onChange={(e) => act((c) => c.seek(Number(e.target.value)))}
        />
        <div className="ticks">
          {days.map((d) => (
            <span key={d} style={{ left: `${((d - week.start) / span) * 100}%` }}>
              {fmt.dow(d + 43200)}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
