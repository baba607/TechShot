"""Tech Shot — video assembly (FFmpeg).

Ports the proven demo-reel build (build/build_reel.py, 2026-11-23) into
reusable functions: audio-driven scene layout, zoompan motion per scene,
libass burned-in headline subtitles, concat + voice mix, 1080x1920
H.264 + AAC, faststart.

Inputs per reel: 5 scene images (1080x1920-ish) + TTS chunk wavs from
src/voice.py. No video is ever generated from text alone — images are made
per scene by Muse from the script.
"""

import hashlib
import json
import subprocess
import wave
from pathlib import Path

import config

GAP_BEFORE = 0.35   # silence before first chunk in a scene
GAP_BETWEEN = 0.08  # silence between sentence chunks in a scene (Rahasya
                    # Bharat: 0.08s — short enough that the narration does
                    # not sound choppy; was 0.30s)
TAIL = 0.45         # silence after last chunk in a scene (0.9 for end card)
MIN_DUR = [3.0, 2.5, 3.0, 4.0, 3.5]  # per scene, seconds

# zoompan expressions per scene (0-3 alternate in/out; 4 = logo end card)
ZOOMS = {
    0: "min(zoom+0.0009,1.14)",
    1: "min(zoom+0.0007,1.12)",
    2: "max(1.14-0.0009*on,1.0)",
    3: "min(zoom+0.0006,1.10)",
}


def run(cmd):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True)


def wav_dur(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def layout_scenes(chunks):
    """Audio-driven scene durations.

    `chunks`: list of (chunk_id, wav_path, duration, scene_index).
    Returns (scene_durations, scene_bounds, total_seconds).
    """
    n = max((c[3] for c in chunks), default=-1) + 1
    scene_chunks = [[] for _ in range(n)]
    for cid, _p, dur, s in chunks:
        scene_chunks[s].append(dur)
    scene_durs, scene_bounds, t = [], [], 0.0
    for i in range(n):
        durs = scene_chunks[i]
        span = (GAP_BEFORE + sum(durs) + GAP_BETWEEN * max(0, len(durs) - 1)
                + (0.9 if i == n - 1 else TAIL))
        dur = max(span, MIN_DUR[i] if i < len(MIN_DUR) else 3.0)
        scene_durs.append(dur)
        scene_bounds.append((t, t + dur))
        t += dur
    return scene_durs, scene_bounds, t


def _resample_wav(path, rate, work_dir):
    """Return a mono 16-bit wav at `rate`, resampling with ffmpeg if needed.

    Kokoro writes 24 kHz, Piper 22050 Hz — and one run may even mix both
    engines — so a chunk at another rate is converted instead of failing.
    """
    with wave.open(str(path), "rb") as w:
        params = w.getparams()
    if params.framerate == rate and params.nchannels == 1 \
            and params.sampwidth == 2:
        return path
    out = Path(work_dir) / f"resampled_{rate}_{Path(path).stem}.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(path),
         "-ar", str(rate), "-ac", "1", "-sample_fmt", "s16", str(out)])
    return out


