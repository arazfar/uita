import { useEffect, useRef, useState } from "react";
import {
  dayKey,
  targetsAtTime,
  weatherAtTime,
  type DisplayTarget,
  type HistoryCatalog,
  type HistoryWeather,
  type HistoryWindow,
} from "./traffic";

export type ReplayDay = {
  date: string;
  start: number;
  loaded: boolean;
  rows: number;
};
type ReplaySnapshot = {
  catalog: HistoryCatalog | null;
  days: ReplayDay[];
  time: number;
  playing: boolean;
  rate: number;
  loading: boolean;
  error: string | null;
  suspended: boolean;
  targets: DisplayTarget[];
  weather: HistoryWeather | null;
  dailyOperations: { date: string; total: number } | null;
};
type ReplayActions = {
  seek: (epoch: number) => void;
  step: (seconds: number) => void;
  seekDay: (start: number) => void;
  setLocalTime: (clock: string) => void;
  play: () => void;
  pause: () => void;
  togglePlayback: () => void;
  setRate: (rate: number) => void;
  retry: () => void;
  refresh: () => void;
};
const EMPTY: ReplaySnapshot = {
  catalog: null,
  days: [],
  time: 0,
  playing: false,
  rate: 60,
  loading: true,
  error: null,
  suspended: false,
  targets: [],
  weather: null,
  dailyOperations: null,
};
const noop = () => {};
const NO_ACTIONS: ReplayActions = {
  seek: noop,
  step: noop,
  seekDay: noop,
  setLocalTime: noop,
  play: noop,
  pause: noop,
  togglePlayback: noop,
  setRate: noop,
  retry: noop,
  refresh: noop,
};

async function readHistory<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch("/uita/api/history/" + path, {
    signal,
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  const data = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : typeof data?.error === "string"
          ? data.error
          : "Recorded traffic is unavailable. Retry the connection.",
    );
  if (!data)
    throw new Error(
      "The history service returned an invalid response. Retry the connection.",
    );
  return data as T;
}

