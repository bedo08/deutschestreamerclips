"""Rendert Hochkant-Clips (1080x1920) im bestaetigten Layout (Boss, 2026-11-08):

    +------------------------+
    |  Facecam des Streamers |  oben, volle Breite
    +------------------------+
    |  komplettes Spielbild  |  ganzes 16:9-Bild, nichts abgeschnitten
    +------------------------+
    |  Platz fuer Titel/Text |
    +------------------------+
    Hintergrund: dasselbe Bild, unscharf und abgedunkelt.

Ersetzt smart_crop.py + render_clips.py (schmaler Mittelstreifen ohne
Facecam, von Boss abgelehnt).

Die Position der Facecam steht in layout.json als Anteil von Breite/Hoehe
(0..1), damit sie fuer jede Aufloesung gilt und pro Streamer angepasst
werden kann.

Aufruf: python render_layout.py <video> [highlights.json] [ausgabeordner]
"""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
W, H = 1080, 1920
CAM_Y, CAM_H = 150, 608      # Facecam-Feld oben
GAME_Y, GAME_H = 820, 608    # Spielbild darunter (1080x608 = 16:9)


def ffprobe_size(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def even(x):
    return int(x) // 2 * 2


def build_filter(src_w, src_h, cam):
    cx, cy = even(cam["x"] * src_w), even(cam["y"] * src_h)
    cw, ch = even(cam["w"] * src_w), even(cam["h"] * src_h)
    return (
        "[0:v]split=3[a][b][c];"
        f"[a]scale=-2:{H},crop={W}:{H},boxblur=20:2,eq=brightness=-0.15[bg];"
        f"[b]crop={cw}:{ch}:{cx}:{cy},scale={W}:{CAM_H}:flags=lanczos[cam];"
        f"[c]scale={W}:{GAME_H}:flags=lanczos[game];"
        f"[bg][cam]overlay=0:{CAM_Y}[t1];"
        f"[t1][game]overlay=0:{GAME_Y},format=yuv420p[v]"
    )


def render(video, start, end, out, cam, frame_only=False):
    src_w, src_h = ffprobe_size(video)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-i", str(video)]
    if frame_only:
        cmd += ["-filter_complex", build_filter(src_w, src_h, cam),
                "-map", "[v]", "-frames:v", "1", str(out)]
    else:
        cmd += ["-t", str(end - start),
                "-filter_complex", build_filter(src_w, src_h, cam),
                "-map", "[v]", "-map", "0:a:0?",
                "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                "-r", "30", "-c:a", "aac", "-b:a", "160k",
                "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)


def main():
    video = Path(sys.argv[1])
    highlights = json.loads(Path(sys.argv[2] if len(sys.argv) > 2
                                 else HERE / "highlights.json").read_text(encoding="utf-8"))
    out_dir = Path(sys.argv[3] if len(sys.argv) > 3 else HERE / "clips_final")
    out_dir.mkdir(exist_ok=True)
    cam = json.loads((HERE / "layout.json").read_text(encoding="utf-8"))["facecam"]

    for i, hl in enumerate(highlights):
        name = f"clip_{i}_{int(hl['peak_time'])}"
        print(f"Rendere {name} ...", flush=True)
        render(video, hl["start"], hl["end"], out_dir / f"{name}.mp4", cam)
        # Kontrollbild aus der Clip-Mitte, fuer die Abnahme ansehen
        mid = (hl["start"] + hl["end"]) / 2
        render(video, mid, mid, out_dir / f"{name}_check.png", cam, frame_only=True)
    print("Fertig.")


if __name__ == "__main__":
    main()
