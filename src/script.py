"""Tech Shot — Hindi script template + validation + .md parsing.

A reel script is a dict:
    {
      "title": str, "hook": str,
      "voiceover": str,                 # Roman Hindi, spoken (~30-45s)
      "voiceover_devanagari": str,      # Devanagari, same text — TTS input.
                                         # Piper AND Kokoro Hindi voices need
                                         # Devanagari; Roman would be misread.
      "voice": "male" | "female",       # male = hm_omega, female = hf_alpha
      "scenes": [ {"text": str, "visual": str, "time": str} x5 ],
      "caption_instagram": str, "caption_youtube_title": str,
      "caption_youtube_description": str, "hashtags": [str],
      "sources": [ {"url": str, "name": str, "date": str} ],
      "claims_not_to_make": [str],
    }

Validation enforces the 30-45s format: hook in 0-3s, 5 scenes, voiceover
~75-112 words at ~2.5 words/sec. `from_markdown()` reads the example
scripts in content/examples/ so `pipeline.py build` can use them directly.
"""

import re

WORDS_PER_SEC = 2.5
MIN_WORDS = 75    # ~30s
MAX_WORDS = 112   # ~45s
SCENE_COUNT = 5
BRAND_CTA = "Aisi hi Tech Updates ke liye Tech Shot ko follow karo!"


def estimate_seconds(voiceover):
    words = len((voiceover or "").split())
    return words / WORDS_PER_SEC, words


def validate(script):
    """Return a list of problems (empty = valid script)."""
    problems = []
    if not script.get("hook"):
        problems.append("Missing hook (0-3s opening line).")
    if not script.get("voiceover"):
        problems.append("Missing voiceover (Roman Hindi).")
    else:
        secs, words = estimate_seconds(script["voiceover"])
        if words < MIN_WORDS:
            problems.append(f"Voiceover too short: {words} words (~{secs:.0f}s); "
                            f"need {MIN_WORDS}-{MAX_WORDS} words for 30-45s.")
        if words > MAX_WORDS:
            problems.append(f"Voiceover too long: {words} words (~{secs:.0f}s); "
                            f"need {MIN_WORDS}-{MAX_WORDS} words for 30-45s.")
    if not script.get("voiceover_devanagari"):
        problems.append("Missing voiceover_devanagari — TTS needs Devanagari "
                        "input; add the same script in Devanagari.")
    scenes = script.get("scenes") or []
    if len(scenes) != SCENE_COUNT:
        problems.append(f"Need exactly {SCENE_COUNT} scenes, found {len(scenes)}.")
    for i, sc in enumerate(scenes, 1):
        if not sc.get("text"):
            problems.append(f"Scene {i}: missing on-screen text.")
        elif len(sc["text"].replace("\\N", " ")) > 60:
            problems.append(f"Scene {i}: on-screen text too long (>60 chars).")
    if not script.get("sources"):
        problems.append("No sources listed — cannot verify, cannot publish.")
    if script.get("voice", "male") not in ("male", "female"):
        problems.append("voice must be 'male' or 'female'.")
    return problems


def draft_from_item(item):
    """Build a DRAFT script skeleton from a discovered news item.

    Facts are filled in; the voiceover is a TODO for a human (or Muse) to
    write in simple Hindi. Drafts are never published — they exist so the
    daily scan leaves editable starting points, not finished scripts.
    """
    title = item.get("title", "Untitled")
    return {
        "title": title,
        "hook": "TODO: 0-3s hook — ek line me khabar, jhatka ke saath.",
        "voiceover": "",
        "voiceover_devanagari": "",
        "voice": "male",
        "scenes": [
            {"text": "TODO", "visual": "TODO: scene 1 image prompt", "time": "0-3s"},
            {"text": "TODO", "visual": "TODO: scene 2 image prompt", "time": "3-10s"},
            {"text": "TODO", "visual": "TODO: scene 3 image prompt", "time": "10-20s"},
            {"text": "TODO", "visual": "TODO: scene 4 image prompt", "time": "20-28s"},
            {"text": "TECH SHOT\\nFOLLOW KARO", "visual": "Tech Shot logo end card",
             "time": "28-35s"},
        ],
        "caption_instagram": "",
        "caption_youtube_title": title,
        "caption_youtube_description": "",
        "hashtags": ["#TechShot", "#TechNewsHindi", "#AINews"],
        "sources": [{
            "url": item.get("source_url") or item.get("link", ""),
            "name": item.get("source", "unknown"),
            "date": (item.get("published").isoformat()
                     if item.get("published") else ""),
        }],
        "claims_not_to_make": [
            "TODO: list every claim that is NOT verified (price, exact specs, "
            "India availability date) — these must never enter the voiceover.",
        ],
    }


