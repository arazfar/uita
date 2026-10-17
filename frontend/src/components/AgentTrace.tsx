import { Brain, Check, CircleDashed, Search, ShieldCheck, Wrench } from 'lucide-react';
import type { LearningJob, LearningEvent } from '../types';
import { ChainOfThought, ChainOfThoughtContent, ChainOfThoughtHeader, ChainOfThoughtStep } from './ai/chain-of-thought';
import './agent-trace.css';

const isRunning = (status: string) => ['queued', 'running'].includes(status);
const label = (value: string) => value.replaceAll('_', ' ').replace(/^\w/, character => character.toUpperCase());
const eventIcon = (kind: string) => kind === 'reasoning' ? Brain : kind.startsWith('tool') ? Wrench : kind.includes('validation') || kind === 'decision' ? ShieldCheck : kind.includes('completed') || kind === 'inference_received' ? Check : Search;

function TraceEvent({ event }: { event: LearningEvent }) {
  const reasoning = event.kind === 'reasoning' && event.data.source === 'provider-response' && typeof event.data.text === 'string';
  return <ChainOfThoughtStep icon={eventIcon(event.kind)} label={event.message}
    description={<><span>{String(event.sequence).padStart(2, '0')} / {label(event.stage)}</span><span>{label(event.kind)}</span></>}>
    {reasoning && <details className="reasoning-detail" open>
      <summary>Provider reasoning · request {String(event.data.request ?? '—')}</summary>
      <pre>{String(event.data.text)}</pre>
      {event.data.truncated === true && <p className="trace-notice">Display excerpt. The provider returned {String(event.data.original_characters)} characters; the journal stores a bounded excerpt.</p>}
    </details>}
    {event.kind === 'candidate' && typeof event.data.explanation === 'string' && <p className="trace-explanation">Candidate explanation: {event.data.explanation}</p>}
  </ChainOfThoughtStep>;
}

/** This panel renders recorded events, never a locally generated thinking script. */
export function AgentTrace({ job }: { job: LearningJob }) {
  const events = job.events ?? [];
  const fixture = job.source !== 'crusoe-live';
  const active = isRunning(job.status);
  const discovery = events.find(event => event.kind === 'discovery');
  const settings = discovery?.data.settings as Record<string, unknown> | undefined;
  const thinkingEnabled = job.provider_usage?.thinking_enabled === true || settings?.thinking_enabled === true;
  const model = typeof job.provider_usage?.model === 'string' ? job.provider_usage.model : typeof discovery?.data.model === 'string' ? discovery.data.model : undefined;
  const hasReasoning = events.some(event => event.kind === 'reasoning');
  return <section className="agent-trace" aria-label="Agent thinking trace">
    <div className="trace-instrument-label">Machine channel / Investigator</div>
    <div className="trace-mode"><strong>{fixture ? 'Offline fixture' : model?.replace('nvidia/NVIDIA-', '') ?? 'Live provider job'}</strong>
      <span>{fixture ? 'No model inference' : thinkingEnabled ? 'Thinking ON · medium' : 'Settings not yet verified'}</span>
    </div>
    <p className="trace-notice">{fixture
      ? 'Recorded fixture steps test the workflow. They are not AI thoughts.'
      : 'Provider reasoning appears after each response completes. Tool and verifier events are recorded separately.'}</p>
    <ChainOfThought defaultOpen>
      <ChainOfThoughtHeader>Investigation trace <span className="trace-count">{events.length} events</span></ChainOfThoughtHeader>
      <ChainOfThoughtContent>
        {!events.length && <p className="trace-notice">{active ? 'Waiting for the worker to record its first event.' : 'No trace events were recorded for this job.'}</p>}
        {events.map(event => <TraceEvent key={event.sequence} event={event} />)}
        {active && <ChainOfThoughtStep icon={CircleDashed} status="active" label={label(job.stage ?? job.status)} description="Waiting for the next recorded event. The journal refreshes with the experiment." />}
        {!fixture && !active && !hasReasoning && <p className="trace-notice">No provider reasoning was exposed for this job. Recorded operations remain available above.</p>}
      </ChainOfThoughtContent>
    </ChainOfThought>
    <p className="trace-boundary">Model output is untrusted. The independent verifier and explicit plan commit remain required.</p>
  </section>;
}
