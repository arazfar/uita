import { createHash, timingSafeEqual } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { extname, resolve } from "node:path";
import { brotliCompressSync, gzipSync, constants as zc } from "node:zlib";
import { defineConfig, loadEnv } from "vite";

// Local-only API for the voice loop. Keys stay on the dev server; the browser
// only ever sees audio, short-lived session tokens and agent decisions.

const TOOLS = [
  {
    type: "function",
    function: {
      name: "grant_priority",
      description:
        "Move one flight to the front of the departure sequence (medical, low battery, emergency).",
      parameters: {
        type: "object",
        properties: {
          id: { type: "string", description: "Flight id like SF-112" },
          reason: { type: "string" },
        },
        required: ["id", "reason"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "reroute",
      description:
        "Re-plan one queued flight so it avoids the named corridors (e.g. weather the pilot reports).",
      parameters: {
        type: "object",
        properties: {
          id: { type: "string" },
          avoid: {
            type: "array",
            items: { type: "string" },
            description: "Corridor keys such as C-E or SF-W",
          },
          reason: { type: "string" },
        },
        required: ["id", "avoid", "reason"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "delay_departure",
      description: "Hold one queued flight on its pad for some minutes.",
      parameters: {
        type: "object",
        properties: {
          id: { type: "string" },
          minutes: { type: "number" },
          reason: { type: "string" },
        },
        required: ["id", "minutes", "reason"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "say_again",
      description:
        "The transmission was unclear or the callsign is unknown; ask the pilot to repeat.",
      parameters: {
        type: "object",
        properties: { reason: { type: "string" } },
        required: ["reason"],
      },
    },
  },
];

const SYSTEM = `You are the UITA sector controller agent for a simulated San Francisco Bay urban air mobility sector.
A deterministic scheduler owns separation and reservations; you never invent clearances.
Read the pilot transmission, identify the flight by callsign (UITA 112 = SF-112), and call exactly one tool.
Only act on flights listed in the sector state. Prefer grant_priority for medical, battery or emergency calls,
reroute for weather or "unable" reports, delay_departure for pilots asking to wait, otherwise say_again.`;

// Arrival sequencing agent: proposes landing slots and holds; the page's deterministic kernel validates.
const SEQ_TOOLS = [
  {
    type: "function",
    function: {
      name: "clear_to_land",
      description: "Give one arrival a landing slot on an open runway. slot_time is seconds from now.",
      parameters: {
        type: "object",
        properties: {
          id: { type: "string" },
          runway: { type: "string", enum: ["28L", "28R"] },
          slot_time: { type: "integer", description: "Seconds from now; must be >= the aircraft's min_slot_s" },
          reason: { type: "string", description: "At most 12 words" },
        },
        required: ["id", "runway", "slot_time", "reason"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "hold",
      description: "Hold one arrival at a published fix until a later slot.",
      parameters: {
        type: "object",
        properties: {
          id: { type: "string" },
          fix: { type: "string", enum: ["MENLO", "DUMBA", "ARCHI", "BDEGA"] },
          minutes: { type: "integer", minimum: 1, maximum: 20 },
          reason: { type: "string", description: "At most 12 words" },
        },
        required: ["id", "fix", "minutes", "reason"],
      },
    },
  },
];
const SEQ_SYSTEM = `You are the SFO arrival sequencing agent. Decide which arrivals land now and which hold.
Rules (a deterministic kernel will VETO violations): same-runway spacing at least 90 s, 120 s behind a heavy;
never use a closed runway; slot_time >= min_slot_s; one aircraft per slot. Frozen aircraft keep their slot.
Priorities: flag MED first, then flag FUEL, then minimise total delay. Prefer the kernel's listed free slots. Use both runways when open.
Call clear_to_land for every aircraft you can slot within about 10 minutes and hold (at its suggested fix) for the rest.
Call one tool per aircraft, in landing order, with increasing slot_time per runway.\nWrite each reason as one short plain-English sentence for the public that states the actual reason for that aircraft (no field names, under 12 words).`;

// One tool-calling chat. Some models (Nemotron with thinking off) return one call per turn, so keep
// the conversation going with tool results until every queued id is decided, the model stops, or time runs out.
async function chatTools(cfg, messages, tools, ids, feedback = () => ({ ok: true, text: "Noted." })) {
  const deadline = Date.now() + cfg.timeoutMs, calls = [], seen = new Set(), msgs = [...messages];
  let note = "";
  for (let round = 0; round < 8 && Date.now() < deadline - 300; round++) {
    const r = await fetch(cfg.url, {
      method: "POST",
      signal: AbortSignal.timeout(Math.max(500, deadline - Date.now())),
      headers: { authorization: `Bearer ${cfg.key}`, "content-type": "application/json" },
      body: JSON.stringify({ model: cfg.model, messages: msgs, tools, tool_choice: "auto", temperature: 0, max_tokens: cfg.maxTokens, ...(cfg.extra || {}) }),
    });
    if (!r.ok) throw new Error(`${cfg.provider} ${r.status}: ${(await r.text()).slice(0, 200)}`);
    const msg = (await r.json()).choices?.[0]?.message || {};
    if (!note) note = String(msg.content || "").replace(/<think>[\s\S]*?<\/think>/g, "").trim().slice(0, 240);
    const tc = msg.tool_calls || [];
    if (!tc.length) break;
    msgs.push({ role: "assistant", content: msg.content || "", tool_calls: tc });
    for (const c of tc) {
      let args = null;
      try { args = JSON.parse(c.function.arguments || "{}"); } catch {}
      const fb = args ? feedback(c.function.name, args) : { ok: false, text: "Unreadable arguments." };
      if (fb.ok && (c.function.name === "clear_to_land" || c.function.name === "hold") && !seen.has(args.id)) { seen.add(args.id); calls.push({ name: c.function.name, args }); }
      const left = ids.filter((id) => !seen.has(id));
      msgs.push({ role: "tool", tool_call_id: c.id, content: `${fb.text} ${left.length ? `Still undecided: ${left.join(", ")}. Decide the next one.` : "All aircraft decided."}` });
    }
    if (ids.every((id) => seen.has(id))) break;
  }
  return { calls, note };
}

// /api/sequence input hygiene: bounded body, whitelisted fields, no free text reaches the prompt.
const clean = (v) => String(v ?? "").replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, 140);
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? Math.round(v) : null);
async function readCapped(req, max) {
  const chunks = [];
  let n = 0;
  for await (const c of req) { n += c.length; if (n > max) return null; chunks.push(c); }
  return Buffer.concat(chunks).toString("utf8");
}
function sanitizeSequence(body) {
  const ID = /^[A-Z0-9-]{1,12}$/, TYPE = /^[A-Z0-9]{1,6}$/, FIXSET = ["MENLO", "DUMBA", "ARCHI", "BDEGA"], RWY = ["28L", "28R"];
  const STATES = ["inbound", "holding", "cleared", "final"], WAKES = { L: "light", M: "medium", H: "heavy", J: "super" };
  const inRange = (v, lo, hi) => typeof v === "number" && Number.isFinite(v) && v >= lo && v <= hi;
  if (!body || typeof body !== "object" || !inRange(body.now, 0, 1e10)) return null;
  if (!Array.isArray(body.queue) || body.queue.length > 16) return null;
  const queue = [];
  for (const q of body.queue) {
    if (!q || typeof q !== "object" || !ID.test(q.id) || !ID.test(q.callsign) || typeof q.type !== "string" || !TYPE.test(q.type)) return null;
    if (!(q.wake in WAKES) || ![null, undefined, "MED", "FUEL"].includes(q.flag)) return null;
    if (!inRange(q.eta_s, -7200, 7200) || !inRange(q.min_slot_s, -600, 7200)) return null;
    if (q.frozen != null && typeof q.frozen !== "boolean") return null;
    if (q.state != null && !STATES.includes(q.state)) return null;
    if (q.suggested_fix != null && !FIXSET.includes(q.suggested_fix)) return null;
    const slotted = q.slot_s != null || q.runway != null;
    if (slotted && (!inRange(q.slot_s, -600, 7200) || !RWY.includes(q.runway))) return null;
    queue.push({ id: q.id, callsign: q.callsign, type: q.type, wake: WAKES[q.wake], flag: q.flag || null, frozen: q.frozen === true,
      state: q.state || "inbound", eta_s: Math.round(q.eta_s), min_slot_s: Math.round(q.min_slot_s), suggested_fix: q.suggested_fix || "MENLO",
      ...(slotted ? { runway: q.runway, slot_s: Math.round(q.slot_s) } : {}) });
  }
  // runways: { "28L": { open, until? }, "28R": { open, until? } }
  const rw = body.runways;
  if (!rw || typeof rw !== "object" || Array.isArray(rw) || Object.keys(rw).some((k) => !RWY.includes(k))) return null;
  const runways = [];
  for (const id of RWY) {
    const r = rw[id];
    if (r == null) continue;
    if (typeof r !== "object" || typeof r.open !== "boolean" || (r.until != null && !inRange(r.until, 0, 7200))) return null;
    runways.push({ id, open: r.open, ...(r.until != null ? { closed_for_s: Math.round(r.until) } : {}) });
  }
  const free = {};
  if (body.free_slots != null) {
    if (typeof body.free_slots !== "object" || Object.keys(body.free_slots).some((k) => !RWY.includes(k))) return null;
    for (const id of RWY) {
      const arr = body.free_slots[id];
      if (arr == null) continue;
      if (!Array.isArray(arr) || arr.length > 16 || arr.some((x) => !inRange(x, 0, 7200))) return null;
      free[id] = arr.map(Math.round);
    }
  }
  return { queue, runways, now: Math.round(body.now), free };
}

async function readJson(req) {
  let body = "";
  for await (const chunk of req) body += chunk;
  return JSON.parse(body || "{}");
}
const send = (res, code, obj) => {
  res.statusCode = code;
  res.setHeader("content-type", "application/json");
  res.end(JSON.stringify(obj));
};

function voiceApi(env) {
  const openaiKey = env.OPENAI_API_KEY,
    crusoeKey = env.CRUSOE_API_KEY;
  const agent =
    crusoeKey && env.CRUSOE_BASE_URL
      ? {
          provider: "crusoe",
          url: env.CRUSOE_BASE_URL.replace(/\/$/, "") + "/chat/completions",
          key: crusoeKey,
          model: env.CRUSOE_MODEL || "openai/gpt-oss-120b",
        }
      : openaiKey
        ? {
            provider: "openai",
            url: "https://api.openai.com/v1/chat/completions",
            key: openaiKey,
            model: env.OPENAI_AGENT_MODEL || "gpt-4.1-mini",
          }
        : null;
  return {
    name: "uita-voice-api",
    configureServer(server) {
      // The integrated research shell is served by FastAPI in isolated staging.
      // Preserve the existing production Vite entry point until explicit cutover.
      server.middlewares.use((req, _res, next) => {
        if (req.url?.split('?')[0] === '/candidates/app.html')
          req.url = req.url.replace('/candidates/app.html', '/candidates/app-legacy.html');
        next();
      });
      // Hosted showcase: one shared password guards the pages and the keyed API.
      // Fail closed: a server bound beyond loopback needs a password unless the
      // operator explicitly opts into a public demo (DEMO_PUBLIC=1).
      const host = server.config.server.host;
      const hosted = host && host !== "127.0.0.1" && host !== "localhost";
      if (
        !env.DEMO_PASSWORD &&
        env.DEMO_PUBLIC !== "1" &&
        host &&
        host !== "127.0.0.1" &&
        host !== "localhost"
      )
        throw new Error("DEMO_PASSWORD is required when serving on " + host);
      if (env.DEMO_PASSWORD)
        server.middlewares.use((req, res, next) => {
          const [, b64] = (req.headers.authorization || "").split(" ");
          const pass = Buffer.from(
            Buffer.from(b64 || "", "base64")
              .toString()
              .split(":")
              .slice(1)
              .join(":"),
          );
          const want = Buffer.from(env.DEMO_PASSWORD);
          if (pass.length === want.length && timingSafeEqual(pass, want))
            return next();
          res.statusCode = 401;
          res.setHeader("www-authenticate", 'Basic realm="UITA"');
          res.end("UITA demo: password required");
        });
      // /vendor/* serves big libraries straight from node_modules: untransformed,
      // compressed once in memory and cacheable for a year. Vite's dev pipeline
      // otherwise ships Cesium's 25 MB raw with no-cache on every visit.
      const VENDOR = {
        "/vendor/cesium/": resolve("node_modules/cesium/Build/Cesium"),
        "/vendor/three/": resolve("node_modules/three186"),
        // Static demo assets: same compression and caching, so a second visit
        // (or a reload on stage) never re-downloads imagery and models.
        "/candidates/sfo-pack/": resolve("candidates/sfo-pack"),
        "/candidates/assets/": resolve("candidates/assets"),
        "/candidates/data/": resolve("candidates/data"),
        "/candidates/audio/": resolve("candidates/audio"),
      };
      const TYPES = {
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".wasm": "application/wasm",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".glb": "model/gltf-binary",
        ".ktx2": "image/ktx2",
        ".xml": "application/xml",
        ".geojson": "application/geo+json",
        ".mp3": "audio/mpeg",
      };
      const packed = new Map();
      server.middlewares.use((req, res, next) => {
        const prefix = Object.keys(VENDOR).find((k) => req.url.startsWith(k));
        if (!prefix || req.method !== "GET") return next();
        const rel = decodeURIComponent(
          req.url.slice(prefix.length).split("?")[0],
        );
        const file = resolve(VENDOR[prefix], rel);
        if (!file.startsWith(VENDOR[prefix]) || !existsSync(file))
          return next();
        const type = TYPES[extname(file)] || "application/octet-stream";
        const accept = String(req.headers["accept-encoding"] || "");
        const enc = /\bbr\b/.test(accept)
          ? "br"
          : /gzip/.test(accept)
            ? "gzip"
            : "";
        const textual = /text|json|svg|xml|wasm/.test(type);
        const key = file + "|" + (textual ? enc : "");
        if (!packed.has(key)) {
          const raw = readFileSync(file);
          packed.set(
            key,
            !textual || !enc
              ? raw
              : enc === "br"
                ? brotliCompressSync(raw, {
                    params: { [zc.BROTLI_PARAM_QUALITY]: 5 },
                  })
                : gzipSync(raw, { level: 6 }),
          );
        }
        res.setHeader("content-type", type);
        // Versioned libraries never change; demo assets might, so cache them a day.
        res.setHeader(
          "cache-control",
          prefix.startsWith("/vendor/")
            ? "public, max-age=31536000, immutable"
            : "public, max-age=86400",
        );
        res.setHeader("access-control-allow-origin", "*");
        if (textual && enc) {
          res.setHeader("content-encoding", enc);
          res.setHeader("vary", "accept-encoding");
        }
        res.end(packed.get(key));
      });
      // Public mode: per-visitor limits on anything that spends money or mutates
      // the shared simulation. Cached clips and GETs stay unlimited.
      if (hosted) {
        const hits = new Map();
        const LIMITS = {
          "/api/tts": 200,
          "/api/stt": 10,
          "/api/agent": 20,
          "/api/sequence": 40,
          "/uita/": 30,
        };
        server.middlewares.use((req, res, next) => {
          if (req.method === "GET") return next();
          const key = Object.keys(LIMITS).find((k) => req.url.startsWith(k));
          if (!key) return next();
          // Railway's edge appends the real client as the right-most hop; earlier
          // hops are client-supplied, so never trust them.
          const xff = String(req.headers["x-forwarded-for"] || "")
            .split(",")
            .map((v) => v.trim())
            .filter(Boolean);
          const ip = xff.pop() || req.socket.remoteAddress;
          const id = key + "|" + ip,
            now = Date.now(),
            recent = (hits.get(id) || []).filter((t) => now - t < 10 * 60e3),
            all = (hits.get(key) || []).filter((t) => now - t < 10 * 60e3);
          // Global cap per endpoint bounds spend even across many addresses.
          if (recent.length >= LIMITS[key] || all.length >= LIMITS[key] * 10)
            return send(res, 429, { error: "rate limited" });
          recent.push(now);
          all.push(now);
          hits.set(id, recent);
          hits.set(key, all);
          next();
        });
      }
      server.middlewares.use((req, res, next) => {
        // The app lives at the site root; old /candidates/app.html links still work.
        if (req.url === "/" || req.url.startsWith("/?")) {
          res.setHeader("content-type", "text/html; charset=utf-8");
          res.setHeader("cache-control", "no-cache");
          return res.end(readFileSync(resolve("candidates/app.html")));
        }
        next();
      });
      // /uita/* → the Uita FastAPI server. The mutation token is added here so it
      // never reaches the browser; GETs pass through unchanged.
      server.middlewares.use(async (req, res, next) => {
        if (!req.url.startsWith("/uita/")) return next();
        const backend = env.UITA_SERVER_URL ||
          (!hosted && req.url.startsWith("/uita/api/history/") ? "http://127.0.0.1:8001" : null);
        if (!backend)
          return send(res, 503, { error: "UITA_SERVER_URL not configured" });
        try {
          const headers = { accept: req.headers.accept || "application/json" };
          let body;
          if (req.method !== "GET") {
            // Sign only same-origin JSON calls to known endpoints; never paid learning jobs.
            const origin = req.headers.origin;
            const path = req.url.slice("/uita".length).split("?")[0];
            const allowed =
              /^\/api\/(control|disruptions|proposals|compare)$/.test(path) ||
              /^\/api\/proposals\/[\w-]+\/(verify|commit)$/.test(path);
            if (
              !allowed ||
              !origin ||
              new URL(origin).host !== req.headers.host ||
              !(req.headers["content-type"] || "").startsWith(
                "application/json",
              )
            )
              return send(res, 403, { error: "forbidden" });
            const chunks = [];
            for await (const c of req) chunks.push(c);
            body = Buffer.concat(chunks);
            headers["content-type"] =
              req.headers["content-type"] || "application/json";
            if (env.UITA_API_TOKEN)
              headers.authorization = "Bearer " + env.UITA_API_TOKEN;
          }
          const r = await fetch(
            backend.replace(/\/$/, "") +
              // The server now mounts recorded history under /uita itself.
              (req.url.startsWith("/uita/api/history/") ? req.url : req.url.slice("/uita".length)),
            { method: req.method, headers, body },
          );
          res.statusCode = r.status;
          res.setHeader(
            "content-type",
            r.headers.get("content-type") || "application/json",
          );
          return res.end(Buffer.from(await r.arrayBuffer()));
        } catch (e) {
          return send(res, 502, { error: String(e?.message || e) });
        }
      });
      server.middlewares.use(async (req, res, next) => {
        if (!req.url.startsWith("/api/")) return next();
        try {
          // Browser key for Google Map Tiles; restrict it by HTTP referrer in Cloud Console.
          if (req.url === "/api/maps-key")
            return send(res, env.GOOGLE_MAPS_API_KEY ? 200 : 404, {
              key: env.GOOGLE_MAPS_API_KEY || null,
            });
          if (req.url === "/api/config")
            return send(res, 200, {
              tts: Boolean(openaiKey),
              agent: agent && { provider: agent.provider, model: agent.model },
            });
          if (req.url === "/api/tts" && req.method === "POST") {
            if (!openaiKey)
              return send(res, 503, { error: "no OPENAI_API_KEY" });
            const { text, voice, instructions } = await readJson(req);
            // Baked clips live in candidates/audio so demos replay offline and identically.
            const id = createHash("sha1")
              .update(voice + "|" + text)
              .digest("hex")
              .slice(0, 16);
            const file = resolve("candidates/audio", id + ".mp3");
            if (existsSync(file)) {
              res.setHeader("content-type", "audio/mpeg");
              return res.end(readFileSync(file));
            }
            const r = await fetch("https://api.openai.com/v1/audio/speech", {
              method: "POST",
              headers: {
                authorization: `Bearer ${openaiKey}`,
                "content-type": "application/json",
              },
              body: JSON.stringify({
                model: env.OPENAI_TTS_MODEL || "gpt-4o-mini-tts",
                voice,
                input: text,
                instructions,
                response_format: "mp3",
              }),
            });
            if (!r.ok) return send(res, r.status, { error: await r.text() });
            const mp3 = Buffer.from(await r.arrayBuffer());
            mkdirSync(resolve("candidates/audio"), { recursive: true });
            writeFileSync(file, mp3);
            res.setHeader("content-type", "audio/mpeg");
            return res.end(mp3);
          }
          if (req.url === "/api/stt" && req.method === "POST") {
            if (!openaiKey)
              return send(res, 503, { error: "no OPENAI_API_KEY" });
            const chunks = [];
            for await (const c of req) chunks.push(c);
            const form = new FormData();
            form.append(
              "file",
              new Blob([Buffer.concat(chunks)], {
                type: req.headers["content-type"] || "audio/webm",
              }),
              "ptt.webm",
            );
            form.append("model", env.OPENAI_STT_MODEL || "gpt-4o-transcribe");
            form.append("language", "en");
            form.append(
              "prompt",
              "Pilot radio call to UITA tower. Callsigns like UITA one one two. Places: San Francisco, Marin, SFO, Oakland, Berkeley, Central, East approach, West approach. Phrases: request priority, low battery, medical, unable, weather, holding, say again.",
            );
            const r = await fetch(
              "https://api.openai.com/v1/audio/transcriptions",
              {
                method: "POST",
                headers: { authorization: `Bearer ${openaiKey}` },
                body: form,
              },
            );
            if (!r.ok) return send(res, r.status, { error: await r.text() });
            return send(res, 200, { text: (await r.json()).text });
          }
          if (req.url === "/api/sequence" && req.method === "POST") {
            // Same-origin JSON only, bounded body, whitelisted fields (public URL: this endpoint spends LLM credits).
            const origin = req.headers.origin;
            let sameOrigin = false;
            try { sameOrigin = !!origin && new URL(origin).host === req.headers.host; } catch {}
            if (!sameOrigin || !(req.headers["content-type"] || "").startsWith("application/json")) return send(res, 403, { error: "forbidden" });
            const raw = await readCapped(req, 32 * 1024);
            if (raw == null) return send(res, 413, { error: "body too large" });
            let parsed;
            try { parsed = JSON.parse(raw || "{}"); } catch { return send(res, 400, { error: "bad json" }); }
            const input = sanitizeSequence(parsed);
            if (!input) return send(res, 400, { error: "invalid sequence request" });
            const { queue, runways, free } = input;
            // Crusoe (Nemotron) first; if it gives no usable tool calls within ~8 s, OpenAI gpt-4.1-mini.
            const freeTxt = Object.entries(free).map(([r, a]) => `${r}: ${a.join(", ")}`).join("; ");
            const messages = [
              { role: "system", content: SEQ_SYSTEM },
              { role: "user", content: `Runways: ${JSON.stringify(runways)}\nLegal free slots in seconds from now (computed by the kernel; pick from these, one aircraft per slot, add 30 s after a heavy): ${freeTxt || "none"}\nArrival queue: ${JSON.stringify(queue)}` },
            ];
            const tries = [];
            if (crusoeKey && env.CRUSOE_BASE_URL)
              // Nemotron reasons for the whole token budget before any tool call; with thinking off it answers in ~1 s per turn.
              tries.push({ provider: "crusoe", url: env.CRUSOE_BASE_URL.replace(/\/$/, "") + "/chat/completions", key: crusoeKey, model: env.CRUSOE_MODEL || "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", timeoutMs: 8000, maxTokens: 1500, extra: { chat_template_kwargs: { enable_thinking: false } } });
            if (openaiKey)
              tries.push({ provider: "openai", url: "https://api.openai.com/v1/chat/completions", key: openaiKey, model: env.OPENAI_SEQUENCE_MODEL || "gpt-4.1-mini", timeoutMs: 12000, maxTokens: 900 });
            if (!tries.length) return send(res, 503, { error: "no agent key" });
            // Tool results tell the model where the next legal slot is, like a real scheduling tool would.
            const occupied = { "28L": [], "28R": [] };
            for (const q of queue || []) if (q.frozen && occupied[q.runway]) occupied[q.runway].push({ t: q.slot_s, heavy: q.wake === "heavy" });
            const closed = Object.fromEntries((runways || []).map((r) => [r.id, !r.open]));
            const nextLegal = (rwy) => occupied[rwy].reduce((m, o) => Math.max(m, o.t + (o.heavy ? 120 : 90)), 0);
            // Scheduling-tool feedback: obviously illegal slots are bounced back with the next legal time so the
            // model can correct itself; the page's kernel still verifies everything independently.
            const feedback = (name, a) => {
              const q = (queue || []).find((x) => x.id === a.id);
              if (!q) return { ok: false, text: `Unknown id ${a.id}.` };
              if (q.frozen) return { ok: false, text: `${a.id} is frozen on final; skip it.` };
              if (name !== "clear_to_land") return { ok: true, text: `Noted: ${a.id} holds at ${a.fix} for ${a.minutes} min.` };
              const t = Number(a.slot_time), occ = occupied[a.runway];
              if (!occ || closed[a.runway]) return { ok: false, text: `Rejected: ${a.runway} is closed. Use 28R >= ${nextLegal("28R")} s or hold.` };
              if (!(t >= q.min_slot_s)) return { ok: false, text: `Rejected: ${a.id} cannot land before ${q.min_slot_s} s.` };
              const heavy = q.wake === "heavy";
              const clash = occ.find((o) => Math.abs(o.t - t) < (o.t <= t ? (o.heavy ? 120 : 90) : heavy ? 120 : 90));
              if (clash) return { ok: false, text: `Rejected: ${a.runway} at ${t} s is too close to another slot at ${clash.t} s. Next legal ${a.runway} >= ${Math.max(nextLegal(a.runway), q.min_slot_s)} s. Propose again for ${a.id}.` };
              occ.push({ t, heavy });
              return { ok: true, text: `Noted: ${a.id} ${a.runway} at ${t} s. Next legal slot: 28R >= ${nextLegal("28R")} s${closed["28L"] ? ", 28L closed" : `, 28L >= ${nextLegal("28L")} s`}.` };
            };
            const fallbacks = [];
            for (const cfg of tries) {
              const started = Date.now();
              try {
                const out = await chatTools(cfg, messages, SEQ_TOOLS, (queue || []).filter((q) => !q.frozen).map((q) => q.id), feedback);
                if (out.calls.length)
                  return send(res, 200, { decisions: out.calls.map((c) => ({ name: c.name, args: { ...c.args, reason: clean(c.args.reason) } })), note: clean(out.note), provider: cfg.provider, model: cfg.model, ms: Date.now() - started, fallbacks, partial: out.calls.length < (queue || []).filter((q) => !q.frozen).length });
                fallbacks.push(`${cfg.provider}: no tool calls (${Date.now() - started} ms)`);
              } catch (e) {
                fallbacks.push(`${cfg.provider}: ${String(e?.message || e).slice(0, 120)}`);
              }
            }
            return send(res, 502, { error: "no usable decisions", fallbacks });
          }
          if (req.url === "/api/agent" && req.method === "POST") {
            if (!agent) return send(res, 503, { error: "no agent key" });
            const { transcript, state } = await readJson(req);
            const started = Date.now();
            const r = await fetch(agent.url, {
              method: "POST",
              headers: {
                authorization: `Bearer ${agent.key}`,
                "content-type": "application/json",
              },
              body: JSON.stringify({
                model: agent.model,
                messages: [
                  { role: "system", content: SYSTEM },
                  {
                    role: "user",
                    content: `Sector state:\n${JSON.stringify(state)}\n\nPilot transmission: "${transcript}"`,
                  },
                ],
                tools: TOOLS,
                tool_choice: "required",
                temperature: 0,
              }),
            });
            if (!r.ok) return send(res, r.status, { error: await r.text() });
            const data = await r.json(),
              call = data.choices?.[0]?.message?.tool_calls?.[0];
            if (!call) return send(res, 502, { error: "no tool call", data });
            return send(res, 200, {
              action: call.function.name,
              args: JSON.parse(call.function.arguments || "{}"),
              provider: agent.provider,
              model: agent.model,
              ms: Date.now() - started,
            });
          }
          send(res, 404, { error: "unknown endpoint" });
        } catch (e) {
          send(res, 500, { error: String(e?.message || e) });
        }
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [voiceApi(env)],
    // Keep generated media quiet, but watch replay source so Vite invalidates
    // transformed modules after edits (ignoring all candidates served stale JS).
    server: {
      watch: { ignored: ["**/candidates/audio/**", "**/candidates/assets/**", "**/candidates/sfo-pack/**", "**/candidates/data/**"] },
      // Only the hosted showcase (password-gated) accepts its public hostnames.
      allowedHosts: env.DEMO_HOSTS ? env.DEMO_HOSTS.split(",") : [],
    },
  };
});
