"""Tech Shot — tests. Run: python -m unittest discover -s tests -v

Covers: news scoring/parsing (mocked RSS), verification rules, library
status transitions + duplicate check, script validation + .md parsing,
captions, voice dispatch (Kokoro unavailable -> Piper fallback, real Piper
if installed), publish dry-run (zero HTTP calls), mocked-feed scan,
workflow YAML validity, and a real quality check on a tiny ffmpeg video.
No test makes a real API call. No test needs network except the optional
live scan smoke test (not part of this suite).
"""

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
from src import voice as voice_mod  # noqa: E402
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
                 mock.patch.object(voice_mod, "synthesize_piper",
                                   side_effect=RuntimeError("no piper")):
                with self.assertRaises(RuntimeError):
                    voice_mod.synthesize("गूगल।", tmp / "x.wav", engine="kokoro")
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
