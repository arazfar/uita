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
  /** Apply a clock change and refresh UI state immediately. */
  act: (fn: (c: SimClock) => void) => void
}

export default function Controls({ week, fmt, t, playing, speed, act }: Props) {
  const days = Array.from({ length: 7 }, (_, i) => fmt.dayStart(week.start + i * 86400 + 12 * 3600))
  const span = week.end - week.start
  const currentDay = fmt.dayStart(Math.min(t, week.end - 1))
  return (
    <div className="controls" role="group" aria-label="Replay controls">
      <div className="row">
        <button className="play" onClick={() => act((clock) => clock.toggle())} title="Play or pause (Space)" aria-label={playing ? 'Pause replay' : 'Play replay'}>
          {playing ? 'Pause' : 'Play'}
        </button>
        <div className="speeds" role="group" aria-label="Playback speed">
          {SPEEDS.map((value) => (
            <button key={value} className={value === speed ? 'on' : ''} aria-pressed={value === speed} aria-label={`${value} times normal speed`} onClick={() => act((clock) => clock.setSpeed(value))}>
              {value}×
            </button>
          ))}
        </div>
        <div className="clock" aria-label="Replay time">{fmt.day(t)} <b>{fmt.hms(t)}</b> {fmt.tzName(t)}</div>
        <div className="days" role="group" aria-label="Jump to a day at 07:00">
          {days.map((day) => (
            <button key={day} className={day === currentDay ? 'current-day' : ''} aria-pressed={day === currentDay} onClick={() => act((clock) => clock.seek(day + 7 * 3600))} title={`Jump to ${fmt.day(day + 43200)} at 07:00`}>
              {fmt.dow(day + 43200)}
            </button>
          ))}
        </div>
      </div>
      <div className="scrub">
        <input type="range" min={week.start} max={week.end - 1} step={1} value={t} aria-label="Replay timeline" aria-valuetext={`${fmt.day(t)}, ${fmt.hms(t)} ${fmt.tzName(t)}`} onChange={(event) => act((clock) => clock.seek(Number(event.target.value)))} />
        <div className="ticks" aria-hidden="true">
          {days.map((day) => (
            <span key={day} style={{ left: `${((day - week.start) / span) * 100}%` }}>{fmt.dow(day + 43200)}</span>
          ))}
        </div>
      </div>
    </div>
  )
}
