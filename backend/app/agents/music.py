"""Soft background music for aesthetic ads, composed on the spot.

Each ad gets its own: a key, a tempo and a chord progression picked from the seed, played as warm
pads with a gentle plucked arpeggio, a soft kick and brushed hats, and a touch of room echo. It's
generated, not sampled, so it belongs to whoever makes the ad and can be posted anywhere. (A
trending sound can still be added in Instagram or TikTok when posting.)
"""
from __future__ import annotations

import random
import wave
from pathlib import Path

RATE = 44100
KEYS = {"C": 48, "D": 50, "Eb": 51, "F": 53, "G": 55, "A": 57}  # MIDI note of the low root
# Chords as (scale degree root in semitones, intervals): major 7, minor 7 and add9 colours.
MAJ7, MIN7, ADD9 = (0, 4, 7, 11), (0, 3, 7, 10), (0, 4, 7, 14)
PROGRESSIONS = [
    [(0, MAJ7), (9, MIN7), (5, MAJ7), (7, ADD9)],   # I vi IV V
    [(2, MIN7), (7, ADD9), (0, MAJ7), (9, MIN7)],   # ii V I vi
    [(5, MAJ7), (4, MIN7), (2, MIN7), (0, ADD9)],   # IV iii ii I
    [(0, ADD9), (5, MAJ7), (9, MIN7), (5, MAJ7)],   # I IV vi IV
]


def _freq(note: float) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def compose(seconds: float, out: Path, seed: int = 0) -> Path:
    """A WAV of soft music, `seconds` long (fading in and out), at `out`."""
    import numpy as np

    rng = random.Random(seed)
    root = KEYS[rng.choice(list(KEYS))]
    prog = rng.choice(PROGRESSIONS)
    bpm = rng.choice([70, 74, 78, 82])
    beat = 60.0 / bpm
    chord_len = beat * 4
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    left, right = np.zeros(n), np.zeros(n)

    def env(length: int, attack: float, release: float) -> np.ndarray:
        e = np.ones(length)
        a, r = min(length, int(attack * RATE)), min(length, int(release * RATE))
        if a:
            e[:a] = np.linspace(0, 1, a)
        if r:
            e[-r:] *= np.linspace(1, 0, r)
        return e

    for k in range(int(seconds / chord_len) + 2):
        start = int(k * chord_len * RATE)
        if start >= n:
            break
        deg, shape = prog[k % len(prog)]
        length = min(n - start, int((chord_len + 0.6) * RATE))  # chords overlap a little
        seg = t[start:start + length] - t[start]
        e = env(length, 0.9, 0.9)
        for i, iv in enumerate(shape):
            f = _freq(root + 12 + deg + iv)
            # Two slightly detuned voices per note, panned apart: a wide, warm pad.
            left[start:start + length] += 0.05 * e * np.sin(2 * np.pi * f * 0.998 * seg + i)
            right[start:start + length] += 0.05 * e * np.sin(2 * np.pi * f * 1.002 * seg + 2 * i)
        bass = _freq(root - 12 + deg)
        left[start:start + length] += 0.07 * e * np.sin(2 * np.pi * bass * seg)
        right[start:start + length] += 0.07 * e * np.sin(2 * np.pi * bass * seg)
        # A plucked arpeggio in eighth notes, up and down the chord.
        notes = [root + 24 + deg + iv for iv in shape]
        pattern = notes + notes[-2:0:-1]
        for j in range(8):
            if rng.random() < 0.25:
                continue  # a few rests keep it from sounding mechanical
            s = start + int(j * beat / 2 * RATE)
            ln = min(n - s, int(0.9 * RATE))
            if ln <= 0:
                continue
            st = np.arange(ln) / RATE
            f = _freq(pattern[j % len(pattern)])
            pluck = 0.035 * np.exp(-st * 5.5) * (np.sin(2 * np.pi * f * st) + 0.3 * np.sin(4 * np.pi * f * st))
            pan = 0.5 + 0.35 * np.sin(j)
            left[s:s + ln] += pluck * (1 - pan)
            right[s:s + ln] += pluck * pan

    # Soft drums: a round kick on beats one and three, brushed hats on the off-beats.
    noise = np.random.default_rng(seed).standard_normal(int(0.12 * RATE))
    hat = np.diff(noise, prepend=0) * np.exp(-np.arange(noise.size) / RATE * 40) * 0.012
    for b in range(int(seconds / beat) + 1):
        s = int(b * beat * RATE)
        if b % 2 == 0 and s < n:
            ln = min(n - s, int(0.3 * RATE))
            st = np.arange(ln) / RATE
            kick = 0.16 * np.exp(-st * 14) * np.sin(2 * np.pi * (55 + 60 * np.exp(-st * 30)) * st)
            left[s:s + ln] += kick
            right[s:s + ln] += kick
        h = int((b + 0.5) * beat * RATE)
        if h < n:
            ln = min(n - h, hat.size)
            left[h:h + ln] += hat[:ln] * 0.8
            right[h:h + ln] += hat[:ln]

    # Room echo, a gentle low-pass, and a fade in and out.
    for delay, gain in ((0.13, 0.25), (0.29, 0.15), (0.47, 0.08)):
        d = int(delay * RATE)
        left[d:] += gain * right[:-d]
        right[d:] += gain * left[:-d]
    # A gentle low-pass (above ~3.5 kHz rolls off), which softens the top end like lo-fi tape.
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    curve = 1 / np.sqrt(1 + (freqs / 3500.0) ** 4)
    left, right = (np.fft.irfft(np.fft.rfft(ch) * curve, n) for ch in (left, right))
    fade = env(n, 0.6, 1.6)
    peak = max(np.abs(left).max(), np.abs(right).max(), 1e-6)
    stereo = np.stack([left, right], axis=1) * fade[:, None] * (0.5 / peak)
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes((stereo * 32767).astype(np.int16).tobytes())
    return out
