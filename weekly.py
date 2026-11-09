"""Woechentliches Langvideo "Die besten Clips der Woche" (seit 2026-11-09).

Anlass (Boss, 2026-11-09): Einnahmen ueber lange Videos. Die bringen pro
Aufruf deutlich mehr als Shorts und zaehlen fuer die 4.000 Wiedergabestunden.

Ablauf (laeuft im taeglichen Workflow NACH daily_run.py, macht aber nur
sonntags (UTC) etwas und nur einmal pro Kalenderwoche, siehe weekly.json):
1. Nimmt aus posted.json die hochgeladenen Clips der letzten 7 Tage, die
   meistgesehenen zuerst, hoechstens MAX_CLIPS, mindestens MIN_CLIPS.
2. Laedt die Original-Clips (16:9) neu von Twitch, wirft zu kurze raus
   (Kapitelmarken brauchen mind. 10 s je Abschnitt).
3. Baut jeden Clip als einheitliches 1920x1080-Stueck mit Einblendung
   "#Platz Streamer" und dem Clip-Titel, dazu Intro und Outro.
   Countdown-Reihenfolge: der beste Clip kommt zuletzt.
4. Klebt alles zusammen, laedt hoch (Querformat, kein #shorts),
   Beschreibung mit Kapitelmarken, Streamer nur als Text (keine Links).

Kontingent: Upload kostet 1.600 Einheiten. Sonntags laedt daily_run.py
deshalb nur clips_per_day_sunday (5) Shorts hoch: 5 + 1 = 9.600 < 10.000.

Aufruf:  python weekly.py            (nur sonntags, mit Upload)
         python weekly.py --force    (jeden Tag, mit Upload)
         python weekly.py --dry-run  (jeden Tag, ohne Upload, Ergebnis in work/weekly/)
"""

import json
import os
import subprocess
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
POSTED = HERE / "posted.json"
STATE = HERE / "weekly.json"
WORK = HERE / "work" / "weekly"
FONT_BIG = HERE / "fonts" / "Anton-Regular.ttf"
FONT_TXT = HERE / "fonts" / "Poppins-Bold.ttf"
YTDLP = [sys.executable, "-m", "yt_dlp"]
MAX_CLIPS = 15
MIN_CLIPS = 8
MIN_SECONDS = 10.5
W, H, FPS = 1920, 1080, 30
ENC = ["-c:v", "libx264", "-preset", "faster", "-crf", "20", "-r", str(FPS),
       "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


def gh(kind, msg):
    print(msg, flush=True)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{kind}::" + " ".join(str(msg).split())[:900], flush=True)


def load_state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else []


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration:stream=codec_type", "-of", "json", str(path)],
                         capture_output=True, text=True).stdout
    info = json.loads(out or "{}")
    dur = float(info.get("format", {}).get("duration", 0) or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    return dur, has_audio


def pick(posted, today):
    since = (today - timedelta(days=6)).strftime("%Y-%m-%d")   # 7 Tage inkl. heute
    week = [p for p in posted if p.get("date", "") >= since and p.get("url")]
    return sorted(week, key=lambda p: -int(p.get("views", 0)))


def write_txt(name, text):
    """drawtext liest den Text aus einer Datei: keine Probleme mit
    Doppelpunkten, Anfuehrungszeichen oder Prozentzeichen im Titel."""
    p = WORK / name
    p.write_text(text, encoding="utf-8")
    return p.name


def card(name, lines, seconds):
    """Einfarbige Texttafel (Intro/Outro) mit Stille."""
    out = WORK / name
    draws = []
    for i, (text, size, font, color, y) in enumerate(lines):
        f = write_txt(f"{out.stem}_{i}.txt", text)
        draws.append(f"drawtext=fontfile='{font}':textfile={f}:fontsize={size}:"
                     f"fontcolor={color}:x=(w-text_w)/2:y={y}")
    vf = ",".join(draws) + f",fade=t=in:st=0:d=0.4,fade=t=out:st={seconds - 0.4}:d=0.4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"color=c=0x0f1115:s={W}x{H}:d={seconds}:r={FPS}",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                    "-vf", vf, "-t", str(seconds), *ENC, out.name],
                   check=True, cwd=WORK)
    return out


