#!/usr/bin/env python3
"""Kokoro-82M TTS runner (Tech Shot primary voice).

Reads Devanagari Hindi text on stdin, writes a .wav file.
Kept as a separate process so the main pipeline never imports torch:
if Kokoro is not installed, this script fails fast with a clear message
and the pipeline falls back to Piper (see src/voice.py).

Install (free):
    pip install torch --index-url https://download.pytorch.org/whl/cpu
    pip install "kokoro @ git+https://github.com/baba607/kokoro.git" soundfile
    # fork of https://github.com/hexgrad/kokoro — if the fork fails to clone,
    # install from upstream hexgrad/kokoro instead.

Usage:
    echo "गूगल ने ..." | python3 src/kokoro_tts.py --voice hm_omega --out out.wav
"""

import argparse
import sys


def main():
    ap = argparse.ArgumentParser(description="Kokoro Hindi TTS (stdin -> wav)")
    ap.add_argument("--voice", default="hm_omega",
                    help="Kokoro voice, e.g. hm_omega (male, default) or hf_alpha (female)")
    ap.add_argument("--lang", default="h", help="Kokoro language code ('h' = Hindi)")
    ap.add_argument("--model", default="hexgrad/Kokoro-82M",
                    help="Hugging Face model id")
    ap.add_argument("--speed", type=float, default=1.01,
                    help="Speech speed multiplier (1.01 = Rahasya Bharat, "
                         "a touch slower than Kokoro's 1.0 default)")
    ap.add_argument("--out", required=True, help="Output .wav path")
    args = ap.parse_args()

    text = sys.stdin.read().strip()
    if not text:
        print("kokoro_tts: empty input text", file=sys.stderr)
        return 2

    try:
        from kokoro import KPipeline
    except ImportError:
        print("kokoro_tts: 'kokoro' package not installed. Install it with:\n"
              "  pip install torch --index-url https://download.pytorch.org/whl/cpu\n"
              "  pip install \"kokoro @ git+https://github.com/hexgrad/kokoro.git\" soundfile",
              file=sys.stderr)
        return 3

    try:
        import soundfile as sf
    except ImportError:
        print("kokoro_tts: 'soundfile' not installed (pip install soundfile)",
              file=sys.stderr)
        return 3

    try:
        pipeline = KPipeline(lang_code=args.lang)
        generator = pipeline(text, voice=args.voice, speed=args.speed)
        audio = None
        for _gs, _ps, audio_chunk in generator:
            audio = audio_chunk  # single-chunk text in, single chunk out
        if audio is None:
            print("kokoro_tts: Kokoro returned no audio", file=sys.stderr)
            return 4
        sf.write(args.out, audio, 24000)
    except Exception as exc:
        print(f"kokoro_tts: generation failed: {exc}", file=sys.stderr)
        return 4
    print(f"kokoro_tts: wrote {args.out} (voice {args.voice}, "
          f"speed {args.speed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
