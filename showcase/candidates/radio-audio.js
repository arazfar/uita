// Shared radio voice for UITA candidates.
//   <script src="radio-audio.js"></script>
//   SkyRadio.say("UITA one zero five, negative...", "atc")      // controller
//   SkyRadio.say("Via Whiskey, Echo...", "pilot", "UTA105")         // pilot, voice per callsign
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
  // Radio key click + short band-limited static that decays, instead of raw
  // white noise (which read as a hi-hat). `open` = key-down, else key-up tail.
  function squelch(d = 0.08, open = true) {
    const now = ac.currentTime, sr = ac.sampleRate;
    // Click: a few ms of a damped 1.1 kHz sine, like a PTT relay.
    const click = ac.createOscillator(), cg = ac.createGain();
    click.frequency.value = open ? 1100 : 900;
    cg.gain.setValueAtTime(0.0001, now);
    cg.gain.exponentialRampToValueAtTime(0.12, now + 0.002);
    cg.gain.exponentialRampToValueAtTime(0.0001, now + 0.018);
    click.connect(cg).connect(ac.destination);
    click.start(now);
    click.stop(now + 0.03);
    // Static: brown-ish noise through a 700–2400 Hz band, soft exponential decay.
    const len = Math.floor(sr * (open ? 0.12 : 0.22)),
      b = ac.createBuffer(1, len, sr),
      x = b.getChannelData(0);
    let last = 0;
    for (let i = 0; i < len; i++) {
      last = (last + 0.06 * (Math.random() * 2 - 1)) / 1.06;
      x[i] = last * 3.2;
    }
    const n = ac.createBufferSource(), hp = ac.createBiquadFilter(), lp = ac.createBiquadFilter(), ng = ac.createGain();
    hp.type = "highpass"; hp.frequency.value = 700;
    lp.type = "lowpass"; lp.frequency.value = 2400;
    n.buffer = b;
    ng.gain.setValueAtTime(0.0001, now + 0.004);
    ng.gain.exponentialRampToValueAtTime(open ? 0.05 : 0.07, now + 0.012);
    ng.gain.exponentialRampToValueAtTime(0.0001, now + len / sr);
    n.connect(hp).connect(lp).connect(ng).connect(ac.destination);
    n.start(now + 0.004);
    return new Promise((r) => setTimeout(r, (open ? 60 : 40)));
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
    await squelch(0.05, false);
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
