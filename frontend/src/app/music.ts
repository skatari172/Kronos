/**
 * Original ambient soundtrack, composed live with the Web Audio API: soft,
 * sparse piano over slow chords, lots of space, warm reverb. Five tracks with
 * their own key, tempo and mood play in a loop with a pause between them; each
 * performance is different, so it never repeats exactly. No audio files, no
 * licences: everything is synthesised in the browser.
 */
import { create } from "zustand";

type Track = {
  name: string;
  /** MIDI note of the key's root (60 = middle C). */
  root: number;
  /** Scale as semitones above the root. */
  scale: number[];
  /** Seconds per beat; a bar is four beats. */
  beat: number;
  /** Chord roots as scale degrees, one per bar, cycled. */
  chords: number[];
  /** Chance a beat gets a melody note (sparse is calmer). */
  density: number;
  /** Melody register, in octaves above the root. */
  octave: number;
  /** Seconds the track plays before moving on. */
  length: number;
};

const MAJOR = [0, 2, 4, 5, 7, 9, 11];
const MINOR = [0, 2, 3, 5, 7, 8, 10];
const LYDIAN = [0, 2, 4, 6, 7, 9, 11];
const DORIAN = [0, 2, 3, 5, 7, 9, 10];

export const TRACKS: Track[] = [
  {
    name: "Dawn over Oakhaven",
    root: 55,
    scale: MAJOR,
    beat: 0.95,
    chords: [0, 4, 5, 3],
    density: 0.32,
    octave: 1,
    length: 170,
  },
  {
    name: "Hearth",
    root: 53,
    scale: MAJOR,
    beat: 1.1,
    chords: [0, 3, 0, 4],
    density: 0.26,
    octave: 1,
    length: 160,
  },
  {
    name: "Meadow",
    root: 57,
    scale: LYDIAN,
    beat: 0.85,
    chords: [0, 1, 0, 4],
    density: 0.38,
    octave: 1,
    length: 180,
  },
  {
    name: "Lanterns",
    root: 52,
    scale: DORIAN,
    beat: 1.05,
    chords: [0, 3, 6, 4],
    density: 0.28,
    octave: 1,
    length: 165,
  },
  {
    name: "Rainfall",
    root: 50,
    scale: MINOR,
    beat: 1.2,
    chords: [0, 5, 3, 4],
    density: 0.24,
    octave: 2,
    length: 175,
  },
];

const MUTE_KEY = "kronos.music.muted";
/** Silence between tracks, in seconds. */
const BREATH = 6;

function loadMuted() {
  try {
    return localStorage.getItem(MUTE_KEY) === "1";
  } catch {
    return false;
  }
}

type Music = {
  muted: boolean;
  /** Playing (audio running and not muted). */
  playing: boolean;
  track: number;
  toggleMute: () => void;
  next: () => void;
  /** Start after the first user gesture (browsers block audio before one). */
  wake: () => void;
  /** Dip the music while a villager speaks. */
  duck: (on: boolean) => void;
};

let engine: Engine | null = null;
/** How many open conversations want the music under their voices. */
let ducks = 0;

// A code reload (dev) must not leave the old engine playing on beside a new one:
// close it, and any engine left over from a previous copy of this module.
const shared = globalThis as { __kronosMusic?: { close: () => void } };
shared.__kronosMusic?.close();
shared.__kronosMusic = { close: () => engine?.close() };
import.meta.hot?.dispose(() => engine?.close());

export const useMusic = create<Music>((set, get) => ({
  muted: loadMuted(),
  playing: false,
  track: Math.floor(Math.random() * TRACKS.length),
  toggleMute: () => {
    const muted = !get().muted;
    try {
      localStorage.setItem(MUTE_KEY, muted ? "1" : "0");
    } catch {
      /* Remembering is a convenience only. */
    }
    set({ muted });
    if (muted) {
      engine?.fade(0);
      // Stop the audio clock once faded, so a muted page costs nothing.
      setTimeout(() => get().muted && engine?.suspend(), 1500);
    } else {
      get().wake();
      engine?.fade(1);
    }
    set({ playing: !muted && !!engine });
  },
  next: () => {
    const track = (get().track + 1) % TRACKS.length;
    set({ track });
    engine?.start(track);
    if (!get().muted) get().wake();
  },
  duck: (on) => {
    ducks = Math.max(0, ducks + (on ? 1 : -1));
    engine?.duckForVoice(ducks > 0);
  },
  wake: () => {
    if (get().muted) return;
    if (!engine) {
      try {
        engine = new Engine(
          (track) => set({ track }),
          // "Playing" means sound is really coming out, not just scheduled.
          (running) => set({ playing: running && !get().muted }),
        );
        // A conversation may already be open when the music first starts.
        engine.duckForVoice(ducks > 0);
      } catch {
        return; // No Web Audio here: stay silent.
      }
      engine.start(get().track);
    }
    void engine.resume();
    engine.fade(1);
  },
}));

