import {
  useCallback,
  useEffect,
  useRef,
  useState,
  Suspense,
  lazy,
} from "react";
import {
  Play,
  Pause,
  SkipForward,
  Download,
  LogOut,
  Volume2,
  VolumeX,
  RotateCcw,
  Plane,
  AlertTriangle,
} from "lucide-react";
import "./research.css";
import type { components } from "./research.generated";
type Wire = components["schemas"];
const ResearchScene = lazy(() => import("./ResearchScene"));

export type Aircraft = {
  id: string;
  callsign: string;
  x_nm: number;
  y_nm: number;
  altitude_ft: number | null;
  groundspeed_kt: number | null;
  track_deg_true: number | null;
  status: string;
  runway: string;
  type: string;
  provenance: { kind: string };
  age_seconds?: number;
};
type Run = {
  id: string;
  revision: number;
  status: string;
  state: {
    clock: number;
    start: number;
    end: number;
    scenario_id: string;
    controller: string;
    aircraft: Aircraft[];
    metrics: Record<string, number>;
    weather: Record<string, unknown>;
    clearances: Record<string, unknown>[];
    speed: number;
    provenance: Record<string, unknown>;
    fallback_reason?: string;
  };
};
type Scenario = {
  id: string;
  start: number;
  end: number;
  split: string;
  coverage: { entries: number; observed: number };
  provenance: { kind: string };
};
type Event = Wire["RunEvent"];
const utc = (value: number) =>
  new Date(value * 1000).toISOString().slice(11, 19) + " UTC";
const fmt = (value: number | null | undefined) =>
  value == null ? "Unknown" : Math.round(value).toLocaleString();
