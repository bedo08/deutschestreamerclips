"""Rendert aus crop_plan.json (Ausgabe von smart_crop.py) fertige 1080x1920-
Hochkant-Clips. Zuschnitt+Skalierung in einem ffmpeg-Durchlauf, leichte
Lautstaerke-Normalisierung (loudnorm) gegen springende Lautstaerke zwischen
Clips, H.264/AAC fuer YouTube/TikTok/Shorts-Kompatibilitaet.
"""

import json
import subprocess
import sys
from pathlib import Path


def render(video_path, plan, out_path):
    crop = f"crop={plan['crop_w']}:{plan['crop_h']}:{plan['crop_x']}:{plan['crop_y']}"
    vf = f"{crop},scale=1080:1920:flags=lanczos"
    cmd = [
        "ffmpeg", "-y", "-ss", str(plan["start"]), "-i", str(video_path),
        "-t", str(plan["end"] - plan["start"]),
        "-vf", vf, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k",
        "-loglevel", "error", str(out_path),
    ]
    subprocess.run(cmd, check=True)


def main():
    video_path = Path(sys.argv[1])
    plan_path = Path(sys.argv[2] if len(sys.argv) > 2 else "crop_plan.json")
    out_dir = Path(sys.argv[3] if len(sys.argv) > 3 else "clips")
    out_dir.mkdir(exist_ok=True)

    plans = json.loads(plan_path.read_text(encoding="utf-8"))
    for i, plan in enumerate(plans):
        out_path = out_dir / f"clip_{i}_{int(plan['peak_time'])}.mp4"
        print(f"Rendere {out_path} ...")
        render(video_path, plan, out_path)
    print("Fertig.")


if __name__ == "__main__":
    main()
