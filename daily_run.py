"""Taeglicher Lauf fuer den Kanal "Deutschestreamerclips".

1. Holt die meistgesehenen Twitch-Clips der letzten 24 Stunden aller Streamer
   aus config.json (yt-dlp, kein Login, kein API-Schluessel noetig). Reicht
   das nicht, wird mit den Top-Clips der letzten 7 Tage aufgefuellt.
2. Waehlt die besten noch nicht hochgeladenen (posted.json), hoechstens
   max_per_streamer pro Streamer.
3. Pro Clip: Download in 1080p, Facecam finden (detect_cam.py), im
   bestaetigten Layout schneiden, Untertitel einbrennen (in EINEM
   ffmpeg-Durchlauf), hochladen (upload.py).
4. Speichert nach jedem einzelnen Erfolg sofort posted.json, damit ein
   Absturz nie zu doppelten Uploads fuehrt.

Aufruf:  python daily_run.py            (echter Lauf mit Upload)
         python daily_run.py --dry-run  (alles ausser Upload, Ergebnis in work/)
"""

import json
import os
import subprocess
from datetime import datetime, timezone
import sys
import traceback
from pathlib import Path

import detect_cam
import subtitles
import titles

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
POSTED = HERE / "posted.json"
WORK = HERE / "work"
FONTS = HERE / "fonts"
W, H = 1080, 1920
YTDLP = [sys.executable, "-m", "yt_dlp"]


def load_posted():
    return json.loads(POSTED.read_text(encoding="utf-8")) if POSTED.exists() else []


def save_posted(posted):
    POSTED.write_text(json.dumps(posted, indent=2, ensure_ascii=False), encoding="utf-8")


