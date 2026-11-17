"""Original background music and sound effects, synthesized with numpy (no samples, no licences)."""
import numpy as np

RATE = 24000
BPM = 100
# vi-IV-I-V in C major, one chord per bar: (root MIDI note, chord intervals).
PROGRESSION = [(57, (0, 3, 7)), (53, (0, 4, 7)), (48, (0, 4, 7)), (55, (0, 4, 7))]


def freq(note):
    return 440.0 * 2 ** ((note - 69) / 12)


def lowpass(signal, cutoff):
    alpha = 1 - np.exp(-2 * np.pi * cutoff / RATE)
    out = np.empty_like(signal)
    level = 0.0
    for start in range(0, len(signal), 4096):  # chunked one-pole filter, fast enough here
        block = signal[start:start + 4096]
        result = np.empty_like(block)
        for i, sample in enumerate(block):
            level += alpha * (sample - level)
            result[i] = level
        out[start:start + 4096] = result
    return out


def tone(f, length, shape="sine", detune=0.0):
    t = np.arange(int(length * RATE)) / RATE
    phase = 2 * np.pi * f * (1 + detune) * t
    if shape == "saw":
        return 2 * ((f * (1 + detune) * t) % 1) - 1
    if shape == "tri":
        return 2 * np.abs(2 * ((f * t) % 1) - 1) - 1
    return np.sin(phase)


def bed(seconds):
    """A calm, steady loop: warm pad, soft bass, plucked arpeggio and a light shaker."""
    beat = 60 / BPM
    bar = 4 * beat
    total = int(seconds * RATE)
    bars = int(np.ceil(seconds / bar)) + 1
    out = np.zeros(int((bars + 1) * bar * RATE), dtype=np.float32)
    rng = np.random.default_rng(7)
    for index in range(bars):
        root, chord = PROGRESSION[index % len(PROGRESSION)]
        start = int(index * bar * RATE)
        n = int(bar * RATE)
        envelope = np.minimum(1, np.arange(n) / (0.35 * RATE)) * np.minimum(1, (n - np.arange(n)) / (0.35 * RATE))
        pad = sum(tone(freq(root + 12 + step), bar, "saw", d) for step in chord for d in (-0.003, 0.003))
        out[start:start + n] += 0.05 * pad * envelope
        out[start:start + n] += 0.16 * tone(freq(root - 12), bar, "sine") * envelope
        notes = [root + 24 + chord[i % 3] + (12 if i % 4 == 3 else 0) for i in range(8)]
        for step, note in enumerate(notes):
            at = start + int(step * beat / 2 * RATE)
            length = int(0.45 * RATE)
            pluck = tone(freq(note), 0.45, "tri") * np.exp(-np.arange(length) / (0.09 * RATE))
            out[at:at + length] += 0.07 * pluck[:len(out) - at]
        for step in range(8):
            at = start + int((step + 0.5) * beat / 2 * RATE)
            length = int(0.05 * RATE)
            hiss = rng.standard_normal(length) * np.exp(-np.arange(length) / (0.012 * RATE))
            out[at:at + length] += 0.02 * np.diff(np.concatenate([[0], hiss]))[:len(out) - at]
    out = lowpass(out, 3200)
    out = out[:total]
    fade = int(1.5 * RATE)
    out[:fade] *= np.linspace(0, 1, fade)
    out[-fade:] *= np.linspace(1, 0, fade)
    return out / max(1e-6, np.abs(out).max())


def whoosh(length=0.45):
    n = int(length * RATE)
    rng = np.random.default_rng(3)
    noise = rng.standard_normal(n).astype(np.float32)
    rising = lowpass(noise, 2500) * np.sin(np.linspace(0, np.pi, n)) ** 2
    return 0.5 * rising / max(1e-6, np.abs(rising).max())


def pop(length=0.12, pitch=880):
    n = int(length * RATE)
    t = np.arange(n) / RATE
    sweep = np.sin(2 * np.pi * (pitch * t + 400 * t * t)) * np.exp(-t / 0.03)
    return 0.35 * sweep.astype(np.float32)
