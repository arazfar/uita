// Half-duplex radio: one transmission at a time, squelch click before each,
// spoken by OpenAI TTS through a VHF-style filter when the server has a key,
// otherwise by the browser's speech synthesis.

let ctx;
const audio = () => (ctx ??= new AudioContext());

function squelch(duration = 0.09) {
  const ac = audio(),
    n = Math.floor(ac.sampleRate * duration),
    buf = ac.createBuffer(1, n, ac.sampleRate),
    d = buf.getChannelData(0);
  for (let i = 0; i < n; i++)
    d[i] = (Math.random() * 2 - 1) * (1 - i / n) * 0.35;
  const src = ac.createBufferSource(),
    bp = ac.createBiquadFilter();
  bp.type = "bandpass";
  bp.frequency.value = 2200;
  src.buffer = buf;
  src.connect(bp).connect(ac.destination);
  src.start();
  return new Promise((r) => setTimeout(r, duration * 1000 + 40));
}

// VHF voice band: ~300–3400 Hz with light saturation.
function radioChain(ac) {
  const hp = ac.createBiquadFilter(),
    lp = ac.createBiquadFilter(),
    shaper = ac.createWaveShaper(),
    gain = ac.createGain();
  hp.type = "highpass";
  hp.frequency.value = 320;
  lp.type = "lowpass";
  lp.frequency.value = 3200;
  const curve = new Float32Array(1024);
  for (let i = 0; i < 1024; i++) {
    const x = (i / 1023) * 2 - 1;
    curve[i] = Math.tanh(2.2 * x);
  }
  shaper.curve = curve;
  gain.gain.value = 0.9;
  hp.connect(lp).connect(shaper).connect(gain).connect(ac.destination);
  return hp;
}

const OPENAI_VOICES = {
  atc: "cedar",
  pilot: ["marin", "ash", "coral", "verse", "sage", "ballad"],
};
const pick = (list, key) =>
  list[[...key].reduce((s, c) => s + c.charCodeAt(0), 0) % list.length];

// Fetched clips are cached by speaker+text; queued lines are fetched ahead of
// their turn so TTS latency (~3 s) overlaps the transmission before them.
const clips = new Map();
function clip(text, speaker, key) {
  const voice =
    speaker === "atc" ? OPENAI_VOICES.atc : pick(OPENAI_VOICES.pilot, key);
  const id = voice + "|" + text;
  if (!clips.has(id))
    clips.set(
      id,
      fetch("/api/tts", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          text,
          voice,
          instructions:
            speaker === "atc"
              ? "Calm, clipped air traffic controller on a busy frequency. Brisk, even pace."
              : "Pilot reading back on a radio. Quick, matter-of-fact.",
        }),
      }).then((res) => {
        if (!res.ok) throw new Error("tts " + res.status);
        return res.arrayBuffer();
      }),
    );
  const p = clips.get(id);
  p.catch(() => clips.delete(id));
  return p;
}

async function speakOpenAI(text, speaker, key) {
  const ac = audio(),
    buf = await ac.decodeAudioData((await clip(text, speaker, key)).slice(0)),
    src = ac.createBufferSource();
  src.buffer = buf;
  src.connect(radioChain(ac));
  return new Promise((r) => {
    src.onended = r;
    src.start();
  });
}

function speakBrowser(text, speaker, key) {
  const synth = window.speechSynthesis;
  if (!synth) return new Promise((r) => setTimeout(r, 60 * text.length));
  const voices = synth.getVoices().filter((v) => v.lang.startsWith("en"));
  const u = new SpeechSynthesisUtterance(text);
  if (voices.length)
    u.voice =
      speaker === "atc"
        ? voices.find((v) =>
            /daniel|alex|google uk english male/i.test(v.name),
          ) || voices[0]
        : pick(voices, key);
  u.rate = speaker === "atc" ? 1.12 : 1.18;
  u.pitch = speaker === "atc" ? 0.95 : 0.85 + ([...key].length % 4) * 0.1;
  return new Promise((r) => {
    u.onend = r;
    u.onerror = r;
    synth.speak(u);
  });
}

export function createRadio({ onChange }) {
  const queue = [];
  let busy = false,
    muted = false,
    openai = false,
    epoch = 0;
  async function pump() {
    if (busy || !queue.length) return;
    busy = true;
    const tx = queue.shift(),
      mine = epoch;
    tx.state = "live";
    onChange?.(tx);
    try {
      if (!muted) {
        await squelch();
        await (openai
          ? speakOpenAI(tx.text, tx.speaker, tx.key).catch(() =>
              speakBrowser(tx.text, tx.speaker, tx.key),
            )
          : speakBrowser(tx.text, tx.speaker, tx.key));
        await squelch(0.06);
      } else await new Promise((r) => setTimeout(r, 400));
    } finally {
      busy = false;
      if (mine === epoch) {
        tx.state = "done";
        onChange?.(tx);
        tx.resolve();
      }
      pump();
    }
  }
  return {
    // Resolves when the transmission has finished playing.
    say(speaker, text, key = speaker) {
      return new Promise((resolve) => {
        const tx = { speaker, text, key, state: "queued", resolve };
        queue.push(tx);
        if (openai && !muted) clip(text, speaker, key).catch(() => {});
        onChange?.(tx);
        pump();
      });
    },
    prefetch(speaker, text, key = speaker) {
      if (openai && !muted) clip(text, speaker, key).catch(() => {});
    },
    get backlog() {
      return queue.length + (busy ? 1 : 0);
    },
    flush() {
      epoch++;
      for (const tx of queue.splice(0)) tx.resolve();
      window.speechSynthesis?.cancel();
    },
    setMuted(v) {
      muted = v;
      if (v) window.speechSynthesis?.cancel();
    },
    setOpenAI(v) {
      openai = v;
    },
    unlock() {
      audio().resume();
    },
  };
}

// Push-to-talk capture. Records the mic and transcribes on the dev server
// (gpt-4o-transcribe); falls back to the browser recognizer without a key.
export function createMic({ onText, onState, server }) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (server && navigator.mediaDevices?.getUserMedia) {
    let rec,
      chunks = [],
      stream;
    return {
      async start() {
        onState?.("hearing", "");
        stream ??= await navigator.mediaDevices.getUserMedia({ audio: true });
        chunks = [];
        rec = new MediaRecorder(stream);
        rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
        rec.onstop = async () => {
          onState?.("transcribing", "");
          const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
          try {
            const r = await fetch("/api/stt", {
              method: "POST",
              headers: { "content-type": blob.type },
              body: blob,
            });
            const { text, error } = await r.json();
            onState?.("idle", text || "");
            if (text?.trim()) onText(text.trim());
            else if (error) console.warn(error);
          } catch (e) {
            onState?.("idle", "");
            console.warn(e);
          }
        };
        rec.start();
      },
      stop() {
        if (rec?.state === "recording") rec.stop();
      },
    };
  }
  if (!SR) return null;
  const rec = new SR();
  rec.lang = "en-US";
  rec.interimResults = true;
  rec.continuous = false;
  let final = "";
  rec.onresult = (e) => {
    final = [...e.results].map((r) => r[0].transcript).join(" ");
    onState?.("hearing", final);
  };
  rec.onend = () => {
    onState?.("idle", final);
    if (final.trim()) onText(final.trim());
    final = "";
  };
  rec.onerror = () => onState?.("idle", "");
  return {
    start() {
      final = "";
      onState?.("hearing", "");
      try {
        rec.start();
      } catch {}
    },
    stop() {
      try {
        rec.stop();
      } catch {}
    },
  };
}