def render_markdown(script):
    """Render a script dict back to the .md format used in content/examples/."""
    lines = [f"# {script.get('title', '')}", ""]
    lines.append("## Verification")
    for s in script.get("sources", []):
        lines.append(f"- Source: {s.get('name', '')} — {s.get('url', '')} ({s.get('date', '')})")
    lines.append("")
    lines.append("## HOOK (0-3 sec)")
    lines.append(script.get("hook", ""))
    lines.append("")
    lines.append("## VOICEOVER SCRIPT (Roman Hindi)")
    lines.append(script.get("voiceover", ""))
    lines.append("")
    lines.append("## VOICEOVER SCRIPT (Devanagari — TTS input)")
    lines.append(script.get("voiceover_devanagari", ""))
    lines.append("")
    lines.append("## SCENE BREAKDOWN")
    lines.append("| Scene | Time | Visual | On-screen text |")
    lines.append("|---|---|---|---|")
    for i, sc in enumerate(script.get("scenes", []), 1):
        lines.append(f"| {i} | {sc.get('time', '')} | {sc.get('visual', '')} | "
                     f"{sc.get('text', '')} |")
    lines.append("")
    lines.append("## CAPTION (Instagram)")
    lines.append(script.get("caption_instagram", ""))
    lines.append("")
    lines.append("## CAPTION (YouTube Shorts)")
    lines.append(f"Title: {script.get('caption_youtube_title', '')}")
    lines.append(script.get("caption_youtube_description", ""))
    lines.append("")
    lines.append("## HASHTAGS")
    lines.append(" ".join(script.get("hashtags", [])))
    lines.append("")
    lines.append("## CLAIMS NOT TO MAKE")
    for c in script.get("claims_not_to_make", []):
        lines.append(f"- {c}")
    lines.append("")
    return "\n".join(lines)


def _section(md, heading):
    """Return the text under a '## HEADING' section (up to the next ##).

    The heading may carry trailing text, e.g. '## Verification (notes)'.
    """
    m = re.search(r"^## " + re.escape(heading) + r".*$([\s\S]*?)(?=^## |\Z)",
                  md, re.MULTILINE)
    return m.group(1).strip() if m else ""


def from_markdown(md_text):
    """Parse an example script .md (content/examples/) into a script dict."""
    title_m = re.search(r"^# (.+)$", md_text, re.MULTILINE)
    script = {
        "title": title_m.group(1).strip() if title_m else "",
        "hook": "",
        "voiceover": "",
        "voiceover_devanagari": "",
        "voice": "male",
        "scenes": [],
        "caption_instagram": "",
        "caption_youtube_title": "",
        "caption_youtube_description": "",
        "hashtags": [],
        "sources": [],
        "claims_not_to_make": [],
    }
    hook_sec = _section(md_text, "HOOK (0–3 sec)") or _section(md_text, "HOOK (0-3 sec)")
    script["hook"] = hook_sec.splitlines()[0].strip(' "') if hook_sec else ""
    vo = _section(md_text, "VOICEOVER SCRIPT (Roman Hindi, ~35 sec, bolne layak)") \
        or _section(md_text, "VOICEOVER SCRIPT (Roman Hindi)")
    script["voiceover"] = " ".join(
        line.strip(' "') for line in vo.splitlines() if line.strip())
    # Sources: bullet lines with a URL under the Verification section.
    ver = _section(md_text, "Verification") or ""
    for m in re.finditer(r"\*\*Source \d+:\*\*\s*(.+?)\s*\((https?://[^)\s]+)\)", ver):
        script["sources"].append({"name": m.group(1).strip(), "url": m.group(2),
                                  "date": ""})
    if not script["sources"]:
        for m in re.finditer(r"(https?://[^\s)]+)", ver):
            script["sources"].append({"name": "", "url": m.group(1), "date": ""})
    # Scene table rows.
    scene_sec = _section(md_text, "SCENE BREAKDOWN (images + FFmpeg zoom/pan — har scene 1 image)") \
        or _section(md_text, "SCENE BREAKDOWN")
    for row in re.finditer(r"^\| \d+ \| ([^|]+)\| ([^|]+)\| ([^|]+)\|", scene_sec, re.MULTILINE):
        script["scenes"].append({
            "time": row.group(1).strip(),
            "visual": row.group(2).strip(),
            "text": row.group(3).strip(),
        })
    cap_ig = _section(md_text, "CAPTION (Instagram)")
    script["caption_instagram"] = cap_ig
    cap_yt = _section(md_text, "CAPTION (YouTube Shorts — search-friendly)") \
        or _section(md_text, "CAPTION (YouTube Shorts)")
    title_m = re.search(r"^Title:\s*(.+)$", cap_yt, re.MULTILINE)
    script["caption_youtube_title"] = title_m.group(1).strip() if title_m else ""
    script["caption_youtube_description"] = re.sub(
        r"^Title:.*$", "", cap_yt, flags=re.MULTILINE).strip()
    tags = _section(md_text, "HASHTAGS")
    script["hashtags"] = re.findall(r"#\w+", tags)
    # "Jo claim NAHI karna" is a bullet inside the Verification section,
    # not a ## heading of its own.
    claims_m = re.search(r"\*\*Jo claim NAHI karna:\*\*\s*(.+)", ver)
    script["claims_not_to_make"] = (
        [claims_m.group(1).strip()] if claims_m else [])
    return script
