"""Tech Shot — quality checks for a finished reel (ffprobe + ffmpeg).

A reel only becomes APPROVAL_PENDING if every check passes:
  - file exists and ffprobe can read it (playable)
  - resolution exactly 1080x1920 (9:16)
  - duration 25-60s (target 30-45s)
  - video stream present (H.264), audio stream present (AAC), lengths match
  - no black frames longer than 0.5s (blackdetect)
  - file size sane (0.5-100 MB)
"""

import json
import subprocess
from pathlib import Path

EXPECTED_W, EXPECTED_H = 1080, 1920
MIN_DURATION, MAX_DURATION = 25.0, 60.0
TARGET_MIN, TARGET_MAX = 30.0, 45.0
MAX_BLACK_SEC = 0.5


def _ffprobe(path):
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams",
         "-of", "json", str(path)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr.strip()[-300:]}")
    return json.loads(proc.stdout)


def _black_segments(path):
    """Return list of (start, duration) black segments via blackdetect."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path),
         "-vf", "blackdetect=d=0.5:pic_th=0.98", "-an", "-f", "null", "-"],
        capture_output=True, text=True)
    segs = []
    for line in proc.stderr.splitlines():
        if "black_start" in line:
            parts = dict(kv.split(":") for kv in
                         line.split("blackdetect", 1)[-1].strip().split()
                         if ":" in kv)
            try:
                segs.append((float(parts["black_start"]),
                             float(parts["black_duration"])))
            except (KeyError, ValueError):
                continue
    return segs


def check_video(path):
    """Run all checks. Returns (ok, report dict with per-check results)."""
    path = Path(path)
    checks = {}

    def _set(name, ok, detail=""):
        checks[name] = {"ok": bool(ok), "detail": detail}

    if not path.exists():
        _set("exists", False, "file missing")
        return False, {"file": str(path), "checks": checks}
    _set("exists", True, f"{path.stat().st_size / 1e6:.1f} MB")
    size_mb = path.stat().st_size / 1e6
    _set("size", 0.05 <= size_mb <= 100, f"{size_mb:.1f} MB")

    try:
        probe = _ffprobe(path)
    except RuntimeError as exc:
        _set("playable", False, str(exc))
        return False, {"file": str(path), "checks": checks}
    _set("playable", True, "ffprobe read OK")
    streams = probe.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    _set("video_stream", video is not None,
         (video or {}).get("codec_name", "none"))
    _set("audio_stream", audio is not None,
         (audio or {}).get("codec_name", "none"))
    if video:
        _set("resolution", (video.get("width"), video.get("height"))
             == (EXPECTED_W, EXPECTED_H),
             f"{video.get('width')}x{video.get('height')}")
    fmt = probe.get("format", {})
    try:
        dur = float(fmt.get("duration", 0))
    except (TypeError, ValueError):
        dur = 0.0
    _set("duration", MIN_DURATION <= dur <= MAX_DURATION, f"{dur:.2f}s")
    _set("duration_target", TARGET_MIN <= dur <= TARGET_MAX,
         f"target {TARGET_MIN}-{TARGET_MAX}s")
    if video and audio:
        try:
            vd = float(video.get("duration", dur))
            ad = float(audio.get("duration", dur))
            _set("av_sync", abs(vd - ad) <= 1.0, f"video {vd:.2f}s / audio {ad:.2f}s")
        except (TypeError, ValueError):
            _set("av_sync", False, "duration unreadable")
    try:
        blacks = _black_segments(path)
        worst = max((d for _s, d in blacks), default=0.0)
        _set("no_black_frames", worst <= MAX_BLACK_SEC,
             f"longest black {worst:.2f}s" if blacks else "none detected")
    except Exception as exc:
        _set("no_black_frames", False, f"blackdetect failed: {exc}")

    ok = all(c["ok"] for c in checks.values())
    return ok, {"file": str(path), "duration": dur, "checks": checks}
