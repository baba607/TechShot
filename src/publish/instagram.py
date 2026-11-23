"""Tech Shot — publish to Instagram Reels (Instagram Graph API, free).

Container flow (no direct file upload — Instagram needs a public video URL):
  1. POST /{ig-user-id}/media  {media_type: REELS, video_url, caption}
     -> container id
  2. GET /{container-id}?fields=status_code  until FINISHED (poll, max ~10 min)
  3. POST /{ig-user-id}/media_publish {creation_id} -> media id (published)

Auth: long-lived Page access token (FACEBOOK_PAGE_ACCESS_TOKEN) + the IG
business account id (INSTAGRAM_BUSINESS_ACCOUNT_ID). The token is read from
the environment only — never logged, never stored in the repo.

`dry_run=True` prints the exact calls that WOULD be made and returns
without any HTTP request (used by tests and `pipeline.py publish --dry-run`).
"""

import time

import requests

import config

POLL_INTERVAL = 10
POLL_MAX_ATTEMPTS = 60
# Thumbnail frame for the Reels grid, in milliseconds. Instagram uses the
# video's first frame as the thumbnail by default — our videos used to
# fade in from black, so all 3 reels showed as black tiles (2026-11-24).
# 2000 ms lands safely inside scene 1 on every reel (30-45 s long).
THUMB_OFFSET_MS = 2000


def _headers():
    return {"Authorization": f"Bearer {config.FACEBOOK_PAGE_ACCESS_TOKEN}"}


def publish(video_url, caption, dry_run=False, ig_user_id=None):
    """Publish a Reel. Returns {ok, platform, media_id|None, detail}."""
    ig_user_id = ig_user_id or config.INSTAGRAM_BUSINESS_ACCOUNT_ID
    if not dry_run:
        config.require_secrets("FACEBOOK_PAGE_ACCESS_TOKEN",
                               "INSTAGRAM_BUSINESS_ACCOUNT_ID")
    if not video_url:
        return {"ok": False, "platform": "instagram",
                "detail": "No public video URL — set TECHSHOT_VIDEO_PUBLIC_URL "
                          "(Instagram cannot upload a file directly)."}
    if dry_run:
        print("[instagram:dry-run] POST "
              f"{config.GRAPH_API_BASE}/{ig_user_id}/media "
              "{media_type: REELS, video_url: <hidden>, caption: <len "
              f"{len(caption)}>, thumb_offset: {THUMB_OFFSET_MS}}}")
        print("[instagram:dry-run] poll container status until FINISHED, "
              "then POST media_publish")
        return {"ok": True, "platform": "instagram", "dry_run": True,
                "detail": "Dry run — no API calls made."}

    base = config.GRAPH_API_BASE
    resp = requests.post(f"{base}/{ig_user_id}/media", headers=_headers(),
                         data={"media_type": "REELS", "video_url": video_url,
                               "caption": caption,
                               "thumb_offset": THUMB_OFFSET_MS},
                         timeout=60)
    if resp.status_code != 200:
        return {"ok": False, "platform": "instagram",
                "detail": f"Container create failed ({resp.status_code}): "
                          f"{resp.text[:300]}"}
    container_id = resp.json().get("id")
    for _ in range(POLL_MAX_ATTEMPTS):
        st = requests.get(f"{base}/{container_id}",
                          headers=_headers(),
                          params={"fields": "status_code"}, timeout=30)
        code = st.json().get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            return {"ok": False, "platform": "instagram",
                    "detail": f"Container {container_id} failed processing."}
        time.sleep(POLL_INTERVAL)
    else:
        return {"ok": False, "platform": "instagram",
                "detail": "Container did not finish processing in time."}
    pub = requests.post(f"{base}/{ig_user_id}/media_publish",
                        headers=_headers(),
                        data={"creation_id": container_id}, timeout=60)
    if pub.status_code != 200:
        return {"ok": False, "platform": "instagram",
                "detail": f"Publish failed ({pub.status_code}): {pub.text[:300]}"}
    return {"ok": True, "platform": "instagram",
            "media_id": pub.json().get("id"),
            "detail": f"Published Reel, media id {pub.json().get('id')}"}
