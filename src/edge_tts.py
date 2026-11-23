#!/usr/bin/env python3
"""edge-tts TTS runner (Tech Shot fallback voice).

Reads Devanagari Hindi text on stdin, writes a .wav file.
Same stdin -> wav pattern as src/kokoro_tts.py, so src/voice.py can call
it the same way.

Voice: hi-IN-MadhurNeural (male Hindi neural voice, Microsoft).
Free, no API key — but it needs network access to Microsoft's speech
service at build time. GitHub Actions runners can reach it; this dev VM
cannot (SSL error to speech.platform.bing.com), so this runner can only
be tested live in CI — see tests, which mock it instead.

edge-tts saves mp3, so this runner converts to 24 kHz mono 16-bit wav
with ffmpeg (same shape as Kokoro's output, so the video mixer treats
both engines identically).

Install (free):
    pip install edge-tts

Usage:
    echo "गूगल ने ..." | python3 src/edge_tts.py --voice hi-IN-MadhurNeural --out out.wav
"""

import argparse
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description="edge-tts Hindi TTS (stdin -> wav)")
    ap.add_argument("--voice", default="hi-IN-MadhurNeural",
                    help="edge-tts voice, e.g. hi-IN-MadhurNeural (male, default)")
    ap.add_argument("--out", required=True, help="Output .wav path")
    args = ap.parse_args()

    text = sys.stdin.read().strip()
    if not text:
        print("edge_tts: empty input text", file=sys.stderr)
        return 2

    try:
        import edge_tts
    except ImportError:
        print("edge_tts: 'edge-tts' package not installed "
              "(pip install edge-tts)", file=sys.stderr)
        return 3

    tmp_mp3 = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_mp3 = f.name
        asyncio.run(edge_tts.Communicate(text, args.voice).save(tmp_mp3))
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", tmp_mp3,
             "-ar", "24000", "-ac", "1", "-sample_fmt", "s16", args.out],
            check=True)
    except Exception as exc:
        print(f"edge_tts: generation failed: {exc}", file=sys.stderr)
        return 4
    finally:
        if tmp_mp3:
            Path(tmp_mp3).unlink(missing_ok=True)
    print(f"edge_tts: wrote {args.out} (voice {args.voice})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
