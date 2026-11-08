"""Findet die Facecam in einem Stream-Clip automatisch.

Warum: Die Facecam sitzt bei jedem Streamer woanders und wechselt sogar beim
selben Streamer von Clip zu Clip (oben links, oben rechts, Mitte, oder die
Kamera ist bildfuellend). Eine feste Position pro Streamer funktioniert nicht
(an 8 echten Clips von xrohat, mertabimula, coachlim, mausabi geprueft,
2026-11-08).

Vorgehen:
1. 8 Bilder ueber den Clip verteilt ziehen.
2. Gesichter mit YuNet (OpenCV, models/face_detection_yunet_2023mar.onnx)
   finden. Das Gesicht, das in den meisten Bildern an derselben Stelle
   auftaucht, ist der Streamer in seiner Facecam (Gesichter im Spiel oder in
   kurz eingeblendeten Videos wandern oder verschwinden).
3. Den Rahmen der Facecam suchen: Die Kante einer eingeblendeten Kamera ist
   in jedem Bild an derselben Stelle, das Spiel daneben bewegt sich. Gesucht
   wird je Seite die Spalte/Zeile mit der staerksten, dauerhaften Kante.
   Findet sich keine klare Kante, gilt der Bildrand bzw. ein Abstand
   passend zur Gesichtsgroesse.
4. Ist das Gesicht sehr gross (bildfuellende Kamera, IRL) oder gibt es keins,
   wird Modus "full" gemeldet: dann nur das ganze Bild, ohne Kamera-Feld.

Ergebnis: {"mode": "cam"|"full", "box": [x, y, w, h], "face": [...]} in Pixeln.
"""

import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
MODEL = HERE / "models" / "face_detection_yunet_2023mar.onnx"
N_FRAMES = 8
BIG_FACE = 0.11          # Gesicht breiter als 11 % des Bildes = Kamera bildfuellend


def probe(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration", "-of", "default=nw=1",
         str(video)], capture_output=True, text=True, check=True).stdout
    vals = dict(l.split("=", 1) for l in out.strip().splitlines() if "=" in l)
    return int(vals["width"]), int(vals["height"]), float(vals["duration"])


def frames(video, w, h, dur, start=0.0, end=None):
    end = dur if end is None else end
    out = []
    for t in np.linspace(start + 0.5, max(start + 0.6, end - 0.5), N_FRAMES):
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video),
                              "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                             capture_output=True).stdout
        if len(raw) == w * h * 3:
            out.append(np.frombuffer(raw, np.uint8).reshape(h, w, 3))
    return out


def faces(imgs, w, h):
    det = cv2.FaceDetectorYN.create(str(MODEL), "", (w, h), 0.75, 0.3, 50)
    found = []
    for i, im in enumerate(imgs):
        _, res = det.detect(im)
        for f in (res if res is not None else []):
            found.append((i, *[float(v) for v in f[:4]], float(f[-1])))
    return found


