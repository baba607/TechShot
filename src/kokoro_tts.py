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
    ap.add_argument("--speed", type=float, default=1.0,
                    help="Speech speed multiplier. MUST stay 1.0: passing any "
                         "other value to this kokoro fork breaks the audio "
                         "(each chunk loud in its first half, ~8dB too quiet "
                         "in the second — measured on v3/v4). At 1.0 the "
                         "argument is omitted entirely (v1's known-good path).")
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
        # At speed 1.0 omit the argument entirely (v1's known-good call);
        # any other value breaks the audio in this fork (see config.py).
        gen_kwargs = {"voice": args.voice}
        if args.speed != 1.0:
            gen_kwargs["speed"] = args.speed
        generator = pipeline(text, **gen_kwargs)
        # Concatenate ALL yielded chunks: a long sentence can yield
        # several, and keeping only the last would lose the rest.
        import numpy as np
        parts = [audio_chunk for _gs, _ps, audio_chunk in generator]
        if not parts:
            print("kokoro_tts: Kokoro returned no audio", file=sys.stderr)
            return 4
        audio = (np.concatenate(parts) if len(parts) > 1 else parts[0])
        sf.write(args.out, audio, 24000)
    except Exception as exc:
        print(f"kokoro_tts: generation failed: {exc}", file=sys.stderr)
        return 4
    print(f"kokoro_tts: wrote {args.out} (voice {args.voice}, "
          f"speed {args.speed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
