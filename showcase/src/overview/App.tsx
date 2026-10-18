import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { Scene } from "./Scene";
import { useHistoryReplay } from "./useHistoryReplay";
import { dayKey, formatLocalTime, formatReplayTime } from "./traffic";
import "./style.css";

type CameraPreset = "overview" | "approach" | "tower" | "region" | "follow";
type SceneStatus = { ready: boolean; error?: string; fps: number };
const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const dateFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Los_Angeles",
  month: "short",
  day: "numeric",
});
const fullDateFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Los_Angeles",
  month: "short",
  day: "numeric",
  year: "numeric",
});
const dayFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: "UTC",
  weekday: "short",
});
const cameras: { id: CameraPreset; label: string }[] = [
  { id: "overview", label: "SFO overview" },
  { id: "approach", label: "Approach" },
  { id: "tower", label: "Tower" },
  { id: "region", label: "Region" },
  { id: "follow", label: "Follow" },
];
const speedOptions = [1, 5, 15, 60, 120, 300, 600];
const sourceUrl = "https://github.com/adsblol/globe_history_2026";
const measure = (value: number | null | undefined, unit?: string) =>
  value == null || !Number.isFinite(value)
    ? "Not recorded"
    : `${number.format(value)}${unit ? ` ${unit}` : ""}`;

function PlayIcon({ playing }: { playing: boolean }) {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
      {playing ? (
        <path d="M5 4h3v12H5zM12 4h3v12h-3z" />
      ) : (
        <path d="M6 3.5 16 10 6 16.5z" />
      )}
    </svg>
  );
}
function Field({
  label,
  value,
  unit,
}: {
  label: string;
  value: string;
  unit?: string;
}) {
  return (
    <div className="readout">
      <dt>{label}</dt>
      <dd>
        {value}
        {unit && <span>{unit}</span>}
      </dd>
    </div>
  );
}

