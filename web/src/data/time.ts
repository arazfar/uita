// Time helpers: unix seconds <-> local wall time in a given IANA tz.

export function toUnix(v: number | string): number {
  if (typeof v === 'number') return v > 1e11 ? v / 1000 : v
  return Date.parse(v) / 1000
}

export interface TimeFormat {
  /** "07:00:12" */
  hms(t: number): string
  /** "07:00" */
  hm(t: number): string
  /** "Mon Aug 3" */
  day(t: number): string
  /** "Mon" */
  dow(t: number): string
  /** local seconds since local midnight */
  secOfDay(t: number): number
  /** unix time of local midnight on the day containing t */
  dayStart(t: number): number
  /** short tz name, e.g. "PDT" */
  tzName(t: number): string
}

export function makeTimeFormat(tz: string): TimeFormat {
  const base = { timeZone: tz }
  const fHms = new Intl.DateTimeFormat('en-GB', { ...base, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  const fHm = new Intl.DateTimeFormat('en-GB', { ...base, hour: '2-digit', minute: '2-digit', hour12: false })
  const fDay = new Intl.DateTimeFormat('en-US', { ...base, weekday: 'short', month: 'short', day: 'numeric' })
  const fDow = new Intl.DateTimeFormat('en-US', { ...base, weekday: 'short' })
  const fTz = new Intl.DateTimeFormat('en-US', { ...base, timeZoneName: 'short' })
  const ms = (t: number) => new Date(t * 1000)
  const secOfDay = (t: number) => {
    const parts = fHms.formatToParts(ms(t))
    const g = (k: string) => Number(parts.find((p) => p.type === k)?.value ?? 0)
    return (g('hour') % 24) * 3600 + g('minute') * 60 + g('second')
  }
  return {
    hms: (t) => fHms.format(ms(t)),
    hm: (t) => fHm.format(ms(t)),
    day: (t) => fDay.format(ms(t)),
    dow: (t) => fDow.format(ms(t)),
    secOfDay,
    dayStart: (t) => Math.floor(t) - secOfDay(t),
    tzName: (t) => fTz.formatToParts(ms(t)).find((p) => p.type === 'timeZoneName')?.value ?? '',
  }
}
