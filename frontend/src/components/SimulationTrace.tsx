import { Brain, ShieldCheck, AlertTriangle, Radio } from "lucide-react";
import {
  ChainOfThought,
  ChainOfThoughtHeader,
  ChainOfThoughtContent,
  ChainOfThoughtStep,
} from "./ai/chain-of-thought";
import type { components } from "../research.generated";
import "./agent-trace.css";

type Event = components["schemas"]["RunEvent"];
export type SimulationTraceProps = {
  events: Event[];
  clock: number;
  source: string;
  live: boolean;
  controller: string;
  status: string;
  comparison: boolean;
};
const kinds = new Set([
  "model_response",
  "model_response_discarded",
  "proposal_verified",
  "proposal_fallback",
  "controller_fallback",
]);
const title: Record<string, string> = {
  model_response: "Agent proposal returned",
  model_response_discarded: "Proposal discarded",
  proposal_verified: "Independent verification",
  proposal_fallback: "Proposal rejected · baseline selected",
  controller_fallback: "Controller fallback",
};
const utc = (clock: number) =>
  new Date(clock * 1000).toISOString().slice(11, 19) + " UTC";

function Step({ event }: { event: Event }) {
  const payload = event.payload as Record<string, any>;
  const metadata = payload.metadata ?? {};
  const trace: { kind: string; data?: Record<string, any> }[] = Array.isArray(
    metadata.trace,
  )
    ? metadata.trace
    : [];
  const verdict = payload.verdict;
  const fixture = metadata.mode === "fixture";
  const reasoning = trace.filter(
    (item) =>
      item.kind === "reasoning" &&
      item.data?.source === "provider-response" &&
      typeof item.data!.text === "string",
  );
  return (
    <ChainOfThoughtStep
      icon={
        event.kind === "proposal_verified"
          ? ShieldCheck
          : event.kind.includes("fallback") || event.kind.includes("discarded")
            ? AlertTriangle
            : Brain
      }
      label={title[event.kind]}
      description={
        <>
          <span>{utc(event.clock)}</span>
          <span>Event {event.sequence}</span>
          {metadata.framework && <span>{metadata.framework}</span>}
        </>
      }
    >
      {event.kind.startsWith("model_response") && (
        <>
          <p className="trace-notice">
            {fixture
              ? "Authored fixture · no model inference"
              : `${metadata.model ?? "Recorded model"} · ${metadata.thinking_enabled === true ? "Thinking ON · medium" : "Thinking settings not recorded"}`}
          </p>
          {reasoning.map((item, index) => (
            <details className="reasoning-detail" key={index} open>
              <summary>Provider reasoning</summary>
              <pre>{item.data!.text}</pre>
              {item.data!.truncated && (
                <p className="trace-notice">
                  Bounded excerpt of {item.data!.original_characters} returned
                  characters.
                </p>
              )}
            </details>
          ))}
          {!reasoning.length && (
            <p className="trace-notice">
              {fixture
                ? "These steps are not AI thoughts."
                : "No provider reasoning was recorded for this response."}
            </p>
          )}
          {typeof payload.proposal?.explanation === "string" && (
            <p className="trace-explanation">
              <strong>Proposal explanation:</strong>{" "}
              {payload.proposal.explanation}
            </p>
          )}
        </>
      )}
      {verdict && (
        <p className="trace-explanation">
          Verifier: {String(verdict.status ?? "unknown")}.{" "}
          {typeof verdict.reason === "string" ? verdict.reason : ""}
        </p>
      )}
      {typeof payload.reason === "string" && (
        <p className="trace-explanation">
          {payload.reason.replaceAll("_", " ")}
        </p>
      )}
      {event.kind === "controller_fallback" &&
        reasoning.map((item, index) => (
          <details className="reasoning-detail" key={index}>
            <summary>Returned reasoning · failed response</summary>
            <pre>{item.data!.text}</pre>
          </details>
        ))}
    </ChainOfThoughtStep>
  );
}

/** The playhead, not wall time, determines what a replay is allowed to reveal. */
export function SimulationTrace({
  events,
  clock,
  source,
  live,
  controller,
  status,
  comparison,
}: SimulationTraceProps) {
  const visible = events.filter(
    (event) => event.clock <= clock && kinds.has(event.kind),
  );
  const shown = visible.slice(-60);
  return (
    <section className="agent-trace" aria-label="Agent thinking trace">
      <div className="trace-instrument-label">Machine channel / Simulation</div>
      <p className="trace-notice">
        {comparison
          ? "Candidate trace · independent of the displayed controller. "
          : ""}
        {source} · {live ? "Live journal" : "Recorded playback"}
      </p>
      <ChainOfThought defaultOpen>
        <ChainOfThoughtHeader>
          Agent thinking trace{" "}
          <span className="trace-count">
            {visible.length} {visible.length === 1 ? "step" : "steps"}
          </span>
        </ChainOfThoughtHeader>
        <ChainOfThoughtContent>
          <p className="trace-notice">
            Provider reasoning appears after each response completes. Proposal
            explanations and verifier results are separate evidence.
          </p>
          {visible.length > shown.length && (
            <p className="trace-notice">
              Showing the latest 60 steps. Export evidence for the full journal.
            </p>
          )}
          {!shown.length && (
            <p className="trace-notice">
              {controller === "fixture"
                ? "Authored fixture · no model reasoning. Waiting for recorded workflow events."
                : controller.startsWith("static")
                  ? "Deterministic controller · no AI reasoning."
                  : "No agent events at this playback time. Play or seek forward to inspect recorded decisions."}
            </p>
          )}
          {shown.map((event) => (
            <Step key={event.sequence} event={event} />
          ))}
          {live && status === "running" && controller === "crusoe" && (
            <ChainOfThoughtStep
              icon={Radio}
              status="active"
              label="Listening for committed agent events"
              description="A running simulation does not imply an inference request is in progress."
            />
          )}
        </ChainOfThoughtContent>
      </ChainOfThought>
      <p className="trace-boundary">
        Model reasoning does not authorize a clearance. The independent traffic
        verifier still decides applicability.
      </p>
    </section>
  );
}
