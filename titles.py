"""Baut knackige YouTube-Titel aus dem, was im Clip gesagt wird.

Anlass (Boss, 2026-11-08): Die Twitch-Clip-Titel sind oft nichtssagend
("F", "Falle"), und der Titel entscheidet bei Shorts viel ueber die Reichweite.

1. Der markanteste Satz des Clips (laut, kurz, Ausruf) wird als Zitat-Titel
   genommen. Ohne KI: Der fruehere KI-Weg (GitHub Models) ist tot, der Dienst
   wurde am 2026-07-30 eingestellt; Entscheidung 2026-11-09: Zitat-Titel bleiben.
2. Gibt es keinen brauchbaren Satz: Twitch-Titel.
3. Danach immer: Streamer-Name dran, hoechstens 100 Zeichen (YouTube-Grenze).
"""

import numpy as np

SR = 16000
# Woerter, auf die kein fertiger Satz endet
HALF = {"wie", "und", "oder", "aber", "der", "die", "das", "den", "dem", "des", "ein",
        "eine", "einen", "einem", "einer", "mit", "von", "zu", "zum", "zur", "in", "im",
        "auf", "an", "am", "fuer", "für", "dass", "weil", "wenn", "als", "ich", "du",
        "er", "sie", "es", "wir", "ihr", "so", "noch", "auch", "dann", "mein", "dein"}


def sentences(words, gap=0.6):
    """Woerter (faster-whisper) zu Saetzen: Satzzeichen oder Sprechpause."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if w.word.strip()[-1:] in ".!?" or nxt is None or nxt.start - w.end > gap:
            text = " ".join(x.word.strip() for x in cur).strip()
            if text:
                out.append((cur[0].start, cur[-1].end, text))
            cur = []
    return out


def quote_title(words, audio):
    """Lautester, kurzer Satz als Zitat."""
    best, best_score = None, -1e9
    for start, end, text in sentences(words):
        n = len(text.split())
        if n < 2 or n > 10:
            continue
        last = text.split()[-1].strip(".,!?").lower()
        if last in HALF:          # abgebrochener Halbsatz ("Ich sehe aus wie")
            continue
        seg = audio[int(start * SR):int(end * SR)] if audio is not None else np.zeros(1)
        loud = float(np.sqrt(np.mean(seg.astype(np.float64) ** 2) + 1e-9)) if seg.size else 0.0
        score = loud * 10 + (2 if text.endswith(("!", "?")) else 0) - abs(n - 5) * 0.3
        if score > best_score:
            best, best_score = text, score
    if not best:
        return None
    best = best.rstrip(".,")
    return f"\"{best[0].upper() + best[1:]}\""


def make_title(words, audio, twitch_title, name):
    """Gibt (titel, methode) zurueck. methode: 'zitat' oder 'twitch'."""
    t, method = quote_title(words, audio), "zitat"
    if not t:
        tt = (twitch_title or "").strip()
        t = tt[0].upper() + tt[1:] if len(tt) >= 6 else "Damit hat keiner gerechnet"
        method = "twitch"
    return f"{t} | {name} #shorts"[:100], method
