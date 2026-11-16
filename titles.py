"""Baut knackige YouTube-Titel aus dem, was im Clip gesagt wird.

Anlass (Boss, 2026-11-08): Die Twitch-Clip-Titel sind oft nichtssagend
("F", "Falle"), und der Titel entscheidet bei Shorts viel ueber die Reichweite.

1. Der markanteste Satz des Clips (laut, kurz, Ausruf) wird als Zitat-Titel
   genommen. Ohne KI: Der fruehere KI-Weg (GitHub Models) ist tot, der Dienst
   wurde am 2026-07-30 eingestellt; Entscheidung 2026-11-09: Zitat-Titel bleiben.
2. Gibt es keinen brauchbaren Satz: Twitch-Titel.
3. Danach immer: Streamer-Name dran, hoechstens 100 Zeichen (YouTube-Grenze).
"""

import re

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


# Clickbait-Stil (Boss, 2026-11-16: "mehr clickbait mit emojis"): Emoji passend
# zum Gesagten vorne, staerkstes Wort GROSS, Fragen enden auf "?!".
# Feinschliff im Neugier-Stil macht Asta von Hand (Weg B).
EMOJI_RULES = [
    (("haha", "lach", "lol"), "🤣"),
    (("fresse", "verpiss", "abgefuckt", "scheiß", "scheiss", "fick", "hurensohn"), "🤬"),
    (("waffe", "schieß", "schiess", "kill", "sniper"), "🔫"),
    (("tot", "gestorben", "stirb", "sterben", "falle"), "💀"),
    (("lava", "feuer", "brenn", "explod", "spreng"), "🔥"),
    (("tor", "fener", "fußball", "fussball"), "⚽"),
    (("geld", "euro", "token", "coins"), "💰"),
    (("musik", "song", "lied"), "🎵"),
    (("argument", "bruder", "digga", "lan"), "🤨"),
    (("hund", "good boy", "katze"), "🐶"),
]
FALLBACK = ["🔥", "😂", "👀", "😱"]
# diese kurzen Schluessel nur als ganzes Wort ("tor" nicht in "Motor", "lan" nicht in "Plan")
WHOLE = {"tor", "tot", "lan", "lol", "lied", "hund", "euro", "geld", "song"}
# Fuellwoerter bekommen keine Grossschrift
FILLER = {"einfach", "eigentlich", "irgendwie", "nicht", "wieder", "schon", "gerade",
          "bisschen", "wirklich", "gemacht"}


def pick_emoji(text):
    low = text.lower()
    for keys, emo in EMOJI_RULES:
        # sonst zaehlt der Wortanfang ("haha" in "Hahahaha", "lach" in "lacht")
        if any(re.search(rf"\b{re.escape(k)}\b" if k in WHOLE else rf"\b{re.escape(k)}", low)
               for k in keys):
            return emo
    if "?" in text:
        return "😳"
    return FALLBACK[sum(map(ord, text)) % len(FALLBACK)]


def stylize(t):
    """'"Hast du zwei Waffen?"' -> '🔫 "Hast du zwei WAFFEN?!"'"""
    core = t.strip()
    q = core.startswith('"') and core.endswith('"') and len(core) > 2
    inner = (core[1:-1] if q else core).rstrip(" .")
    inner = re.sub(r"\s+([?!])", r"\1", inner)            # "IMKER ?????" -> "IMKER?????"
    if re.search(r"\?[?!]*$", inner):
        inner = re.sub(r"[?!]+$", "?!", inner)            # jede Frage endet auf "?!"
    elif not inner.endswith("!"):
        inner += "!"
    words = inner.split()
    letters = lambda w: sum(ch.isalpha() for ch in w)
    weight = lambda w: letters(w) * (w.lower().strip(".,!?\"") not in FILLER)
    if words and not any(w.isupper() and letters(w) > 2 for w in words):
        best = max(range(len(words)), key=lambda i: weight(words[i]))
        if letters(words[best]) >= 4:
            words[best] = words[best].upper()
    inner = " ".join(words)
    body = f'"{inner}"' if q else inner
    return f"{pick_emoji(inner)} {body}"


def make_title(words, audio, twitch_title, name):
    """Gibt (titel, methode) zurueck. methode: 'zitat' oder 'twitch'."""
    t, method = quote_title(words, audio), "zitat"
    if not t:
        tt = (twitch_title or "").strip()
        t = tt[0].upper() + tt[1:] if len(tt) >= 6 else "Damit hat keiner gerechnet"
        method = "twitch"
    tail = f" | {name} #shorts"
    return stylize(t)[:100 - len(tail)] + tail, method
