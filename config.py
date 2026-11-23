"""Tech Shot — env-based configuration.

Every secret / credential comes from the environment (locally from a `.env`
file that is NEVER committed, in GitHub Actions from repository Secrets).
This module contains NO secret values — only names and non-sensitive defaults.

Secret names used by this project (exact names, as stored in GitHub Secrets):
    FACEBOOK_PAGE_ID
    INSTAGRAM_BUSINESS_ACCOUNT_ID
    FACEBOOK_PAGE_ACCESS_TOKEN   (long-lived Page token; also used for Instagram)
    META_APP_ID
    YOUTUBE_CHANNEL_ID
    YOUTUBE_CLIENT_ID
    YOUTUBE_CLIENT_SECRET
    YOUTUBE_REFRESH_TOKEN
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

BRAND = "Tech Shot"
BRAND_TAGLINE = "Tech + AI ki khabrein, simple Hindi me"

# --- Content library -------------------------------------------------------
CONTENT_DIR = Path(os.environ.get("TECHSHOT_CONTENT_DIR", REPO_ROOT / "content"))

# --- Publishing (values come ONLY from the environment) --------------------
FACEBOOK_PAGE_ID = os.environ.get("FACEBOOK_PAGE_ID")
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN")
META_APP_ID = os.environ.get("META_APP_ID")
YOUTUBE_CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID")
YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

# Public HTTPS URL where a finished video is hosted (Instagram needs this —
# it cannot upload a file directly). E.g. a raw file URL in this repo.
# Set per publish run; never a secret.
VIDEO_PUBLIC_URL = os.environ.get("TECHSHOT_VIDEO_PUBLIC_URL")

# YouTube uploads stay PRIVATE by default: the Google Cloud project is not
# audited yet, so public uploads are not possible until verification.
# Set TECHSHOT_YOUTUBE_PRIVACY=public only after the project is audited.
YOUTUBE_PRIVACY = os.environ.get("TECHSHOT_YOUTUBE_PRIVACY", "private")

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# --- Voice ------------------------------------------------------------------
# PRIMARY voice: Kokoro-82M (hexgrad/kokoro) — open-weight, Apache-2.0, free.
# Runs in GitHub Actions and locally. Default voice hm_omega (male);
# hf_alpha (female) is on standby via KOKORO_VOICE_FEMALE.
# FALLBACK: Piper (offline, already installed locally) — used ONLY if Kokoro
# fails. Do NOT wire Google Neural2 or Azure here (paid; no Tech Shot
# credentials — those belong to the user's other project, not this one).
# Chatterbox / VoiceStudio are NOT used anywhere (test/idea level only).
TTS_ENGINE = os.environ.get("TECHSHOT_TTS_ENGINE", "kokoro")
KOKORO_REPO = os.environ.get(
    "TECHSHOT_KOKORO_REPO", "https://github.com/baba607/kokoro"
)
# Default is the user's fork (baba607/kokoro, fork in progress 2026-11-23).
# If the fork URL fails to clone, installers fall back to upstream
# https://github.com/hexgrad/kokoro — see .github/workflows/build.yml.
# Override with TECHSHOT_KOKORO_REPO if the fork moves.
KOKORO_MODEL = os.environ.get("TECHSHOT_KOKORO_MODEL", "hexgrad/Kokoro-82M")
KOKORO_VOICE = os.environ.get("TECHSHOT_KOKORO_VOICE", "hm_omega")
KOKORO_VOICE_FEMALE = os.environ.get(
    "TECHSHOT_VOICE_FEMALE", os.environ.get("VOICE_FEMALE", "hf_alpha")
)
KOKORO_LANG = os.environ.get("TECHSHOT_KOKORO_LANG", "h")  # 'h' = Hindi
PIPER_MODEL = os.environ.get(
    "TECHSHOT_PIPER_MODEL",
    os.path.expanduser("~/workspace/tech-shot/voices/hi_IN-pratham-medium.onnx"),
)
# Python that has piper-tts installed (the demo venv). Defaults to current.
PIPER_PYTHON = os.environ.get("TECHSHOT_PIPER_PYTHON", "python3")
PIPER_LENGTH_SCALE = float(os.environ.get("TECHSHOT_PIPER_LENGTH_SCALE", "1.0"))

# --- Video ------------------------------------------------------------------
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 30

# --- News -------------------------------------------------------------------
SCAN_MIN_SCORE = float(os.environ.get("TECHSHOT_SCAN_MIN_SCORE", "6.0"))
SCAN_LIMIT = int(os.environ.get("TECHSHOT_SCAN_LIMIT", "10"))


def missing_secrets(*names):
    """Return the subset of the named secrets that are not set."""
    return [n for n in names if not os.environ.get(n)]


def require_secrets(*names):
    """Raise a clear error naming (not printing) any missing secret."""
    missing = missing_secrets(*names)
    if missing:
        raise RuntimeError(
            "Missing required secret(s): " + ", ".join(missing)
            + ". Set them as environment variables (locally) or GitHub Secrets."
        )
