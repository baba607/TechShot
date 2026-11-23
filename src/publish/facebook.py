"""Tech Shot — publish to Facebook Page Reels (Facebook Graph API, free).

Flow: POST /{page-id}/video_reels with the video file (multipart upload)
and description -> video id. The Page token (FACEBOOK_PAGE_ACCESS_TOKEN)
must have pages_read_engagement + pages_manage_posts (granted when the
long-lived Page token was created).

`dry_run=True` prints the call that WOULD be made, no HTTP.
"""

import requests

import config


def publish(video_path, description, dry_run=False, page_id=None):
    """Publish a Reel to the Facebook Page. Returns {ok, platform, ...}."""
    page_id = page_id or config.FACEBOOK_PAGE_ID
    if not dry_run:
        config.require_secrets("FACEBOOK_PAGE_ACCESS_TOKEN", "FACEBOOK_PAGE_ID")
    if dry_run:
        print(f"[facebook:dry-run] POST {config.GRAPH_API_BASE}/{page_id}/"
              "video_reels {file: <video>, description: <len "
              f"{len(description)}>}}")
        return {"ok": True, "platform": "facebook", "dry_run": True,
                "detail": "Dry run — no API calls made."}
    with open(video_path, "rb") as fh:
        resp = requests.post(
            f"{config.GRAPH_API_BASE}/{page_id}/video_reels",
            headers={"Authorization": f"Bearer {config.FACEBOOK_PAGE_ACCESS_TOKEN}"},
            data={"description": description},
            files={"file": (f"{page_id}-reel.mp4", fh, "video/mp4")},
            timeout=300)
    if resp.status_code != 200:
        return {"ok": False, "platform": "facebook",
                "detail": f"Upload failed ({resp.status_code}): {resp.text[:300]}"}
    vid = resp.json().get("id")
    return {"ok": True, "platform": "facebook", "media_id": vid,
            "detail": f"Published Facebook Reel, video id {vid}"}
