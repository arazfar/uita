// Shared radio voice for UITA candidates.
//   <script src="radio-audio.js"></script>
//   SkyRadio.say("SkyFlow one zero five, negative...", "atc")      // controller
//   SkyRadio.say("Via Whiskey, Echo...", "pilot", "SKF105")         // pilot, voice per callsign
//   SkyRadio.prefetch(lines)  // [{text, speaker, key}] — bake/warm clips up front
// Clips come from the dev server's /api/tts (OpenAI gpt-4o-mini-tts), cached on disk in
// candidates/audio/, played through a VHF band-pass with squelch, one at a time.
// Browsers block audio until a click: SkyRadio shows a "Sound on" gate on first load.
(() => {
  const VOICES = { atc: "cedar", pilot: ["marin", "ash", "coral", "verse", "sage", "ballad"] };
  const pick = (k) =>
    VOICES.pilot[[...String(k)].reduce((s, c) => s + c.charCodeAt(0), 0) % VOICES.pilot.length];
  const STYLE = {
    atc: "Calm, clipped air traffic controller on a busy frequency. Brisk, even pace.",
    pilot: "Pilot reading back on a radio. Quick, matter-of-fact.",
  };
  let ac, enabled = false, chain = Promise.resolve(), onTx = () => {}, current = null;
  const cache = new Map();
  const voiceOf = (speaker, key) => (speaker === "atc" ? VOICES.atc : pick(key || speaker));
  function clip(text, speaker, key) {
    const voice = voiceOf(speaker, key), id = voice + "|" + text;
    if (!cache.has(id))
      cache.set(
        id,
        fetch("/api/tts", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ text, voice, instructions: STYLE[speaker] || STYLE.pilot }),
        }).then((r) => {
          if (!r.ok) throw new Error("tts " + r.status);
          return r.arrayBuffer();
        }),
      );
    const p = cache.get(id);
    p.catch(() => cache.delete(id));
    return p;
  }
  function out() {
    const hp = ac.createBiquadFilter(), lp = ac.createBiquadFilter(), sh = ac.createWaveShaper();
    hp.type = "highpass"; hp.frequency.value = 320;
    lp.type = "lowpass"; lp.frequency.value = 3200;
    const c = new Float32Array(1024);
    for (let i = 0; i < 1024; i++) c[i] = Math.tanh(2.2 * ((i / 1023) * 2 - 1));
    sh.curve = c;
    hp.connect(lp).connect(sh).connect(ac.destination);
    return hp;
  }
  function squelch(d = 0.08) {
    const n = Math.floor(ac.sampleRate * d), b = ac.createBuffer(1, n, ac.sampleRate), x = b.getChannelData(0);
    for (let i = 0; i < n; i++) x[i] = (Math.random() * 2 - 1) * (1 - i / n) * 0.3;
    const s = ac.createBufferSource(); s.buffer = b; s.connect(ac.destination); s.start();
    return new Promise((r) => setTimeout(r, d * 1000 + 30));
  }
  async function play(text, speaker, key) {
    const data = await clip(text, speaker, key);
    if (!enabled) return;
    onTx({ text, speaker, key, live: true });
    await squelch();
    const buf = await ac.decodeAudioData(data.slice(0)), src = ac.createBufferSource();
    src.buffer = buf; src.connect(out());
    current = src;
    // Never let a suspended AudioContext freeze a demo clock.
    await new Promise((r) => {
      src.onended = r;
      setTimeout(r, buf.duration * 1000 + 1200);
      src.start();
    });
    await squelch(0.05);
    onTx({ text, speaker, key, live: false });
  }
  const SkyRadio = {
    // Queue on the single frequency. Resolves when this line has finished playing.
    say(text, speaker = "atc", key) {
      clip(text, speaker, key).catch(() => {});
      const cap = new Promise((r) => setTimeout(r, 4000 + 450 * text.split(" ").length));
      const run = chain
        .then(() => (enabled ? Promise.race([play(text, speaker, key), cap]) : null))
        .catch(() => {});
      chain = run;
      return run;
    },
    prefetch(lines) {
      for (const l of lines) clip(l.text, l.speaker || "atc", l.key).catch(() => {});
    },
    flush() { chain = Promise.resolve(); },
    // Cut the line on air (pause/restart) and drop anything queued.
    stop() {
      chain = Promise.resolve();
      try { current?.stop(); } catch {}
      current = null;
    },
    get enabled() { return enabled; },
    enable() {
      ac ??= new AudioContext();
      ac.resume();
      enabled = true;
      document.getElementById("skyradio-gate")?.remove();
      document.dispatchEvent(new Event("skyradio:enabled"));
    },
    disable() { enabled = false; },
    onTransmit(fn) { onTx = fn; },
  };
  window.SkyRadio = SkyRadio;
  addEventListener("DOMContentLoaded", () => {
    const g = document.createElement("button");
    g.id = "skyradio-gate";
    g.textContent = "🔊 Sound on — enter the control room";
    Object.assign(g.style, {
      position: "fixed", left: "50%", bottom: "28px", transform: "translateX(-50%)", zIndex: 99999,
      font: "600 14px Inter, system-ui, sans-serif", padding: "12px 20px", borderRadius: "999px",
      border: "1px solid #4aa3c7", background: "#0f2530", color: "#e6f4fa", cursor: "pointer",
      boxShadow: "0 8px 30px #0008",
    });
    g.onclick = () => SkyRadio.enable();
    document.body.append(g);
    addEventListener("keydown", (e) => e.key === "s" && !enabled && SkyRadio.enable(), { once: false });
  });
})();
