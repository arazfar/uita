import {
  clearanceFor,
  phrase,
  readback,
  parse,
  check,
  correction,
  intentOf,
  callsign,
  spokenCallsign,
  digits,
} from "./radio.mjs";
import { createRadio, createMic } from "./voice.mjs";
import { routes, edgeKey, position } from "./scheduler.mjs";

// The sector controller loop. The scheduler decides; the agent negotiates;
// the radio says it; nothing commits until the readback matches.

const LEAD = 0.6; // issue takeoff clearance this many minutes before departure
// SF-108 is rerouted around the storm; its pilot reads back the usual route
// (expectation bias) and the hearback check has to catch it.
const ERROR_FLIGHT = "SF-108";
const stamp = (t) =>
  `${String(Math.floor(t)).padStart(2, "0")}:${String(Math.floor((t % 1) * 60)).padStart(2, "0")}`;
const esc = (s) =>
  String(s).replace(
    /[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c],
  );

export function createATC({ root, getPlan, getTime, replan, focus }) {
  const $ = (s) => root.querySelector(s);
  const log = $("#sf-radio-log"),
    stateEl = $("#sf-radio-state"),
    engineEl = $("#sf-engine");
  let processed = new Set(),
    last = getTime(),
    holds = 0,
    voice = true,
    errored = false,
    config = { tts: false, agent: null },
    generation = 0,
    stats = { voice: 0, datalink: 0, caught: 0, agent: 0 };

  const radio = createRadio({
    onChange(tx) {
      const live = tx.state === "live";
      stateEl.textContent = live
        ? tx.speaker === "atc"
          ? "TRANSMITTING"
          : "RECEIVING"
        : radio.backlog
          ? "BUSY"
          : "MONITORING";
      stateEl.dataset.live = live ? tx.speaker : "";
      if (tx.row) tx.row.classList.toggle("is-live", live);
    },
  });

  function hold(d) {
    holds = Math.max(0, holds + d);
  }

  function row(kind, who, text, extra = "") {
    const li = document.createElement("li");
    li.className = "sf-tx sf-tx-" + kind;
    li.innerHTML = `<div class="sf-tx-meta"><time>${stamp(getTime())}</time><b>${esc(who)}</b>${extra}</div><p>${esc(text)}</p>`;
    log.prepend(li);
    while (log.children.length > 60) log.lastChild.remove();
    return li;
  }
  function chips(li, stages) {
    let el = li.querySelector(".sf-chips");
    if (!el) {
      el = document.createElement("div");
      el.className = "sf-chips";
      li.append(el);
    }
    el.innerHTML = stages
      .map(
        (s) =>
          `<span class="sf-chip sf-chip-${s.split(" ")[0]}">${esc(s)}</span>`,
      )
      .join("");
  }

  async function say(speaker, text, key, li) {
    if (!voice) return;
    const p = radio.say(speaker, text, key);
    // Highlight the row while it is on air.
    const tx = { row: li };
    li?.classList.add("is-queued");
    await p;
    li?.classList.remove("is-queued");
    return tx;
  }

  async function clear(f, { voiced, prefix = "", amended = false } = {}) {
    const gen = generation,
      c = clearanceFor(f, amended ? "reroute" : "takeoff");
    if (!voiced || !voice) {
      // Routine traffic goes by datalink: same structured check, no airtime.
      const ok = check(c, parse(readback(c))).ok;
      const li = row(
        "datalink",
        callsign(f.id),
        phrase(c).replace(/^UITA [a-z ]+, /, ""),
        `<span class="sf-ch">DATALINK</span>`,
      );
      chips(li, [
        "issued",
        "readback",
        ok ? "verified" : "mismatch",
        "committed",
      ]);
      stats.datalink++;
      return;
    }
    hold(1);
    focus(f.id);
    stats.voice++;
    const stages = ["issued"];
    try {
      const atcText = prefix + phrase(c);
      const a = row(
        "atc",
        "UITA Tower",
        atcText,
        `<span class="sf-ch">VOICE</span>`,
      );
      chips(a, stages);
      {
        const e =
          f.id === ERROR_FLIGHT && !errored
            ? { via: routes(f.from, f.to)[0].slice(1, -1) }
            : null;
        radio.prefetch("pilot", readback(c, e), f.id);
        if (e) radio.prefetch("pilot", readback(c), f.id);
      }
      await say("atc", atcText, "atc", a);
      if (gen !== generation) return;
      const err =
        f.id === ERROR_FLIGHT && !errored
          ? { via: routes(f.from, f.to)[0].slice(1, -1) }
          : null;
      if (err && JSON.stringify(err.via) === JSON.stringify(c.via))
        err.via = [];
      const rb = readback(c, err);
      const p = row(
        "pilot",
        callsign(f.id),
        rb,
        `<span class="sf-ch">VOICE</span>`,
      );
      await say("pilot", rb, f.id, p);
      if (gen !== generation) return;
      let r = check(c, parse(rb));
      stages.push("readback");
      if (!r.ok) {
        errored = true;
        stats.caught++;
        stages.push("mismatch: " + r.mismatches.map((m) => m.field).join(", "));
        chips(a, stages);
        const why = r.mismatches
          .map(
            (m) =>
              `${m.field} heard ${JSON.stringify(m.heard)} ≠ issued ${JSON.stringify(m.issued)}`,
          )
          .join("; ");
        row(
          "check",
          "Hearback check",
          "Readback mismatch caught before commit — " + why,
          `<span class="sf-ch sf-ch-warn">BLOCKED</span>`,
        );
        const fix = correction(c, r.mismatches);
        const a2 = row(
          "atc",
          "UITA Tower",
          fix,
          `<span class="sf-ch">VOICE</span>`,
        );
        await say("atc", fix, "atc", a2);
        if (gen !== generation) return;
        const rb2 = readback(c);
        row("pilot", callsign(f.id), rb2, `<span class="sf-ch">VOICE</span>`);
        await say("pilot", rb2, f.id);
        r = check(c, parse(rb2));
      }
      stages.push(
        r.ok ? "verified" : "mismatch",
        r.ok ? "committed" : "not committed",
      );
      chips(a, stages);
    } finally {
      hold(-1);
    }
  }

  function sectorState(plan, now) {
    return plan.flights
      .map((f) => ({ f, s: position(f, now).state }))
      .filter(({ s }) => s !== "arrived")
      .map(({ f, s }) => ({
        id: f.id,
        callsign: callsign(f.id),
        state: s,
        from: f.from,
        to: f.to,
        departure: +f.departure.toFixed(1),
        deadline: +f.deadline.toFixed(1),
        corridors: f.path.slice(1).map((n, i) => edgeKey(f.path[i], n)),
        priority: !!f.priority,
      }));
  }

  async function decide(text, plan, now) {
    if (config.agent)
      try {
        const r = await fetch("/api/agent", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            transcript: text,
            state: sectorState(plan, now),
          }),
        });
        if (r.ok) return await r.json();
        console.warn(await r.text());
      } catch (e) {
        console.warn(e);
      }
    const { intent, id } = intentOf(text);
    const f = plan.flights.find((x) => x.id === id);
    const action = {
      priority: "grant_priority",
      reroute: "reroute",
      hold: "delay_departure",
      unknown: "say_again",
    }[intent];
    return {
      action: f ? action : "say_again",
      args: {
        id,
        avoid: f
          ? f.path
              .slice(1)
              .map((n, i) => edgeKey(f.path[i], n))
              .slice(0, 1)
          : [],
        minutes: 5,
        reason: "keyword fallback",
      },
      provider: "rules",
      model: "keyword fallback",
      ms: 0,
    };
  }

  async function pilotCall(text, source = "typed") {
    const gen = generation;
    hold(1);
    try {
      const now = getTime(),
        before = getPlan();
      row(
        "pilot",
        "Pilot (" + source + ")",
        text,
        `<span class="sf-ch">${source === "mic" ? "LIVE MIC" : "VOICE"}</span>`,
      );
      if (source !== "mic") await say("pilot", text, "judge");
      const d = await decide(text, before, now);
      if (gen !== generation) return;
      stats.agent++;
      const id = d.args?.id,
        f = before.flights.find((x) => x.id === id);
      row(
        "agent",
        "Sector agent",
        `${d.action}(${[id, d.args?.avoid?.join("+"), d.args?.minutes && d.action === "delay_departure" ? d.args.minutes + " min" : ""].filter(Boolean).join(", ")}) — ${d.args?.reason || ""}`,
        `<span class="sf-ch sf-ch-agent">${esc(d.provider)} · ${esc(d.model)}${d.ms ? " · " + d.ms + " ms" : ""}</span>`,
      );
      if (d.action === "say_again" || !f) {
        const t =
          "Station calling UITA Tower, say again callsign and request.";
        const li = row(
          "atc",
          "UITA Tower",
          t,
          `<span class="sf-ch">VOICE</span>`,
        );
        await say("atc", t, "atc", li);
        return;
      }
      if (f.departure <= now) {
        const t = `${spokenCallsign(id)}, you are airborne on a committed route, unable to amend. Continue as cleared, landing slot confirmed.`;
        const li = row(
          "atc",
          "UITA Tower",
          t,
          `<span class="sf-ch">VOICE</span>`,
        );
        row(
          "check",
          "Scheduler",
          "Airborne reservations are immutable in this model; request declined deterministically.",
          `<span class="sf-ch sf-ch-warn">DECLINED</span>`,
        );
        await say("atc", t, "atc", li);
        return;
      }
      const request =
        d.action === "grant_priority"
          ? { priority: [id] }
          : d.action === "reroute"
            ? { avoid: { [id]: d.args.avoid || [] } }
            : {
                notBefore: {
                  [id]: now + Math.max(1, Math.min(30, d.args.minutes || 5)),
                },
              };
      const { plan: after, errors, before: m0, after: m1 } = replan(request);
      const g = after.flights.find((x) => x.id === id);
      const moved = after.flights.filter((x) => {
        const o = before.flights.find((y) => y.id === x.id);
        return x.id !== id && Math.abs(o.departure - x.departure) > 0.05;
      });
      row(
        "check",
        "Validator",
        `${errors.length} reservation conflicts · ${moved.length} other flights re-sequenced · on-time ${m0.onTime}→${m1.onTime}/28`,
        `<span class="sf-ch ${errors.length ? "sf-ch-warn" : "sf-ch-ok"}">${errors.length ? "REJECTED" : "COMMITTED"}</span>`,
      );
      for (const x of moved.slice(0, 4)) {
        const o = before.flights.find((y) => y.id === x.id);
        const li = row(
          "datalink",
          callsign(x.id),
          `amended: expect departure ${stamp(x.departure)} (${x.departure > o.departure ? "+" : ""}${(x.departure - o.departure).toFixed(1)} min)`,
          `<span class="sf-ch">DATALINK</span>`,
        );
        chips(li, ["issued", "readback", "verified", "committed"]);
      }
      // Re-issue the requesting flight's clearance by voice, now or at its new time.
      processed.delete(id);
      const prefix =
        d.action === "grant_priority"
          ? `${spokenCallsign(id)}, priority approved. `
          : d.action === "reroute"
            ? `${spokenCallsign(id)}, roger, avoiding ${(d.args.avoid || []).join(" and ")}. `
            : `${spokenCallsign(id)}, roger, delay approved, expect departure at ${digits(stamp(g.departure).replace(":", ""))}. `;
      if (g.departure - LEAD <= getTime() || d.action !== "delay_departure") {
        processed.add(id);
        await clear(g, {
          voiced: true,
          prefix,
          amended: d.action === "reroute",
        });
      } else {
        const li = row(
          "atc",
          "UITA Tower",
          prefix.trim(),
          `<span class="sf-ch">VOICE</span>`,
        );
        await say("atc", prefix.trim(), "atc", li);
      }
    } finally {
      hold(-1);
    }
  }

  function tick(time, selected) {
    if (time < last - 1e-6) return reset(time);
    const plan = getPlan(),
      jumped = time - last > 3;
    for (const f of plan.flights) {
      const at = f.departure - LEAD;
      if (processed.has(f.id) || at > time) continue;
      processed.add(f.id);
      if (at < last - 1e-6 && !jumped) continue;
      const voiced =
        !jumped &&
        (f.id === ERROR_FLIGHT || f.id === selected || f.priority) &&
        radio.backlog < 2;
      clear(f, { voiced });
    }
    last = time;
  }

  function reset(time) {
    generation++;
    radio.flush();
    holds = 0;
    errored = false;
    last = time;
    processed = new Set(
      getPlan()
        .flights.filter((f) => f.departure - LEAD <= time)
        .map((f) => f.id),
    );
    log.innerHTML = "";
    row(
      "system",
      "UITA Tower",
      `Monitoring sector 01 from ${stamp(time)}. Departures within ${LEAD} min get a clearance; voice for the selected flight, priority traffic and the storm reroute.`,
    );
  }

  // Controls
  $("#sf-voice").addEventListener("change", (e) => {
    voice = e.target.checked;
    radio.setMuted(!voice);
  });
  const ptt = $("#sf-ptt"),
    input = $("#sf-pilot-input");
  $("#sf-pilot-form").addEventListener("submit", (e) => {
    e.preventDefault();
    radio.unlock();
    const t = input.value.trim();
    if (t) pilotCall(t, "typed");
    input.value = "";
  });
  root.querySelectorAll("[data-call]").forEach((b) =>
    b.addEventListener("click", () => {
      radio.unlock();
      const plan = getPlan(),
        now = getTime();
      const waiting = plan.flights
        .filter((f) => f.departure > now + LEAD + 0.2)
        .sort((a, b) => b.departure - b.release - (a.departure - a.release))[0];
      if (!waiting) return;
      const cs = spokenCallsign(waiting.id);
      const corridor = edgeKey(waiting.path[0], waiting.path[1]);
      input.value = {
        priority: `${cs}, medical transport on board, request priority departure.`,
        weather: `${cs}, unable ${corridor.replace("-", " to ")}, reporting turbulence on that corridor, request another route.`,
        delay: `${cs}, passenger running late, request five minute delay on the pad.`,
      }[b.dataset.call];
      input.focus();
    }),
  );
  const mic = () =>
    createMic({
      server: config.tts,
      onText: (t) => pilotCall(t, "mic"),
      onState: (s, t) => {
        ptt.dataset.state = s;
        ptt.textContent =
          s === "hearing"
            ? "Listening… release to send"
            : s === "transcribing"
              ? "Transcribing…"
              : "Hold to talk as pilot";
        if (t && s === "hearing") input.value = t;
      },
    });
  let micInstance;
  const down = (e) => {
    e.preventDefault();
    radio.unlock();
    micInstance ??= mic();
    if (!micInstance) {
      ptt.textContent = "Mic unavailable — type below";
      return;
    }
    micInstance.start();
  };
  const up = () => micInstance?.stop();
  ptt.addEventListener("pointerdown", down);
  ptt.addEventListener("pointerup", up);
  ptt.addEventListener("pointerleave", up);

  fetch("/api/config")
    .then((r) => (r.ok ? r.json() : null))
    .then((c) => {
      if (!c) return;
      config = c;
      radio.setOpenAI(c.tts);
      engineEl.textContent = [
        c.tts ? "OpenAI voice" : "browser voice",
        c.agent ? `agent: ${c.agent.model}` : "agent: rules",
      ].join(" · ");
    })
    .catch(() => {});

  reset(last);
  return {
    tick,
    reset,
    pilotCall,
    unlock: () => radio.unlock(),
    get holding() {
      return holds > 0;
    },
    get stats() {
      return stats;
    },
  };
}
