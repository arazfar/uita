import { byId, edgeKey } from "./scheduler.mjs";

// Structured clearances, spoken phraseology, and the readback check.
// The scheduler decides; this module only says it and verifies what came back.

const DIGITS = [
  "zero",
  "one",
  "two",
  "three",
  "four",
  "five",
  "six",
  "seven",
  "eight",
  "niner",
];
const WORD_DIGIT = {
  zero: 0,
  oh: 0,
  one: 1,
  won: 1,
  two: 2,
  to: 2,
  too: 2,
  three: 3,
  tree: 3,
  four: 4,
  for: 4,
  fower: 4,
  five: 5,
  fife: 5,
  six: 6,
  seven: 7,
  eight: 8,
  ait: 8,
  nine: 9,
  niner: 9,
};
// Spoken names for every graph node. Order matters for parsing: longer first.
export const SPOKEN = {
  SF: "San Francisco",
  MAR: "Marin",
  SFO: "S F O",
  OAK: "Oakland",
  BER: "Berkeley",
  W: "West approach",
  C: "Central",
  E: "East approach",
};
const NODE_PATTERNS = [
  ["SFO", /\b(s ?f ?o|sfo|airport)\b/],
  ["SF", /\b(san francisco|city)\b/],
  ["MAR", /\bmarin\b/],
  ["OAK", /\boakland\b/],
  ["BER", /\bberkeley\b/],
  ["W", /\bwest( approach)?\b/],
  ["C", /\bcentral( crossing)?\b/],
  ["E", /\beast( approach)?\b/],
];

export const digits = (n) =>
  String(n)
    .split("")
    .map((d) => DIGITS[+d] ?? d)
    .join(" ");
export const callsign = (id) => "SkyFlow " + id.replace(/^SF-/, "");
export const spokenCallsign = (id) =>
  "SkyFlow " + digits(id.replace(/^SF-/, ""));
// Altitude band is deterministic per route so the same flight always reads the same band.
export const band = (path) => 1 + (edgeKey(path[0], path[1]).length % 3);
const hhmm = (t) => {
  const m = Math.round(t * 60) / 60;
  return (
    String(Math.floor(m)).padStart(2, "0") +
    String(Math.round((m % 1) * 60) % 60).padStart(2, "0")
  );
};

export function clearanceFor(flight, kind = "takeoff") {
  if (kind === "hold")
    return {
      kind,
      id: flight.id,
      pad: flight.from,
      expect: hhmm(flight.departure),
    };
  return {
    kind,
    id: flight.id,
    via: flight.path.slice(1, -1),
    dest: flight.to,
    band: band(flight.path),
    slot: hhmm(flight.arrival),
  };
}

export function phrase(c) {
  const cs = spokenCallsign(c.id);
  if (c.kind === "hold")
    return `${cs}, hold on the pad at ${SPOKEN[c.pad]}, expect departure at ${digits(c.expect)}.`;
  const via = c.via.length
    ? ` via ${c.via.map((n) => SPOKEN[n]).join(", ")}`
    : " direct";
  const verb = c.kind === "reroute" ? "re-cleared" : "cleared for takeoff,";
  return `${cs}, ${verb} ${SPOKEN[c.dest]}${via}, climb band ${digits(c.band)}, landing slot ${digits(c.slot)}.`;
}

// What the pilot says back. `error` swaps one field to exercise the hearback check.
export function readback(c, error = null) {
  const r = { ...c, ...(error || {}) };
  const cs = spokenCallsign(c.id);
  if (c.kind === "hold")
    return `Hold at ${SPOKEN[r.pad]}, expect ${digits(r.expect)}, ${cs}.`;
  const via = r.via.length
    ? ` via ${r.via.map((n) => SPOKEN[n]).join(", ")}`
    : " direct";
  return `Cleared ${SPOKEN[r.dest]}${via}, band ${digits(r.band)}, slot ${digits(r.slot)}, ${cs}.`;
}

