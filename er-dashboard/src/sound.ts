/**
 * Alert sounds, made with the Web Audio API (no audio files). Browsers only allow sound after a click, so
 * sound is off until a person turns it on; turning it on creates the AudioContext inside that click.
 */
let ctx: AudioContext | null = null;

export function enableSound(): boolean {
  try {
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return false;
    ctx ??= new Ctor();
    void ctx.resume();
    return true;
  } catch {
    return false;
  }
}

function tone(freq: number, start: number, dur: number, type: OscillatorType, peak: number): void {
  if (!ctx) return;
  const t0 = ctx.currentTime + start;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(0.0001, t0);
  gain.gain.exponentialRampToValueAtTime(peak, t0 + 0.015);
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  osc.connect(gain).connect(ctx.destination);
  osc.start(t0);
  osc.stop(t0 + dur + 0.02);
}

/** Critical (cardiac arrest): a two-tone siren, three rounds, hard to miss. */
export function playCritical(): void {
  for (let i = 0; i < 3; i++) {
    tone(988, i * 0.5, 0.22, "square", 0.22);
    tone(740, i * 0.5 + 0.25, 0.22, "square", 0.22);
  }
}

/** High (life-threatening finding such as STEMI, airway, stroke window): two soft chimes. */
export function playHigh(): void {
  tone(660, 0, 0.28, "sine", 0.28);
  tone(880, 0.3, 0.38, "sine", 0.28);
}

/** Short test sound played when a person turns sound on, so they know it works. */
export function playTest(): void {
  tone(784, 0, 0.18, "sine", 0.2);
}
