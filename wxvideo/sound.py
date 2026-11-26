"""
West WX Watchers video sound: a light music bed and sound effects, all made here in code (no licensed audio).

  mix = Mix(seconds); mix.music(); mix.cue('whoosh', 3.2); mix.cue('pop', 4.6); mix.write('a.wav')

Effects: whoosh (camera moves), pop (a label lands), tick (a row appears), ding (a number finishes),
swell (the logo at the end).
"""
import math, wave
import numpy as np

SR = 44100

def _note(n):   # MIDI note -> Hz
    return 440.0 * 2 ** ((n - 69) / 12)

def _env(n, a, d, s, r, hold):
    """ADSR envelope, n samples long; a/d/r in seconds, s level, hold = seconds before release."""
    t = np.arange(n) / SR
    e = np.where(t < a, t / max(a, 1e-4), np.where(t < a + d, 1 - (1 - s) * (t - a) / max(d, 1e-4), s))
    rel = t > hold
    e[rel] *= np.exp(-(t[rel] - hold) / max(r, 1e-4))
    return e

def _lowpass(x, cut):
    """One-pole low-pass (cut in Hz), applied forwards (vectorised with an IIR filter)."""
    from scipy.signal import lfilter
    a = math.exp(-2 * math.pi * cut / SR)
    return lfilter([1 - a], [1, -a], x)

