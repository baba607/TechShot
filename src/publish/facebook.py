"""Tech Shot — publish to Facebook Page Reels (Facebook Graph API, free).

Flow — the video_reels resumable upload (3 phases + a status check):
  1. start:  POST /{page-id}/video_reels {upload_phase: start, file_size}
              -> {video_id, upload_url} (rupload.facebook.com)
  2. upload: POST {upload_url} with the raw file bytes and headers
              Authorization: OAuth <token>, Offset: 0, file_size: <bytes>
              (note: the header is "Offset", NOT "file_offset" — the
              server rejects file_offset with "Header Offset not
              convertable to unsigned long")
  3. check:  GET /{video_id}?fields=status until video_status is
              upload_complete (processing to "ready" only starts after
              finish — waiting for "ready" here never moves)
  4. finish: POST /{page-id}/video_reels
              {upload_phase: finish, video_id, description,
               video_state: PUBLISHED} -> {id}

Earlier failures, in order: a plain file upload ("upload_phase is
required"), a bare video_url finish ("Missing parameter: video_id"),
and file_offset in phase 2 (the Offset error above).

`dry_run=True` prints the calls that WOULD be made, no HTTP.
"""

import os
import time

import requests

import config


def _wait_ready(video_id, token, timeout=120, interval=5):
    """Poll GET /{video_id}?fields=status until the video can be finished.

    The video sits at video_status "upload_complete" after the bytes land
    — processing to "ready" only starts once finish is called (the
    180s wait for "ready" never moved). So "upload_complete" is good
    enough to proceed; the finish call reports if the video is not
    actually usable. Returns {ok, detail}.
    """
    deadline = time.time() + timeout
    last = "unknown"
    while time.time() < deadline:
        try:
            resp = requests.get(
                f"{config.GRAPH_API_BASE}/{video_id}",
                headers={"Authorization": f"Bearer {token}"},
                params={"fields": "status"}, timeout=30)
        except requests.RequestException as exc:
            return {"ok": False,
                    "detail": f"Status check failed: {exc}"}
        if resp.status_code == 200:
            data = resp.json()
            st = data.get("status") or {}
            last = st.get("video_status") or data.get("video_status") or last
            if last in ("ready", "upload_complete"):
                return {"ok": True, "detail": f"video {last}"}
            if last in ("upload_failed", "error", "expired"):
                return {"ok": False,
                        "detail": f"Video status {last}: {resp.text[:300]}"}
        time.sleep(interval)
    return {"ok": False,
            "detail": f"Video not ready after {timeout}s (last: {last})"}


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
              f"<{size} bytes, Offset: 0, file_size: {size}>")
        print("[facebook:dry-run] 3) GET "
              f"{config.GRAPH_API_BASE}/<video_id>?fields=status "
              "(wait for ready)")
        print(f"[facebook:dry-run] 4) POST {base} "
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
                     "Offset": "0", "file_size": str(size)},
            data=fh, timeout=300)
    if resp.status_code != 200:
        return {"ok": False, "platform": "facebook",
                "detail": f"Upload failed ({resp.status_code}): "
                f"{resp.text[:300]}"}

    # 3) Wait until Meta has the whole file and processed it.
    status = _wait_ready(video_id, token)
    if not status["ok"]:
        return {"ok": False, "platform": "facebook",
                "detail": status["detail"]}

    # 4) Finish — publish the reel.
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
