// Simulation clock. now() advances lazily from performance.now(), so any
// number of consumers (render loop, UI ticker) can read it without a timer.

export class SimClock {
  private t: number
  private last = performance.now()
  speed = 60
  playing = false

  constructor(readonly min: number, readonly max: number, start = min) {
    this.t = start
  }

  now(): number {
    const p = performance.now()
    if (this.playing) {
      this.t += ((p - this.last) / 1000) * this.speed
      if (this.t >= this.max) {
        this.t = this.max
        this.playing = false
      }
    }
    this.last = p
    return this.t
  }

  seek(t: number): void {
    this.now()
    this.t = Math.min(this.max, Math.max(this.min, t))
  }

  setSpeed(s: number): void {
    this.now()
    this.speed = s
  }

  play(): void {
    this.now()
    if (this.t >= this.max) this.t = this.min
    this.playing = true
  }

  pause(): void {
    this.now()
    this.playing = false
  }

  toggle(): void {
    if (this.playing) this.pause()
    else this.play()
  }
}