/** The database remains authoritative. Loading and hidden views never advance the replay clock. */
export function useHistoryReplay(): ReplaySnapshot & ReplayActions {
  const [snapshot, setSnapshot] = useState<ReplaySnapshot>(EMPTY);
  const actions = useRef<ReplayActions>(NO_ACTIONS);
  const stableActions = useRef<ReplayActions>({
    seek: (value) => actions.current.seek(value),
    step: (value) => actions.current.step(value),
    seekDay: (value) => actions.current.seekDay(value),
    setLocalTime: (value) => actions.current.setLocalTime(value),
    play: () => actions.current.play(),
    pause: () => actions.current.pause(),
    togglePlayback: () => actions.current.togglePlayback(),
    setRate: (value) => actions.current.setRate(value),
    retry: () => actions.current.retry(),
    refresh: () => actions.current.refresh(),
  });

  useEffect(() => {
    let active = true,
      catalog: HistoryCatalog | null = null,
      frame: HistoryWindow | null = null;
    let time = 0,
      rate = 60,
      playing = false,
      loading = true,
      error: string | null = null;
    let documentHidden = document.hidden,
      shellHidden = false,
      failedPhase: "catalog" | "window" = "catalog";
    let catalogGeneration = 0,
      windowGeneration = 0,
      catalogRequest: AbortController | null = null,
      windowRequest: AbortController | null = null;
    let animation = 0,
      lastTick = performance.now(),
      lastPaint = 0,
      lastPublishedTime = Number.NaN;
    const cache = new Map<number, HistoryWindow>();
    const anchor = () =>
      catalog
        ? catalog.start +
          Math.floor((time - catalog.start) / catalog.chunk_seconds) *
            catalog.chunk_seconds
        : 0;
    const ready = () =>
      !!catalog && !!frame && frame.start === anchor() && !error && !loading;
    const publish = () => {
      if (!active) return;
      lastPublishedTime = time;
      const days: ReplayDay[] = [];
      if (catalog)
        for (let start = catalog.start; start < catalog.end; start += 86400) {
          const date = dayKey(start),
            loaded = catalog.days.find((day) => day.date === date);
          days.push({ date, start, loaded: !!loaded, rows: loaded?.rows ?? 0 });
        }
      setSnapshot({
        catalog,
        days,
        time,
        playing,
        rate,
        loading,
        error,
        suspended: documentHidden || shellHidden,
        targets: ready() ? targetsAtTime(frame, time, catalog!.source) : [],
        weather: ready() ? weatherAtTime(frame, time) : null,
        dailyOperations:
          catalog?.daily_operations.find((day) => day.date === dayKey(time)) ??
          null,
      });
    };

    async function loadWindow() {
      if (!catalog) return;
      const start = anchor(),
        token = ++windowGeneration,
        revision = catalogGeneration;
      windowRequest?.abort();
      const request = new AbortController();
      windowRequest = request;
      loading = true;
      error = null;
      frame = null;
      publish();
      try {
        const result =
          cache.get(start) ??
          (await readHistory<HistoryWindow>(
            "window?start=" + start,
            request.signal,
          ));
        if (
          !active ||
          token !== windowGeneration ||
          revision !== catalogGeneration
        )
          return;
        if (
          result.start !== start ||
          !Number.isFinite(result.end) ||
          !Array.isArray(result.flights) ||
          !Array.isArray(result.weather)
        )
          throw new Error(
            "The history interval does not match the requested time. Retry this interval.",
          );
        frame = result;
        cache.set(start, result);
        if (cache.size > 8) cache.delete(cache.keys().next().value!);
        loading = false;
        lastTick = performance.now();
        publish();
      } catch (cause) {
        if (
          !active ||
          token !== windowGeneration ||
          revision !== catalogGeneration ||
          request.signal.aborted
        )
          return;
        frame = null;
        loading = false;
        playing = false;
        failedPhase = "window";
        error =
          cause instanceof Error
            ? cause.message
            : "Recorded traffic could not load. Retry this interval.";
        publish();
      }
    }

    async function loadCatalog() {
      const token = ++catalogGeneration;
      ++windowGeneration;
      catalogRequest?.abort();
      windowRequest?.abort();
      const request = new AbortController();
      catalogRequest = request;
      playing = false;
      loading = true;
      error = null;
      frame = null;
      catalog = null;
      cache.clear();
      publish();
      try {
        const result = await readHistory<HistoryCatalog>(
          "catalog",
          request.signal,
        );
        if (!active || token !== catalogGeneration) return;
        if (
          !Number.isFinite(result.start) ||
          !Number.isFinite(result.end) ||
          result.end <= result.start ||
          !(result.chunk_seconds > 0) ||
          !Array.isArray(result.days) ||
          !Array.isArray(result.daily_operations)
        )
          throw new Error(
            "Recorded traffic coverage is invalid. Refresh the data coverage.",
          );
        catalog = result;
        time =
          time >= result.start && time < result.end
            ? time
            : Math.min(result.end - 1, result.start + 12 * 3600);
        await loadWindow();
      } catch (cause) {
        if (!active || token !== catalogGeneration || request.signal.aborted)
          return;
        loading = false;
        playing = false;
        failedPhase = "catalog";
        error =
          cause instanceof Error
            ? cause.message
            : "Recorded traffic coverage could not load. Retry the connection.";
        publish();
      }
    }

    function seek(epoch: number) {
      if (!catalog) return;
      playing = false;
      time = Math.max(
        catalog.start,
        Math.min(
          catalog.end - 1,
          Number.isFinite(epoch) ? epoch : catalog.start,
        ),
      );
      lastTick = performance.now();
      // Cached seeks also invalidate pending requests for another interval.
      void loadWindow();
    }
    function play() {
      if (!catalog || error || time >= catalog.end - 1) return;
      playing = true;
      lastTick = performance.now();
      publish();
    }
    function pause() {
      playing = false;
      lastTick = performance.now();
      publish();
    }
    actions.current = {
      seek,
      step: (seconds) => seek(time + seconds),
      seekDay: (start) => seek(start + 12 * 3600),
      setLocalTime: (clock) => {
        if (!catalog || !/^([01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$/.test(clock))
          return;
        // This preserved August 24–30 capture uses PDT throughout the entire week.
        seek(
          Date.parse(
            `${dayKey(time)}T${clock.length === 5 ? clock + ":00" : clock}-07:00`,
          ) / 1000,
        );
      },
      play,
      pause,
      togglePlayback: () => (playing ? pause() : play()),
      setRate: (value) => {
        if (Number.isFinite(value) && value >= 1 && value <= 600) {
          rate = value;
          lastTick = performance.now();
          publish();
        }
      },
      retry: () => {
        if (!catalog || failedPhase === "catalog") void loadCatalog();
        else void loadWindow();
      },
      refresh: () => {
        void loadCatalog();
      },
    };

    function visibilityChanged() {
      documentHidden = document.hidden;
      lastTick = performance.now();
      publish();
    }
    function shellMessage(event: MessageEvent) {
      if (event.origin !== location.origin || event.source !== window.parent)
        return;
      if (event.data?.skyflow === "pause") shellHidden = true;
      else if (
        event.data?.skyflow === "resume" ||
        event.data?.skyflow === "play"
      )
        shellHidden = false;
      else return;
      lastTick = performance.now();
      publish();
    }
    function tick(now: number) {
      if (!active) return;
      const delta = Math.min(0.5, Math.max(0, (now - lastTick) / 1000));
      lastTick = now;
      if (playing && !documentHidden && !shellHidden && ready() && catalog) {
        time = Math.min(catalog.end - 1, time + delta * rate);
        if (time >= catalog.end - 1) playing = false;
        if (frame!.start !== anchor()) void loadWindow();
      }
      if (
        !documentHidden &&
        !shellHidden &&
        time !== lastPublishedTime &&
        now - lastPaint >= 200
      ) {
        publish();
        lastPaint = now;
      }
      animation = requestAnimationFrame(tick);
    }
    document.addEventListener("visibilitychange", visibilityChanged);
    window.addEventListener("message", shellMessage);
    void loadCatalog();
    animation = requestAnimationFrame(tick);
    return () => {
      active = false;
      ++catalogGeneration;
      ++windowGeneration;
      catalogRequest?.abort();
      windowRequest?.abort();
      cancelAnimationFrame(animation);
      document.removeEventListener("visibilitychange", visibilityChanged);
      window.removeEventListener("message", shellMessage);
      actions.current = NO_ACTIONS;
    };
  }, []);
  return { ...snapshot, ...stableActions.current };
}