const key = () => crypto.randomUUID();
async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch("/api/v2" + path, {
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    method: body ? "POST" : "GET",
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Service unavailable" }));
    throw new Error(error.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

function TrafficMap({
  aircraft,
  selected,
  onSelect,
  three,
}: {
  aircraft: Aircraft[];
  selected: string | null;
  onSelect: (id: string) => void;
  three: boolean;
}) {
  const visible = aircraft.filter(
    (a) => !["complete", "diverted", "pending"].includes(a.status),
  );
  if (three)
    return (
      <Suspense fallback={<p>Loading 3D view…</p>}>
        <ResearchScene
          visible={visible}
          selected={selected}
          onSelect={onSelect}
        />
      </Suspense>
    );
  return (
    <svg
      className="research-map"
      viewBox="-85 -85 170 170"
      role="img"
      aria-label="SFO traffic in local nautical miles, north up"
    >
      <rect x="-85" y="-85" width="170" height="170" fill="#14231e" />
      {[20, 40, 60, 80].map((r) => (
        <g key={r}>
          <circle r={r} fill="none" stroke="#35483d" strokeWidth=".15" />
          <text x="1" y={-r + 3} fill="#9aa99c" fontSize="2.2">
            {r} NM
          </text>
        </g>
      ))}
      <path d="M-80 0H80M0 -80V80" stroke="#35483d" strokeWidth=".15" />
      <g transform="rotate(63)">
        <rect x="-.1" y="-2" width=".4" height="4" fill="#d3c8a7" />
        <rect x=".65" y="-2" width=".4" height="4" fill="#d3c8a7" />
      </g>
      <text x="2" y="5" fill="#d3c8a7" fontSize="2.4">
        KSFO · 28L / 28R
      </text>
      <text x="-81" y="-78" fill="#cad3c8" fontSize="2.4">
        N ↑ · LOCAL ENU · SCHEMATIC RUNWAYS
      </text>
      {visible.map((a) => (
        <g
          key={a.id}
          onClick={() => onSelect(a.id)}
          className="research-aircraft"
          transform={`translate(${a.x_nm} ${-a.y_nm})`}
        >
          <circle r="2.5" fill="transparent" />
          <path
            d="M0 -1.3L.8 1 0 .5-.8 1Z"
            transform={`rotate(${a.track_deg_true || 0})`}
            fill={a.id === selected ? "#ffc16c" : "#d5e2d5"}
          />
          <text
            x="1.4"
            y="-1"
            fontSize="2.2"
            fill={a.id === selected ? "#ffc16c" : "#d5e2d5"}
          >
            {a.callsign}
          </text>
          <text x="1.4" y="1.6" fontSize="1.8" fill="#a9baad">
            {fmt(a.altitude_ft)} ft · {fmt(a.groundspeed_kt)} kt
          </text>
        </g>
      ))}
    </svg>
  );
}

export default function Research() {
  const [user, setUser] = useState<{ username: string; role: string; access_mode: "private" | "public_demo" } | null>(
      null,
    ),
    [checking, setChecking] = useState(true);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [scenarios, setScenarios] = useState<Scenario[]>([]),
    [scenario, setScenario] = useState("");
  const [run, setRun] = useState<Run | null>(null),
    [mode, setMode] = useState("Simulate"),
    [selected, setSelected] = useState<string | null>(null),
    [events, setEvents] = useState<Event[]>([]);
  const [three, setThree] = useState(false),
    [speech, setSpeech] = useState(false),
    [controller, setController] =
      useState<NonNullable<Wire["RunCreate"]["controller"]>>("fixture"),
    [replayClock, setReplayClock] = useState(0),
    [replay, setReplay] = useState<Aircraft[]>([]);
  const [fixtureFault, setFixtureFault] = useState("none");
  const [connection, setConnection] = useState("connecting");
  const [snapshotAvailable, setSnapshotAvailable] = useState(true);
  const [checkpoints, setCheckpoints] = useState<
      { revision: number; clock: number }[]
    >([]),
    [replayRevision, setReplayRevision] = useState<number | null>(null),
    [replayRun, setReplayRun] = useState<Run | null>(null);
  const [comparison, setComparison] = useState<{
    id: string;
    status: string;
    result?: {
      results: {
        controller: string;
        status: string;
        metrics: Record<string, number>;
      }[];
    };
  } | null>(null);
  const [standards, setStandards] = useState<{ limitations: string[] } | null>(
      null,
    ),
    [tab, setTab] = useState("Traffic");
  const speechRef = useRef(false);
  speechRef.current = speech;
  const perform = useCallback(async (task: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await task();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Operation failed");
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => {
    api<{ username: string; role: string; access_mode: "private" | "public_demo" }>("/me")
      .then(setUser)
      .catch(() => {})
      .finally(() => setChecking(false));
  }, []);
  useEffect(() => {
    if (!user) return;
    perform(async () => {
      const list = await api<Scenario[]>("/scenarios");
      setScenarios(list);
      const demo =
        list.find((s) => s.id === "2026-08-06-1500-research-v2-metered") ||
        list[0];
      setScenario(demo?.id || "");
      setReplayClock(demo?.start || 0);
      setStandards(await api("/standards"));
      const recent = await api<{ id: string }[]>("/runs");
      if (recent.length) setRun(await api<Run>("/runs/" + recent[0].id));
    });
  }, [user, perform]);
  useEffect(() => {
    if (!run || replayRevision !== null) return;
    let active = true;
    const timer = setInterval(
      () =>
        api<Run>("/runs/" + run.id)
          .then((r) => {
            if (active) {
              setRun(r);
              setSnapshotAvailable(true);
            }
          })
          .catch(() => {
            if (active) setSnapshotAvailable(false);
          }),
      1000,
    );
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [run?.id, replayRevision]);
  useEffect(() => {
    if (!run) return;
    setEvents([]);
    let stream: EventSource | null = null;
    let stopped = false,
      cursor = 0,
      retry = 1000;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const connect = () => {
      if (stopped) return;
      stream = new EventSource(
        "/api/v2/runs/" + run.id + "/stream?after=" + cursor,
      );
      stream.onopen = () => {
        retry = 1000;
        setConnection("connected");
      };
      stream.onmessage = (message) => {
        const event = JSON.parse(message.data) as Event;
        cursor = Math.max(cursor, event.sequence);
        setEvents((items) =>
          items.some((e) => e.sequence === event.sequence)
            ? items
            : [...items, event].slice(-300),
        );
        if (
          speechRef.current &&
          typeof event.payload.text === "string" &&
          "speechSynthesis" in window
        )
          window.speechSynthesis.speak(
            new SpeechSynthesisUtterance(event.payload.text),
          );
      };
      stream.onerror = () => {
        setConnection("reconnecting");
        stream?.close();
        timer = setTimeout(connect, retry);
        retry = Math.min(retry * 2, 5000);
      };
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      stream?.close();
    };
  }, [run?.id]);
  useEffect(() => {
    if (mode !== "Replay" || !scenario) return;
    const timer = setTimeout(
      () =>
        api<{ aircraft: Aircraft[] }>(
          `/replay?scenario_id=${encodeURIComponent(scenario)}&clock=${replayClock}`,
        )
          .then((r) => setReplay(r.aircraft))
          .catch((e) => setError(e.message)),
      150,
    );
    return () => clearTimeout(timer);
  }, [mode, scenario, replayClock]);
  useEffect(() => {
    if (!comparison || ["complete", "failed"].includes(comparison.status))
      return;
    const timer = setInterval(
      () =>
        api<typeof comparison>("/jobs/" + comparison.id)
          .then(setComparison)
          .catch((e) => setError(e.message)),
      1000,
    );
    return () => clearInterval(timer);
  }, [comparison?.id, comparison?.status]);
  const chosen = scenarios.find((s) => s.id === scenario),
    active = replayRun || run;
  const aircraft = mode === "Replay" ? replay : active?.state.aircraft || [],
    flight = aircraft.find((a) => a.id === selected);
  const mutateRun = async (
    endpoint: string,
    fields: Record<string, unknown>,
  ): Promise<Run> => {
    if (!run) throw new Error("Select a run");
    const idempotency_key = key();
    for (let attempt = 0; attempt < 2; attempt++) {
      const current = await api<Run>("/runs/" + run.id);
      try {
        return await api<Run>("/runs/" + run.id + endpoint, {
          ...fields,
          expected_revision: current.revision,
          idempotency_key,
        });
      } catch (error) {
        if (
          attempt ||
          !(error instanceof Error) ||
          !error.message.includes("Stale revision")
        )
          throw error;
      }
    }
    throw new Error("Run changed; try again");
  };
  const control = (
    action: Wire["Control"]["action"],
    extra: Partial<Pick<Wire["Control"], "seconds" | "speed">> = {},
  ) =>
    perform(async () => {
      if (run)
        setRun(
          await mutateRun("/control", {
            action,
            seconds: 1,
            speed: 1,
            ...extra,
            expected_revision: run.revision,
            idempotency_key: key(),
          } satisfies Wire["Control"]),
        );
    });
  const inject = (kind: Wire["Disruption"]["kind"]) =>
    perform(async () => {
      if (run)
        setRun(
          await mutateRun("/disruptions", {
            kind,
            runway: "28R",
            expected_revision: run.revision,
            idempotency_key: key(),
            aircraft_id: selected,
            value: kind === "communications" ? 30 : 1,
            duration_seconds: 120,
          } satisfies Wire["Disruption"]),
        );
    });
  if (checking)
    return (
      <main className="research-login">
        <h1>Connecting to Uita…</h1>
      </main>
    );
  if (!user)
    return (
      <main className="research-login">
        <div className="research-login-inner">
          <span className="research-brand">uita.</span>
          <h1>
            A shared sky,
            <br />
            under study.
          </h1>
          <p>Sign in to the private research workbench.</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const fields = new FormData(e.currentTarget);
              perform(async () => {
                await api("/login", {
                  username: fields.get("username"),
                  password: fields.get("password"),
                });
                setUser(await api("/me"));
                history.replaceState(null, "", "/");
              });
            }}
          >
            <label>
              Username
              <input name="username" autoComplete="username" required />
            </label>
            <label>
              Password
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </label>
            <button disabled={busy} type="submit">
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
          {error && <p role="alert">{error}</p>}
          <p className="research-note">
            Research simulation. No connection to operational aircraft control.
          </p>
        </div>
      </main>
    );
  return (
    <main className="research-shell">
      <header className="research-header">
        <a className="research-brand" href="/">
          uita.
        </a>
        <nav aria-label="Workbench mode">
          {["Replay", "Simulate", "Compare"].map((m) => (
            <button
              key={m}
              aria-current={mode === m ? "page" : undefined}
              onClick={() => setMode(m)}
            >
              {m}
            </button>
          ))}
        </nav>
        <div className="research-account">
          <span>
            {user.username} · {user.role}
          </span>
          {user.access_mode !== "public_demo" && <button
            aria-label="Sign out"
            onClick={() =>
              perform(async () => {
                await api("/logout", {});
                setUser(null);
                setRun(null);
              })
            }
          >
            <LogOut size={17} />
          </button>}
        </div>
      </header>
      <section className="research-toolbar">
        <label>
          Scenario
          <select
            value={scenario}
            onChange={(e) => {
              setScenario(e.target.value);
              setReplayClock(
                scenarios.find((s) => s.id === e.target.value)?.start || 0,
              );
            }}
          >
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.id} · {s.provenance.kind}
              </option>
            ))}
          </select>
        </label>
        <label>
          Controller
          <select
            value={controller}
            onChange={(e) =>
              setController(
                e.target.value as NonNullable<Wire["RunCreate"]["controller"]>,
              )
            }
          >
            <option value="fixture">Autonomous fixture · free</option>
            <option value="static">Deterministic planner</option>
            <option value="fcfs">First come, first served</option>
            <option value="crusoe">Crusoe · $0.50 cap</option>
          </select>
        </label>
        {controller === "fixture" && (
          <label>
            Fixture behavior
            <select
              aria-label="Fixture behavior"
              value={fixtureFault}
              onChange={(e) => setFixtureFault(e.target.value)}
            >
              <option value="none">Normal proposals</option>
              <option value="provider_timeout">Simulate model failure</option>
              <option value="budget_exhausted">
                Simulate budget exhaustion
              </option>
            </select>
          </label>
        )}
        <button
          disabled={busy || !scenario || user.role === "viewer"}
          onClick={() =>
            perform(async () => {
              setRun(
                await api("/runs", {
                  scenario_id: scenario,
                  controller,
                  fixture_fault:
                    controller === "fixture" ? fixtureFault : "none",
                  idempotency_key: key(),
                }),
              );
              setReplayRevision(null);
              setReplayRun(null);
              setMode("Simulate");
            })
          }
        >
          Create run
        </button>
        <span className="research-coverage">
          {chosen?.coverage?.observed ?? 0} observed /{" "}
          {chosen?.coverage?.entries ?? 0} entries · {chosen?.split}
        </span>
      </section>
      {error && (
        <div className="research-alert" role="alert">
          <AlertTriangle size={17} />
          {error}
          <button onClick={() => setError("")} aria-label="Dismiss message">
            Dismiss
          </button>
        </div>
      )}
      {run && (
        <p className="research-note" role="status">
          Event stream {snapshotAvailable ? connection : "reconnecting"}
          {run.state.fallback_reason
            ? ` · Deterministic fallback: ${run.state.fallback_reason.replaceAll("_", " ")}`
            : ""}
          {run.status === "failed"
            ? " · Scenario failed. Inspect Evidence; fork an earlier checkpoint to continue."
            : ""}
        </p>
      )}
      {mode === "Compare" ? (
        <section className="research-comparison">
          <h1>Compare this run with the baseline</h1>
          <p>
            Freeze the executed run and replay its timed disruptions with the
            deterministic planner. Both use the same scenario, seed, elapsed
            simulation time, and verification rules. Unfinished traffic stays in
            the backlog. No new inference is required.
          </p>
          <button
            disabled={busy || user.role === "viewer" || !run}
            onClick={() =>
              perform(async () => {
                if (!run) return;
                const frozen =
                  run.status === "running"
                    ? await mutateRun("/control", { action: "pause" })
                    : await api<Run>("/runs/" + run.id);
                setRun(frozen);
                setComparison(
                  await api("/runs/" + run.id + "/compare", {
                    expected_revision: frozen.revision,
                    idempotency_key: key(),
                  }),
                );
              })
            }
          >
            Compare with deterministic baseline
          </button>
          {comparison && <p role="status">Comparison {comparison.status}</p>}
          {comparison?.status === "failed" && (
            <p role="alert">
              Comparison failed. The job retains its failure evidence.
            </p>
          )}
          {comparison?.result?.results && (
            <table>
              <thead>
                <tr>
                  <th>Controller</th>
                  <th>State</th>
                  <th>Completed</th>
                  <th>Backlog</th>
                  <th>Violations</th>
                </tr>
              </thead>
              <tbody>
                {comparison.result.results.map((r) => (
                  <tr key={r.controller}>
                    <td>{r.controller}</td>
                    <td>{r.status}</td>
                    <td>{r.metrics.completed}</td>
                    <td>{r.metrics.backlog}</td>
                    <td>{r.metrics.violations}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {comparison && (
            <a
              href={"/api/v2/jobs/" + comparison.id}
              download="uita-comparison.json"
            >
              Export comparison evidence
            </a>
          )}
        </section>
      ) : (
        <section className="research-workspace">
          <div className="research-display">
            <div className="research-display-heading">
              <div>
                <h1>San Francisco terminal area</h1>
                <p>
                  {mode === "Replay"
                    ? "Historical observations"
                    : replayRevision !== null
                      ? "Simulation checkpoint replay"
                      : "Autonomous research simulation"}{" "}
                  ·{" "}
                  {mode === "Replay"
                    ? utc(replayClock)
                    : active
                      ? utc(active.state.clock)
                      : "No run selected"}
                </p>
              </div>
              <button onClick={() => setThree(!three)} aria-pressed={three}>
                {three ? "2D map" : "3D view"}
              </button>
            </div>
            <TrafficMap
              aircraft={aircraft}
              selected={selected}
              onSelect={setSelected}
              three={three}
            />
            <div className="research-map-caption">
              {mode === "Replay"
                ? "Missing tracks remain missing. Positions older than 120 seconds are omitted."
                : "Simulated motion · conservative dependent-runway model · August construction configuration"}
            </div>
          </div>
          <aside className="research-inspector">
            <div className="research-tabs">
              {["Traffic", "Communications", "Evidence"].map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  aria-pressed={tab === t}
                >
                  {t}
                </button>
              ))}
            </div>
            {tab === "Traffic" && (
              <>
                <h2>{flight ? flight.callsign : "Aircraft in view"}</h2>
                {flight && (
                  <dl>
                    <dt>Altitude</dt>
                    <dd>{fmt(flight.altitude_ft)} ft</dd>
                    <dt>Ground speed</dt>
                    <dd>{fmt(flight.groundspeed_kt)} kt</dd>
                    <dt>State</dt>
                    <dd>{flight.status}</dd>
                    <dt>Evidence</dt>
                    <dd>{flight.provenance.kind}</dd>
                  </dl>
                )}
                <div className="research-table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Flight</th>
                        <th>State</th>
                        <th>Altitude</th>
                      </tr>
                    </thead>
                    <tbody>
                      {aircraft.map((a) => (
                        <tr
                          key={a.id}
                          className={a.id === selected ? "selected" : ""}
                        >
                          <td>
                            <button onClick={() => setSelected(a.id)}>
                              {a.callsign}
                            </button>
                          </td>
                          <td>{a.status}</td>
                          <td>{fmt(a.altitude_ft)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!aircraft.length && (
                    <p className="research-empty">
                      {mode === "Replay"
                        ? "No recent observed positions in this window."
                        : "Create a run, then play or step to admit traffic."}
                    </p>
                  )}
                </div>
              </>
            )}
            {tab === "Communications" && (
              <>
                <div className="research-inline">
                  <h2>Pilot communications</h2>
                  <button
                    onClick={() => {
                      setSpeech(!speech);
                      if (speech) window.speechSynthesis?.cancel();
                    }}
                    aria-label={speech ? "Mute speech" : "Enable speech"}
                  >
                    {speech ? <Volume2 size={18} /> : <VolumeX size={18} />}
                  </button>
                </div>
                <p className="research-note">
                  Synthetic exchanges generated from structured simulation
                  events.
                </p>
                {events
                  .filter((e) => /clearance|pilot|readback/.test(e.kind))
                  .slice(-40)
                  .reverse()
                  .map((e) => (
                    <article className="research-event" key={e.sequence}>
                      <time>{utc(e.clock)}</time>
                      <strong>{e.kind.replaceAll("_", " ")}</strong>
                      <p>
                        {String(
                          e.payload.text ||
                            "See structured evidence for this event.",
                        )}
                      </p>
                    </article>
                  ))}
              </>
            )}
            {tab === "Evidence" && (
              <>
                <h2>Decisions and limits</h2>
                {standards?.limitations.map((l) => (
                  <p className="research-note" key={l}>
                    {l}
                  </p>
                ))}
                {events
                  .slice(-35)
                  .reverse()
                  .map((e) => (
                    <details className="research-event" key={e.sequence}>
                      <summary>
                        {utc(e.clock)} · {e.kind.replaceAll("_", " ")}
                      </summary>
                      <pre>{JSON.stringify(e.payload, null, 2)}</pre>
                    </details>
                  ))}
              </>
            )}
          </aside>
        </section>
      )}
      <footer className="research-controls">
        {mode === "Replay" ? (
          <>
            <label className="research-scrubber">
              Historical clock
              <input
                type="range"
                min={chosen?.start || 0}
                max={chosen?.end || 1}
                value={replayClock}
                onChange={(e) => setReplayClock(Number(e.target.value))}
              />
            </label>
            <span>{utc(replayClock)}</span>
          </>
        ) : (
          <>
            <button
              disabled={
                !run ||
                busy ||
                replayRevision !== null ||
                user.role === "viewer"
              }
              onClick={() =>
                control(run?.status === "running" ? "pause" : "play")
              }
            >
              {run?.status === "running" ? (
                <Pause size={17} />
              ) : (
                <Play size={17} />
              )}{" "}
              {run?.status === "running" ? "Pause" : "Play"}
            </button>
            <button
              aria-label="Step ten seconds"
              disabled={
                !run ||
                busy ||
                replayRevision !== null ||
                user.role === "viewer"
              }
              onClick={() => control("step", { seconds: 10 })}
            >
              <SkipForward size={17} />
              10s
            </button>
            <select
              aria-label="Playback speed"
              value={run?.state.speed || 1}
              disabled={!run || busy}
              onChange={(e) =>
                control("speed", { speed: Number(e.target.value) })
              }
            >
              {[1, 5, 10, 30].map((n) => (
                <option key={n} value={n}>
                  {n}×
                </option>
              ))}
            </select>
            <span>
              {run?.status || "No run"} · {run ? utc(run.state.clock) : "—"}
            </span>
            <div className="research-metrics">
              <span>
                <Plane size={14} /> {active?.state.metrics.completed || 0}{" "}
                completed
              </span>
              <span>{active?.state.metrics.backlog || 0} backlog</span>
              <span>
                {active?.state.metrics.violations || 0} modeled violations
              </span>
            </div>
            {run && (
              <a
                href={"/api/v2/runs/" + run.id + "/export"}
                download="uita-evidence.json"
              >
                <Download size={17} />
                Export
              </a>
            )}
          </>
        )}
      </footer>
      {mode === "Simulate" && run && (
        <section className="research-secondary">
          <span>Inject a synthetic event</span>
          {(
            [
              ["runway_closure", "Close 28R"],
              ["weather", "Low visibility"],
              ["readback_error", "Readback error"],
              ["communications", "Radio delay"],
            ] as const
          ).map(([kind, label]) => (
            <button
              key={kind}
              disabled={
                busy || user.role === "viewer" || replayRevision !== null
              }
              onClick={() => inject(kind)}
            >
              {label}
            </button>
          ))}
          <button
            onClick={() =>
              perform(async () =>
                setCheckpoints(await api("/runs/" + run.id + "/checkpoints")),
              )
            }
          >
            <RotateCcw size={14} />
            Checkpoints
          </button>
          {checkpoints.length > 0 && (
            <select
              aria-label="Replay checkpoint"
              value={replayRevision || ""}
              onChange={(e) =>
                perform(async () => {
                  if (!e.target.value) {
                    setReplayRevision(null);
                    setReplayRun(null);
                    return;
                  }
                  setReplayRevision(Number(e.target.value));
                  setReplayRun(
                    await api("/runs/" + run.id + "/replay/" + e.target.value),
                  );
                })
              }
            >
              <option value="">Current run</option>
              {checkpoints.map((c) => (
                <option key={c.revision} value={c.revision}>
                  {utc(c.clock)} · revision {c.revision}
                </option>
              ))}
            </select>
          )}
        </section>
      )}
      <div className="research-status">
        Private research workspace · Recorded observations, reconstruction and
        simulated outcomes are distinct evidence · Not for operational control
      </div>
    </main>
  );
}
