"""Blendet die gesprochenen Woerter als Untertitel in fertige Clips ein
(Boss, 2026-11-08: "vergiss nicht die gesprochenen woerter auch einzublenden").

Ablauf pro Clip:
1. Audio lokal mit faster-whisper (Modell "medium", Deutsch) erkennen, mit
   Zeitstempel pro Wort.
2. Woerter in kurze Haeppchen (max. 3 Woerter) teilen und als ASS-Untertitel
   schreiben: das gerade gesprochene Wort leuchtet gelb, der Rest ist weiss.
   Position: das freie Feld unter dem Spielbild (render_layout.py).
3. Mit ffmpeg einbrennen -> <clip>_sub.mp4.

Laeuft mit der Python-Umgebung von backtalk (dort ist faster-whisper drin):
  <backtalk>/.venv/Scripts/python.exe -I subtitles.py clips_final
"""

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

HERE = Path(__file__).resolve().parent
MODEL = "medium"
MAX_WORDS = 3
POS = (540, 1660)        # Mitte des freien Feldes unter dem Spielbild
WHITE, YELLOW = "&H00FFFFFF", "&H0000E5FF"   # ASS-Farben: &HAABBGGRR

HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Anton,96,{WHITE},{WHITE},&H00000000,&H80000000,0,0,0,0,100,100,1,0,1,7,3,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ts(t):
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def clean(word):
    return word.strip().replace("{", "").replace("}", "").upper()


def chunks(words):
    group = []
    for w in words:
        group.append(w)
        ends_sentence = w.word.strip()[-1:] in ".!?,"
        if len(group) >= MAX_WORDS or ends_sentence:
            yield group
            group = []
    if group:
        yield group


def load_audio(video):
    """Audio als 16-kHz-Mono-Array. Per ffmpeg, weil faster-whispers eigener
    Decoder (PyAV) in der backtalk-Umgebung nicht zur av-Version passt."""
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-vn",
                          "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(model, video, audio=None):
    """Woerter mit Zeitstempeln."""
    if audio is None:
        audio = load_audio(video)
    if audio.size == 0:
        return []
    segments, _ = model.transcribe(audio, language="de", word_timestamps=True,
                                   vad_filter=True, beam_size=5)
    return [w for s in segments for w in (s.words or []) if w.word.strip()]


def build_ass(words, pos=POS):
    events = []
    for group in chunks(words):
        texts = [clean(w.word) for w in group]
        for i, w in enumerate(group):
            end = group[i + 1].start if i + 1 < len(group) else w.end + 0.15
            parts = [(f"{{\\c{YELLOW}}}{t}{{\\c{WHITE}}}" if j == i else t)
                     for j, t in enumerate(texts)]
            events.append([w.start, end, " ".join(parts)])
    # nie zwei Zeilen gleichzeitig: jede endet spaetestens, wenn die naechste beginnt
    for cur, nxt in zip(events, events[1:]):
        cur[1] = min(cur[1], nxt[0])
    lines = [HEADER]
    for start, end, text in events:
        if end - start < 0.02:
            continue
        lines.append(f"Dialogue: 0,{ts(start)},{ts(end)},Sub,,0,0,0,,"
                     f"{{\\pos({pos[0]},{pos[1]})}}{text}")
    return "\n".join(lines) + "\n"


def main():
    clip_dir = Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "clips_final")
    clips = sorted(p for p in clip_dir.glob("clip_*.mp4") if not p.stem.endswith("_sub"))
    print(f"Lade Whisper {MODEL} ...", flush=True)
    model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    fonts = HERE / "fonts"

    for clip in clips:
        print(f"Erkenne Sprache in {clip.name} ...", flush=True)
        # Audio selbst per ffmpeg laden: faster-whispers eigener Decoder (PyAV)
        # passt in der backtalk-Umgebung nicht zur installierten av-Version.
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(clip), "-vn",
                              "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                             capture_output=True, check=True).stdout
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = model.transcribe(audio, language="de", word_timestamps=True,
                                       vad_filter=True, beam_size=5)
        words = [w for s in segments for w in (s.words or []) if w.word.strip()]
        ass = clip.with_suffix(".ass")
        ass.write_text(build_ass(words), encoding="utf-8")
        print(f"  {len(words)} Woerter erkannt, brenne ein ...", flush=True)
        out = clip.with_name(clip.stem + "_sub.mp4")
        # relative Pfade im Clip-Ordner: der ass-Filter mag keine Windows-Laufwerksdoppelpunkte
        fonts_rel = Path(os.path.relpath(fonts, clip_dir.resolve()))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip.name,
                        "-vf", f"ass={ass.name}:fontsdir={fonts_rel.as_posix()}",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                        "-c:a", "copy", "-movflags", "+faststart", out.name],
                       check=True, cwd=clip_dir)
    print("Fertig.")


if __name__ == "__main__":
    main()
