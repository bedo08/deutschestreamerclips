"""Kanal-Waechter: prueft jeden Abend beide YouTube-Kanaele und schickt Boss
einen kurzen Bericht per Telegram (Boss, 2026-11-08: "Waechter mit Bericht").

Prueft:
- Sind heute (UTC) bei beiden Kanaelen 4 neue Videos online? (oeffentlicher
  Video-Feed, kein Schluessel noetig)
- Gab es Fehler im heutigen Lauf von Deutschestreamerclips? (oeffentliche
  GitHub-Anmerkungen)
- Abos und Aufrufe beider Kanaele und die Veraenderung seit gestern
  (YouTube-API mit dem Schluessel von Deutschestreamerclips, der darf
  oeffentliche Zahlen jedes Kanals lesen). Verlauf in stats.json.
- Das Video mit den meisten Aufrufen unter den neuesten.

Probleme stehen im Bericht ganz oben. Keine Emojis, keine langen
Gedankenstriche (Boss' Schreibregeln).

Braucht: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID (Secrets), token.json/client_secret.json
fuer die Zahlen (sonst laeuft der Bericht ohne Zahlen).
Lokal testen: python watch.py --dry-run  (gibt den Bericht nur aus)
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATS = HERE / "stats.json"
CHANNELS = [
    {"name": "Auto Fakten Exklusiv", "id": "UCXwa75j39kDjz6In3zrPV3A", "per_day": 4},
    {"name": "Deutschestreamerclips", "id": "UCEY6LjhCRhcyY6a34SHnNoA", "per_day": 6},
]
REPO = "bedo08/deutschestreamerclips"


def http(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "kanal-waechter"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def feed(channel_id):
    """Neueste Videos aus dem oeffentlichen Feed: [(veroeffentlicht, titel, aufrufe)]."""
    xml = http(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
    out = []
    for entry in xml.split("<entry>")[1:]:
        pub = re.search(r"<published>([^<]+)", entry)
        title = re.search(r"<media:title>([^<]*)", entry)
        views = re.search(r'views="(\d+)"', entry)
        if pub and title:
            out.append((datetime.fromisoformat(pub.group(1)), unescape(title.group(1)),
                        int(views.group(1)) if views else 0))
    return out


def unescape(s):
    return (s.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
             .replace("&lt;", "<").replace("&gt;", ">"))


def channel_stats(ids):
    """Abos/Aufrufe/Videos per YouTube-API. None, wenn kein Schluessel da ist."""
    try:
        import upload
        yt = upload.client()
        res = yt.channels().list(part="statistics", id=",".join(ids)).execute()
        return {i["id"]: {k: int(v) for k, v in i["statistics"].items()
                          if isinstance(v, str) and v.isdigit()}
                for i in res.get("items", [])}
    except Exception as e:
        print(f"Zahlen nicht abrufbar: {type(e).__name__}: {e}", flush=True)
        return None


def run_problems(today):
    """Fehler des LETZTEN heutigen Laufs von Deutschestreamerclips (fruehere,
    spaeter behobene Laeufe zaehlen nicht)."""
    probs = []
    try:
        runs = json.loads(http(f"https://api.github.com/repos/{REPO}/actions/runs?per_page=20"))
        todays = [r for r in runs.get("workflow_runs", [])
                  if r["name"].startswith("Taeglicher") and r["created_at"].startswith(today)
                  and r["status"] == "completed"]
        if not todays:
            return ["Deutschestreamerclips: heute kein abgeschlossener Lauf gefunden"]
        last = max(todays, key=lambda r: r["created_at"])
        if last["conclusion"] == "success":
            return []
        probs.append(f"Deutschestreamerclips: letzter Lauf ist fehlgeschlagen ({last['html_url']})")
        for r in [last]:
            jobs = json.loads(http(r["jobs_url"]))
            for j in jobs.get("jobs", []):
                ann = json.loads(http(f"https://api.github.com/repos/{REPO}/check-runs/{j['id']}/annotations"))
                for a in ann:
                    m = a.get("message", "")
                    if a.get("annotation_level") == "failure" and "exit code" not in m:
                        probs.append(m[:200])
    except Exception as e:
        probs.append(f"Laufstatus nicht abrufbar ({type(e).__name__})")
    return probs


def fmt(n):
    return f"{n:,}".replace(",", ".")


def delta(now, before):
    if before is None:
        return ""
    d = now - before
    return f" ({'+' if d >= 0 else ''}{fmt(d)})"


def build_report():
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    hist = json.loads(STATS.read_text(encoding="utf-8")) if STATS.exists() else {}
    stats = channel_stats([c["id"] for c in CHANNELS])
    problems, blocks = [], []

    for c in CHANNELS:
        try:
            vids = feed(c["id"])
        except Exception as e:
            problems.append(f"{c['name']}: Feed nicht lesbar ({type(e).__name__})")
            continue
        today_vids = [v for v in vids if v[0].strftime("%Y-%m-%d") == today]
        if len(today_vids) < c["per_day"]:
            problems.append(f"{c['name']}: heute nur {len(today_vids)} von {c['per_day']} Videos online")
        lines = [f"{c['name']}", f"Heute: {len(today_vids)} von {c['per_day']} Videos"]
        s = (stats or {}).get(c["id"])
        if s:
            old = hist.get(yesterday, {}).get(c["id"], {})
            lines.append(f"Abos: {fmt(s.get('subscriberCount', 0))}"
                         f"{delta(s.get('subscriberCount', 0), old.get('subscriberCount'))}")
            lines.append(f"Aufrufe gesamt: {fmt(s.get('viewCount', 0))}"
                         f"{delta(s.get('viewCount', 0), old.get('viewCount'))}")
            hist.setdefault(today, {})[c["id"]] = s
        if vids:
            best = max(vids[:15], key=lambda v: v[2])
            lines.append(f"Bestes der neuesten: {best[1].replace(' #shorts', '').replace(' #Shorts', '')}"
                         f" ({fmt(best[2])} Aufrufe)")
        blocks.append("\n".join(lines))

    problems += run_problems(today)
    if stats is None:
        problems.append("Abos und Aufrufe nicht abrufbar (Schlüssel fehlt oder ungültig)")

    try:
        from zoneinfo import ZoneInfo
        local = now.astimezone(ZoneInfo("Europe/Vienna"))
    except Exception:
        local = now.astimezone(timezone(timedelta(hours=1)))
    head = f"Kanal-Wächter, {local.strftime('%d.%m.%Y')}"
    status = ("PROBLEME:\n- " + "\n- ".join(problems)) if problems else "Alles läuft."
    STATS.write_text(json.dumps(hist, indent=2), encoding="utf-8")
    return f"{head}\n{status}\n\n" + "\n\n".join(blocks), problems


def send(text):
    token = os.environ["TELEGRAM_TOKEN"].strip()
    chat = os.environ["TELEGRAM_CHAT_ID"].strip()
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    res = json.loads(http(f"https://api.telegram.org/bot{token}/sendMessage", data))
    if not res.get("ok"):
        raise RuntimeError(f"Telegram: {res}")


if __name__ == "__main__":
    report, problems = build_report()
    print(report)
    if "--dry-run" not in sys.argv:
        send(report)
        print("Bericht verschickt.")