def stable_face(found, n_imgs, w):
    """Gesicht, das in den meisten Bildern an fast derselben Stelle ist."""
    best, best_score = None, 0
    for _, x, y, fw, fh, _ in found:
        cx, cy = x + fw / 2, y + fh / 2
        near = [f for f in found
                if abs(f[1] + f[3] / 2 - cx) < 0.04 * w and abs(f[2] + f[4] / 2 - cy) < 0.04 * w]
        frames_hit = len({f[0] for f in near})
        score = frames_hit + 0.001 * fw
        if score > best_score:
            best_score = score
            arr = np.array([f[1:5] for f in near])
            best = (np.median(arr, axis=0), frames_hit)
    if best is None or best[1] < max(2, n_imgs // 3):
        return None
    return best[0]


def edge_profile(grays, axis, band):
    """Dauerhafte Kantenstaerke je Spalte (axis=1) oder Zeile (axis=0)."""
    profs = []
    for g in grays:
        if axis == 1:
            d = np.abs(np.diff(g[band[0]:band[1], :], axis=1)).mean(axis=0)
        else:
            d = np.abs(np.diff(g[:, band[0]:band[1]], axis=0)).mean(axis=1)
        profs.append(d)
    # 25-%-Quantil ueber die Bilder: nur Kanten, die (fast) immer da sind
    return np.percentile(np.array(profs), 25, axis=0)


def find_edge(prof, lo, hi, limit, fallback):
    lo, hi = int(max(0, lo)), int(min(limit - 1, hi))
    if hi - lo < 3:
        return fallback
    seg = prof[lo:hi]
    i = int(np.argmax(seg))
    if seg[i] > 4 * (np.median(prof) + 0.5):
        return lo + i + 1
    return fallback


def detect(video, start=0.0, end=None):
    w, h, dur = probe(video)
    imgs = frames(video, w, h, dur, start, end)
    if len(imgs) < 3:
        return {"mode": "full", "reason": "zu wenige Bilder"}
    found = faces(imgs, w, h)
    face = stable_face(found, len(imgs), w)
    if face is None:
        return {"mode": "full", "reason": "kein stabiles Gesicht"}
    fx, fy, fw, fh = [float(v) for v in face]
    if fw > BIG_FACE * w:
        return {"mode": "full", "reason": "Kamera bildfuellend", "face": [fx, fy, fw, fh]}
    cx, cy = fx + fw / 2, fy + fh / 2
    # Facecams sitzen praktisch immer am Bildrand. Ein Gesicht mitten im Bild
    # heisst: die Kamera ist das Bild (IRL), keine eingeblendete Facecam.
    # (Fall mertabimula IRL-Clip, 2026-11-08: sonst wird ein Ausschnitt mit
    # einem halben Menschen als "Facecam" gezeigt.)
    if 0.25 * w < cx < 0.75 * w and cy > 0.30 * h:
        # Breite, in der alle Personen stehen (fuer den Zuschnitt der Kameraszene)
        xs = [f[1] for f in found] + [f[1] + f[3] for f in found]
        span = [max(0.0, min(xs) - fw), min(float(w), max(xs) + fw)]
        return {"mode": "full", "reason": "Gesicht in Bildmitte", "face": [fx, fy, fw, fh],
                "span": span}
    grays = [cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32) for im in imgs]
    rows = (int(max(0, fy - fh)), int(min(h, fy + 2 * fh)))
    cols = (int(max(0, fx - fw)), int(min(w, fx + 2 * fw)))
    colp = edge_profile(grays, 1, rows)
    rowp = edge_profile(grays, 0, cols)
    reach = 5.5 * fw
    left = find_edge(colp, cx - reach, cx - 1.3 * fw, w, max(0, cx - 2.8 * fw))
    right = find_edge(colp, cx + 1.3 * fw, cx + reach, w, min(w, cx + 2.8 * fw))
    top = find_edge(rowp, cy - reach * 0.7, cy - 1.2 * fh, h, max(0, cy - 1.8 * fh))
    bottom = find_edge(rowp, cy + 1.2 * fh, cy + reach * 0.7, h, min(h, cy + 2.2 * fh))
    # Bildrand nehmen, wenn er nah ist und keine Kante gefunden wurde
    if cx - 2.8 * fw <= 0:
        left = 0 if left == max(0, cx - 2.8 * fw) else left
    if cy - 1.8 * fh <= 0:
        top = 0 if top == max(0, cy - 1.8 * fh) else top
    bw, bh = right - left, bottom - top
    box = [int(left) // 2 * 2, int(top) // 2 * 2, int(bw) // 2 * 2, int(bh) // 2 * 2]
    return {"mode": "cam", "box": box, "face": [fx, fy, fw, fh]}


def debug_image(video, result, out_png):
    w, h, dur = probe(video)
    im = frames(video, w, h, dur)[N_FRAMES // 2].copy()
    if "face" in result:
        x, y, fw, fh = map(int, result["face"])
        cv2.rectangle(im, (x, y), (x + fw, y + fh), (0, 0, 255), 4)
    if result["mode"] == "cam":
        x, y, bw, bh = result["box"]
        cv2.rectangle(im, (x, y), (x + bw, y + bh), (0, 255, 0), 6)
    cv2.putText(im, result["mode"], (40, h - 40), cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 255, 255), 6)
    cv2.imwrite(str(out_png), cv2.resize(im, (480, 270)))


if __name__ == "__main__":
    for v in sys.argv[1:]:
        r = detect(v)
        print(Path(v).name, r)
        debug_image(v, r, Path(v).with_suffix(".cam.png"))
