"""Findet wirklich spannende Momente ueber die Audiospur, nicht nur laute.

Reine Lautstaerke (alte Version) griff oft daneben: Dauerlaute Musik, laute
Spielgeraeusche oder einfach ein lautstarker Redeabschnitt landeten vorn,
obwohl nichts Besonderes passierte. "Laut" ist nicht gleich "spannend".

Neuer Score kombiniert zwei Signale pro 1-Sekunden-Fenster:
1. Relativer Lautstaerke-Sprung: aktuelle RMS-Lautstaerke geteilt durch den
   gleitenden Durchschnitt der letzten 20s. Erfasst ploetzliche Ausbrueche
   (Schreien, Lachen, Hype) statt dauerhaft lauter Hintergrundgeraeusche, die
   im Verhaeltnis zu ihrer eigenen Baseline nicht mehr "ploetzlich" sind.
2. Hochfrequenz-Anteil: Lachen/Schreien/aufgeregtes Reden hat deutlich mehr
   Energie in hohen Frequenzen als normales Reden oder tiefe Spielmusik.
   Simpler Hochpass (Differenz aufeinanderfolgender Samples als Approximation
   einer Hochpass-Filterung) liefert dieses Signal ohne zusaetzliche Pakete.

Beide Signale werden z-normalisiert und gewichtet addiert (60% Sprung, 40%
Hochfrequenz), damit weder ein einzelner lauter Bass-Schlag noch dauerhaftes
hohes Gezische (z.B. Mikro-Rauschen) allein den Ausschlag gibt.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

SR = 16000
WINDOW_SEC = 1.0
CLIP_LEN = 45  # Sekunden pro Kandidaten-Clip
PRE_ROLL = 6  # Sekunden vor dem Peak mit reinnehmen, fuer Kontext
BASELINE_WINDOWS = 20  # Sekunden gleitender Durchschnitt fuer den "Sprung"


def load_audio(video_path):
    cmd = [
        "ffmpeg", "-i", str(video_path), "-vn", "-ac", "1", "-ar", str(SR),
        "-f", "s16le", "-loglevel", "error", "-",
    ]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    return audio


def per_window(audio, fn):
    win = int(WINDOW_SEC * SR)
    n_windows = len(audio) // win
    out = np.zeros(n_windows)
    for i in range(n_windows):
        out[i] = fn(audio[i * win : (i + 1) * win])
    return out


def rms(chunk):
    return np.sqrt(np.mean(chunk.astype(np.float64) ** 2) + 1e-9)


def high_freq_energy(chunk):
    # Differenz aufeinanderfolgender Samples daempft tiefe/langsame Anteile
    # und betont schnelle Schwankungen (hohe Frequenzen) - billiger Hochpass.
    hp = np.diff(chunk.astype(np.float64))
    return np.sqrt(np.mean(hp**2) + 1e-9)


def zscore(x):
    std = x.std()
    return (x - x.mean()) / std if std > 1e-9 else np.zeros_like(x)


def excitement_score(audio):
    loudness = per_window(audio, rms)
    hf = per_window(audio, high_freq_energy)

    baseline_win = BASELINE_WINDOWS
    baseline = np.convolve(loudness, np.ones(baseline_win) / baseline_win, mode="same")
    jump = loudness / (baseline + 1e-6)

    return 0.6 * zscore(jump) + 0.4 * zscore(hf), loudness


INTRO_SKIP = 60  # Sekunden am Anfang ignorieren (meist Intro-Jingle, kein echter Moment)
OUTRO_SKIP = 30  # Sekunden am Ende ignorieren


def pick_top_moments(score, duration, n=4, min_gap_sec=90):
    order = np.argsort(score)[::-1]
    picked = []
    for idx in order:
        t = idx * WINDOW_SEC
        if t < INTRO_SKIP or t > duration - OUTRO_SKIP:
            continue
        if all(abs(t - p) >= min_gap_sec for p in picked):
            picked.append(t)
        if len(picked) >= n:
            break
    return sorted(picked)


def main():
    video_path = Path(sys.argv[1])
    n_clips = int(sys.argv[2]) if len(sys.argv) > 2 else 4

    print("Lade Audiospur...")
    audio = load_audio(video_path)
    duration = len(audio) / SR
    print(f"Dauer: {duration/60:.1f} Minuten")

    score, loudness = excitement_score(audio)
    moments = pick_top_moments(score, duration, n=n_clips)

    results = []
    for t in moments:
        start = max(0, t - PRE_ROLL)
        end = min(duration, start + CLIP_LEN)
        results.append({"peak_time": round(t, 1), "start": round(start, 1), "end": round(end, 1)})

    print(json.dumps(results, indent=2))
    Path("highlights.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