def build_full_audio(chunks, scene_bounds, total, work_dir, sample_rate=None):
    """Mix chunk wavs onto one mono timeline with the layout gaps.

    The timeline follows the first chunk's sample rate (Kokoro 24 kHz,
    Piper 22050 Hz); chunks at another rate are resampled with ffmpeg.
    """
    if sample_rate is None:
        if chunks:
            with wave.open(str(chunks[0][1]), "rb") as w:
                sample_rate = w.getframerate()
        else:
            sample_rate = 22050
    timeline = bytearray()

    def add_silence(sec):
        timeline.extend(b"\x00\x00" * int(sample_rate * sec))

    def add_chunk(path, at_sec):
        path = _resample_wav(path, sample_rate, work_dir)
        with wave.open(str(path), "rb") as w:
            params, frames = w.getparams(), w.readframes(w.getnframes())
        assert params.framerate == sample_rate and params.nchannels == 1 \
            and params.sampwidth == 2, params
        need = int(at_sec * sample_rate) * 2
        if len(timeline) < need:
            timeline.extend(b"\x00\x00" * ((need - len(timeline)) // 2))
        timeline.extend(frames)

    by_scene = {}
    for _cid, path, dur, s in chunks:
        by_scene.setdefault(s, []).append((path, dur))
    for i, (start, _end) in enumerate(scene_bounds):
        pos = start + GAP_BEFORE
        for j, (path, dur) in enumerate(by_scene.get(i, [])):
            if j > 0:
                pos += GAP_BETWEEN
            add_chunk(path, pos)
            pos += dur
    need = int(total * sample_rate) * 2
    if len(timeline) < need:
        timeline.extend(b"\x00\x00" * ((need - len(timeline)) // 2))
    out = Path(work_dir) / "voiceover.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(bytes(timeline))
    return out


def _ass_time(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def write_ass(scene_texts, scene_bounds, path):
    with open(path, "w") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\n"
                "PlayResY: 1920\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n")
        f.write("[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, "
                "SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
                "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
                "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
                "MarginV, Encoding\n")
        f.write("Style: Head,DejaVu Sans,58,&H00FFFFFF,&H000000FF,&H00000000,"
                "&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,60,60,190,1\n\n")
        f.write("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, "
                "MarginR, MarginV, Effect, Text\n")
        for i, text in enumerate(scene_texts):
            s, e = scene_bounds[i]
            f.write(f"Dialogue: 0,{_ass_time(s + 0.15)},{_ass_time(e - 0.10)},"
                    f"Head,,0,0,0,,{text}\n")
    return Path(path)


def render_segment(image, duration, index, work_dir, is_end_card=False):
    """One scene -> one mp4 segment with zoompan motion."""
    frames = int(round(duration * config.VIDEO_FPS))
    seg = Path(work_dir) / f"seg{index}.mp4"
    w, h = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    if is_end_card:
        # Logo on dark navy canvas, gentle zoom.
        run(["ffmpeg", "-y", "-v", "error", "-i", str(image),
             "-filter_complex",
             "[0:v]scale=980:980:force_original_aspect_ratio=decrease,"
             "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x0a1628,format=yuv420p,"
             f"zoompan=z='min(zoom+0.0004,1.06)':x='iw/2-(iw/zoom/2)':"
             f"y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={config.VIDEO_FPS}",
             "-t", f"{duration:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             str(seg)])
    else:
        zoom = ZOOMS.get(index % 4, "min(zoom+0.0007,1.12)")
        run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(image),
             "-vf", f"scale=2160:3840,zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':"
                    f"y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={config.VIDEO_FPS},"
                    "format=yuv420p",
             "-t", f"{duration:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             str(seg)])
    return seg


def pick_music_track(reel_id=None):
    """Pick one bundled CC0 music track (stable rotation by reel id).

    Any *.mp3 in config.MUSIC_DIR (assets/music/) is eligible; the track
    is chosen by sha256(reel_id) so the same reel always gets the same
    music and reels rotate across the available tracks. Returns None
    when music is disabled or no tracks are bundled.
    """
    if not config.MUSIC_ENABLED:
        return None
    music_dir = config.MUSIC_DIR
    tracks = sorted(music_dir.glob("*.mp3")) if music_dir.is_dir() else []
    if not tracks:
        return None
    if reel_id:
        idx = int(hashlib.sha256(str(reel_id).encode()).hexdigest(), 16)
        return tracks[idx % len(tracks)]
    return tracks[0]


def _music_filter(total, sample_rate):
    """FFmpeg audio filter: quiet music under the voiceover + limiter.

    Music at config.MUSIC_VOLUME (0.25), 2s fade-in, fade-out over the
    last 4s, mixed with the voiceover and capped by a limiter (0.95)
    so voice + music never clips. Expects inputs [1:a] (voiceover) and
    [2:a] (music); produces [aout].
    """
    vol = config.MUSIC_VOLUME
    fade_in = config.MUSIC_FADE_IN
    fade_out = config.MUSIC_FADE_OUT
    limit = config.MUSIC_LIMIT
    return (
        f"[2:a]aresample={sample_rate},pan=mono|c0=0.5*c0+0.5*c1,"
        f"volume={vol},afade=t=in:st=0:d={fade_in},"
        f"afade=t=out:st={total - fade_out:.2f}:d={fade_out},"
        f"atrim=0:{total:.2f}[music];"
        f"[1:a][music]amix=inputs=2:duration=first:normalize=0,"
        f"alimiter=limit={limit}[aout]")


def _encode_cmd(concat_list, full_audio, ass, total, out_path, music=None):
    """Build the final ffmpeg encode command (video + audio mix)."""
    video_filter = (
        "[0:v]fade=t=out:st={:.2f}:d=0.6,"
        "subtitles={}:fontsdir=/usr/share/fonts[v]".format(
            total - 0.6, str(ass).replace(":", "\\:")))
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
           "-i", str(concat_list), "-i", str(full_audio)]
    if music is not None:
        with wave.open(str(full_audio), "rb") as w:
            sample_rate = w.getframerate()
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        filter_complex = video_filter + ";" + _music_filter(total, sample_rate)
        audio_map = "[aout]"
    else:
        filter_complex = video_filter
        audio_map = "1:a"
    cmd += ["-filter_complex", filter_complex,
            "-map", "[v]", "-map", audio_map,
            "-c:v", "libx264", "-preset", "medium",
            "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart", "-shortest", str(out_path)]
    return cmd


def build_reel(scene_images, chunks, scene_texts, out_path, work_dir,
               reel_id=None):
    """Assemble a finished reel. Returns (out_path, info dict)."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    scene_durs, scene_bounds, total = layout_scenes(chunks)
    print("scene durations:", [f"{d:.2f}" for d in scene_durs],
          "total:", f"{total:.2f}s")
    full_audio = build_full_audio(chunks, scene_bounds, total, work_dir)
    ass = write_ass(scene_texts, scene_bounds, work_dir / "subs.ass")
    segs = []
    for i, img in enumerate(scene_images):
        segs.append(render_segment(img, scene_durs[i], i, work_dir,
                                   is_end_card=(i == len(scene_images) - 1)))
    concat_list = work_dir / "segments.txt"
    with open(concat_list, "w") as f:
        for s in segs:
            f.write(f"file '{s}'\n")
    out_path = Path(out_path)
    # NOTE: no fade-in here on purpose. The old chain had
    # fade=t=in:st=0:d=0.4, which made frame 0 pure black — and Instagram
    # uses frame 0 as the profile-grid thumbnail, so all 3 reels showed
    # as black tiles (2026-11-24). Fade-out at the end is kept.
    music = pick_music_track(reel_id)
    if music is not None:
        print(f"[music] track: {music.name} (volume {config.MUSIC_VOLUME})")
    try:
        run(_encode_cmd(concat_list, full_audio, ass, total, out_path,
                        music=music))
    except subprocess.CalledProcessError:
        if music is not None:
            # Music must never fail a build — retry voice-only.
            print("[music] WARNING: music mix failed — retrying voice-only.")
            run(_encode_cmd(concat_list, full_audio, ass, total, out_path,
                            music=None))
        else:
            raise
    info = {"scene_durations": [round(d, 2) for d in scene_durs],
            "total": round(total, 2), "output": str(out_path)}
    print("DONE:", out_path)
    print(json.dumps(info))
    return out_path, info