export default function App() {
  const history = useHistoryReplay();
  const {
    catalog,
    time,
    playing,
    rate,
    loading,
    error,
    targets,
    weather,
    dailyOperations,
  } = history;
  const [cameraPreset, setCameraPreset] = useState<CameraPreset>("overview");
  const [cameraRevision, setCameraRevision] = useState(0);
  const [showTracks, setShowTracks] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [quality, setQuality] = useState<"high" | "balanced">(() =>
    window.matchMedia("(max-width: 799px)").matches ? "balanced" : "high",
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [targetQuery, setTargetQuery] = useState("");
  const [status, setStatus] = useState<SceneStatus>({ ready: false, fps: 0 });
  const initiallySelected = useRef(false);
  const onStatus = useCallback((next: SceneStatus) => setStatus(next), []);
  const onSelect = useCallback((id: string | null) => {
    initiallySelected.current = true;
    setSelectedId(id);
  }, []);
  const selected = targets.find((target) => target.id === selectedId);
  const state = selected?.state;
  const mappedCount = targets.filter((target) => target.state.y != null).length;
  const sortedTargets = useMemo(
    () =>
      [...targets].sort(
        (a, b) =>
          a.callsign.localeCompare(b.callsign) || a.id.localeCompare(b.id),
      ),
    [targets],
  );
  const filteredTargets = useMemo(() => {
    const query = targetQuery.trim().toLowerCase();
    return query
      ? sortedTargets.filter((target) =>
          [
            target.callsign,
            target.id,
            target.registration,
            target.aircraftType,
          ].some((value) => value?.toLowerCase().includes(query)),
        )
      : sortedTargets;
  }, [sortedTargets, targetQuery]);
  const activeDay = catalog ? dayKey(time) : "";
  const sourceReady = Boolean(catalog && !loading && !error);
  const statusText = error
    ? "Data unavailable · replay paused"
    : loading
      ? "Loading interval · clock held"
      : playing
        ? `Playing · ${rate}×`
        : "Paused · recorded observations";
  const weekLabel = catalog
    ? `${dateFormat.format(new Date(catalog.start * 1000))}–${fullDateFormat.format(new Date((catalog.end - 1) * 1000))}`
    : "Recorded week archive";
  const coverageDays = history.days.filter((day) => day.loaded).length;
  const totalRows = history.days.reduce((sum, day) => sum + day.rows, 0);
  const progress = catalog
    ? ((time - catalog.start) / (catalog.end - 1 - catalog.start)) * 100
    : 0;

  useEffect(() => {
    if (initiallySelected.current || targets.length === 0) return;
    initiallySelected.current = true;
    const mapped = targets
      .filter((target) => target.state.y != null)
      .sort(
        (a, b) =>
          Math.hypot(a.state.x, a.state.z) - Math.hypot(b.state.x, b.state.z),
      );
    const nearbyAirborne = mapped.find(
      (target) =>
        target.state.onGround === false &&
        target.state.y != null &&
        target.state.y <= 1500 &&
        Math.hypot(target.state.x, target.state.z) <= 5000,
    );
    const nearbyLow = mapped.find(
      (target) =>
        target.state.onGround === true ||
        (target.state.y != null && target.state.y <= 1500),
    );
    setSelectedId((nearbyAirborne ?? nearbyLow ?? mapped[0] ?? targets[0]).id);
  }, [targets]);

  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        event.repeat ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        target?.closest(
          'input, select, textarea, button, [contenteditable="true"]',
        )
      )
        return;
      if (event.key === " ") {
        event.preventDefault();
        history.togglePlayback();
      }
      if (event.key.toLowerCase() === "t" && window.parent !== window) {
        event.preventDefault();
        window.parent.postMessage(
          { skyflow: "toggle" },
          window.location.origin,
        );
      }
    };
    const message = (event: MessageEvent) => {
      if (
        event.source === window.parent &&
        event.origin === window.location.origin &&
        event.data?.skyflow === "pause"
      )
        history.pause();
    };
    window.addEventListener("keydown", keydown);
    window.addEventListener("message", message);
    return () => {
      window.removeEventListener("keydown", keydown);
      window.removeEventListener("message", message);
    };
  }, [history.pause, history.togglePlayback]);

  function chooseCamera(preset: CameraPreset) {
    setCameraPreset(preset);
    setCameraRevision((revision) => revision + 1);
  }

  return (
    <main className="observatory week-observatory">
      <header className="identity-band">
        <div className="identity">
          <svg
            className="brand-mark"
            viewBox="0 0 32 32"
            fill="none"
            aria-hidden="true"
          >
            <path
              d="M6 5v14c0 5 4 8 10 8s10-3 10-8V5M12 5v14c0 2 1.5 3 4 3s4-1 4-3V5"
              stroke="currentColor"
              strokeWidth="2.5"
            />
            <path d="M3 5h6M23 5h6" stroke="currentColor" strokeWidth="2.5" />
          </svg>
          <div className="identity-copy">
            <span className="wordmark">
              UITA <span>/</span> SFO
            </span>
            <span className="identity-description">San Francisco airspace</span>
          </div>
        </div>
        <div className="mode-inset">
          <span
            className={`status-lamp ${error ? "lamp-error" : loading ? "lamp-amber" : "lamp-green"}`}
          />
          <span>Recorded week</span>
        </div>
        <div className="header-source">
          <span className="equipment-label">ADSB.lol observations</span>
          <span>{weekLabel}</span>
        </div>
        <div className="clock-inset">
          <span>
            <span>
              {catalog
                ? dateFormat.format(new Date(time * 1000))
                : "Replay time"}
            </span>
            <br />
            <span>PDT</span>
          </span>
          <strong>{catalog ? formatLocalTime(time) : "—:—:—"}</strong>
        </div>
      </header>

      <div className="workspace">
        <section
          className="map-instrument"
          aria-label="Interactive SFO landscape"
        >
          <div className="instrument-face map-face">
            <div className="instrument-title">
              <span className="equipment-label">01 / Spatial display</span>
              <h1>San Francisco Bay</h1>
            </div>
            <div className="camera-bank" role="group" aria-label="Camera view">
              {cameras.map((camera) => (
                <button
                  key={camera.id}
                  type="button"
                  aria-pressed={cameraPreset === camera.id}
                  disabled={
                    camera.id === "follow" && (!selected || state?.y == null)
                  }
                  title={
                    camera.id === "follow" && (!selected || state?.y == null)
                      ? "Select an aircraft with map placement"
                      : undefined
                  }
                  onClick={() => chooseCamera(camera.id)}
                >
                  {camera.label}
                </button>
              ))}
            </div>
          </div>
          <div className="scene-container">
            <div className="scene-mount">
              <Scene
                time={time}
                targets={targets}
                cameraPreset={cameraPreset}
                cameraRevision={cameraRevision}
                showTracks={showTracks}
                showLabels={showLabels}
                quality={quality}
                onSelect={onSelect}
                selectedId={selectedId}
                onStatus={onStatus}
              />
            </div>
            {!status.ready && !status.error && (
              <div className="scene-loading" role="status">
                <span className="status-lamp lamp-amber" />
                <div>
                  <strong>Preparing the landscape</strong>
                  <span>Loading terrain and airport assets</span>
                </div>
              </div>
            )}
            {status.error && (
              <div className="scene-error" role="alert">
                <strong>Map unavailable</strong>
                <p>{status.error}</p>
                <p>Source observations remain available in the register.</p>
              </div>
            )}
            <div className="scene-caption">
              <span className="scene-caption-title">
                SFO <span>37°37′ N / 122°23′ W</span>
              </span>
              <span>
                {cameraPreset === "region"
                  ? "Regional observations · local SFO terrain detail"
                  : "Procedural landscape · schematic airport"}
              </span>
            </div>
            {error && (
              <div className="data-connection-error" role="alert">
                <strong>Recorded traffic unavailable</strong>
                <p>{error}</p>
                <button type="button" onClick={history.retry}>
                  Retry data connection
                </button>
              </div>
            )}
            {!error && loading && status.ready && (
              <div className="data-loading" role="status">
                <span className="status-lamp lamp-amber" />
                Loading observations · replay clock held
              </div>
            )}
            <div className="scene-help">
              <span>Drag to orbit</span>
              <span>Scroll to zoom</span>
              <span>Select a target</span>
            </div>
          </div>
          <div className="display-control-bank">
            <div className="scene-toggles" role="group" aria-label="Map layers">
              <button
                type="button"
                className="layer-toggle"
                aria-pressed={showTracks}
                onClick={() => setShowTracks((value) => !value)}
              >
                <span className="toggle-mark" aria-hidden="true">
                  {showTracks ? "✓" : ""}
                </span>
                History · 2 min
              </button>
              <button
                type="button"
                className="layer-toggle"
                aria-pressed={showLabels}
                onClick={() => setShowLabels((value) => !value)}
              >
                <span className="toggle-mark" aria-hidden="true">
                  {showLabels ? "✓" : ""}
                </span>
                Target labels
              </button>
            </div>
            <div className="render-controls">
              <label htmlFor="render-quality">Detail</label>
              <select
                id="render-quality"
                value={quality}
                onChange={(event) =>
                  setQuality(event.target.value as "high" | "balanced")
                }
              >
                <option value="high">High</option>
                <option value="balanced">Balanced</option>
              </select>
              <span className="fps-readout">
                {status.ready && status.fps > 0
                  ? `${Math.round(status.fps)} fps`
                  : status.error
                    ? "Unavailable"
                    : "Loading"}
              </span>
            </div>
          </div>
        </section>

        <aside
          className="traffic-instrument"
          aria-label="Traffic and source observation evidence"
        >
          <div className="instrument-face traffic-face">
            <div className="instrument-title">
              <span className="equipment-label">02 / Traffic & evidence</span>
              <h2>Observation register</h2>
            </div>
            <span
              className="traffic-count"
              title="Regional targets with measurements no more than 15 seconds old"
            >
              {sourceReady ? String(targets.length).padStart(2, "0") : "—"}
              <small>regional · ≤15 s</small>
            </span>
          </div>
          <div className="inspector-body">
            <div className="coverage-readouts">
              <div>
                <span>Map placement</span>
                <strong>
                  {sourceReady ? `${mappedCount} / ${targets.length}` : "—"}
                </strong>
                <small>Altitude or ground flag</small>
              </div>
              <div>
                <span>SFO operations · day</span>
                <strong>
                  {dailyOperations ? number.format(dailyOperations.total) : "—"}
                </strong>
                <small>FAA OPSNET · arrivals + departures</small>
              </div>
            </div>
            <section
              className="selection-instrument"
              aria-labelledby="selected-aircraft-title"
            >
              <div className="section-heading">
                <h3 id="selected-aircraft-title">Source observation</h3>
                <span className="section-index">A</span>
              </div>
              {selected && state ? (
                <>
                  <div className="selected-identity">
                    <div>
                      <span className="selected-callsign">
                        {selected.callsign}
                      </span>
                      <span className="aircraft-identifier">
                        Target ID {selected.id}
                      </span>
                    </div>
                    <span className="observation-state is-visible">
                      <span className="status-lamp" />
                      {Math.max(0, time - state.t).toFixed(1)} s old
                    </span>
                  </div>
                  <dl className="aircraft-readouts">
                    <Field
                      label="Barometric altitude"
                      value={
                        state.altitudeFt == null
                          ? "Not recorded"
                          : number.format(state.altitudeFt)
                      }
                      unit={state.altitudeFt == null ? undefined : "ft"}
                    />
                    <Field
                      label="Ground speed"
                      value={
                        state.speedKt == null
                          ? "Not recorded"
                          : number.format(state.speedKt)
                      }
                      unit={state.speedKt == null ? undefined : "kt"}
                    />
                    <Field
                      label="Track heading"
                      value={
                        state.heading == null
                          ? "Not recorded"
                          : String(Math.round(state.heading) % 360).padStart(
                              3,
                              "0",
                            )
                      }
                      unit={state.heading == null ? undefined : "°"}
                    />
                    <Field
                      label="Ground flag"
                      value={
                        state.onGround == null
                          ? "Not recorded"
                          : state.onGround
                            ? "On ground"
                            : "Airborne"
                      }
                    />
                  </dl>
                  {state.y == null && (
                    <p className="capture-note">
                      List only — neither altitude nor a ground flag permits map
                      placement.
                    </p>
                  )}
                  <div className="evidence-note">
                    <span className="evidence-label">
                      Measured {formatLocalTime(state.t)} PDT
                    </span>
                    <p>Original ADSB.lol sample. No extrapolation.</p>
                    <details className="source-observation-details">
                      <summary>Full source observation</summary>
                      <dl className="source-facts">
                        <div>
                          <dt>Timestamp</dt>
                          <dd>{formatReplayTime(state.t)}</dd>
                        </div>
                        <div>
                          <dt>Latitude</dt>
                          <dd>{state.latitude.toFixed(6)}°</dd>
                        </div>
                        <div>
                          <dt>Longitude</dt>
                          <dd>{state.longitude.toFixed(6)}°</dd>
                        </div>
                        <div>
                          <dt>Registration</dt>
                          <dd>{selected.registration || "Not recorded"}</dd>
                        </div>
                        <div>
                          <dt>Aircraft type</dt>
                          <dd>{selected.aircraftType || "Not recorded"}</dd>
                        </div>
                        <div>
                          <dt>Source</dt>
                          <dd>{selected.source}</dd>
                        </div>
                      </dl>
                      <p>
                        Reported altitude is not surveyed height. Ground
                        placement and enlarged aircraft symbols are schematic.
                      </p>
                    </details>
                  </div>
                </>
              ) : (
                <p className="empty-selection">
                  {loading
                    ? "Loading recorded observations…"
                    : selectedId
                      ? "The selected aircraft has no fresh observation at this time."
                      : "Select a target on the map or in the register."}
                </p>
              )}
            </section>
            <section
              className="traffic-register"
              aria-labelledby="traffic-list-title"
            >
              <div className="section-heading">
                <h3 id="traffic-list-title">Fresh observations</h3>
                <span className="register-total">
                  {sourceReady
                    ? targetQuery.trim()
                      ? `${filteredTargets.length} / ${targets.length}`
                      : `${targets.length} targets`
                    : "Unavailable"}
                </span>
              </div>
              <div className="target-search">
                <label htmlFor="target-search">Find an aircraft</label>
                <div>
                  <input
                    id="target-search"
                    type="search"
                    value={targetQuery}
                    onChange={(event) => setTargetQuery(event.target.value)}
                    placeholder="Callsign, ICAO, registration"
                    autoComplete="off"
                    spellCheck={false}
                  />
                  {targetQuery && (
                    <button
                      type="button"
                      onClick={() => setTargetQuery("")}
                      aria-label="Clear aircraft search"
                    >
                      ×
                    </button>
                  )}
                </div>
              </div>
              <div className="traffic-table-heading" aria-hidden="true">
                <span>Callsign</span>
                <span>Altitude / ft</span>
              </div>
              <div
                className="traffic-list"
                role="group"
                aria-label="Select an observed aircraft"
              >
                {filteredTargets.map((target) => (
                  <button
                    type="button"
                    className={`traffic-row ${selectedId === target.id ? "is-selected" : ""}`}
                    key={target.id}
                    aria-pressed={selectedId === target.id}
                    onClick={() => onSelect(target.id)}
                  >
                    <span
                      className={`aircraft-glyph ${target.state.y == null ? "" : "is-visible"}`}
                      aria-hidden="true"
                    >
                      {target.state.onGround === true ||
                      target.state.heading == null
                        ? "•"
                        : "✈"}
                    </span>
                    <span className="traffic-callsign">
                      {target.callsign}
                      <small>
                        {target.state.y == null
                          ? "List only · altitude unavailable"
                          : target.state.onGround === true
                            ? "Reported on ground"
                            : target.id}
                      </small>
                    </span>
                    <span className="traffic-altitude">
                      {target.state.altitudeFt == null
                        ? "—"
                        : number.format(target.state.altitudeFt)}
                    </span>
                    <span className="selection-arrow" aria-hidden="true">
                      ›
                    </span>
                  </button>
                ))}
              </div>
              {targets.length === 0 && (
                <p className="empty-selection">
                  {error
                    ? "Traffic records could not load. Use Retry data connection."
                    : loading
                      ? "Loading source observations…"
                      : "No fresh observations in this interval."}
                </p>
              )}
              {targets.length > 0 && filteredTargets.length === 0 && (
                <p className="empty-selection">
                  No fresh observations match “{targetQuery}”.
                </p>
              )}
            </section>
            <details className="weather-instrument">
              <summary>
                Observed SFO weather{" "}
                <span>
                  {weather
                    ? `${formatLocalTime(weather.t).slice(0, 5)} PDT`
                    : "Unavailable"}
                </span>
              </summary>
              {weather ? (
                <>
                  <dl className="source-facts">
                    <div>
                      <dt>Observation</dt>
                      <dd>{formatReplayTime(weather.t)}</dd>
                    </div>
                    <div>
                      <dt>Visibility</dt>
                      <dd>{measure(weather.visibilityMi, "mi")}</dd>
                    </div>
                    <div>
                      <dt>Ceiling</dt>
                      <dd>{measure(weather.ceilingFt, "ft")}</dd>
                    </div>
                    <div>
                      <dt>Wind</dt>
                      <dd>
                        {measure(weather.windKt, "kt")}
                        {weather.windDirection == null
                          ? ""
                          : ` / ${measure(weather.windDirection, "°")}`}
                      </dd>
                    </div>
                  </dl>
                  <p>
                    Hourly source observation. Scene lighting is illustrative.
                  </p>
                </>
              ) : (
                <p>
                  No hourly weather observation is available at this replay
                  time.
                </p>
              )}
            </details>
            <details className="source-footnote data-limits">
              <summary>
                Data coverage & limits{" "}
                <span>
                  {catalog ? `${coverageDays}/7 dates` : "Unavailable"}
                </span>
              </summary>
              <p>
                {catalog
                  ? `${number.format(totalRows)} observations across ${coverageDays} loaded local dates.`
                  : "Coverage is unavailable until the archive connects."}
              </p>
              {catalog?.loaded_at && (
                <p>Last import: {String(catalog.loaded_at)}</p>
              )}
              <p>
                One original sample per aircraft per 5 seconds. Targets
                disappear after 15 seconds without a measurement.
              </p>
              <p>
                Regional observations include nearby airports and overflights.
                They are not a complete SFO operation roster.
              </p>
              <p>
                Arrival rates, runway use, delay, and safety events are not
                inferred. <strong>Safety events: not evaluated.</strong>
              </p>
              <p>
                Aircraft are enlarged. Ground placement and procedural elevation
                are schematic. Source values remain unchanged.
              </p>
              <p>
                Detailed terrain covers the SFO area; distant land is a
                simplified county map.
              </p>
              <p>
                <a
                  href={catalog?.source_url || sourceUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  ADSB.lol trace archive · ODbL-1.0
                </a>
              </p>
              <p>
                Imagery: USGS NAIP. Coastline: US Census. Geometry:{" "}
                <a
                  href="https://www.openstreetmap.org/copyright"
                  target="_blank"
                  rel="noreferrer"
                >
                  © OpenStreetMap contributors
                </a>
                .
              </p>
              <button
                type="button"
                className="refresh-source"
                onClick={history.refresh}
                disabled={loading}
              >
                Refresh data coverage
              </button>
            </details>
          </div>
        </aside>
      </div>

      <section
        className="playback-instrument week-playback"
        aria-label="Recorded week replay controls"
      >
        <div className="week-navigation">
          <div className="week-days" role="group" aria-label="Replay day">
            {history.days.length ? (
              history.days.map((day) => (
                <button
                  key={day.date}
                  type="button"
                  disabled={!day.loaded}
                  aria-pressed={activeDay === day.date}
                  onClick={() => history.seekDay(day.start)}
                  title={
                    day.loaded
                      ? `${number.format(day.rows)} observations · open at noon PDT`
                      : "This date is not loaded"
                  }
                >
                  <span>
                    {dayFormat.format(new Date(`${day.date}T12:00:00Z`))}{" "}
                    <strong>{day.date.slice(-2)}</strong>
                  </span>
                  <small>
                    <span
                      className={`status-lamp ${day.loaded ? "lamp-green" : ""}`}
                    />
                    {day.loaded ? "Loaded" : "Unavailable"}
                  </small>
                </button>
              ))
            ) : (
              <span className="week-not-loaded">
                {loading
                  ? "Loading week coverage…"
                  : "Week coverage unavailable"}
              </span>
            )}
          </div>
          <div className="timeline week-timeline">
            <div className="timeline-labels">
              <label htmlFor="replay-position">Recorded week · PDT</label>
              <span>
                {catalog
                  ? `${coverageDays}/7 dates loaded`
                  : "No archive connection"}
              </span>
            </div>
            <input
              id="replay-position"
              type="range"
              min={catalog?.start ?? 0}
              max={catalog ? catalog.end - 1 : 1}
              step="1"
              value={catalog ? time : 0}
              disabled={!catalog}
              onChange={(event) => history.seek(Number(event.target.value))}
              aria-valuetext={
                catalog ? formatReplayTime(time) : "Archive unavailable"
              }
              style={{ "--replay-progress": `${progress}%` } as CSSProperties}
            />
            <div className="timeline-ticks">
              <span>
                {catalog
                  ? `${dateFormat.format(new Date(catalog.start * 1000))} · 00:00`
                  : "Start"}
              </span>
              <span>
                {catalog
                  ? `${dateFormat.format(new Date((catalog.end - 1) * 1000))} · 23:59`
                  : "End"}
              </span>
            </div>
          </div>
        </div>
        <div className="week-transport-row">
          <div className="transport-heading">
            <span className="equipment-label">03 / Replay transport</span>
            <span className="transport-state" role="status">
              <span
                className={`status-lamp ${error ? "lamp-error" : loading ? "lamp-amber" : playing ? "lamp-green" : ""}`}
              />
              {statusText}
            </span>
          </div>
          <div className="transport-actions">
            <button
              type="button"
              className="play-key"
              onClick={history.togglePlayback}
              disabled={
                !catalog ||
                (loading && !playing) ||
                Boolean(error) ||
                Boolean(catalog && time >= catalog.end - 1)
              }
            >
              <PlayIcon playing={playing} />
              {playing ? "Pause" : "Play"}
            </button>
            <button
              type="button"
              className="step-key"
              disabled={!catalog}
              onClick={() => history.seek(catalog!.start)}
              aria-label="Restart week"
            >
              ↤
            </button>
            <button
              type="button"
              className="step-key"
              disabled={!catalog}
              onClick={() => history.step(-900)}
            >
              −15<span>min</span>
            </button>
            <button
              type="button"
              className="step-key"
              disabled={!catalog}
              onClick={() => history.step(10)}
            >
              +10<span>s</span>
            </button>
            <button
              type="button"
              className="step-key"
              disabled={!catalog}
              onClick={() => history.step(900)}
            >
              +15<span>min</span>
            </button>
            <button
              type="button"
              className="step-key week-end"
              disabled={!catalog}
              onClick={() => history.seek(catalog!.end - 1)}
            >
              Week end
            </button>
          </div>
          <div className="week-time-controls">
            <label className="playback-rate" htmlFor="playback-rate">
              <span className="equipment-label">Speed</span>
              <select
                id="playback-rate"
                aria-label="Playback speed"
                value={rate}
                disabled={!catalog}
                onChange={(event) =>
                  history.setRate(Number(event.target.value))
                }
              >
                {speedOptions.map((speed) => (
                  <option key={speed} value={speed}>
                    {speed}×
                  </option>
                ))}
              </select>
            </label>
            <label className="local-time-field" htmlFor="replay-local-time">
              <span className="equipment-label">Time · PDT</span>
              <input
                id="replay-local-time"
                type="time"
                step="1"
                disabled={!catalog}
                value={catalog ? formatLocalTime(time) : ""}
                onChange={(event) => {
                  if (event.target.value)
                    history.setLocalTime(event.target.value);
                }}
              />
            </label>
          </div>
        </div>
      </section>
      <footer className="workspace-status">
        <span>
          <span
            className={`status-lamp ${error ? "lamp-error" : loading ? "lamp-amber" : "lamp-green"}`}
          />
          <a href={sourceUrl} target="_blank" rel="noreferrer">
            ADSB.lol
          </a>{" "}
          · Recorded measurements
        </span>
        <span>
          USGS NAIP · US Census ·{" "}
          <a
            href="https://www.openstreetmap.org/copyright"
            target="_blank"
            rel="noreferrer"
          >
            © OpenStreetMap
          </a>
        </span>
        <span>Research visualization · Not for navigation</span>
      </footer>
    </main>
  );
}
