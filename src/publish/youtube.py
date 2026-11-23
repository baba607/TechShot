"""Tech Shot — publish to YouTube Shorts (YouTube Data API v3, free).

OAuth: the refresh token (YOUTUBE_REFRESH_TOKEN) + client id/secret are
exchanged for a short-lived access token at
https://oauth2.googleapis.com/token — no browser sign-in at publish time.

Upload: resumable session (single PUT is fine for ~8 MB reels), part
snippet+status. privacyStatus comes from config YOUTUBE_PRIVACY, default
"private": the Cloud project is NOT audited yet, so public uploads are not
possible until Google verification — do not set "public" before that.

Quota: 1 upload = 1,600 units of the 10,000/day free quota (~6/day; the
3/day target fits comfortably).

`dry_run=True` prints the calls that WOULD be made, no HTTP.
"""

import json

import requests

import config

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


def _access_token():
    config.require_secrets("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET",
                           "YOUTUBE_REFRESH_TOKEN")
    resp = requests.post(TOKEN_URL, data={
        "client_id": config.YOUTUBE_CLIENT_ID,
        "client_secret": config.YOUTUBE_CLIENT_SECRET,
        "refresh_token": config.YOUTUBE_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Token refresh failed ({resp.status_code}): "
                           f"{resp.text[:200]}")
    return resp.json()["access_token"]


def publish(video_path, title, description, tags, dry_run=False):
    """Upload a Short. Returns {ok, platform, video_id|None, detail}."""
    if dry_run:
        print(f"[youtube:dry-run] POST {TOKEN_URL} (refresh -> access token)")
        print(f"[youtube:dry-run] POST {UPLOAD_URL}?uploadType=resumable "
              f"{{snippet: title=<{len(title)} chars>, tags={len(tags)}>, "
              f"status: privacyStatus={config.YOUTUBE_PRIVACY}}}")
        print("[youtube:dry-run] PUT video bytes (single chunk)")
        return {"ok": True, "platform": "youtube", "dry_run": True,
                "detail": "Dry run — no API calls made."}
    token = _access_token()
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json; charset=UTF-8",
               "X-Upload-Content-Type": "video/mp4"}
    body = {"snippet": {"title": title, "description": description,
                        "tags": tags, "categoryId": "28"},
            "status": {"privacyStatus": config.YOUTUBE_PRIVACY}}
    data = open(video_path, "rb").read()
    headers["X-Upload-Content-Length"] = str(len(data))
    session = requests.post(
        f"{UPLOAD_URL}?uploadType=resumable&part=snippet,status",
        headers=headers, data=json.dumps(body), timeout=60)
    if session.status_code != 200:
        return {"ok": False, "platform": "youtube",
                "detail": f"Upload session failed ({session.status_code}): "
                          f"{session.text[:300]}"}
    upload_url = session.headers.get("Location")
    put = requests.put(upload_url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "video/mp4",
        "Content-Length": str(len(data))}, data=data, timeout=600)
    if put.status_code not in (200, 201):
        return {"ok": False, "platform": "youtube",
                "detail": f"Upload failed ({put.status_code}): {put.text[:300]}"}
    vid = put.json().get("id")
    url = f"https://www.youtube.com/shorts/{vid}"
    return {"ok": True, "platform": "youtube", "video_id": vid,
            "detail": f"Uploaded Short ({config.YOUTUBE_PRIVACY}): {url}"}
