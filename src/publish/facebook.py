"""Tech Shot — publish to Facebook Page Reels (Facebook Graph API, free).

Flow — the video_reels resumable upload (3 phases):
  1. start:  POST /{page-id}/video_reels {upload_phase: start, file_size}
              -> {video_id, upload_url}
  2. upload: POST {upload_url} with the raw file bytes
              (Authorization: OAuth <token>, file_offset: 0)
  3. finish: POST /{page-id}/video_reels
              {upload_phase: finish, video_id, description,
               video_state: PUBLISHED} -> {id}

The earlier attempts failed because video_reels does NOT take a plain
file upload ("(#100) The parameter upload_phase is required") and does
NOT take a bare video_url finish call ("(#100) Missing parameter:
video_id") — it needs the full start/upload/finish sequence.

`dry_run=True` prints the calls that WOULD be made, no HTTP.
"""

import os

import requests

import config


def publish(video_path, description, dry_run=False, page_id=None):
    """Publish a Reel to the Facebook Page. Returns {ok, platform, ...}."""
    page_id = page_id or config.FACEBOOK_PAGE_ID
    size = os.path.getsize(video_path)
    base = f"{config.GRAPH_API_BASE}/{page_id}/video_reels"
    if dry_run:
        print(f"[facebook:dry-run] 1) POST {base} "
              "{upload_phase: start, file_size: "
              f"{size}}} -> {{video_id, upload_url}}")
        print("[facebook:dry-run] 2) POST {upload_url} "
              f"<{size} bytes, file_offset: 0>")
        print(f"[facebook:dry-run] 3) POST {base} "
              "{upload_phase: finish, video_id: <id>, description: <len "
              f"{len(description)}>, video_state: PUBLISHED}}")
        return {"ok": True, "platform": "facebook", "dry_run": True,
                "detail": "Dry run — no API calls made."}
    config.require_secrets("FACEBOOK_PAGE_ACCESS_TOKEN", "FACEBOOK_PAGE_ID")
    token = config.FACEBOOK_PAGE_ACCESS_TOKEN
    headers = {"Authorization": f"Bearer {token}"}

    # 1) Start an upload session.
    resp = requests.post(base, headers=headers,
                         data={"upload_phase": "start", "file_size": size},
                         timeout=60)
    if resp.status_code != 200:
        return {"ok": False, "platform": "facebook",
                "detail": f"Start failed ({resp.status_code}): "
                f"{resp.text[:300]}"}
    body = resp.json()
    video_id, upload_url = body.get("video_id"), body.get("upload_url")
    if not video_id or not upload_url:
        return {"ok": False, "platform": "facebook",
                "detail": f"Start gave no video_id/upload_url: "
                f"{resp.text[:300]}"}

    # 2) Upload the file bytes to the session URL.
    with open(video_path, "rb") as fh:
        resp = requests.post(
            upload_url,
            headers={"Authorization": f"OAuth {token}",
                     "file_offset": "0"},
            data=fh, timeout=300)
    if resp.status_code != 200:
        return {"ok": False, "platform": "facebook",
                "detail": f"Upload failed ({resp.status_code}): "
                f"{resp.text[:300]}"}

    # 3) Finish — publish the reel.
    resp = requests.post(base, headers=headers,
                         data={"upload_phase": "finish", "video_id": video_id,
                               "description": description,
                               "video_state": "PUBLISHED"},
                         timeout=60)
    if resp.status_code != 200:
        return {"ok": False, "platform": "facebook",
                "detail": f"Finish failed ({resp.status_code}): "
                f"{resp.text[:300]}"}
    vid = resp.json().get("id") or video_id
    return {"ok": True, "platform": "facebook", "media_id": vid,
            "detail": f"Published Facebook Reel, video id {vid}"}