const freq = (midi: number) => 440 * 2 ** ((midi - 69) / 12);

class Engine {
  private ctx: AudioContext;
  private master: GainNode;
  private wet: GainNode;
  private voiceDuck!: GainNode;
  private timer = 0;
  private track = 0;
  private startedAt = 0;
  private nextBeat = 0;
  private beatIndex = 0;
  private lastNote = 0;
  private resting = 0;

  constructor(
    private onTrack: (track: number) => void,
    onRunning: (running: boolean) => void,
  ) {
    this.ctx = new AudioContext();
    this.ctx.onstatechange = () => onRunning(this.ctx.state === "running");
    onRunning(this.ctx.state === "running");
    this.master = this.ctx.createGain();
    this.master.gain.value = 0;
    // Warm, soft top end.
    const tone = this.ctx.createBiquadFilter();
    tone.type = "lowpass";
    tone.frequency.value = 2600;
    // As loud as it can go without clipping: squeeze the dynamics, lift
    // everything up, then a brick-wall limiter just below full scale.
    const squeeze = this.ctx.createDynamicsCompressor();
    squeeze.threshold.value = -24;
    squeeze.knee.value = 12;
    squeeze.ratio.value = 4;
    squeeze.attack.value = 0.01;
    squeeze.release.value = 0.4;
    const lift = this.ctx.createGain();
    lift.gain.value = 3.2;
    const limiter = this.ctx.createDynamicsCompressor();
    limiter.threshold.value = -3;
    limiter.knee.value = 0;
    limiter.ratio.value = 20;
    limiter.attack.value = 0.001;
    limiter.release.value = 0.12;
    // The limiter lets the very first millisecond of a note through: keep headroom.
    const ceiling = this.ctx.createGain();
    ceiling.gain.value = 0.9;
    // After all the loudness processing, so a dip for speech isn't squeezed
    // back up by the compressor: villagers talking get the room to themselves.
    this.voiceDuck = this.ctx.createGain();
    this.master
      .connect(tone)
      .connect(squeeze)
      .connect(lift)
      .connect(limiter)
      .connect(ceiling)
      .connect(this.voiceDuck)
      .connect(this.ctx.destination);
    // A long, gentle hall: generated impulse response.
    const reverb = this.ctx.createConvolver();
    reverb.buffer = this.impulse(4.5, 2.6);
    this.wet = this.ctx.createGain();
    this.wet.gain.value = 0.55;
    this.wet.connect(reverb).connect(this.master);
  }

  private impulse(seconds: number, decay: number) {
    const rate = this.ctx.sampleRate;
    const length = Math.floor(rate * seconds);
    const buffer = this.ctx.createBuffer(2, length, rate);
    for (let channel = 0; channel < 2; channel++) {
      const data = buffer.getChannelData(channel);
      for (let i = 0; i < length; i++)
        data[i] = (Math.random() * 2 - 1) * (1 - i / length) ** decay;
    }
    return buffer;
  }

  suspend() {
    if (this.ctx.state === "running") void this.ctx.suspend();
  }

  /** Stop for good: no more notes, and release the audio device. */
  close() {
    clearInterval(this.timer);
    this.timer = 0;
    void this.ctx.close().catch(() => {});
  }

  /** Music well under speech: about -26 dB while a villager talks. */
  duckForVoice(on: boolean) {
    const now = this.ctx.currentTime;
    this.voiceDuck.gain.cancelScheduledValues(now);
    this.voiceDuck.gain.setTargetAtTime(on ? 0.05 : 1, now, on ? 0.12 : 0.6);
  }

  resume() {
    return this.ctx.state === "suspended"
      ? this.ctx.resume()
      : Promise.resolve();
  }

  fade(to: number) {
    const now = this.ctx.currentTime;
    this.master.gain.cancelScheduledValues(now);
    // Quick in (audible at once), gentle out.
    this.master.gain.setTargetAtTime(to * 1, now, to ? 0.1 : 0.4);
  }

