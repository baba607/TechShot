"""Tech Shot — silence trim for TTS chunks (Auto-Editor style).

Rahasya Bharat trims every sentence's leading/trailing silence and long
internal pauses (max 0.35s kept), so the narration sounds tight instead
of breathy. Same idea here, applied to each chunk wav after synthesis.

Two implementations, in order:
  1. `auto-editor` CLI if installed (pip install auto-editor) — the same
     tool Rahasya Bharat uses. Called with --margin <max_silence>.
  2. Pure-stdlib fallback (wave module + amplitude threshold) — no extra
     dependency, always available.

FAIL-SAFE: any error, any missing tool, any unexpected wav format — the
original file is left untouched and the build continues. Trimming must
never fail a build. Returns True if the file was trimmed, False otherwise.
"""

import shutil
import struct
import subprocess
import wave
from pathlib import Path

import config

# Amplitude threshold for "silence" in the stdlib fallback, as a fraction
# of the chunk's own peak amplitude (relative, so quiet chunks still work).
SILENCE_FRACTION = 0.02
# Shortest silence run worth cutting (shorter gaps are left alone).
MIN_SILENCE_SEC = 0.10
# Analysis window for the stdlib fallback.
WINDOW_SEC = 0.010


def _auto_editor_available():
    return shutil.which("auto-editor") is not None


def _trim_with_auto_editor(path, max_silence):
    """Trim with the auto-editor CLI. Raises on any failure."""
    out = path.with_name(path.stem + ".trimmed" + path.suffix)
    subprocess.run(
        ["auto-editor", str(path), "--margin", f"{max_silence}s",
         "--no-open", "-o", str(out)],
        check=True, capture_output=True, timeout=120)
    if not out.exists() or out.stat().st_size < 100:
        raise RuntimeError("auto-editor produced no output")
    out.replace(path)


def _read_mono16(path):
    """Read a wav as (params, samples list). Only 16-bit PCM is supported."""
    with wave.open(str(path), "rb") as w:
        params = w.getparams()
        if params.sampwidth != 2:
            raise ValueError(f"unsupported sample width {params.sampwidth}")
        frames = w.readframes(w.getnframes())
    nch = params.nchannels
    total = len(frames) // 2
    samples = struct.unpack(f"<{total}h", frames)
    if nch > 1:
        # Downmix to mono for silence detection (trim keeps channel count).
        samples = [sum(samples[i:i + nch]) // nch
                   for i in range(0, len(samples), nch)]
    return params, samples


def _silent_windows(samples, rate, threshold):
    """Per-window silence flags (True = silent), 10ms windows."""
    win = max(1, int(rate * WINDOW_SEC))
    flags = []
    for i in range(0, len(samples), win):
        chunk = samples[i:i + win]
        peak = max((abs(s) for s in chunk), default=0)
        flags.append(peak <= threshold)
    return flags, win


def _trim_with_stdlib(path, max_silence):
    """Trim with the wave module. Raises on any failure."""
    params, samples = _read_mono16(path)
    rate = params.framerate
    if not samples:
        raise ValueError("empty wav")
    peak = max(abs(s) for s in samples)
    threshold = max(peak * SILENCE_FRACTION, 1)
    flags, win = _silent_windows(samples, rate, threshold)
    keep_windows = max(1, int(max_silence / WINDOW_SEC))
    min_sil_windows = max(1, int(MIN_SILENCE_SEC / WINDOW_SEC))

    # Build the kept sample ranges: audible windows plus up to
    # `keep_windows` silent windows around them; long internal silent
    # runs shrink to `keep_windows`.
    n = len(flags)
    keep = [False] * n
    i = 0
    first_audible = next((k for k, f in enumerate(flags) if not f), None)
    if first_audible is None:
        raise ValueError("wav is all silence")
    while i < n:
        if not flags[i]:
            keep[i] = True
            i += 1
            continue
        j = i
        while j < n and flags[j]:
            j += 1
        run = j - i
        if i == 0:
            # Leading silence: keep at most max_silence at the end of it.
            for k in range(max(i, j - keep_windows), j):
                keep[k] = True
        elif j == n:
            # Trailing silence: keep at most max_silence at the start of it.
            for k in range(i, min(j, i + keep_windows)):
                keep[k] = True
        elif run >= min_sil_windows:
            # Long internal pause: keep max_silence of it, centred.
            mid = (i + j) // 2
            half = keep_windows // 2
            for k in range(max(i, mid - half), min(j, mid + half + 1)):
                keep[k] = True
        else:
            # Short gap between words: leave it alone.
            for k in range(i, j):
                keep[k] = True
        i = j
    kept_samples = []
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    nch = params.nchannels
    frame_bytes = 2 * nch
    for k, kflag in enumerate(keep):
        if not kflag:
            continue
        start = k * win * frame_bytes
        end = min(len(raw), (k + 1) * win * frame_bytes)
        kept_samples.append(raw[start:end])
    out = path.with_name(path.stem + ".trimmed" + path.suffix)
    with wave.open(str(out), "wb") as w:
        w.setparams(params)
        for blob in kept_samples:
            w.writeframes(blob)
    out.replace(path)


def trim_wav(path, max_silence=None):
    """Trim silence in `path` in place. Returns True if trimmed.

    Never raises: on any error the original file is kept and False is
    returned (with a warning on stdout). `max_silence` defaults to
    config.TRIM_MAX_SILENCE (0.35s).
    """
    path = Path(path)
    max_silence = (config.TRIM_MAX_SILENCE if max_silence is None
                   else max_silence)
    try:
        if _auto_editor_available():
            try:
                _trim_with_auto_editor(path, max_silence)
                return True
            except Exception as exc:
                print(f"[trim] auto-editor failed ({exc}) — stdlib fallback.")
        _trim_with_stdlib(path, max_silence)
        return True
    except Exception as exc:
        print(f"[trim] WARNING: could not trim {path.name} ({exc}) — "
              "keeping original.")
        # Remove a half-written .trimmed file if one exists.
        leftover = path.with_name(path.stem + ".trimmed" + path.suffix)
        try:
            leftover.unlink(missing_ok=True)
        except OSError:
            pass
        return False
