"""Sound for the website's tour: original music and interface sounds, synthesized here.

Nothing is sampled or licensed from anyone: every sound is made from sine waves and noise
below, so the files are ours to publish. Writes:

    site/audio/tour-music.mp3     a 16-bar loop the page plays under the tour
    site/audio/click.wav          a trackpad click
    site/audio/key-1..3.wav       three keystrokes, so typing doesn't sound mechanical

With ``--video EVENTS.json DURATION OUT.wav`` it also renders the full soundtrack for a
recorded video: the music arranged to that length (a soft opening on the desktop, the
beat while the app is in use, a final chord under the closing line) with every click and
keystroke at the times the recording logged.

    uv run --with numpy --with scipy python scripts/demo/tour_audio.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

RATE = 44_100
BPM = 118
BEAT = 60 / BPM
BAR = 4 * BEAT
SITE = Path(__file__).resolve().parents[2] / "site" / "audio"

# A minor: Am - F - C - G, one chord per bar.
CHORDS = [(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)]
BASS = [45, 41, 48, 43]
rng = np.random.default_rng(7)


def hz(note: float) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def t(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * RATE)) / RATE


def env(n: int, attack: float, decay: float) -> np.ndarray:
    x = np.arange(n) / RATE
    a = np.minimum(1, x / max(attack, 1e-4))
    return a * np.exp(-x / decay)


def lowpass(x: np.ndarray, cutoff: float, order: int = 2) -> np.ndarray:
    return sosfilt(butter(order, cutoff, "low", fs=RATE, output="sos"), x)


def highpass(x: np.ndarray, cutoff: float, order: int = 2) -> np.ndarray:
    return sosfilt(butter(order, cutoff, "high", fs=RATE, output="sos"), x)


def bandpass(x: np.ndarray, low: float, high: float) -> np.ndarray:
    return sosfilt(butter(2, [low, high], "band", fs=RATE, output="sos"), x)


def saw(freq: float, n: int, harmonics: int = 12) -> np.ndarray:
    x = np.arange(n) / RATE
    out = np.zeros(n)
    for k in range(1, harmonics + 1):
        if freq * k > RATE / 2:
            break
        out += np.sin(2 * np.pi * freq * k * x) / k
    return out * 0.6


# -- instruments ----------------------------------------------------------------------
def kick() -> np.ndarray:
    x = t(0.4)
    freq = 48 + 110 * np.exp(-x / 0.045)
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    body = np.sin(phase) * env(len(x), 0.001, 0.16)
    click = highpass(rng.standard_normal(len(x)), 2000) * env(len(x), 0.0005, 0.004) * 0.3
    return (body + click) * 0.95


def clap() -> np.ndarray:
    x = t(0.25)
    noise = bandpass(rng.standard_normal(len(x)), 900, 5000)
    e = np.zeros(len(x))
    for offset in (0, 0.012, 0.024):  # three quick hands make a clap
        i = int(offset * RATE)
        e[i:] += env(len(x) - i, 0.0005, 0.03 if offset < 0.02 else 0.11)
    return noise * e * 0.45


def hat(open_: bool = False) -> np.ndarray:
    x = t(0.18 if open_ else 0.05)
    noise = highpass(rng.standard_normal(len(x)), 7000)
    return noise * env(len(x), 0.0005, 0.06 if open_ else 0.012) * 0.22


def bass_note(note: int, length: float) -> np.ndarray:
    n = int(length * RATE)
    tone = saw(hz(note), n, 8) + 0.5 * np.sin(2 * np.pi * hz(note - 12) * np.arange(n) / RATE)
    return lowpass(tone, 420) * env(n, 0.004, length * 0.7) * 0.55


def pluck(note: int, length: float = 0.3) -> np.ndarray:
    n = int(length * RATE)
    x = np.arange(n) / RATE
    tone = np.sign(np.sin(2 * np.pi * hz(note) * x)) * 0.35 + np.sin(2 * np.pi * hz(note) * x)
    return lowpass(tone, 3200) * env(n, 0.002, 0.09) * 0.22


def pad(chord: tuple[int, ...], length: float) -> tuple[np.ndarray, np.ndarray]:
    n = int(length * RATE)
    left, right = np.zeros(n), np.zeros(n)
    for note in chord:
        for detune, side in ((-0.09, left), (0.09, right), (0.0, left), (0.0, right)):
            side += saw(hz(note + detune), n, 6)
    shape = np.minimum(1, np.arange(n) / (0.35 * RATE)) * np.minimum(
        1, (n - np.arange(n)) / (0.3 * RATE)
    )
    return lowpass(left, 1500) * shape * 0.05, lowpass(right, 1500) * shape * 0.05


def bell(note: int, length: float = 3.5) -> np.ndarray:
    n = int(length * RATE)
    x = np.arange(n) / RATE
    f = hz(note)
    tone = np.sin(2 * np.pi * f * x) + 0.4 * np.sin(2 * np.pi * f * 2.76 * x) * np.exp(-x / 0.4)
    return tone * env(n, 0.003, 1.2) * 0.25


# -- arranging --------------------------------------------------------------------------
class Mix:
    def __init__(self, seconds: float) -> None:
        self.left = np.zeros(int(seconds * RATE) + RATE * 4)
        self.right = np.zeros_like(self.left)

    def add(self, at: float, sound: np.ndarray, gain: float = 1.0, pan: float = 0.0) -> None:
        i = int(at * RATE)
        if i >= len(self.left) or i < 0:
            return
        sound = sound[: len(self.left) - i]
        self.left[i : i + len(sound)] += sound * gain * (1 - max(0.0, pan))
        self.right[i : i + len(sound)] += sound * gain * (1 + min(0.0, pan))

    def add_stereo(
        self, at: float, sound: tuple[np.ndarray, np.ndarray], gain: float = 1.0
    ) -> None:
        i = int(at * RATE)
        n = min(len(sound[0]), len(self.left) - i)
        self.left[i : i + n] += sound[0][:n] * gain
        self.right[i : i + n] += sound[1][:n] * gain

    def duck(self, kicks: list[float], depth: float = 0.55) -> None:
        """Sidechain: everything dips under each kick, the pumping that makes it move."""
        gain = np.ones_like(self.left)
        shape = 1 - depth * np.exp(-np.arange(int(0.25 * RATE)) / (0.07 * RATE))
        for k in kicks:
            i = int(k * RATE)
            seg = gain[i : i + len(shape)]
            seg[:] = np.minimum(seg, shape[: len(seg)])
        self.left *= gain
        self.right *= gain

    def master(self, seconds: float, fade: float = 0.0) -> np.ndarray:
        stereo = np.stack([self.left, self.right], axis=1)[: int(seconds * RATE)]
        if fade:
            n = int(fade * RATE)
            stereo[-n:] *= np.linspace(1, 0, n)[:, None] ** 2
        peak = np.max(np.abs(stereo)) or 1
        return np.tanh(stereo / peak * 1.3) * 0.89


def bars(mix: Mix, start: float, count: int, *, drums: bool, bass: bool, arp: bool) -> list[float]:
    kicks: list[float] = []
    for b in range(count):
        at = start + b * BAR
        chord = CHORDS[b % 4]
        mix.add_stereo(at, pad(chord, BAR + 0.2))
        if bass:
            for eighth in range(8):
                mix.add(at + eighth * BEAT / 2, bass_note(BASS[b % 4], BEAT / 2 * 0.9), 0.9)
        if arp:
            notes = [n + 12 for n in chord] + [chord[0] + 24]
            for s in range(16):
                note = notes[[0, 1, 2, 3, 2, 1, 2, 3][s % 8]]
                pan = -0.35 if s % 2 else 0.35
                mix.add(at + s * BEAT / 4, pluck(note), 0.9, pan)
                mix.add(at + s * BEAT / 4 + BEAT * 0.75, pluck(note), 0.25, -pan)  # echo
        if drums:
            for beat in range(4):
                mix.add(at + beat * BEAT, kick(), 1.0)
                kicks.append(at + beat * BEAT)
                if beat in (1, 3):
                    mix.add(at + beat * BEAT, clap(), 0.9)
                mix.add(at + beat * BEAT + BEAT / 2, hat(open_=beat == 3), 1.0, 0.2)
                mix.add(at + beat * BEAT + BEAT / 4, hat(), 0.5, -0.2)
                mix.add(at + beat * BEAT + 3 * BEAT / 4, hat(), 0.5, -0.2)
    return kicks


def loop() -> np.ndarray:
    """16 bars that loop seamlessly: 4 lighter, then the full groove."""
    seconds = 16 * BAR
    mix = Mix(seconds)
    kicks = bars(mix, 0, 4, drums=False, bass=True, arp=True)
    kicks += bars(mix, 4 * BAR, 12, drums=True, bass=True, arp=True)
    mix.duck(kicks)
    # Wrap the tails that ring past the end back to the start, so the loop is seamless.
    n = int(seconds * RATE)
    for side in (mix.left, mix.right):
        side[: len(side) - n] += side[n:]
    return mix.master(seconds)


def soundtrack(duration: float, events: list[dict[str, object]]) -> np.ndarray:
    """The music arranged to the video, with the interface sounds on top."""
    mix = Mix(duration)
    marks = {str(e["name"]): float(e["t"]) for e in events if str(e["name"]).startswith("mark:")}
    opened = marks.get("mark:opened", 6.0)
    closing = marks.get("mark:closing", duration - 8)
    tagline = marks.get("mark:tagline", duration - 5)
    # Soft opening on the desktop: pad and arpeggio, no beat.
    intro_bars = max(1, int(opened / BAR + 0.5))
    bars(mix, 0, intro_bars, drums=False, bass=False, arp=True)
    start = intro_bars * BAR
    main_bars = max(1, int((closing - start) / BAR))
    kicks = bars(mix, start, main_bars, drums=True, bass=True, arp=True)
    after = start + main_bars * BAR
    bars(mix, after, max(1, int((tagline - after) / BAR) + 1), drums=False, bass=True, arp=False)
    mix.duck(kicks)
    for note in (57, 64, 69, 72):  # the closing chord under the tagline
        mix.add(tagline, bell(note, 4.5), 0.8)
    music = mix.master(duration, fade=2.5) * 0.5

    sfx = Mix(duration)
    click = _load("click.wav")
    keys = [_load(f"key-{i}.wav") for i in (1, 2, 3)]
    for i, e in enumerate(events):
        name, at = str(e["name"]), float(e["t"])
        if name == "click":
            sfx.add(at, click, 0.9)
        elif name == "key":
            sfx.add(at, keys[i % 3], 0.55 * float(rng.uniform(0.8, 1.0)))
    voices = np.stack([sfx.left, sfx.right], axis=1)[: len(music)]
    return np.clip(music + voices, -1, 1)


# -- interface sounds -----------------------------------------------------------------
def click_sound() -> np.ndarray:
    x = t(0.06)
    tick = np.sin(2 * np.pi * 2300 * x) * env(len(x), 0.0003, 0.006)
    thud = np.sin(2 * np.pi * 180 * x) * env(len(x), 0.0005, 0.012) * 0.6
    noise = bandpass(rng.standard_normal(len(x)), 1500, 7000) * env(len(x), 0.0002, 0.004) * 0.5
    return (tick + thud + noise) * 0.8


def key_sound(seed: int) -> np.ndarray:
    local = np.random.default_rng(seed)
    x = t(0.07)
    clack = bandpass(local.standard_normal(len(x)), 1800 + 300 * seed, 5200) * env(
        len(x), 0.0004, 0.008
    )
    bottom = np.sin(2 * np.pi * (140 + 20 * seed) * x) * env(len(x), 0.001, 0.015) * 0.5
    return (clack + bottom) * 0.75


def _write_wav(path: Path, samples: np.ndarray) -> None:
    data = samples if samples.ndim == 2 else samples[:, None]
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as f:
        f.setnchannels(data.shape[1])
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(pcm.tobytes())


def _load(name: str) -> np.ndarray:
    with wave.open(str(SITE / name), "rb") as f:
        return np.frombuffer(f.readframes(f.getnframes()), "<i2").astype(float) / 32767


def main(argv: list[str]) -> None:
    SITE.mkdir(parents=True, exist_ok=True)
    if argv[:1] == ["--video"]:
        events_path, duration, out = argv[1], float(argv[2]), Path(argv[3])
        events = json.loads(Path(events_path).read_text())
        _write_wav(out, soundtrack(duration, events))
        print(f"Wrote {out}")
        return
    _write_wav(SITE / "click.wav", click_sound())
    for i in (1, 2, 3):
        _write_wav(SITE / f"key-{i}.wav", key_sound(i))
    raw = SITE / "tour-music.wav"
    _write_wav(raw, loop() * 0.7)
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(raw),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(SITE / "tour-music.mp3"),
        ],
        check=True,
    )
    raw.unlink()
    print(f"Wrote {SITE}")


if __name__ == "__main__":
    main(sys.argv[1:])