def segment(src, out, rank, name, title, has_audio):
    """Ein Clip als 1920x1080-Stueck mit Einblendung oben links."""
    rank_f = write_txt(f"{out.stem}_rank.txt", f"#{rank}  {name}")
    title_f = write_txt(f"{out.stem}_title.txt", title[:60])
    big, txt = FONT_BIG.relative_to(HERE).as_posix(), FONT_TXT.relative_to(HERE).as_posix()
    big, txt = "../../" + big, "../../" + txt
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,fps={FPS},"
          f"drawtext=fontfile='{big}':textfile={rank_f}:fontsize=64:fontcolor=white:"
          f"box=1:boxcolor=0xf5a623@0.92:boxborderw=18:x=40:y=40,"
          f"drawtext=fontfile='{txt}':textfile={title_f}:fontsize=40:fontcolor=white:"
          f"box=1:boxcolor=black@0.6:boxborderw=14:x=40:y=150:enable='lt(t,4)',"
          f"fade=t=in:st=0:d=0.25")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", src.name]
    if has_audio:
        cmd += ["-vf", vf, "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-map", "0:v:0", "-map", "0:a:0"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-vf", vf,
                "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    subprocess.run(cmd + [*ENC, out.name], check=True, cwd=WORK)


def stamp(sec):
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 \
        else f"{sec // 60}:{sec % 60:02d}"


def main():
    dry = "--dry-run" in sys.argv
    force = "--force" in sys.argv or dry
    now = datetime.now(timezone.utc)
    week_id = now.strftime("%G-W%V")
    if not force and now.weekday() != 6:
        print("Langvideo nur sonntags, heute nichts zu tun.")
        return
    state = load_state()
    if not dry and any(s.get("week") == week_id for s in state):
        gh("notice", f"Langvideo fuer {week_id} schon hochgeladen, nichts zu tun")
        return

    posted = json.loads(POSTED.read_text(encoding="utf-8")) if POSTED.exists() else []
    cands = pick(posted, now)
    if len(cands) < MIN_CLIPS:
        gh("warning", f"Langvideo: nur {len(cands)} Clips in den letzten 7 Tagen, mindestens {MIN_CLIPS} noetig")
        return

    WORK.mkdir(parents=True, exist_ok=True)
    for old in WORK.iterdir():
        old.unlink()

    # Clips holen, zu kurze oder kaputte ueberspringen
    ok = []
    for i, c in enumerate(cands):
        if len(ok) >= MAX_CLIPS:
            break
        src = WORK / f"src_{i:02d}.mp4"
        try:
            subprocess.run(YTDLP + ["-q", "--no-progress", "-f", "best[height<=1080]",
                                    "-o", str(src), "--force-overwrites", c["url"]], check=True)
            dur, has_audio = probe(src)
            if dur < MIN_SECONDS:
                print(f"  zu kurz ({dur:.1f}s): {c['title']}", flush=True)
                continue
            ok.append({**c, "src": src, "dur": dur, "audio": has_audio})
        except Exception as e:
            print(f"  Download fehlgeschlagen: {c['url']}: {e}", flush=True)
    if len(ok) < MIN_CLIPS:
        gh("warning", f"Langvideo: nur {len(ok)} brauchbare Clips, mindestens {MIN_CLIPS} noetig")
        return

    # Countdown: Platz N (schwaechster) zuerst, Platz 1 (meistgesehen) zuletzt
    n = len(ok)
    order = list(reversed(ok))
    first = (now - timedelta(days=6)).strftime("%d.%m.")
    last = now.strftime("%d.%m.%Y")
    names = []
    for c in ok:
        nm = CFG["streamers"].get(c["login"], c["login"])
        if nm not in names:
            names.append(nm)

    intro = card("intro.mp4", [
        ("DIE BESTEN CLIPS DER WOCHE", 110, "../../fonts/Anton-Regular.ttf", "white", "(h/2)-150"),
        (f"{first} bis {last}", 54, "../../fonts/Poppins-Bold.ttf", "0xf5a623", "(h/2)+10"),
        (", ".join(names), 44, "../../fonts/Poppins-Bold.ttf", "0xb0b6bf", "(h/2)+100"),
    ], 3.5)
    outro = card("outro.mp4", [
        ("JEDEN TAG NEUE CLIPS", 100, "../../fonts/Anton-Regular.ttf", "white", "(h/2)-110"),
        ("Deutschestreamerclips abonnieren", 56, "../../fonts/Poppins-Bold.ttf", "0xf5a623", "(h/2)+40"),
    ], 4.0)

    parts, chapters, t = [intro], [], probe(intro)[0]
    for pos, c in enumerate(order):
        rank = n - pos
        name = CFG["streamers"].get(c["login"], c["login"])
        title = (c.get("title") or "").strip() or "Unfassbarer Moment"
        out = WORK / f"seg_{pos:02d}.mp4"
        segment(c["src"], out, rank, name, title, c["audio"])
        start = 0 if pos == 0 else t           # erstes Kapitel muss bei 0:00 beginnen
        chapters.append(f"{stamp(start)} Platz {rank}: {name}, {title[:60]}")
        t += probe(out)[0]
        parts.append(out)
        print(f"  Platz {rank}: {name}: {title}", flush=True)
    parts.append(outro)

    lst = WORK / "list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    final = WORK / "weekly.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", lst.name, "-c", "copy", "-movflags", "+faststart", final.name],
                   check=True, cwd=WORK)
    total, _ = probe(final)
    title = f"Die besten Clips der Woche | {', '.join(names)}"
    title = title if len(title) <= 100 else "Die besten Clips der Woche | Deutsche Streamer"
    desc = "\n".join([
        f"Die {n} meistgesehenen Clips der Woche ({first} bis {last}), Platz {n} bis Platz 1.",
        "",
        *chapters,
        "",
        "Streamer (alle live auf Twitch): " + ", ".join(
            f"{CFG['streamers'].get(l, l)} ({l})" for l in dict.fromkeys(c["login"] for c in ok)),
        "Alle Rechte an den Inhalten liegen bei den Streamern.",
        "",
        "#twitch #deutschestreamer #clips #bestof",
    ])
    gh("notice", f"Langvideo gebaut: {n} Clips, {stamp(total)} Min.")
    if dry:
        (WORK / "beschreibung.txt").write_text(title + "\n\n" + desc, encoding="utf-8")
        print(f"Testlauf fertig: {final}")
        return

    import upload
    yt = upload.client()
    upload.assert_channel(yt)
    body = {
        "snippet": {"title": title, "description": desc,
                    "tags": names + ["Twitch", "Clips", "Best of", "Deutsche Streamer", "Highlights"],
                    "categoryId": "20", "defaultLanguage": "de", "defaultAudioLanguage": "de"},
        "status": {"privacyStatus": CFG["privacy"], "selfDeclaredMadeForKids": False},
    }
    from googleapiclient.http import MediaFileUpload
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(final), chunksize=-1, resumable=True,
                                                        mimetype="video/mp4"))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]
    state.append({"week": week_id, "date": now.strftime("%Y-%m-%d"), "youtube_id": vid,
                  "clips": [c["url"] for c in ok], "duration": round(total)})
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    gh("notice", f"Langvideo hochgeladen: https://youtu.be/{vid} ({stamp(total)} Min.)")
    for p in WORK.iterdir():
        p.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        traceback.print_exc()
        gh("error", f"Langvideo: {type(e).__name__}: {e}")
        sys.exit(1)
