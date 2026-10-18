/** Quiet procedural cab acoustics. Coordinates are world metres, y up.
 * These are illustrative engine sounds, not measured aircraft recordings.
 * This owns a separate AudioContext so muting ambience cannot alter radio audio.
 */
export function createTowerSpatialAudio() {
  const voices = new Map();
  let context, master, room, noiseBuffer, analyser, samples;
  let enabled = false,
    paused = false,
    disposed = false,
    pageHidden = false;
  let nextUpdate = 0,
    error = null;
  const clamp = (n, min, max) => Math.max(min, Math.min(max, n));
  const finitePoint = (p) => p && [p.x, p.y, p.z].every(Number.isFinite);
  const active = () =>
    enabled && !paused && !document.hidden && !pageHidden && !disposed;
  const smooth = (param, value, seconds = 0.15) => {
    param.setTargetAtTime(value, context.currentTime, seconds);
  };

  function noise() {
    const source = context.createBufferSource();
    source.buffer = noiseBuffer;
    source.loop = true;
    return source;
  }

  function initialize() {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
      error = "Web Audio is unavailable";
      return false;
    }
    context = new AudioContextClass();
    master = context.createGain();
    master.gain.value = 0;
    // The limiter only handles this module; radio remains on its existing path.
    const limiter = context.createDynamicsCompressor();
    limiter.threshold.value = -18;
    limiter.ratio.value = 4;
    analyser = context.createAnalyser();
    analyser.fftSize = 512;
    samples = new Float32Array(analyser.fftSize);
    master.connect(limiter).connect(analyser).connect(context.destination);
    noiseBuffer = context.createBuffer(
      1,
      context.sampleRate * 3,
      context.sampleRate,
    );
    const data = noiseBuffer.getChannelData(0);
    let low = 0;
    for (let i = 0; i < data.length; i++) {
      low = (low + 0.035 * (Math.random() * 2 - 1)) / 1.035;
      data[i] = low * 3;
    }
    const ventilation = noise(),
      filter = context.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.value = 260;
    room = context.createGain();
    room.gain.value = 0.012;
    ventilation.connect(filter).connect(room).connect(master);
    ventilation.start();
    return true;
  }

  function sync() {
    if (disposed) return;
    // Creating or resuming runs directly from the existing sound-button gesture.
    if (active()) {
      try {
        if (!context && !initialize()) return;
        smooth(master.gain, 0.6);
        if (context.state === "suspended") {
          context
            .resume()
            .then(() => {
              if (!active()) void context.suspend().catch(() => {});
            })
            .catch((cause) => {
              error = String(cause.message || cause);
            });
        }
      } catch (cause) {
        error = String(cause.message || cause);
      }
    } else if (context && context.state !== "closed") {
      master.gain.cancelScheduledValues(context.currentTime);
      master.gain.setValueAtTime(0, context.currentTime);
      void context.suspend().catch(() => {});
    }
  }

  function makeVoice() {
    const roar = noise(),
      fan = context.createOscillator();
    const fanGain = context.createGain(),
      envelope = context.createGain();
    const glass = context.createBiquadFilter(),
      panner = context.createPanner();
    fan.type = "sine";
    fanGain.gain.value = 0.12;
    envelope.gain.value = 0;
    glass.type = "lowpass";
    glass.Q.value = 0.5;
    panner.panningModel = "HRTF";
    panner.distanceModel = "inverse";
    panner.refDistance = 100;
    panner.maxDistance = 8000;
    panner.rolloffFactor = 1.2;
    // Exhaust-facing radiation is stronger; the broad cone avoids sharp pans.
    panner.coneInnerAngle = 100;
    panner.coneOuterAngle = 280;
    panner.coneOuterGain = 0.55;
    roar.connect(envelope);
    fan.connect(fanGain).connect(envelope);
    envelope.connect(glass).connect(panner).connect(master);
    roar.start(context.currentTime, Math.random() * noiseBuffer.duration);
    fan.start();
    return {
      roar,
      fan,
      fanGain,
      envelope,
      glass,
      panner,
      distance: 0,
      powerKnown: false,
    };
  }

  function stopVoice(voice) {
    voice.roar.stop();
    voice.fan.stop();
    for (const node of [
      voice.roar,
      voice.fan,
      voice.fanGain,
      voice.envelope,
      voice.glass,
      voice.panner,
    ])
      node.disconnect();
  }

  function position(node, x, y, z) {
    if (node.positionX) {
      smooth(node.positionX, x, 0.06);
      smooth(node.positionY, y, 0.06);
      smooth(node.positionZ, z, 0.06);
    } else node.setPosition(x, y, z);
  }

  function orientation(panner, x, y, z) {
    if (panner.orientationX) {
      smooth(panner.orientationX, x, 0.06);
      smooth(panner.orientationY, y, 0.06);
      smooth(panner.orientationZ, z, 0.06);
    } else panner.setOrientation(x, y, z);
  }

  function update({ camera, actors }) {
    if (!context || !active() || context.state !== "running") return;
    // AudioParams interpolate between 10 Hz updates. There is no second frame loop.
    if (context.currentTime < nextUpdate) return;
    nextUpdate = context.currentTime + 0.1;
    camera.updateWorldMatrix(true, false);
    const m = camera.matrixWorld.elements,
      listener = context.listener;
    position(listener, m[12], m[13], m[14]);
    if (listener.forwardX) {
      for (const [name, value] of [
        ["forwardX", -m[8]],
        ["forwardY", -m[9]],
        ["forwardZ", -m[10]],
        ["upX", m[4]],
        ["upY", m[5]],
        ["upZ", m[6]],
      ])
        smooth(listener[name], value, 0.06);
    } else listener.setOrientation(-m[8], -m[9], -m[10], m[4], m[5], m[6]);

    // Bound the graph for busy backend feeds. Never alter or derive aircraft motion.
    const nearest = actors
      .filter((a) => a.vis && finitePoint(a.pos))
      .map((a) => ({
        a,
        distance: Math.hypot(a.pos.x - m[12], a.pos.y - m[13], a.pos.z - m[14]),
      }))
      .filter(({ distance }) => distance < 8000)
      .sort((a, b) => a.distance - b.distance)
      .slice(0, 6);
    const selected = new Set(nearest.map(({ a }) => a));
    for (const [actor, voice] of voices) {
      if (!selected.has(actor)) {
        stopVoice(voice);
        voices.delete(actor);
      }
    }
    for (const { a, distance } of nearest) {
      let voice = voices.get(a);
      if (!voice) {
        voice = makeVoice();
        voices.set(a, voice);
      }
      const thrust = a.flightState?.thrust,
        maxThrust = a.flight?.profile?.thrust;
      const known =
        Number.isFinite(thrust) && Number.isFinite(maxThrust) && maxThrust > 0;
      // Missing backend thrust stays an intentionally quiet generic ambience.
      // Speed, callsign, or altitude do not establish an engine's power setting.
      const power = known ? clamp(thrust / maxThrust, 0, 1) : 0.12;
      voice.distance = distance;
      voice.powerKnown = known;
      position(voice.panner, a.pos.x, a.pos.y, a.pos.z);
      if (finitePoint(a.dir))
        orientation(voice.panner, -a.dir.x, -a.dir.y, -a.dir.z);
      smooth(voice.envelope.gain, known ? 0.12 + power * 0.5 : 0.08, 0.4);
      smooth(voice.fan.frequency, 48 + power * 72, 0.5);
      // Closed cab glass removes high-frequency detail; distance adds air absorption.
      smooth(
        voice.glass.frequency,
        clamp(720 - distance * 0.055, 220, 720),
        0.4,
      );
    }
  }

  function visibility() {
    sync();
  }
  function pagehide() {
    pageHidden = true;
    sync();
  }
  function pageshow() {
    pageHidden = false;
    sync();
  }
  document.addEventListener("visibilitychange", visibility);
  window.addEventListener("pagehide", pagehide);
  window.addEventListener("pageshow", pageshow);

  return {
    setEnabled(value) {
      enabled = Boolean(value);
      if (!enabled || disposed) {
        sync();
        return;
      }
      try {
        // Unlock even while playback is paused: a later host playhead message is
        // not a user gesture. Keep the master silent until playback is active.
        if (!context && !initialize()) return;
        if (!active()) {
          master.gain.cancelScheduledValues(context.currentTime);
          master.gain.setValueAtTime(0, context.currentTime);
        }
        context
          .resume()
          .then(() => {
            // Re-read current intent after resume; pause/mute may have changed
            // while the browser processed its audio-context state transition.
            sync();
          })
          .catch((cause) => {
            error = String(cause.message || cause);
          });
        if (active()) smooth(master.gain, 0.6);
      } catch (cause) {
        error = String(cause.message || cause);
      }
    },
    setPaused(value) {
      const next = Boolean(value);
      if (next !== paused) {
        paused = next;
        sync();
      }
    },
    update,
    getSnapshot() {
      let outputRms = 0;
      // A suspended context can retain its last analyser window. It emits no audio.
      if (active() && context?.state === "running") {
        analyser.getFloatTimeDomainData(samples);
        outputRms = Math.sqrt(
          samples.reduce((sum, value) => sum + value * value, 0) /
            samples.length,
        );
      }
      return {
        enabled,
        paused,
        active: active() && context?.state === "running",
        state: context?.state || "uninitialized",
        error,
        outputRms,
        voices: [...voices].map(([actor, voice]) => ({
          id: actor.cs,
          distance: voice.distance,
          powerKnown: voice.powerKnown,
        })),
      };
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("pagehide", pagehide);
      window.removeEventListener("pageshow", pageshow);
      for (const voice of voices.values()) stopVoice(voice);
      voices.clear();
      if (context && context.state !== "closed")
        void context.close().catch(() => {});
    },
  };
}