  start(track: number) {
    this.track = track;
    this.onTrack(track);
    this.startedAt = this.ctx.currentTime;
    this.nextBeat = this.ctx.currentTime + 0.05; // the first chord, straight away
    this.beatIndex = 0;
    this.lastNote = 7; // the tonic, an octave up
    this.resting = 0;
    if (!this.timer)
      this.timer = window.setInterval(() => this.schedule(), 120);
  }

  /** Schedule what falls in the next half second (lookahead scheduling). */
  private schedule() {
    const t = TRACKS[this.track];
    const horizon = this.ctx.currentTime + 0.5;
    while (this.nextBeat < horizon) {
      const elapsed = this.nextBeat - this.startedAt;
      if (elapsed > t.length) {
        // A breath of silence, then the next track.
        const next = (this.track + 1) % TRACKS.length;
        const at = this.nextBeat + BREATH;
        this.start(next);
        this.startedAt = at;
        this.nextBeat = at;
        return;
      }
      this.beat(t, this.nextBeat);
      this.beatIndex++;
      this.nextBeat += t.beat * (0.97 + Math.random() * 0.06); // a little rubato
    }
  }

  private beat(t: Track, at: number) {
    const bar = Math.floor(this.beatIndex / 4);
    const inBar = this.beatIndex % 4;
    const degree = t.chords[bar % t.chords.length];
    const note = (deg: number, octave = 0) => {
      const d = ((deg % 7) + 7) % 7;
      const up = Math.floor(deg / 7);
      return t.root + t.scale[d] + 12 * (octave + up);
    };
    // Chord on the bar: a low root and a soft open voicing, rolled.
    if (inBar === 0) {
      this.piano(note(degree, -1), at, 0.16, 6);
      [0, 2, 4].forEach((step, i) =>
        this.piano(note(degree + step), at + 0.06 * (i + 1), 0.07, 5.5),
      );
    }
    // Phrases with long rests, like someone thinking at the piano.
    if (this.resting > 0) {
      this.resting--;
      return;
    }
    if (Math.random() > t.density) return;
    if (Math.random() < 0.12) {
      this.resting = 4 + Math.floor(Math.random() * 8);
      return;
    }
    // A gentle random walk, leaning toward chord tones.
    const steps = [-2, -1, -1, 0, 1, 1, 2, 3, -3];
    let next = this.lastNote + steps[Math.floor(Math.random() * steps.length)];
    if (Math.random() < 0.35)
      next = degree + 7 + [0, 2, 4][Math.floor(Math.random() * 3)];
    next = Math.max(2, Math.min(15, next));
    this.lastNote = next;
    const midi = note(next, t.octave - 1);
    const offset = inBar % 2 ? t.beat * 0.5 * Math.random() : 0;
    this.piano(
      midi,
      at + offset,
      0.11 + Math.random() * 0.05,
      3.5 + Math.random() * 2,
    );
    // Now and then, a soft octave or third echo.
    if (Math.random() < 0.15)
      this.piano(midi + 12, at + offset + t.beat * 0.75, 0.04, 3);
  }

  /** A soft felt-piano note: two detuned partials, quick attack, long decay. */
  private piano(midi: number, at: number, velocity: number, decay: number) {
    const voice = this.ctx.createGain();
    voice.gain.setValueAtTime(0, at);
    voice.gain.linearRampToValueAtTime(velocity, at + 0.012);
    voice.gain.exponentialRampToValueAtTime(velocity * 0.35, at + 0.6);
    voice.gain.exponentialRampToValueAtTime(0.0001, at + decay);
    const dry = this.ctx.createGain();
    dry.gain.value = 0.6;
    voice.connect(dry).connect(this.master);
    voice.connect(this.wet);
    const f = freq(midi);
    for (const [ratio, type, level, detune] of [
      [1, "triangle", 1, -3],
      [1, "sine", 0.7, 4],
      [2, "sine", 0.18, 0],
      [3, "sine", 0.05, 0],
    ] as const) {
      const osc = this.ctx.createOscillator();
      osc.type = type;
      osc.frequency.value = f * ratio;
      osc.detune.value = detune;
      const g = this.ctx.createGain();
      g.gain.value = level;
      osc.connect(g).connect(voice);
      osc.start(at);
      osc.stop(at + decay + 0.1);
    }
  }
}
