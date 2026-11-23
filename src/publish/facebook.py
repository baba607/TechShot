"""Tech Shot — publish to Facebook Page Reels (Facebook Graph API, free).

Flow: POST /{page-id}/video_reels with upload_phase=finish and the video's
PUBLIC URL (video_url) + description -> video id. The video is already
hosted on a GitHub release by the build workflow, so no file upload is
needed — the same public URL Instagram uses (TECHSHOT_VIDEO_PUBLIC_URL,
set by the publish workflow). The earlier multipart file upload failed
with "(#100) The parameter upload_phase is required" — video_reels only
accepts the resumable-upload phases, and the URL form is finish-only.

`dry_run=True` prints the call that WOULD be made, no HTTP.
"""

import os

import requests

import config


def publish(video_path, description, dry_run=False, page_id=None):
    """Publish a Reel to the Facebook Page. Returns {ok, platform, ...}.

    video_path is accepted for a uniform publisher signature but is not
    uploaded — the public release URL is used instead.
    """
    page_id = page_id or config.FACEBOOK_PAGE_ID
    video_url = os.environ.get("TECHSHOT_VIDEO_PUBLIC_URL", "")
    if dry_run:
        print(f"[facebook:dry-run] POST {config.GRAPH_API_BASE}/{page_id}/"
              "video_reels {upload_phase: finish, video_url: "
              f"{video_url or '<public url>'}, description: <len "
              f"{len(description)}>}}")
        return {"ok": True, "platform": "facebook", "dry_run": True,
                "detail": "Dry run — no API calls made."}
    if not video_url:
        return {"ok": False, "platform": "facebook",
                "detail": "TECHSHOT_VIDEO_PUBLIC_URL is not set — the "
                "publish workflow sets it from the GitHub release URL."}
    config.require_secrets("FACEBOOK_PAGE_ACCESS_TOKEN", "FACEBOOK_PAGE_ID")
    resp = requests.post(
        f"{config.GRAPH_API_BASE}/{page_id}/video_reels",
        headers={"Authorization": f"Bearer {config.FACEBOOK_PAGE_ACCESS_TOKEN}"},
        data={"upload_phase": "finish", "video_url": video_url,
              "description": description},
        timeout=300)
    if resp.status_code != 200:
        return {"ok": False, "platform": "facebook",
                "detail": f"Upload failed ({resp.status_code}): {resp.text[:300]}"}
    vid = resp.json().get("id")
    return {"ok": True, "platform": "facebook", "media_id": vid,
            "detail": f"Published Facebook Reel, video id {vid}"}
