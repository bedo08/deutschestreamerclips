"""Bestimmt pro Clip automatisch einen Hochkant-Ausschnitt (9:16), der die
Browser-/UI-Leiste oben zuverlaessig draussen laesst und den Bildausschnitt
auf die bildlich aktivste Spalte (= Gameplay, nicht Chat/Minimap-Rand) legt,
statt eines starren Mitte-Crops.

Vorgehen (reine ffmpeg+numpy-Pipeline, kein zusaetzliches Paket noetig):
1. Mehrere Sample-Frames ueber die Clip-Dauer per ffmpeg als rohe RGB-Bytes
   holen (gleiches Muster wie find_highlights.py fuer Audio).
2. Oberen UI-Streifen erkennen: Zeilen, die ueber alle Sample-Frames hinweg
   fast keine Bewegung zeigen (statische Browserleiste/HUD-Kante), werden
   vom nutzbaren Bild abgezogen. Deckel bei 20% der Hoehe, damit ein falsch
   positiver Treffer nicht echtes Gameplay frisst.
3. Im verbleibenden Bild die Spalte mit der hoechsten Kantenenergie (Sobel-
   aehnliche Gradientensumme, ueber die Sample-Frames gemittelt) als Zentrum
   fuer ein 9:16-Fenster waehlen. Hohe Kantendichte = viel visuelle Aktivitaet
   = typischerweise die Spielszene, nicht der eher gleichfoermige Chat-Text
   oder die kleine Minimap-Ecke.
4. Daraus ein ffmpeg crop=w:h:x:y liefern, das render_clips.py nutzt.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np


def ffprobe_size(video_path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    w, h = out.split(",")
    return int(w), int(h)


def grab_frame(video_path, t, w, h):
    cmd = [
        "ffmpeg", "-ss", str(t), "-i", str(video_path), "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
        "-loglevel", "error", "-",
    ]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    expected = w * h * 3
    if len(raw) != expected:
        return None
    return np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3).astype(np.float32)


def detect_top_bar(frames, h, max_frac=0.20):
    """Findet die hoechste Zeile y0, ab der sich zwischen den Sample-Frames
    wirklich was bewegt (echtes Gameplay) statt eines statischen UI-Streifens."""
    if len(frames) < 2:
        return 0
    gray = [f.mean(axis=2) for f in frames]
    diffs = [np.abs(gray[i] - gray[i - 1]) for i in range(1, len(gray))]
    row_motion = np.mean([d.mean(axis=1) for d in diffs], axis=0)  # pro Zeile
    cap = int(h * max_frac)
    threshold = max(row_motion[cap:].mean() * 0.15, 1.0)
    y0 = 0
    for y in range(cap):
        if row_motion[y] > threshold:
            break
        y0 = y + 1
    return y0


def detect_best_column_window(frames, y0, w, h, target_w):
    """Sucht das target_w breite Fenster mit der meisten echten Bewegung
    ueber die Zeit (Frame-zu-Frame-Differenz), nicht der meisten Kantenenergie
    in einem Einzelbild. Standbild-Text (Chat) hat viele Kanten, aber wenig
    Bewegung; Gameplay bewegt sich staendig (Kamera, Mobs, Spieler). Reine
    Kantenenergie waehlte faelschlich die Chat-Spalte, Bewegungsenergie waehlt
    die tatsaechlich aktive Szene."""
    region = [f[y0:, :, :].mean(axis=2) for f in frames]
    if len(region) < 2:
        return 0
    motion_energy = np.zeros(w)
    for i in range(1, len(region)):
        diff = np.abs(region[i] - region[i - 1])
        col_energy = diff.sum(axis=0)
        motion_energy[: len(col_energy)] += col_energy
    if target_w >= w:
        return 0
    cumsum = np.cumsum(np.insert(motion_energy, 0, 0))
    window_sums = cumsum[target_w:] - cumsum[:-target_w]
    x0 = int(np.argmax(window_sums))
    return x0


def plan_crop(video_path, start, end, n_samples=6):
    w, h = ffprobe_size(video_path)
    times = np.linspace(start + 1, end - 1, n_samples)
    frames = [f for t in times if (f := grab_frame(video_path, t, w, h)) is not None]
    if len(frames) < 2:
        raise RuntimeError("zu wenige Sample-Frames extrahiert")

    y0 = detect_top_bar(frames, h)
    usable_h = h - y0
    target_w = round(usable_h * 9 / 16)
    if target_w > w:
        # Quelle ist schmaler als 9:16 bei voller Hoehe -> Hoehe stattdessen kappen
        target_w = w
        usable_h = round(target_w * 16 / 9)
    x0 = detect_best_column_window(frames, y0, w, h, target_w)
    x0 = min(x0, w - target_w)

    return {
        "source_w": w, "source_h": h,
        "crop_x": x0, "crop_y": y0, "crop_w": target_w, "crop_h": usable_h,
    }


def main():
    video_path = Path(sys.argv[1])
    highlights = json.loads(Path(sys.argv[2] if len(sys.argv) > 2 else "highlights.json").read_text(encoding="utf-8"))

    plans = []
    for i, hl in enumerate(highlights):
        plan = plan_crop(video_path, hl["start"], hl["end"])
        plan.update(hl)
        plans.append(plan)
        print(f"Clip {i}: crop={plan['crop_w']}x{plan['crop_h']} @ ({plan['crop_x']},{plan['crop_y']}) "
              f"(oberer UI-Streifen: {plan['crop_y']}px entfernt)")

    Path("crop_plan.json").write_text(json.dumps(plans, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
