"""Tech Shot — content library (file-based status tracking).

Layout: content/YYYY/MM/DD/<id>/item.json  (+ script.md, final_video.mp4, ...)
Every item carries a status; transitions are validated so a reel can never
skip verification or approval:

    DISCOVERED -> VERIFIED -> SCRIPT_READY -> AUDIO_READY -> VIDEO_READY
      -> APPROVAL_PENDING -> APPROVED -> SCHEDULED -> PUBLISHED
    Any state -> FAILED (with a reason). APPROVAL_PENDING -> SCRIPT_READY
    (rejected, back for rework). APPROVED/PUBLISHED may publish again to
    another platform.

Duplicate check: a source URL already in the library is never scanned twice.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

STATUSES = [
    "DISCOVERED", "VERIFIED", "SCRIPT_READY", "AUDIO_READY", "VIDEO_READY",
    "APPROVAL_PENDING", "APPROVED", "SCHEDULED", "PUBLISHED", "FAILED",
]

ALLOWED = {
    "DISCOVERED": {"VERIFIED", "FAILED"},
    "VERIFIED": {"SCRIPT_READY", "FAILED"},
    "SCRIPT_READY": {"AUDIO_READY", "VIDEO_READY", "FAILED"},
    "AUDIO_READY": {"VIDEO_READY", "FAILED"},
    "VIDEO_READY": {"APPROVAL_PENDING", "FAILED"},
    "APPROVAL_PENDING": {"APPROVED", "SCRIPT_READY", "FAILED"},
    "APPROVED": {"SCHEDULED", "PUBLISHED", "FAILED"},
    "SCHEDULED": {"PUBLISHED", "FAILED"},
    "PUBLISHED": {"PUBLISHED", "FAILED"},
    "FAILED": {"DISCOVERED"},  # retry from scratch only
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def slugify(title):
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "reel").lower()).strip("-")
    return slug[:50] or "reel"


def item_id(date=None, title="reel"):
    dt = date or datetime.now(timezone.utc)
    return f"{dt:%Y%m%d}-{slugify(title)}"


def item_dir(content_dir, reel_id):
    """content/YYYY/MM/DD/<id>/ derived from the id's date prefix."""
    m = re.match(r"(\d{4})(\d{2})(\d{2})-", reel_id)
    if not m:
        raise ValueError(f"Bad reel id '{reel_id}' (expected YYYYMMDD-slug).")
    y, mo, d = m.groups()
    return Path(content_dir) / y / mo / d / reel_id


def _item_file(content_dir, reel_id):
    return item_dir(content_dir, reel_id) / "item.json"


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic on same filesystem


def create_item(content_dir, title, sources=None, score=None, summary=""):
    reel_id = item_id(title=title)
    data = {
        "id": reel_id, "title": title, "summary": summary,
        "score": score, "sources": sources or [],
        "status": "DISCOVERED", "created_at": _now(), "updated_at": _now(),
        "history": [{"at": _now(), "from": None, "to": "DISCOVERED",
                     "note": "Discovered by scan."}],
        "publish": {},
    }
    _write_json(_item_file(content_dir, reel_id), data)
    return data


def load_item(content_dir, reel_id):
    path = _item_file(content_dir, reel_id)
    if not path.exists():
        raise FileNotFoundError(f"No such reel: {reel_id} ({path})")
    return json.loads(path.read_text(encoding="utf-8"))


def save_item(content_dir, data):
    data["updated_at"] = _now()
    _write_json(_item_file(content_dir, data["id"]), data)
    return data


def set_status(content_dir, reel_id, new_status, note=""):
    data = load_item(content_dir, reel_id)
    old = data["status"]
    if new_status not in ALLOWED.get(old, set()):
        raise ValueError(f"Illegal transition {old} -> {new_status} for {reel_id}.")
    data["status"] = new_status
    data["history"].append({"at": _now(), "from": old, "to": new_status,
                            "note": note})
    return save_item(content_dir, data)


def list_items(content_dir, status=None):
    items = []
    for path in sorted(Path(content_dir).rglob("item.json")):
        if "examples" in path.parts:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if status is None or data.get("status") == status:
            items.append(data)
    return sorted(items, key=lambda d: d.get("created_at", ""), reverse=True)


def find_duplicate(content_dir, url):
    """Return the reel id that already used this source URL, else None."""
    if not url:
        return None
    for data in list_items(content_dir):
        for src in data.get("sources", []):
            if src.get("url") == url:
                return data["id"]
    return None
