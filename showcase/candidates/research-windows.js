// Immutable playback windows; live snapshots are deliberately never cached here.
export class PlaybackWindows {
  constructor(fetchWindow, sourceLimit = 4, windowLimit = 3) {
    this.fetchWindow = fetchWindow;
    this.sourceLimit = sourceLimit;
    this.windowLimit = windowLimit;
    this.sources = new Map();
  }
  bucket(source, clock) {
    return Math.max(source.start, Math.floor(clock / 120) * 120);
  }
  load(kind, source, clock, signal) {
    const key = `${kind}:${source.id}`,
      bucket = this.bucket(source, clock);
    let windows = this.sources.get(key);
    if (!windows) windows = new Map();
    this.sources.delete(key);
    this.sources.set(key, windows);
    while (this.sources.size > this.sourceLimit) {
      const [oldKey, old] = this.sources.entries().next().value;
      for (const entry of old.values())
        if (!entry.data) entry.controller.abort();
      this.sources.delete(oldKey);
    }
    let entry = windows.get(bucket);
    if (!entry) {
      entry = { controller: new AbortController(), users: 0, data: null };
      windows.set(bucket, entry);
      entry.promise = Promise.resolve()
        .then(() =>
          this.fetchWindow(kind, source.id, bucket, entry.controller.signal),
        )
        .then((data) => {
          entry.data = {...data, window_start: bucket};
          return entry.data;
        })
        .catch((error) => {
          if (windows.get(bucket) === entry) windows.delete(bucket);
          throw error;
        });
    }
    windows.delete(bucket);
    windows.set(bucket, entry);
    while (windows.size > this.windowLimit) {
      const [oldKey, old] = windows.entries().next().value;
      if (!old.data) old.controller.abort();
      windows.delete(oldKey);
    }
    if (signal?.aborted)
      return Promise.reject(new DOMException("Aborted", "AbortError"));
    entry.users++;
    return new Promise((resolve, reject) => {
      let done = false;
      const finish = (fn, value) => {
        if (done) return;
        done = true;
        signal?.removeEventListener("abort", abort);
        entry.users--;
        fn(value);
      };
      const abort = () => {
        finish(reject, new DOMException("Aborted", "AbortError"));
        if (!entry.users && !entry.data) {
          entry.controller.abort();
          if (windows.get(bucket) === entry) windows.delete(bucket);
        }
      };
      signal?.addEventListener("abort", abort, { once: true });
      entry.promise.then(
        (data) => finish(resolve, data),
        (error) => finish(reject, error),
      );
    });
  }
  prefetch(kind, source, clock) {
    if (clock <= source.end)
      return this.load(kind, source, clock).catch(() => null);
  }
}
