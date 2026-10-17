import { createHash, timingSafeEqual } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
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

const SYSTEM = `You are the SkyFlow sector controller agent for a simulated San Francisco Bay urban air mobility sector.
A deterministic scheduler owns separation and reservations; you never invent clearances.
Read the pilot transmission, identify the flight by callsign (SkyFlow 112 = SF-112), and call exactly one tool.
Only act on flights listed in the sector state. Prefer grant_priority for medical, battery or emergency calls,
reroute for weather or "unable" reports, delay_departure for pilots asking to wait, otherwise say_again.`;

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
    name: "skyflow-voice-api",
    configureServer(server) {
      // Hosted showcase: one shared password guards the pages and the keyed API.
      // Fail closed: a server bound beyond loopback must have a password.
      const host = server.config.server.host;
      if (
        !env.DEMO_PASSWORD &&
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
          res.setHeader("www-authenticate", 'Basic realm="SkyFlow"');
          res.end("SkyFlow demo: password required");
        });
      server.middlewares.use((req, res, next) => {
        if (req.url === "/" && env.DEMO_PASSWORD) {
          res.statusCode = 302;
          res.setHeader("location", "/candidates/app.html");
          return res.end();
        }
        next();
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
              "Pilot radio call to SkyFlow tower. Callsigns like SkyFlow one one two. Places: San Francisco, Marin, SFO, Oakland, Berkeley, Central, East approach, West approach. Phrases: request priority, low battery, medical, unable, weather, holding, say again.",
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
    // Candidate pages are static and baked audio lands in candidates/audio; don't
    // full-reload open demos every time a clip or another candidate is written.
    server: {
      watch: { ignored: ["**/candidates/**"] },
      // Only the hosted showcase (password-gated) accepts its public hostnames.
      allowedHosts: env.DEMO_HOSTS ? env.DEMO_HOSTS.split(",") : [],
    },
  };
});