def list_clips(login, rng):
    out = subprocess.run(
        YTDLP + ["--flat-playlist", "--playlist-end", "15", "--print",
                 "%(url)s\t%(view_count)s\t%(duration)s\t%(title)s",
                 f"https://www.twitch.tv/{login}/clips?filter=clips&range={rng}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}).stdout or ""
    clips = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or not parts[0].startswith("http"):
            continue
        try:
            views = int(parts[1])
            dur = float(parts[2])
        except ValueError:
            continue
        clips.append({"url": parts[0], "views": views, "duration": dur,
                      "title": parts[3].strip(), "login": login})
    return clips


def pick(posted, want):
    done = {p["url"] for p in posted}
    chosen, per = [], {}
    for rng in ("24hr", "7d"):
        pool = []
        for login in CFG["streamers"]:
            pool += [c for c in list_clips(login, rng)
                     if c["url"] not in done and c["views"] >= CFG["min_views"]
                     and c["duration"] >= CFG["min_duration"]]
        for c in sorted(pool, key=lambda c: -c["views"]):
            if len(chosen) >= want:
                return chosen
            if c["url"] in {x["url"] for x in chosen}:
                continue
            if per.get(c["login"], 0) >= CFG["max_per_streamer"]:
                continue
            chosen.append(c)
            per[c["login"]] = per.get(c["login"], 0) + 1
    return chosen


def layout_filter(src_w, src_h, cam):
    """Facecam oben (falls gefunden), ganzes Spielbild darunter, Hintergrund
    unscharf. Gibt (filter, untertitel_y) zurueck."""
    game_h = 608
    bg = (f"[a]scale=-2:{H},crop={W}:{H},boxblur=20:2,eq=brightness=-0.15[bg];"
          f"[c]scale={W}:{game_h}:flags=lanczos[game];")
    if cam["mode"] == "cam":
        x, y, bw, bh = cam["box"]
        cam_h = min(760, int(W * bh / bw) // 2 * 2)
        # zu hohe Kamera-Box: mittig auf das Gesicht zuschneiden
        crop_h = min(bh, int(bw * cam_h / W) // 2 * 2)
        fy = cam["face"][1] + cam["face"][3] / 2
        cy = int(min(max(y, fy - crop_h / 2), y + bh - crop_h)) // 2 * 2
        cam_y = 120
        game_y = cam_y + cam_h + 24
        f = ("[0:v]split=3[a][b][c];" + bg +
             f"[b]crop={bw}:{crop_h}:{x}:{cy},scale={W}:{cam_h}:flags=lanczos[cam];"
             f"[bg][cam]overlay=0:{cam_y}[t1];[t1][game]overlay=0:{game_y}")
        sub_y = game_y + game_h + (H - game_y - game_h) // 2
    elif "face" in cam:
        # Kameraszene (IRL): grosses Quadrat um die Person(en), sonst sind die
        # Leute in einem flachen 16:9-Streifen winzig (Testlauf 2026-11-08).
        # Breite: mindestens quadratisch, breiter wenn mehr Personen nebeneinander
        lo, hi = cam.get("span", [0, src_w])
        cw = int(min(src_w, max(src_h, hi - lo))) // 2 * 2
        x = int(min(max(0, (lo + hi) / 2 - cw / 2), src_w - cw)) // 2 * 2
        out_h = int(W * src_h / cw) // 2 * 2
        sq_y = max(160, (H - out_h) // 2 - 220)
        f = ("[0:v]split=2[a][c];"
             f"[a]scale=-2:{H},crop={W}:{H},boxblur=20:2,eq=brightness=-0.15[bg];"
             f"[c]crop={cw}:{src_h}:{x}:0,scale={W}:{out_h}:flags=lanczos[sq];"
             f"[bg][sq]overlay=0:{sq_y}")
        sub_y = sq_y + out_h + 220
    else:
        game_y = 560
        f = ("[0:v]split=2[a][c];" + bg + f"[bg][game]overlay=0:{game_y}")
        sub_y = game_y + game_h + 250
    return f, min(sub_y, H - 140)


def render(src, out, cam, words):
    w, h, _ = detect_cam.probe(src)
    f, sub_y = layout_filter(w, h, cam)
    ass = out.with_suffix(".ass")
    ass.write_text(subtitles.build_ass(words, (W // 2, sub_y)), encoding="utf-8")
    fonts_rel = Path("..") / FONTS.name if out.parent.parent == HERE else FONTS
    f += f",ass={ass.name}:fontsdir={fonts_rel.as_posix()},format=yuv420p[v]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src.name,
                    "-filter_complex", f, "-map", "[v]", "-map", "0:a:0?",
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-r", "30",
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out.name],
                   check=True, cwd=out.parent)


def main():
    dry = "--dry-run" in sys.argv
    WORK.mkdir(exist_ok=True)
    posted = load_posted()
    # Tagessperre (2026-11-08): Es gibt einen zweiten Start als Absicherung, falls
    # GitHub den ersten verschluckt. Der holt nur nach, was heute (UTC) fehlt.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    already = sum(1 for p in posted if p.get("date") == today)
    # Sonntags einer weniger: Platz im Kontingent fuer das Langvideo (weekly.py),
    # 5 x 1.600 + 1 x 1.600 = 9.600 von 10.000 Einheiten (2026-11-09).
    sunday = datetime.now(timezone.utc).weekday() == 6
    per_day = CFG.get("clips_per_day_sunday", CFG["clips_per_day"]) if sunday else CFG["clips_per_day"]
    want = per_day - already
    if want <= 0 and not dry:
        print(f"Heute ({today}) schon {already} Clips hochgeladen, nichts zu tun.")
        gh_notice(f"Heute schon {already} Clips hochgeladen, nichts zu tun")
        return
    if dry:
        want = CFG["clips_per_day"]
    clips = pick(posted, want)
    print(f"{len(clips)} Clips ausgewaehlt:", flush=True)
    for c in clips:
        print(f"  {c['views']:>6} Aufrufe  {c['login']}: {c['title']}", flush=True)
    if not clips:
        print("Nichts Neues. Ende.")
        return

    from faster_whisper import WhisperModel
    model = WhisperModel("medium", device="cpu", compute_type="int8")
    yt = None
    if not dry:
        import upload
        try:
            yt = upload.client()
            upload.assert_channel(yt)    # bricht ab, wenn der Schluessel zum falschen Kanal gehoert
        except BaseException as e:
            gh_error(f"YouTube-Anmeldung: {type(e).__name__}: {e}")
            raise

    ok = 0
    for i, c in enumerate(clips):
        slug = c["url"].rstrip("/").rsplit("/", 1)[-1][:60]
        try:
            src = WORK / f"{slug}_src.mp4"
            subprocess.run(YTDLP + ["-q", "--no-progress", "-f", "best[height<=1080]",
                                    "-o", str(src), "--force-overwrites", c["url"]], check=True)
            cam = detect_cam.detect(src)
            print(f"[{i+1}] {c['login']}: Facecam {cam['mode']} {cam.get('box', '')}", flush=True)
            audio = subtitles.load_audio(src)
            words = subtitles.transcribe(model, src, audio)
            name = CFG["streamers"][c["login"]]
            yt_title, how = titles.make_title(words, audio, c["title"], name)
            print(f"    Titel ({how}): {yt_title}", flush=True)
            out = WORK / f"{slug}.mp4"
            render(src, out, cam, words)
            if dry:
                print(f"    fertig (Testlauf): {out}", flush=True)
                continue
            vid = upload.upload(yt, out, c, name, CFG["privacy"], title=yt_title)
            gh_notice(f"Titel ({how}): {yt_title}")
            posted.append({"url": c["url"], "login": c["login"], "title": c["title"],
                           "yt_title": yt_title, "title_method": how,
                           "views": c["views"], "youtube_id": vid, "date": today})
            save_posted(posted)
            ok += 1
            print(f"    hochgeladen: https://youtube.com/shorts/{vid}", flush=True)
            src.unlink(missing_ok=True)
            out.unlink(missing_ok=True)
        except Exception as e:
            print(f"[{i+1}] FEHLER bei {c['url']}, wird beim naechsten Lauf erneut versucht:",
                  flush=True)
            traceback.print_exc()
            gh_error(f"Clip {c['login']} '{c['title']}': {type(e).__name__}: {e}")
    print(f"Fertig: {ok} hochgeladen." if not dry else "Testlauf fertig.")
    if not dry:
        gh_notice(f"{ok} von {len(clips)} Clips hochgeladen")
    if not dry and ok == 0:
        sys.exit(1)


def gh_error(msg):
    """Fehler zusaetzlich als GitHub-Anmerkung ausgeben. Die Job-Protokolle
    sind nur eingeloggt lesbar, Anmerkungen eines oeffentlichen Repos per API
    auch ohne Login (2026-11-08: zweiter Lauf scheiterte, Grund unsichtbar)."""
    if os.environ.get("GITHUB_ACTIONS"):
        print("::error::" + " ".join(str(msg).split())[:900], flush=True)


def gh_notice(msg):
    if os.environ.get("GITHUB_ACTIONS"):
        print("::notice::" + " ".join(str(msg).split())[:900], flush=True)


if __name__ == "__main__":
    main()
