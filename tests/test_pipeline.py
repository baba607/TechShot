"""Tech Shot — tests. Run: python -m unittest discover -s tests -v

Covers: news scoring/parsing (mocked RSS), verification rules, library
status transitions + duplicate check, script validation + .md parsing,
captions, voice dispatch (Kokoro unavailable -> Piper fallback, real Piper
if installed), publish dry-run (zero HTTP calls), mocked-feed scan,
workflow YAML validity, and a real quality check on a tiny ffmpeg video.
No test makes a real API call. No test needs network except the optional
live scan smoke test (not part of this suite).
"""

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import config  # noqa: E402
from src import captions, library, news, quality, script as script_mod, verify  # noqa: E402
from src import latin_fix, pron_fix, trim, voice as voice_mod  # noqa: E402
from src import video as video_mod  # noqa: E402
from src.publish import facebook, instagram, youtube  # noqa: E402

MOCK_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test News</title>
<item><title>Google launches Gemini free in India</title>
<link>https://example.com/gemini-india</link>
<pubDate>Mon, 23 Nov 2026 10:00:00 GMT</pubDate>
<description>Google Gemini now free for users in India.</description></item>
<item><title>Rumor: mystery phone leak allegedly coming</title>
<link>https://example.com/rumor-phone</link>
<pubDate>Mon, 23 Nov 2026 09:00:00 GMT</pubDate>
<description>Unconfirmed leak from a tipster.</description></item>
<item><title>Google launches Gemini free in India</title>
<link>https://example.com/gemini-india</link>
<pubDate>Mon, 23 Nov 2026 10:00:00 GMT</pubDate>
<description>Duplicate URL.</description></item>
</channel></rss>"""


def good_script():
    return {
        "title": "Test reel",
        "hook": "Ye khabar aapke kaam ki hai!",
        "voiceover": ("Google ne apna naya AI model launch kar diya hai aur ye "
                      "khabar har mobile user ke liye bahut kaam ki hai kyunki "
                      "is se aapka roz ka kaam aasan ho jayega aur time bachega. "
                      "Is model me naye features hain jo aapke sawaalon ke jawab "
                      "aur behtar tareeke se denge aur aapki madad har kaam me "
                      "karenge. Agar aap roz mobile par kaam karte hain to ye "
                      "update aapke liye hai. "
                      "Aisi hi Tech Updates ke liye Tech Shot ko follow karo!"),
        "voiceover_devanagari": ("गूगल ने अपना नया एआई मॉडल लॉन्च कर दिया है। "
                                 "यह खबर हर मोबाइल यूज़र के काम की है।"),
        "voice": "male",
        "scenes": [
            {"text": "SCENE 1", "visual": "img1", "time": "0-3s"},
            {"text": "SCENE 2", "visual": "img2", "time": "3-10s"},
            {"text": "SCENE 3", "visual": "img3", "time": "10-20s"},
            {"text": "SCENE 4", "visual": "img4", "time": "20-28s"},
            {"text": "TECH SHOT", "visual": "logo", "time": "28-35s"},
        ],
        "caption_instagram": "Test caption #TechShot",
        "caption_youtube_title": "Test Title",
        "caption_youtube_description": "Test desc",
        "hashtags": ["#TechShot", "#Test"],
        "sources": [{"url": "https://example.com/x", "name": "Example", "date": "2026-11-23"}],
        "claims_not_to_make": ["price"],
    }


class TestNews(unittest.TestCase):
    def test_parse_rss(self):
        items = news.parse_rss(MOCK_RSS, "Test Feed")
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["title"], "Google launches Gemini free in India")
        self.assertIsNotNone(items[0]["published"])

    def test_score_india_free_beats_rumor(self):
        items = news.parse_rss(MOCK_RSS, "Test Feed")
        good = news.score(items[0])
        bad = news.score(items[1])
        self.assertGreater(good, 6.0)
        self.assertLess(bad, good)
        self.assertLessEqual(bad, 5.0)

    def test_discover_dedupes_and_filters(self):
        def fake_fetch(url, name):
            return news.parse_rss(MOCK_RSS, name)
        found = news.discover(feeds=[("T", "http://x")], min_score=6.0,
                              fetch=fake_fetch)
        self.assertEqual(len(found), 1)  # duplicate URL dropped, rumor filtered
        self.assertEqual(found[0]["link"], "https://example.com/gemini-india")


class TestVerify(unittest.TestCase):
    def test_verified_single_source_small_story(self):
        verdict, _ = verify.verify({
            "title": "Small update", "score": 5.0,
            "sources": [{"url": "https://example.com/a", "name": "Ex",
                         "date": "2026-11-23"}]})
        self.assertEqual(verdict, "VERIFIED")

    def test_big_story_needs_second_domain(self):
        item = {"title": "Big launch", "score": 9.0,
                "sources": [{"url": "https://example.com/a", "name": "Ex",
                             "date": "2026-11-23"}]}
        verdict, reasons = verify.verify(item)
        self.assertEqual(verdict, "UNVERIFIED")
        self.assertTrue(any("2nd" in r for r in reasons))
        item["sources"].append({"url": "https://other.com/b", "name": "Ot",
                                "date": "2026-11-23"})
        self.assertEqual(verify.verify(item)[0], "VERIFIED")

    def test_rumor_fails(self):
        verdict, _ = verify.verify({
            "title": "Rumor: leaked phone", "score": 7.0,
            "sources": [{"url": "https://example.com/a", "name": "Ex",
                         "date": "2026-11-23"}]})
        self.assertEqual(verdict, "UNVERIFIED")

    def test_no_source_no_date_fails(self):
        verdict, _ = verify.verify({"title": "X", "score": 5.0, "sources": []})
        self.assertEqual(verdict, "UNVERIFIED")


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_transitions_and_duplicate(self):
        item = library.create_item(self.tmp, "Gemini launch",
                                   sources=[{"url": "https://example.com/a"}],
                                   score=8.0)
        self.assertEqual(item["status"], "DISCOVERED")
        with self.assertRaises(ValueError):  # cannot skip verification
            library.set_status(self.tmp, item["id"], "APPROVED")
        library.set_status(self.tmp, item["id"], "VERIFIED")
        library.set_status(self.tmp, item["id"], "SCRIPT_READY")
        self.assertEqual(
            library.find_duplicate(self.tmp, "https://example.com/a"), item["id"])
        self.assertIsNone(
            library.find_duplicate(self.tmp, "https://example.com/other"))

    def test_reject_path(self):
        item = library.create_item(self.tmp, "X")
        for st in ("VERIFIED", "SCRIPT_READY", "VIDEO_READY", "APPROVAL_PENDING"):
            library.set_status(self.tmp, item["id"], st)
        library.set_status(self.tmp, item["id"], "SCRIPT_READY")  # reject -> rework
        self.assertEqual(library.load_item(self.tmp, item["id"])["status"],
                         "SCRIPT_READY")


class TestScript(unittest.TestCase):
    def test_validate_good(self):
        self.assertEqual(script_mod.validate(good_script()), [])

    def test_validate_short_voiceover_and_missing_devanagari(self):
        s = good_script()
        s["voiceover"] = "Bahut chhota."
        s["voiceover_devanagari"] = ""
        problems = script_mod.validate(s)
        self.assertTrue(any("too short" in p for p in problems))
        self.assertTrue(any("Devanagari" in p for p in problems))

    def test_from_markdown_example(self):
        md = (REPO_ROOT / "content/examples/demo-reel-01-gemini-4-neon.md"
              ).read_text(encoding="utf-8")
        s = script_mod.from_markdown(md)
        self.assertIn("Gemini 4 Neon", s["voiceover"])
        self.assertEqual(len(s["scenes"]), 5)
        self.assertTrue(len(s["sources"]) >= 2)
        self.assertTrue(any("Gemini" in h for h in s["hashtags"]))

    def test_all_examples_parse(self):
        for name in ("demo-reel-01-gemini-4-neon.md", "reel-02-chatgpt-dots.md",
                     "reel-03-gemini-tasks-india.md"):
            md = (REPO_ROOT / "content/examples" / name).read_text(encoding="utf-8")
            s = script_mod.from_markdown(md)
            self.assertEqual(len(s["scenes"]), 5, name)
            self.assertTrue(s["voiceover"], name)
            self.assertTrue(s["sources"], name)


class TestCaptions(unittest.TestCase):
    def test_instagram_has_brand_tags(self):
        cap = captions.instagram_caption(good_script())
        self.assertIn("#TechShot", cap)

    def test_youtube_title_max_100(self):
        s = good_script()
        s["caption_youtube_title"] = "X" * 150
        self.assertLessEqual(len(captions.youtube_title(s)), 100)

    def test_youtube_tags_max_15(self):
        s = good_script()
        s["hashtags"] = [f"#Tag{i}" for i in range(20)]
        self.assertLessEqual(len(captions.youtube_tags(s)), 15)


class TestVoice(unittest.TestCase):
    def test_config_defaults_kokoro_primary(self):
        self.assertEqual(config.TTS_ENGINE, "kokoro")
        self.assertEqual(config.KOKORO_VOICE, "hm_omega")
        self.assertEqual(config.KOKORO_VOICE_FEMALE, "hf_alpha")
        self.assertEqual(config.KOKORO_REPO, "https://github.com/baba607/kokoro")
        self.assertEqual(config.KOKORO_MODEL, "hexgrad/Kokoro-82M")
        self.assertEqual(config.KOKORO_SPEED, 1.0)  # must stay 1.0:
        # an explicit speed != 1.0 breaks the audio in this kokoro fork
        # (v3 1.01x / v4 0.95x: second half of every chunk ~8dB too quiet)
        self.assertEqual(config.EDGE_TTS_VOICE, "hi-IN-MadhurNeural")
        self.assertTrue(config.MUSIC_ENABLED)

    def test_resolve_voice(self):
        self.assertEqual(voice_mod.resolve_voice("male"), "hm_omega")
        self.assertEqual(voice_mod.resolve_voice("female"), "hf_alpha")

    def test_no_paid_engines_wired(self):
        # The module docstring *mentions* these names to say they are NOT
        # used; the check below applies to the code after the docstring.
        src = (REPO_ROOT / "src/voice.py").read_text(encoding="utf-8")
        code = re.sub(r'^"""[\s\S]*?"""', "", src, count=1)
        for bad in ("neural2", "Neural2", "azure", "Azure", "chatterbox",
                    "Chatterbox", "voicestudio", "VoiceStudio"):
            self.assertNotIn(bad, code)

    def test_kokoro_speed_passed_to_runner(self):
        # synthesize_kokoro must pass --speed 1.0 to the runner script.
        tmp = Path(tempfile.mkdtemp())
        out = tmp / "out.wav"
        out.touch()
        try:
            seen = {}

            def fake_run(cmd, input_text=None):
                seen["cmd"] = cmd
                return mock.Mock(returncode=0, stderr=b"")

            with mock.patch.object(voice_mod, "_run", fake_run):
                voice_mod.synthesize_kokoro("गूगल।", out)
            self.assertIn("--speed", seen["cmd"])
            self.assertIn("1.0", seen["cmd"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_kokoro_runner_accepts_speed_flag(self):
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "src/kokoro_tts.py"), "--help"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--speed", proc.stdout)

    def test_edge_runner_accepts_voice_flag(self):
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "src/edge_tts.py"), "--help"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("hi-IN-MadhurNeural", proc.stdout)

    def test_edge_tts_command(self):
        tmp = Path(tempfile.mkdtemp())
        out = tmp / "out.wav"
        out.touch()
        try:
            seen = {}

            def fake_run(cmd, input_text=None):
                seen["cmd"] = cmd
                return mock.Mock(returncode=0, stderr=b"")

            with mock.patch.object(voice_mod, "_run", fake_run):
                voice_mod.synthesize_edge("गूगल।", out)
            cmd = " ".join(seen["cmd"])
            self.assertIn("edge_tts.py", cmd)
            self.assertIn("hi-IN-MadhurNeural", cmd)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_fallback_order_kokoro_edge_piper(self):
        # Kokoro fails -> edge-tts is tried next (mocked, no network) and
        # wins; Piper is never reached.
        tmp = Path(tempfile.mkdtemp())
        out = tmp / "out.wav"
        out.touch()
        try:
            with mock.patch.object(voice_mod, "synthesize_kokoro",
                                   side_effect=RuntimeError("no kokoro")), \
                 mock.patch.object(voice_mod, "synthesize_edge",
                                   return_value=out), \
                 mock.patch.object(voice_mod, "synthesize_piper",
                                   side_effect=AssertionError("piper called")):
                path, engine = voice_mod.synthesize("गूगल।", out,
                                                    engine="kokoro")
                self.assertEqual(engine, "edge-tts")
                self.assertEqual(path, out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_kokoro_failure_falls_back_to_piper(self):
        # Simulate Kokoro missing: runner fails -> Piper used (if installed).
        venv_py = Path.home() / "workspace/tech-shot/venv/bin/python"
        model = Path.home() / "workspace/tech-shot/voices/hi_IN-pratham-medium.onnx"
        if not (venv_py.exists() and model.exists()):
            self.skipTest("Piper venv/model not present on this machine")
        tmp = Path(tempfile.mkdtemp())
        out = tmp / "out.wav"
        try:
            with mock.patch.object(voice_mod, "synthesize_kokoro",
                                   side_effect=RuntimeError("kokoro missing")), \
                 mock.patch.object(voice_mod, "synthesize_edge",
                                   side_effect=RuntimeError("no edge-tts")), \
                 mock.patch.object(config, "PIPER_PYTHON", str(venv_py)):
                path, engine = voice_mod.synthesize(
                    "गूगल ने नया मॉडल लॉन्च किया है।", out, engine="kokoro")
                self.assertEqual(engine, "piper")
                self.assertTrue(path.exists())
                self.assertGreater(path.stat().st_size, 1000)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_both_engines_fail_raises(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            with mock.patch.object(voice_mod, "synthesize_kokoro",
                                   side_effect=RuntimeError("no kokoro")), \
                 mock.patch.object(voice_mod, "synthesize_edge",
                                   side_effect=RuntimeError("no edge-tts")), \
                 mock.patch.object(voice_mod, "synthesize_piper",
                                   side_effect=RuntimeError("no piper")):
                with self.assertRaises(RuntimeError):
                    voice_mod.synthesize("गूगल।", tmp / "x.wav", engine="kokoro")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestLatinFix(unittest.TestCase):
    def test_dictionary_tech_terms(self):
        self.assertEqual(latin_fix.fix_latin_words("GTA 6 आ गया"),
                         "जीटीए 6 आ गया")
        self.assertEqual(latin_fix.fix_latin_words("PS5 पर खेलो"),
                         "पीएस5 पर खेलो")
        self.assertEqual(latin_fix.fix_latin_words("Instagram पर Follow करो"),
                         "इंस्टाग्राम पर फॉलो करो")
        self.assertEqual(latin_fix.fix_latin_words("Subscribe karo, AI news"),
                         "सब्सक्राइब करो, एआई न्यूज़")
        self.assertEqual(latin_fix.fix_latin_words("212 GB storage"),
                         "212 जीबी स्टोरेज")
        self.assertEqual(latin_fix.fix_latin_words("Metacritic 99"),
                         "मेटाक्रिटिक 99")
        self.assertEqual(latin_fix.fix_latin_words("YouTube Shorts"),
                         "यूट्यूब शॉट्स")

    def test_case_insensitive(self):
        self.assertEqual(latin_fix.fix_latin_words("gta"), "जीटीए")
        self.assertEqual(latin_fix.fix_latin_words("GtA"), "जीटीए")

    def test_devanagari_and_digits_untouched(self):
        text = "गूगल ने 5999 रुपये में लॉन्च किया।"
        self.assertEqual(latin_fix.fix_latin_words(text), text)
        self.assertEqual(latin_fix.fix_latin_words("212"), "212")
        self.assertEqual(latin_fix.fix_latin_words(""), "")

    def test_unknown_word_transliterated(self):
        # Generic fallback: readable Devanagari, no Latin letters left.
        out = latin_fix.fix_latin_words("hello world")
        self.assertNotRegex(out, r"[A-Za-z]")
        self.assertEqual(out, "हेल्लो वर्ल्ड")

    def test_mixed_sentence(self):
        got = latin_fix.fix_latin_words(
            "इंतज़ार खत्म! GTA 6 आ गया — 19 नवंबर को PS5 पर लॉन्च।")
        self.assertEqual(got, "इंतज़ार खत्म! जीटीए 6 आ गया — 19 नवंबर को पीएस5 पर लॉन्च।")


class TestPronFix(unittest.TestCase):
    def test_robotic_words_from_v6_transcript(self):
        # The exact words Whisper heard wrong on the v6 GTA 6 reel.
        self.assertEqual(
            pron_fix.fix_pronunciation("इंतज़ार खत्म! जीटीए 6 आ गया"),
            "इन्तजार खत्म! जी टी ए सिक्स आ गया")
        self.assertEqual(
            pron_fix.fix_pronunciation("19 नवंबर को पीएस5 और एक्सबॉक्स"),
            "19 नवंबर को पी एस पाँच और एक्स बोक्स")
        self.assertEqual(
            pron_fix.fix_pronunciation("एक्सबॉक्स सीरीज़ एक्स/एस पर"),
            "एक्स बोक्स सीरीज एक्स एस पर")
        self.assertEqual(
            pron_fix.fix_pronunciation("रिव्यूज़ में धमाका — मेटाक्रिटिक 99"),
            "रिव्यूज में धमाका — मेटा क्रिटिक 99")
        self.assertEqual(
            pron_fix.fix_pronunciation("वाइस सिटी में लूसिया और जेसन"),
            "वाइस सिटी में लुसिया और जेसन")
        self.assertEqual(
            pron_fix.fix_pronunciation("टेक शॉट को फॉलो करो"),
            "टेक शोट को फोलो करो")

    def test_nukta_and_aw_rules(self):
        # Nukta consonants -> base (Kokoro reads ज़ as द/ज).
        self.assertEqual(pron_fix.fix_pronunciation("ज़रूर"), "जरूर")
        self.assertEqual(pron_fix.fix_pronunciation("फ़ोन"), "फोन")
        # "aw" vowel -> "o" in loanwords.
        self.assertEqual(pron_fix.fix_pronunciation("लॉन्च"), "लोन्च")
        self.assertEqual(pron_fix.fix_pronunciation("ऑनलाइन"), "ओनलाइन")
        # Slash is read aloud as "slash" — drop it.
        self.assertEqual(pron_fix.fix_pronunciation("एक्स/एस"), "एक्स एस")

    def test_clean_hindi_untouched(self):
        text = "13 साल का इंतजार था — दो बार डिले हुआ।"
        self.assertEqual(pron_fix.fix_pronunciation(text), text)
        self.assertEqual(pron_fix.fix_pronunciation(""), "")
        self.assertEqual(
            pron_fix.fix_pronunciation("इंडिया में प्राइस 5999 रुपये"),
            "इंडिया में प्राइस 5999 रुपये")


class TestTrim(unittest.TestCase):
    def _make_wav(self, path, segments, rate=24000):
        """segments: list of (kind, seconds) with kind 'tone' or 'silence'."""
        import math
        import struct
        import wave
        samples = []
        for kind, sec in segments:
            n = int(sec * rate)
            if kind == "tone":
                samples += [int(12000 * math.sin(2 * math.pi * 440 * t / rate))
                            for t in range(n)]
            else:
                samples += [0] * n
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        return len(samples) / rate

    def test_stdlib_trim_edges_and_pause(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            wav = tmp / "t.wav"
            self._make_wav(wav, [("silence", 1.0), ("tone", 1.0),
                                 ("silence", 1.0), ("tone", 0.5),
                                 ("silence", 0.8)])
            self.assertTrue(trim.trim_wav(wav, max_silence=0.35))
            import wave
            with wave.open(str(wav), "rb") as w:
                dur = w.getnframes() / w.getframerate()
            # 0.35 + 1.0 + 0.35 + 0.5 + 0.35 = 2.55s (± one 10ms window)
            self.assertAlmostEqual(dur, 2.55, delta=0.05)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_trim_fail_safe_on_garbage(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            bad = tmp / "bad.wav"
            bad.write_bytes(b"not a wav at all")
            self.assertFalse(trim.trim_wav(bad))
            self.assertEqual(bad.read_bytes(), b"not a wav at all")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_trim_keeps_second_half_audible(self):
        # REGRESSION (2026-11-24): auto-editor replaced the 2nd half of
        # every Kokoro chunk with digital silence while keeping the
        # duration — half the narration inaudible. The stdlib trim must
        # never do that: audible content stays audible to the end.
        tmp = Path(tempfile.mkdtemp())
        try:
            wav = tmp / "t.wav"
            self._make_wav(wav, [("tone", 1.0), ("silence", 0.5),
                                 ("tone", 1.0)])
            self.assertTrue(trim.trim_wav(wav, max_silence=0.35))
            import wave as _wave
            with _wave.open(str(wav), "rb") as w:
                frames = w.readframes(w.getnframes())
                rate = w.getframerate()
            import struct as _struct
            samples = _struct.unpack(f"<{len(frames) // 2}h", frames)
            # Last 0.5s must still be audible (the 2nd tone, not silence).
            tail = samples[int(len(samples) - 0.5 * rate):]
            self.assertGreater(max(abs(s) for s in tail), 1000)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestMusic(unittest.TestCase):
    def test_gap_between_is_020(self):
        # 0.08 was breathless (user feedback 2026-11-24); sentences need
        # room to breathe, while scene cuts stay tight (GAP_BEFORE/TAIL 0.10).
        self.assertEqual(video_mod.GAP_BETWEEN, 0.20)

    def test_tracks_bundled(self):
        tracks = sorted(config.MUSIC_DIR.glob("*.mp3"))
        self.assertGreaterEqual(len(tracks), 3)
        names = {t.name for t in tracks}
        self.assertIn("ancient-power-of-serpents.mp3", names)
        self.assertIn("dark-ambient.mp3", names)
        self.assertIn("island-mystery.mp3", names)

    def test_pick_track_deterministic_and_rotates(self):
        a = video_mod.pick_music_track("20261123-gta-6-launched-19-november")
        b = video_mod.pick_music_track("20261123-gta-6-launched-19-november")
        self.assertEqual(a, b)
        self.assertTrue(a.exists())
        picks = {video_mod.pick_music_track(f"reel-{i}").name
                 for i in range(20)}
        self.assertGreater(len(picks), 1)  # rotation actually varies

    def test_music_filter_args(self):
        filt = video_mod._music_filter(total=40.0, sample_rate=24000)
        self.assertIn("volume=0.25", filt)
        self.assertIn("afade=t=in:st=0:d=2.0", filt)
        self.assertIn("afade=t=out:st=36.00:d=4.0", filt)
        self.assertIn("amix=inputs=2", filt)
        self.assertIn("alimiter=limit=0.95", filt)
        self.assertIn("[aout]", filt)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not available")
    def test_build_reel_with_music(self):
        import math
        import struct
        import wave
        tmp = Path(tempfile.mkdtemp())
        try:
            rate = 24000

            def tone_wav(path, sec, freq=440):
                s = [int(12000 * math.sin(2 * math.pi * freq * t / rate))
                     for t in range(int(sec * rate))]
                with wave.open(str(path), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(rate)
                    w.writeframes(struct.pack(f"<{len(s)}h", *s))

            c1, c2 = tmp / "c1.wav", tmp / "c2.wav"
            tone_wav(c1, 2.0)
            tone_wav(c2, 2.0)
            images = []
            for i in (1, 2):
                img = tmp / f"scene_{i}.png"
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                                "-i", "color=c=0x336699:s=1080x1920:d=1",
                                "-frames:v", "1", str(img)], check=True)
                images.append(img)
            chunks = [("s0c0", c1, 2.0, 0), ("s1c0", c2, 2.0, 1)]
            out = tmp / "out.mp4"
            video_mod.build_reel(images, chunks, ["SCENE 1", "SCENE 2"],
                                 out, tmp / "work",
                                 reel_id="20261123-test-music")
            self.assertTrue(out.exists())
            # The 4.9s test reel is shorter than the 30-45s quality
            # target, so check the individual streams, not overall ok.
            # (Was 6.25s before the 2026-11-24 pacing fix tightened the gaps.)
            _ok, report = quality.check_video(out)
            checks = report["checks"]
            self.assertTrue(checks["playable"]["ok"])
            self.assertTrue(checks["video_stream"]["ok"])
            self.assertTrue(checks["audio_stream"]["ok"])
            self.assertEqual(checks["resolution"]["detail"], "1080x1920")
            self.assertTrue(checks["av_sync"]["ok"])
            self.assertAlmostEqual(report["duration"], 4.9, delta=0.1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestPublishDryRun(unittest.TestCase):
    def test_no_http_calls_in_dry_run(self):
        def _boom(*a, **k):
            raise AssertionError("Real HTTP call attempted in dry-run!")
        with mock.patch("requests.post", _boom), mock.patch("requests.get", _boom), \
             mock.patch("requests.put", _boom):
            for res in (
                instagram.publish("https://example.com/v.mp4", "cap", dry_run=True),
                facebook.publish("/tmp/v.mp4", "desc", dry_run=True),
                youtube.publish("/tmp/v.mp4", "t", "d", ["x"], dry_run=True),
            ):
                self.assertTrue(res["ok"])
                self.assertTrue(res.get("dry_run"))


class TestScanMocked(unittest.TestCase):
    # A modest (non-"big") item: score ~7, single source is enough to verify.
    SCAN_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test News</title>
<item><title>Google updates Android app for users</title>
<link>https://example.com/android-update</link>
<pubDate>Mon, 23 Nov 2026 10:00:00 GMT</pubDate>
<description>Google updates its Android app.</description></item>
</channel></rss>"""

    def test_scan_creates_verified_item(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            with mock.patch("config.CONTENT_DIR", tmp):
                import pipeline
                with mock.patch.object(
                        news, "fetch_feed",
                        side_effect=lambda url, name: news.parse_rss(
                            self.SCAN_RSS, name)):
                    rc = pipeline.cmd_scan(mock.Mock(limit=10, min_score=6.0,
                                                     dry_run=False))
            self.assertEqual(rc, 0)
            items = library.list_items(tmp)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["status"], "SCRIPT_READY")
            d = library.item_dir(tmp, items[0]["id"])
            self.assertTrue((d / "script.md").exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestNextReady(unittest.TestCase):
    def _make_library(self, tmp):
        # Three items with distinct created_at, oldest first.
        ids = []
        for i, (title, status) in enumerate((("Old reel", "APPROVED"),
                                             ("Mid reel", "SCRIPT_READY"),
                                             ("New reel", "SCRIPT_READY"))):
            item = library.create_item(tmp, title)
            ids.append(item["id"])
            library.set_status(tmp, item["id"], "VERIFIED")
            library.set_status(tmp, item["id"], "SCRIPT_READY")
            if status == "APPROVED":
                for st in ("VIDEO_READY", "APPROVAL_PENDING", "APPROVED"):
                    library.set_status(tmp, item["id"], st)
            # Back-date created_at so ordering is deterministic.
            data = library.load_item(tmp, item["id"])
            data["created_at"] = f"2026-11-2{i}T00:00:00+00:00"
            library.save_item(tmp, data)
        return ids

    def _run(self, tmp, argv):
        import pipeline
        from io import StringIO
        out, err = StringIO(), StringIO()
        with mock.patch("config.CONTENT_DIR", tmp), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = pipeline.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_next_oldest_approved_and_ready_oldest_first(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            ids = self._make_library(tmp)
            rc, out, _ = self._run(tmp, ["next"])
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), ids[0])  # the APPROVED one
            rc, out, _ = self._run(tmp, ["ready"])
            self.assertEqual(rc, 0)
            # SCRIPT_READY ids, oldest first.
            self.assertEqual(out.split(), [ids[1], ids[2]])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_next_none_ready_exits_1_machine_readable(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            rc, out, err = self._run(tmp, ["next"])
            self.assertEqual(rc, 1)
            self.assertEqual(out, "")  # stdout stays clean for scripts
            self.assertIn("no APPROVED reel", err)
            # ready with nothing ready: exit 0, no output.
            rc, out, _ = self._run(tmp, ["ready"])
            self.assertEqual(rc, 0)
            self.assertEqual(out, "")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestWorkflows(unittest.TestCase):
    def test_yaml_valid_and_secrets_named(self):
        import yaml
        wf_dir = REPO_ROOT / ".github/workflows"
        names = {p.name for p in wf_dir.glob("*.yml")}
        self.assertEqual(names, {"daily-scan.yml", "build.yml", "publish.yml"})
        for p in wf_dir.glob("*.yml"):
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
            # YAML 1.1 parses the key `on` as boolean True — accept either.
            self.assertTrue("on" in data or True in data, p.name)
            self.assertIn("jobs", data)
        pub = (wf_dir / "publish.yml").read_text(encoding="utf-8")
        for secret in ("FACEBOOK_PAGE_ID", "INSTAGRAM_BUSINESS_ACCOUNT_ID",
                       "FACEBOOK_PAGE_ACCESS_TOKEN", "META_APP_ID",
                       "YOUTUBE_CHANNEL_ID", "YOUTUBE_CLIENT_ID",
                       "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
            self.assertIn(f"secrets.{secret}", pub)
        build = (wf_dir / "build.yml").read_text(encoding="utf-8")
        self.assertIn("baba607/kokoro", build)
        self.assertIn("hexgrad/kokoro", build)  # upstream fallback present
        self.assertIn("edge-tts", build)  # 2nd fallback voice
        # auto-editor must NOT be installed by build.yml: it replaced the
        # 2nd half of every Kokoro chunk with digital silence (2026-11-24
        # audio bug). (The file may still mention it in a comment.)
        self.assertNotIn("pip install --quiet auto-editor", build)

    def test_staggered_schedule_crons(self):
        # IST = UTC+5:30, no DST. Verify each workflow's cron + IST slot.
        import yaml
        wf_dir = REPO_ROOT / ".github/workflows"

        def crons(name):
            data = yaml.safe_load((wf_dir / name).read_text(encoding="utf-8"))
            on = data.get("on") or data.get(True) or {}
            return [s["cron"] for s in (on.get("schedule") or [])]

        # 22:30 UTC = 04:00 IST next day (scan).
        self.assertEqual(crons("daily-scan.yml"), ["30 22 * * *"])
        # 03:30 UTC = 09:00 IST, 08:30 UTC = 14:00 IST, 13:30 UTC = 19:00 IST.
        self.assertEqual(crons("publish.yml"),
                         ["30 3 * * *", "30 8 * * *", "30 13 * * *"])
        # build.yml stays manual-only (no schedule).
        self.assertEqual(crons("build.yml"), [])

    def test_publish_picks_next_approved_reel(self):
        pub = (REPO_ROOT / ".github/workflows/publish.yml"
               ).read_text(encoding="utf-8")
        self.assertIn("pipeline.py next", pub)
        self.assertIn("no reel ready", pub)
        self.assertIn("instagram,facebook,youtube", pub)

    def test_no_secret_values_in_repo(self):
        # The repo must contain secret NAMES only — never real IDs/tokens.
        # (The tests dir itself is skipped: this file holds the forbidden
        # values as literals in order to check for them.)
        import re
        for path in REPO_ROOT.rglob("*"):
            if path.is_dir() or ".git" in path.parts or "tests" in path.parts:
                continue
            if path.suffix in (".mp4", ".wav", ".onnx", ".webp", ".png"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("1439366359260904", text, str(path))  # FB page id
            self.assertNotIn("17841474391591717", text, str(path))  # IG account id
            self.assertNotIn("4663575847256279", text, str(path))   # Meta app id
            self.assertNotIn("UCOkonr576sJUOSYYpE84QcA", text, str(path))  # YT channel
            self.assertNotIn("136899767415-e050d3gmtlcla6lj9mvbldmtkse7c7gp",
                             text, str(path))  # OAuth client id


class TestQuality(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not available")
    def test_check_real_video(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            vid = tmp / "test.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=0x336699:s=1080x1920:d=31",
                "-f", "lavfi", "-i", "sine=frequency=440:d=31",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(vid)], check=True)
            ok, report = quality.check_video(vid)
            self.assertTrue(ok, json.dumps(report, indent=2))
            self.assertEqual(report["checks"]["resolution"]["detail"], "1080x1920")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
