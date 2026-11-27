"""Tech Shot — voiceover (TTS).

PRIMARY: Kokoro-82M (hexgrad/kokoro) — open-weight, Apache-2.0, free.
  Default voice hm_omega (male); hf_alpha (female) on standby.
  Kokoro repo URL is config KOKORO_REPO (default baba607/kokoro, the user's
  fork of hexgrad/kokoro; installers fall back to upstream if the fork
  fails to clone). Speed 1.01x (config KOKORO_SPEED, Rahasya Bharat).
FALLBACK order: Kokoro -> edge-tts (free, no key) -> Piper (offline,
hi_IN-pratham-medium). A failed engine falls through to the next; the
build never stops for a voice failure until all three are exhausted.

Deliberately NOT wired: Google Neural2 / Azure (paid, no Tech Shot
credentials). Chatterbox / VoiceStudio are not used anywhere.

Both engines need DEVANAGARI input for Hindi — Roman Hindi would be
mispronounced. Scripts must carry `voiceover_devanagari` (see src/script.py).
Before synthesis, src/latin_fix converts any Latin words left in the
Devanagari script; after synthesis, src/trim trims each chunk's silence
(max 0.35s kept) so the narration sounds tight.
"""

import subprocess
import sys
from pathlib import Path

import config
from src import latin_fix, pron_fix, trim

KOKORO_RUNNER = Path(__file__).resolve().parent / "kokoro_tts.py"
EDGE_TTS_RUNNER = Path(__file__).resolve().parent / "edge_tts.py"


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
           "--speed", str(config.KOKORO_SPEED),
           "--out", str(out_wav)]
    proc = _run(cmd, input_text=text_devanagari)
    if proc.returncode != 0 or not Path(out_wav).exists():
        err = (proc.stderr or b"").decode(errors="replace").strip()[-800:]
        raise RuntimeError(f"Kokoro TTS failed (voice {voice}): {err or 'no output'}")
    return Path(out_wav)


def synthesize_edge(text_devanagari, out_wav):
    """edge-tts fallback (free, no key). Raises RuntimeError on failure."""
    cmd = [sys.executable, str(EDGE_TTS_RUNNER),
           "--voice", config.EDGE_TTS_VOICE,
           "--out", str(out_wav)]
    proc = _run(cmd, input_text=text_devanagari)
    if proc.returncode != 0 or not Path(out_wav).exists():
        err = (proc.stderr or b"").decode(errors="replace").strip()[-800:]
        raise RuntimeError(f"edge-tts failed (voice {config.EDGE_TTS_VOICE}): "
                           f"{err or 'no output'}")
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

    Tries the primary engine first (Kokoro by default), falling through
    edge-tts and then Piper on failure. Returns (path, engine_used).
    Raises RuntimeError if every engine fails.
    """
    engine = engine or config.TTS_ENGINE
    if not (text_devanagari or "").strip():
        raise RuntimeError("Empty text — nothing to synthesize.")
    errors = []
    _FALLBACKS = {"kokoro": ["edge-tts", "piper"],
                  "edge-tts": ["piper"], "piper": []}
    if engine not in _FALLBACKS:
        raise RuntimeError(f"Unknown TTS engine '{engine}' — check "
                           "TECHSHOT_TTS_ENGINE (kokoro | edge-tts | piper).")
    order = [engine] + _FALLBACKS[engine]
    for eng in order:
        try:
            if eng == "kokoro":
                path = synthesize_kokoro(text_devanagari, out_wav, gender)
            elif eng == "edge-tts":
                path = synthesize_edge(text_devanagari, out_wav)
            elif eng == "piper":
                path = synthesize_piper(text_devanagari, out_wav)
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
    else the script-level voiceover is split across scenes in order.
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
    # Distribute script-level chunks across scenes in contiguous blocks
    # (in script order), so the narration stays in order and the closing
    # CTA lands in the final scene, over the end card. Round-robin
    # interleaving scrambled it: with 6 sentences over 5 scenes it put
    # sentence 6 in scene 0, so the CTA played mid-reel and the end card
    # went out silent (caught 2026-11-27 on all 3 morning reels).
    # Extra sentences go to the LAST scenes, so the CTA always stays last.
    per_scene = [[] for _ in scenes] or [[]]
    n, s = len(script_chunks), len(per_scene)
    base, extra = divmod(n, s)
    idx = 0
    for scene_i in range(s):
        if base >= 1:
            size = base + (1 if scene_i >= s - extra else 0)
        else:
            # Fewer sentences than scenes: one per scene, first scenes.
            size = 1 if scene_i < n else 0
        per_scene[scene_i] = script_chunks[idx:idx + size]
        idx += size
    for scene_idx, scene in enumerate(scenes or [{}]):
        own = split_devanagari_chunks(scene.get("voiceover_devanagari", ""))
        scene_chunks = own if own else per_scene[scene_idx]
        for j, text in enumerate(scene_chunks):
            cid = f"s{scene_idx}c{j}"
            out = work_dir / f"chunk_{cid}.wav"
            # Latin words left in the Devanagari script (GTA, PS5, ...) are
            # converted first — Kokoro mangles raw Latin in a Hindi sentence.
            text = latin_fix.fix_latin_words(text)
            # Then pronunciation fixes: some Devanagari spellings come out
            # robotic (इंतज़ार->इंद्दार, पीएस5->प्येस पांग, "/" read as
            # "slash") — rewrite them into forms Kokoro says cleanly.
            # Subtitles are unaffected: they come from the scene text.
            text = pron_fix.fix_pronunciation(text)
            if not out.exists() or out.stat().st_size < 1000:
                # Fresh synthesis. (Cached chunks are reused as-is; delete
                # the work/ dir to force a fresh voiceover.)
                synthesize(text, out, gender=gender, engine=engine)
            # Trim leading/trailing silence + long pauses (max 0.35s kept).
            # Fail-safe inside trim_wav: the original is kept on any error.
            trim.trim_wav(out)
            with wave.open(str(out), "rb") as w:
                dur = w.getnframes() / float(w.getframerate())
            chunks.append((cid, out, dur, scene_idx))
            print(f"[voice] chunk {cid}: {dur:.2f}s (scene {scene_idx})")
    return chunks