function numbersIn(text) {
  // Collapse runs of spoken or written digits into numbers: "one zero six" -> "106".
  const out = [];
  let run = "";
  for (const w of text.split(/[\s,.;:-]+/)) {
    if (w in WORD_DIGIT) run += WORD_DIGIT[w];
    else if (/^\d+$/.test(w)) run += w;
    else {
      if (run) out.push({ value: run, before: w });
      run = "";
      out.push({ word: w });
    }
  }
  if (run) out.push({ value: run });
  return out;
}

export function parse(text) {
  const t = " " + text.toLowerCase().replace(/[^a-z0-9 ,.]/g, " ") + " ";
  const tokens = numbersIn(t.trim());
  const out = {};
  for (let i = 0; i < tokens.length; i++) {
    const prev = tokens[i - 1]?.word;
    const v = tokens[i].value;
    if (!v) continue;
    if (prev === "skyflow" || prev === "flight") out.id = "SF-" + v;
    else if (prev === "band" || prev === "level") out.band = +v;
    else if (prev === "slot" || prev === "at" || prev === "expect") {
      if (out.slot === undefined) out.slot = v.padStart(4, "0");
    }
  }
  if (/\bhold\b/.test(t)) out.kind = "hold";
  // Destination: the node named right after "cleared"/"to"/"hold at"; via: nodes after "via".
  const viaAt = t.indexOf(" via ");
  const head = viaAt >= 0 ? t.slice(0, viaAt) : t.replace(/ band .*/, "");
  const tail = viaAt >= 0 ? t.slice(viaAt + 5).replace(/ band .*/, "") : "";
  const found = (s) => {
    const hits = [];
    for (const [id, re] of NODE_PATTERNS) {
      const m = new RegExp(re.source, "g");
      let x;
      while ((x = m.exec(s))) hits.push({ id, at: x.index });
    }
    // Drop SF matches that are really the "s f o" airport.
    return hits
      .filter(
        (h) =>
          !(
            h.id === "SF" &&
            hits.some((o) => o.id === "SFO" && Math.abs(o.at - h.at) < 3)
          ),
      )
      .sort((a, b) => a.at - b.at)
      .map((h) => h.id);
  };
  const headNodes = found(head);
  if (headNodes.length) out.dest = headNodes.at(-1);
  if (out.kind === "hold") out.pad = out.dest;
  out.via = viaAt >= 0 ? found(tail) : /\bdirect\b/.test(t) ? [] : undefined;
  if (out.expect === undefined && out.kind === "hold") out.expect = out.slot;
  return out;
}

const FIELDS = {
  takeoff: ["id", "dest", "via", "band", "slot"],
  reroute: ["id", "dest", "via", "band", "slot"],
  hold: ["id", "pad", "expect"],
};
export function check(c, heard) {
  const mismatches = [];
  for (const f of FIELDS[c.kind]) {
    const a = JSON.stringify(c[f]),
      b = JSON.stringify(heard[f]);
    if (a !== b) mismatches.push({ field: f, issued: c[f], heard: heard[f] });
  }
  return { ok: mismatches.length === 0, mismatches };
}

export function correction(c, mismatches) {
  const cs = spokenCallsign(c.id);
  const say = {
    dest: () => `destination ${SPOKEN[c.dest]}`,
    via: () =>
      c.via.length ? `via ${c.via.map((n) => SPOKEN[n]).join(", ")}` : "direct",
    band: () => `band ${digits(c.band)}`,
    slot: () => `slot ${digits(c.slot)}`,
    id: () => `callsign ${cs}`,
    pad: () => `pad ${SPOKEN[c.pad]}`,
    expect: () => `expect ${digits(c.expect)}`,
  };
  return `${cs}, negative. ${mismatches.map((m) => say[m.field]()).join(", ")}. Read back.`;
}

// Classify a free-text pilot transmission when no LLM is configured.
export function intentOf(text) {
  const t = text.toLowerCase();
  const id = parse(text).id;
  if (/(battery|fuel|emergency|mayday|pan|medical|priority)/.test(t))
    return { intent: "priority", id };
  if (/(unable|weather|storm|turbulence|avoid)/.test(t))
    return { intent: "reroute", id };
  if (/(delay|hold|wait)/.test(t)) return { intent: "hold", id };
  return { intent: "unknown", id };
}

export const nodeName = (id) => byId[id]?.name ?? id;
