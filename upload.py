"""YouTube-Upload fuer Deutschestreamerclips (YouTube Data API v3).

Zugangsdaten: client_secret.json (OAuth-Client aus dem EIGENEN Google-Cloud-
Projekt dieses Kanals, nicht dem von Auto-Shorts: Tageslimit 10.000 Einheiten
pro Projekt, ein Upload kostet 1.600) und token.json. Beide nie ins Repo,
in GitHub als Secrets YT_CLIENT_SECRET / YT_TOKEN.

Einmalig lokal: python upload.py --login  -> Browser, mit dem Google-Konto
anmelden, das den Kanal "Deutschestreamerclips" besitzt, und den Kanal waehlen.
"""

import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

HERE = Path(__file__).resolve().parent
CLIENT_SECRET = HERE / "client_secret.json"
TOKEN = HERE / "token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube"]


def client(interactive=False):
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES) if TOKEN.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif interactive:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
            creds = flow.run_local_server(port=0)
        else:
            raise RuntimeError("kein gueltiger token.json, einmal 'python upload.py --login' ausfuehren")
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def make_title(clip, name):
    t = clip["title"].strip() or "Unfassbarer Moment"
    t = t[0].upper() + t[1:]
    return f"{t} | {name} #shorts"[:100]


def make_description(clip, name):
    login = clip["login"]
    return "\n".join([
        f"{name} live auf Twitch: https://www.twitch.tv/{login}",
        f"Original-Clip: {clip['url']}",
        "",
        "Die besten Momente deutscher Twitch-Streamer, jeden Tag neu.",
        "Alle Rechte an den Inhalten liegen bei den Streamern.",
        "",
        f"#shorts #{login} #twitch #deutschestreamer #clips",
    ])


def upload(yt, video, clip, name, privacy):
    body = {
        "snippet": {"title": make_title(clip, name),
                    "description": make_description(clip, name),
                    "tags": [name, clip["login"], "Twitch", "Clips", "Deutsche Streamer", "Shorts"],
                    "categoryId": "20",          # Gaming
                    "defaultLanguage": "de", "defaultAudioLanguage": "de"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(video), chunksize=-1, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]


if __name__ == "__main__":
    if "--login" in sys.argv:
        yt = client(interactive=True)
        ch = yt.channels().list(part="snippet", mine=True).execute()
        for item in ch.get("items", []):
            print("Angemeldet fuer Kanal:", item["snippet"]["title"])