class Mix:
    def __init__(self, seconds):
        self.n = int(seconds * SR) + SR
        self.L = np.zeros(self.n); self.R = np.zeros(self.n)
        self.seconds = seconds

    def _add(self, x, t, gain=1.0, pan=0.0):
        i = int(t * SR)
        if i >= self.n: return
        x = x[: self.n - i]
        self.L[i:i + len(x)] += x * gain * math.sqrt((1 - pan) / 2)
        self.R[i:i + len(x)] += x * gain * math.sqrt((1 + pan) / 2)

    # ---------------------------------------------------------------- music bed
    def music(self, bpm=100, gain=0.55, key=62):
        """Bright, steady news-style bed: pad chords, bass, plucked arpeggio and a soft beat (D - Bm - G - A)."""
        beat = 60 / bpm; bar = 4 * beat
        prog = [(0, [0, 4, 7, 11]), (-3, [0, 3, 7, 10]), (-7, [0, 4, 7, 11]), (-5, [0, 4, 7, 10])]   # D maj7, Bm7, G maj7, A7
        t0 = 0.0; k = 0
        rng = np.random.default_rng(7)
        while t0 < self.seconds:
            root, ch = prog[k % 4]; base = key + root
            # pad: soft, a few harmonics, slow attack
            n = int(bar * SR * 1.1); tt = np.arange(n) / SR
            pad = np.zeros(n)
            for iv in ch:
                f = _note(base + iv)
                for h, w in ((1, 1.0), (2, 0.35), (3, 0.15)):
                    pad += w * np.sin(2 * math.pi * f * h * tt + 0.3 * np.sin(2 * math.pi * 0.25 * tt))
            pad = _lowpass(pad, 1800) * _env(n, 0.5, 0.6, 0.75, 0.4, bar)
            self._add(pad, t0, 0.035 * gain)
            # bass on beats 1 and 3
            for b in (0, 2):
                n = int(beat * 1.8 * SR); tt = np.arange(n) / SR; f = _note(base - 24)
                bs = (np.sin(2 * math.pi * f * tt) + 0.3 * np.sin(4 * math.pi * f * tt)) * _env(n, 0.01, 0.25, 0.6, 0.2, beat * 1.4)
                self._add(bs, t0 + b * beat, 0.16 * gain)
            # plucked arpeggio, eighth notes
            arp = [ch[0], ch[1], ch[2], ch[3] if len(ch) > 3 else ch[0] + 12, ch[2], ch[1], ch[2], ch[0] + 12]
            for j, iv in enumerate(arp):
                n = int(beat * 0.9 * SR); tt = np.arange(n) / SR; f = _note(base + 12 + iv)
                tri = 2 / math.pi * np.arcsin(np.sin(2 * math.pi * f * tt))
                pl = tri * np.exp(-tt / 0.18)
                self._add(pl, t0 + j * beat / 2, 0.06 * gain, pan=(-0.35 if j % 2 else 0.35))
            # beat: soft kick on 1 and 3, shaker on the off-beats
            for b in range(4):
                if b % 2 == 0:
                    n = int(0.3 * SR); tt = np.arange(n) / SR
                    f = 50 + 70 * np.exp(-tt / 0.03)
                    kick = np.sin(2 * math.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.12)
                    self._add(kick, t0 + b * beat, 0.32 * gain)
                n = int(0.08 * SR)
                sh = rng.standard_normal(n); sh = sh - _lowpass(sh, 6000)
                sh *= np.exp(-np.arange(n) / SR / 0.025)
                self._add(sh, t0 + b * beat + beat / 2, 0.05 * gain)
            t0 += bar; k += 1
        # fade in and out
        fi = int(0.8 * SR); fo = int(1.6 * SR); end = int(self.seconds * SR)
        ramp = np.ones(self.n); ramp[:fi] = np.linspace(0, 1, fi)
        ramp[max(0, end - fo):end] = np.linspace(1, 0, min(fo, end)); ramp[end:] = 0
        self.L *= ramp; self.R *= ramp

    # ---------------------------------------------------------------- effects
    def cue(self, kind, t, gain=1.0, pan=0.0):
        if t < 0 or t > self.seconds: return
        rng = np.random.default_rng(int(t * 1000) % 99991)
        if kind == 'whoosh':                      # air swoosh: dark to bright and back
            n = int(0.9 * SR); x = rng.standard_normal(n)
            lo = _lowpass(_lowpass(x, 500), 500); hi = _lowpass(_lowpass(x, 2600), 2600) - _lowpass(x, 400)
            u = np.sin(np.pi * np.linspace(0, 1, n))
            out = lo * (1 - u) * 1.6 + hi * u
            env = u ** 2.2
            self._add(out * env, t, 0.22 * gain, pan)
        elif kind == 'pop':                       # quick pitched blip
            n = int(0.12 * SR); tt = np.arange(n) / SR
            f = 900 * np.exp(-tt / 0.05) + 380
            x = np.sin(2 * math.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.035)
            self._add(x, t, 0.28 * gain, pan)
        elif kind == 'tick':
            n = int(0.05 * SR); tt = np.arange(n) / SR
            x = np.sin(2 * math.pi * 1800 * tt) * np.exp(-tt / 0.012)
            self._add(x, t, 0.12 * gain, pan)
        elif kind == 'ding':                      # small bell
            n = int(1.4 * SR); tt = np.arange(n) / SR; f = 1320
            x = sum(w * np.sin(2 * math.pi * f * m * tt) * np.exp(-tt / d) for m, w, d in ((1, 1, 0.6), (2.76, 0.4, 0.25), (5.4, 0.2, 0.1)))
            self._add(x, t, 0.12 * gain, pan)
        elif kind == 'swell':                     # rising chord for the logo
            n = int(2.0 * SR); tt = np.arange(n) / SR
            x = sum(np.sin(2 * math.pi * _note(n_) * tt) for n_ in (62, 66, 69, 74))
            x = _lowpass(x, 2500) * np.clip(tt / 0.6, 0, 1) * np.exp(-np.clip(tt - 0.8, 0, None) / 0.5)
            self._add(x, t, 0.07 * gain)

    def write(self, path):
        m = np.stack([self.L, self.R], 1)
        rms = np.sqrt(np.mean(m[: int(self.seconds * SR)] ** 2)) or 1.0
        m *= 10 ** (-17 / 20) / rms                    # about -17 dBFS average: loud enough for phones
        m = np.tanh(m * 1.1) / 1.1                     # soft limit the peaks
        pcm = (m * 32767).astype('<i2')
        with wave.open(path, 'wb') as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
