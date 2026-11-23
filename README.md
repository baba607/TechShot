# Tech Shot — Hindi Tech + AI News Reels (free, automated, approval-first)

**Tech + AI ki khabrein, simple Hindi me.** 🚀
Instagram Reels · Facebook Reels · YouTube Shorts — target 3/day.

**Cost: ₹0/month.** No paid API, no subscription. Everything below is free.

> **Approval mode first:** nothing ever publishes without a human watching
> the video and approving it. The pipeline only *prepares* reels — a human
> decides what goes live. Verification fail = **NO PUBLISH**, no exceptions.

## How it works

```
News (free RSS) → Score 0-10 → Verify (source + date + 2nd source for big stories)
  → Duplicate check → Hindi script (30-45s) → Images (Muse, scene-wise)
  → Voice (Kokoro, Piper fallback) → FFmpeg assemble (1080x1920, zoom/pan, subtitles)
  → Quality check → HUMAN APPROVAL → Publish (per platform)
```

Statuses: `DISCOVERED → VERIFIED → SCRIPT_READY → AUDIO_READY → VIDEO_READY
→ APPROVAL_PENDING → APPROVED → SCHEDULED → PUBLISHED / FAILED`

## Setup (local)

```bash
git clone https://github.com/baba607/TechShot.git
cd TechShot
pip install -r requirements.txt
# Voice (primary): Kokoro — see "Voice" below
# Voice (fallback): pip install piper-tts  (+ hi_IN-pratham-medium.onnx model)
cp .env.example .env   # if present; never commit .env
```

FFmpeg 8+ must be installed (`ffmpeg -version`). No other system deps locally.

## Secrets (GitHub → Settings → Secrets and variables → Actions)

Values live **only** in GitHub Secrets / your local `.env` — never in code.
The workflows reference these exact names:

| Secret | Used by | Notes |
|---|---|---|
| `FACEBOOK_PAGE_ID` | Facebook publish | Page "TechShot.Hindi" |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | Instagram publish | IG business account id |
| `FACEBOOK_PAGE_ACCESS_TOKEN` | Facebook + Instagram | Long-lived Page token (never expires) |
| `META_APP_ID` | Reference | Meta developer app "Tech Shot" |
| `YOUTUBE_CHANNEL_ID` | YouTube publish | Channel "Tech Shot Hindi" |
| `YOUTUBE_CLIENT_ID` | YouTube publish | Desktop OAuth client |
| `YOUTUBE_CLIENT_SECRET` | YouTube publish | From Google Cloud console |
| `YOUTUBE_REFRESH_TOKEN` | YouTube publish | OAuth refresh token |

Also set (optional): `TECHSHOT_VIDEO_PUBLIC_URL` (public video URL — Instagram
needs it), `TECHSHOT_KOKORO_REPO` (defaults to the baba607/kokoro fork).

## Voice

- **Primary: Kokoro-82M** — open-weight, Apache-2.0, free, runs in GitHub
  Actions. Default voice **`hm_omega`** (male).
- **Standby: `hf_alpha`** (female) — set a script's `voice: female`, or
  `TECHSHOT_KOKORO_VOICE=hf_alpha`.
- **Fallback: Piper** (`hi_IN-pratham-medium`, offline) — used only if Kokoro
  fails. Nothing else is wired: no Google Neural2, no Azure (paid).
- Repo: `KOKORO_REPO` (default `https://github.com/baba607/kokoro`, the
  user's fork of `https://github.com/hexgrad/kokoro`). Installers try the
  fork first and fall back to upstream if the fork fails to clone.
- Both engines need **Devanagari** Hindi input — scripts carry
  `voiceover_devanagari` alongside the Roman Hindi voiceover.

## Run it

```bash
# 1. Daily scan: news -> verify -> draft scripts (no publishing)
python pipeline.py scan --limit 10

# 2. Finish the draft script (content/YYYY/MM/DD/<id>/script.md):
#    write the Roman + Devanagari voiceover, 5 scenes, captions.
#    See content/examples/ for the finished format.

# 3. Build: voice -> video -> quality check (needs 5 scene images in the reel dir)
python pipeline.py build 20261123-gemini-4-neon

# 4. WATCH final_video.mp4, then approve or reject
python pipeline.py approve 20261123-gemini-4-neon
# python pipeline.py reject 20261123-gemini-4-neon --note "scene 3 image off"

# 5. Publish (only APPROVED reels, only with --approve)
python pipeline.py publish --id 20261123-gemini-4-neon --platform instagram --approve
python pipeline.py publish --id 20261123-gemini-4-neon --platform youtube --approve --dry-run

# Library status
python pipeline.py status
python pipeline.py status 20261123-gemini-4-neon
```

## GitHub Actions

| Workflow | Trigger | Does |
|---|---|---|
| `daily-scan.yml` | Daily 10:00 IST + manual | Scan → verify → draft scripts → commit + tracking issue. **Never publishes.** |
| `build.yml` | Manual (`reel_id`) | Installs Kokoro (fork → upstream fallback) + Piper fallback, builds the reel, uploads the mp4 as an artifact for human review. **Never publishes.** |
| `publish.yml` | Manual (`reel_id`, `platforms`, `approve=yes`) | Publishes ONLY if `approve=yes` AND the reel is APPROVED. |

## YouTube caveats (known)

- The Cloud project is **not audited** yet → uploads stay **private**
  (`TECHSHOT_YOUTUBE_PRIVACY=private`, the default). Set it to `public`
  only after Google verification.
- **Testing-mode** refresh tokens expire in 7 days — re-authorize weekly
  until the OAuth app is in Production.

## Layout

```
pipeline.py            CLI (scan / build / approve / reject / publish / status)
config.py              Env-based config — secret NAMES only, no values
src/
  news.py              RSS discovery + scoring (Google News, Gadgets360, official blogs)
  verify.py            Verification rules (fail = NO PUBLISH)
  script.py            Hindi script template, validation, .md parser
  voice.py             Kokoro primary / Piper fallback TTS
  kokoro_tts.py        Kokoro runner (stdin Devanagari -> wav)
  video.py             FFmpeg assembly (zoompan, subtitles, 1080x1920)
  quality.py           ffprobe checks (playable, ratio, duration, audio, black frames)
  captions.py          IG + YouTube captions / hashtags
  library.py           content/YYYY/MM/DD/<id>/ status tracking (JSON)
  publish/
    instagram.py       IG Graph API container flow (Reels)
    facebook.py        FB Page Reels via Graph API
    youtube.py         YouTube Data API v3 resumable upload
content/
  examples/            The 3 finished scripts (reel 01/02/03) as reference
  YYYY/MM/DD/<id>/     One folder per reel (item.json, script.md, final_video.mp4)
tests/                 Unit tests (mocked feeds, dry-run publish, real Piper fallback)
.github/workflows/     daily-scan.yml / build.yml / publish.yml
```

## Tests

```bash
python -m py_compile $(find . -name '*.py' -not -path './venv/*')
python -m unittest discover -s tests -v
```

## Rules that never bend

1. Unverified story → never publish, however viral.
2. No dates / prices / specs invented — only what the sources say.
3. No real shop data, no secrets in code, no credentials in chat.
4. A human watches every video before it goes live.
