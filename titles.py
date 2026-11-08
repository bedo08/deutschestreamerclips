"""Baut knackige YouTube-Titel aus dem, was im Clip gesagt wird.

Anlass (Boss, 2026-11-08): Die Twitch-Clip-Titel sind oft nichtssagend
("F", "Falle"), und der Titel entscheidet bei Shorts viel ueber die Reichweite.

1. Erst GitHub Models (kostenlos in GitHub Actions ueber GITHUB_TOKEN, Workflow
   braucht `permissions: models: read`). Bekommt Transkript + Twitch-Titel,
   liefert einen kurzen deutschen Titel. Kein echtes Geld (Boss-Vorgabe).
2. Faellt das aus (lokal kein Token, Limit, Fehler): Ersatz ohne KI. Der
   markanteste Satz des Clips (laut, kurz, Ausruf) wird als Zitat-Titel genommen.
3. Danach immer: Streamer-Name dran, keine Emojis, keine langen Gedankenstriche,
   hoechstens 100 Zeichen (YouTube-Grenze).
"""

import json
import os
import re
import urllib.request

import numpy as np

MODEL = "openai/gpt-4o-mini"
ENDPOINT = "https://models.github.ai/inference/chat/completions"
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


def transcript_text(words):
    return " ".join(w.word.strip() for w in words).strip()


def ai_title(transcript, twitch_title, name):
    token = os.environ.get("GITHUB_TOKEN")
    if not token or not transcript:
        return None
    prompt = (
        f"Twitch-Clip von {name}. Original-Titel: \"{twitch_title}\".\n"
        f"Was im Clip gesagt wird (automatisch erkannt, kann Fehler enthalten):\n"
        f"\"{transcript[:1500]}\"\n\n"
        "Schreib EINEN kurzen, packenden deutschen Titel fuer YouTube Shorts, "
        "hoechstens 55 Zeichen. Er soll neugierig machen und zum Inhalt passen. "
        "Nichts erfinden, was im Clip nicht vorkommt. Keine Emojis, keine Hashtags, "
        "keine Anfuehrungszeichen, keinen Gedankenstrich, nicht den Streamer-Namen "
        "anhaengen. Antworte nur mit dem Titel."
    )
    body = json.dumps({"model": MODEL, "temperature": 0.7, "max_tokens": 40,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = json.load(r)["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"    KI-Titel nicht verfuegbar ({type(e).__name__}: {str(e)[:120]}), nehme Ersatz",
              flush=True)
        return None
    return clean(text) or None


def quote_title(words, audio):
    """Ersatz ohne KI: lautester, kurzer Satz als Zitat."""
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


def clean(text):
    t = text.strip().strip("\"'„“”").replace("—", " ").replace("–", " ")
    t = re.sub(r"#\S+", "", t)
    t = "".join(ch for ch in t if ord(ch) < 0x2190 or ch in "äöüÄÖÜß")  # Emojis raus
    return " ".join(t.split())[:70]


def make_title(words, audio, twitch_title, name):
    """Gibt (titel, methode) zurueck. methode: 'ki', 'zitat' oder 'twitch'."""
    t = ai_title(transcript_text(words), twitch_title, name)
    method = "ki"
    if not t:
        t, method = quote_title(words, audio), "zitat"
    if not t:
        tt = (twitch_title or "").strip()
        t = tt[0].upper() + tt[1:] if len(tt) >= 6 else "Damit hat keiner gerechnet"
        method = "twitch"
    return f"{t} | {name} #shorts"[:100], method
