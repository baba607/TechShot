"""Tech Shot — voiceover (TTS).

PRIMARY: Kokoro-82M (hexgrad/kokoro) — open-weight, Apache-2.0, free.
  Default voice hm_omega (male); hf_alpha (female) on standby.
  Kokoro repo URL is config KOKORO_REPO (default baba607/kokoro, the user's
  fork of hexgrad/kokoro; installers fall back to upstream if the fork
  fails to clone).
FALLBACK: Piper (offline, hi_IN-pratham-medium) — used ONLY if Kokoro fails.

Deliberately NOT wired: Google Neural2 / Azure (paid, no Tech Shot
credentials). Chatterbox / VoiceStudio are not used anywhere.

Both engines need DEVANAGARI input for Hindi — Roman Hindi would be
mispronounced. Scripts must carry `voiceover_devanagari` (see src/script.py).
"""

import subprocess
import sys
from pathlib import Path

import config

KOKORO_RUNNER = Path(__file__).resolve().parent / "kokoro_tts.py"


def resolve_voice(gender="male"):
    """Map a script's voice gender to a Kokoro voice name."""
    if gender == "female":
        return config.KOKORO_VOICE_FEMALE  # hf_alpha (standby)
    return config.KOKORO_VOICE            # hm_omega (default, male)


def _run(cmd, input_text=None):
    if isinstance(input_text, str):
        input_text = input_text.encode("utf-8")
    proc = subprocess.run(cmd, input=input_text, capture_output=True)
    return proc


def synthesize_kokoro(text_devanagari, out_wav, gender="male"):
    """One Kokoro call via the runner script. Raises RuntimeError on failure."""
    voice = resolve_voice(gender)
    cmd = [sys.executable, str(KOKORO_RUNNER),
           "--voice", voice,
           "--lang", config.KOKORO_LANG,
           "--model", config.KOKORO_MODEL,
           "--out", str(out_wav)]
    proc = _run(cmd, input_text=text_devanagari)
    if proc.returncode != 0 or not Path(out_wav).exists():
        err = (proc.stderr or b"").decode(errors="replace").strip()[-800:]
        raise RuntimeError(f"Kokoro TTS failed (voice {voice}): {err or 'no output'}")
    return Path(out_wav)


def synthesize_piper(text_devanagari, out_wav):
    """Piper fallback (offline). Raises RuntimeError on failure."""
    cmd = [config.PIPER_PYTHON, "-m", "piper",
           "--model", config.PIPER_MODEL,
           "--output_file", str(out_wav)]
    if config.PIPER_LENGTH_SCALE != 1.0:
        cmd += ["--length_scale", str(config.PIPER_LENGTH_SCALE)]
    proc = _run(cmd, input_text=text_devanagari)
    if proc.returncode != 0 or not Path(out_wav).exists():
        err = (proc.stderr or b"").decode(errors="replace").strip()[-800:]
        raise RuntimeError(f"Piper TTS failed: {err or 'no output'}")
    return Path(out_wav)


def synthesize(text_devanagari, out_wav, gender="male", engine=None):
    """Synthesize Devanagari text to a .wav.

    Tries the primary engine first (Kokoro by default), falls back to Piper
    on failure. Returns (path, engine_used). Raises RuntimeError if both fail.
    """
    engine = engine or config.TTS_ENGINE
    if not (text_devanagari or "").strip():
        raise RuntimeError("Empty text — nothing to synthesize.")
    errors = []
    order = [engine] + (["piper"] if engine != "piper" else [])
    for eng in order:
        try:
            if eng == "kokoro":
                path = synthesize_kokoro(text_devanagari, out_wav, gender)
            elif eng == "piper":
                path = synthesize_piper(text_devanagari, out_wav)
            else:
                raise RuntimeError(f"Unknown TTS engine '{eng}' — check "
                                   "TECHSHOT_TTS_ENGINE (kokoro | piper).")
            if eng != engine:
                print(f"[voice] {engine} failed, fell back to {eng}.")
            return path, eng
        except RuntimeError as exc:
            errors.append(str(exc))
            print(f"[voice] {eng} failed: {exc}")
    raise RuntimeError("All TTS engines failed: " + " | ".join(errors))


def split_devanagari_chunks(text):
    """Split Devanagari voiceover into sentence chunks (on । and .)."""
    import re
    parts = [p.strip() for p in re.split(r"(?<=[।.])\s+", text.strip()) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def synthesize_chunks(script, work_dir, engine=None):
    """TTS every scene's Devanagari voiceover.

    Returns a list of (chunk_id, wav_path, duration_sec, scene_index).
    Scene chunks come from the scene's own `voiceover_devanagari` if present,
    else the script-level voiceover is split evenly across scenes.
    """
    import wave

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    gender = script.get("voice", "male")
    chunks = []
    scenes = script.get("scenes") or []
    script_chunks = split_devanagari_chunks(script.get("voiceover_devanagari", ""))
    if not script_chunks:
        raise RuntimeError("No voiceover_devanagari in script — TTS needs "
                           "Devanagari input. Add it to the script first.")
    # Distribute script-level chunks across scenes round-robin if scenes
    # do not carry their own text.
    per_scene = [[] for _ in scenes] or [[]]
    for i, chunk in enumerate(script_chunks):
        per_scene[i % len(per_scene)].append(chunk)
    for scene_idx, scene in enumerate(scenes or [{}]):
        own = split_devanagari_chunks(scene.get("voiceover_devanagari", ""))
        scene_chunks = own if own else per_scene[scene_idx]
        for j, text in enumerate(scene_chunks):
            cid = f"s{scene_idx}c{j}"
            out = work_dir / f"chunk_{cid}.wav"
            if not out.exists() or out.stat().st_size < 1000:
                synthesize(text, out, gender=gender, engine=engine)
            with wave.open(str(out), "rb") as w:
                dur = w.getnframes() / float(w.getframerate())
            chunks.append((cid, out, dur, scene_idx))
            print(f"[voice] chunk {cid}: {dur:.2f}s (scene {scene_idx})")
    return chunks
