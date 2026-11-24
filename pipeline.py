#!/usr/bin/env python3
"""Tech Shot — pipeline CLI.

    python pipeline.py scan [--limit N] [--min-score S] [--dry-run]
    python pipeline.py build <reel-id> [--skip-tts] [--dry-run]
    python pipeline.py approve <reel-id>
    python pipeline.py reject <reel-id> [--note TEXT]
    python pipeline.py publish --id <reel-id> --platform instagram|facebook|youtube [--approve] [--dry-run]
    python pipeline.py status [reel-id]
    python pipeline.py next       # oldest APPROVED reel id (scheduled publish)
    python pipeline.py ready      # SCRIPT_READY reel ids, oldest first

APPROVAL MODE (the whole point): nothing publishes without a human.
`publish` refuses unless BOTH hold: the reel's status is APPROVED (set by
`approve`, only after a human watched the video) AND the --approve flag is
passed. The GitHub publish workflow enforces the same rule server-side.

2026-11-24 — the user changed the rule: "no more approvals — build and
post directly". Muse therefore builds the reels each morning (scene
images made by Muse, build via the manual build.yml workflow) and
approves them, so the scheduled publish runs have APPROVED reels to
pick. `publish` still requires APPROVED status + --approve.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from src import captions, library, news, quality, script as script_mod, verify
from src import video as video_mod
from src import voice as voice_mod
from src.publish import facebook, instagram, youtube

PLATFORMS = ("instagram", "facebook", "youtube")


def cmd_scan(args):
    items = news.discover(limit=args.limit, min_score=args.min_score)
    print(f"[scan] {len(items)} candidate(s) above score {args.min_score}")
    made = 0
    for item in items:
        dup = library.find_duplicate(config.CONTENT_DIR, item["link"])
        if dup:
            print(f"[scan] skip (already in library as {dup}): {item['title'][:60]}")
            continue
        if args.dry_run:
            print(f"[scan:dry-run] would create: {item['title'][:80]} "
                  f"(score {item['score']})")
            continue
        data = library.create_item(
            config.CONTENT_DIR, item["title"],
            sources=[{"url": item["link"], "name": item["source"],
                      "date": item["published"].isoformat() if item["published"] else ""}],
            score=item["score"], summary=item.get("summary", ""))
        verdict, reasons = verify.verify({**item, "sources": data["sources"]})
        print(f"[scan] {data['id']} — score {item['score']} — {verdict}: "
              + "; ".join(reasons))
        if verdict == "VERIFIED":
            library.set_status(config.CONTENT_DIR, data["id"], "VERIFIED",
                               "; ".join(reasons))
            draft = script_mod.draft_from_item(item)
            d = library.item_dir(config.CONTENT_DIR, data["id"])
            (d / "script.md").write_text(script_mod.render_markdown(draft),
                                         encoding="utf-8")
            library.set_status(config.CONTENT_DIR, data["id"], "SCRIPT_READY",
                               "Draft script written — human to finish the voiceover.")
            print(f"[scan] draft script -> {d / 'script.md'}")
        else:
            data = library.load_item(config.CONTENT_DIR, data["id"])
            data["verification"] = {"verdict": verdict, "reasons": reasons}
            library.save_item(config.CONTENT_DIR, data)
            print(f"[scan] left DISCOVERED — needs a 2nd source / date before a script.")
        made += 1
    print(f"[scan] done: {made} new item(s).")
    return 0


def _load_script(item_dir):
    md = item_dir / "script.md"
    if not md.exists():
        raise FileNotFoundError(f"No script.md in {item_dir} — write the "
                                "voiceover first (see content/examples/).")
    return script_mod.from_markdown(md.read_text(encoding="utf-8"))


def cmd_build(args):
    data = library.load_item(config.CONTENT_DIR, args.reel_id)
    if data["status"] not in ("SCRIPT_READY", "AUDIO_READY"):
        print(f"[build] reel {args.reel_id} is {data['status']} — need SCRIPT_READY.")
        return 1
    d = library.item_dir(config.CONTENT_DIR, args.reel_id)
    script = _load_script(d)
    problems = script_mod.validate(script)
    if problems:
        print("[build] script invalid:")
        for p in problems:
            print("  -", p)
        return 1
    work = d / "work"
    work.mkdir(exist_ok=True)
    # 1. Voice (Kokoro primary, Piper fallback) — skip if wav chunks exist.
    if args.skip_tts:
        chunks = []
        for wav in sorted(work.glob("chunk_*.wav")):
            parts = wav.stem.replace("chunk_", "").split("c")
            scene_idx = int(parts[0][1:]) if parts[0].startswith("s") else 0
            chunks.append((wav.stem, wav, video_mod.wav_dur(wav), scene_idx))
        if not chunks:
            print("[build] --skip-tts but no chunk_*.wav in work/ — run without it.")
            return 1
    else:
        if args.dry_run:
            print("[build:dry-run] would TTS voiceover "
                  f"({script.get('voice', 'male')}) and assemble video.")
            return 0
        chunks = voice_mod.synthesize_chunks(script, work)
        library.set_status(config.CONTENT_DIR, args.reel_id, "AUDIO_READY",
                           "Voiceover done.")
    # 2. Images: 5 scene images must exist (made by Muse from the script).
    images = []
    for i in range(1, 6):
        found = sorted(d.glob(f"scene_{i}.*"))
        found = [f for f in found if f.suffix.lower() in (".webp", ".png", ".jpg")]
        if not found:
            print(f"[build] missing scene_{i} image in {d} — generate the scene "
                  "images first (Muse, from the script's scene table).")
            return 1
        images.append(found[0])
    # 3. Assemble + quality check.
    scene_texts = [s.get("text", "").replace(" ", "\\N", 1)
                   if "\\N" not in s.get("text", "") else s["text"]
                   for s in script["scenes"]]
    out = d / "final_video.mp4"
    _path, info = video_mod.build_reel(images, chunks, scene_texts, out, work,
                                       reel_id=args.reel_id)
    ok, report = quality.check_video(out)
    for name, c in report["checks"].items():
        print(f"[quality] {'PASS' if c['ok'] else 'FAIL'} {name}: {c['detail']}")
    if not ok:
        library.set_status(config.CONTENT_DIR, args.reel_id, "FAILED",
                           "Quality check failed.")
        print("[build] quality FAILED — video NOT sent for approval.")
        return 1
    if data["status"] != "VIDEO_READY":
        library.set_status(config.CONTENT_DIR, args.reel_id, "VIDEO_READY",
                           f"Video ready ({info['total']}s).")
    library.set_status(config.CONTENT_DIR, args.reel_id, "APPROVAL_PENDING",
                       "Watch final_video.mp4, then approve/reject.")
    print(f"[build] done — {out} ({info['total']}s). Awaiting human approval.")
    return 0


def cmd_approve(args):
    data = library.load_item(config.CONTENT_DIR, args.reel_id)
    if data["status"] != "APPROVAL_PENDING":
        print(f"[approve] reel {args.reel_id} is {data['status']} — only "
              "APPROVAL_PENDING can be approved (watch the video first).")
        return 1
    library.set_status(config.CONTENT_DIR, args.reel_id, "APPROVED",
                       "Human approved after watching.")
    print(f"[approve] {args.reel_id} APPROVED — publishable.")
    return 0


def cmd_reject(args):
    data = library.load_item(config.CONTENT_DIR, args.reel_id)
    if data["status"] != "APPROVAL_PENDING":
        print(f"[reject] reel {args.reel_id} is {data['status']} — only "
              "APPROVAL_PENDING can be rejected.")
        return 1
    library.set_status(config.CONTENT_DIR, args.reel_id, "SCRIPT_READY",
                       args.note or "Rejected — rework the script/video.")
    print(f"[reject] {args.reel_id} sent back to SCRIPT_READY.")
    return 0


def cmd_publish(args):
    if not args.approve:
        print("[publish] REFUSED — approval mode: pass --approve only after "
              "a human watched the video and ran `pipeline.py approve`.")
        return 1
    data = library.load_item(config.CONTENT_DIR, args.reel_id)
    if data["status"] not in ("APPROVED", "PUBLISHED", "SCHEDULED"):
        print(f"[publish] REFUSED — reel {args.reel_id} is {data['status']}; "
              "run `pipeline.py approve` first.")
        return 1
    d = library.item_dir(config.CONTENT_DIR, args.reel_id)
    video_path = d / "final_video.mp4"
    if not video_path.exists():
        print(f"[publish] no final_video.mp4 in {d} — run build first.")
        return 1
    script = _load_script(d)
    results = {}
    for platform in args.platform:
        if platform == "instagram":
            url = args.video_url or config.VIDEO_PUBLIC_URL
            res = instagram.publish(url, captions.instagram_caption(script),
                                    dry_run=args.dry_run)
        elif platform == "facebook":
            res = facebook.publish(video_path,
                                   captions.instagram_caption(script),
                                   dry_run=args.dry_run)
        else:
            res = youtube.publish(video_path, captions.youtube_title(script),
                                  captions.youtube_description(script),
                                  captions.youtube_tags(script),
                                  dry_run=args.dry_run)
        results[platform] = res
        print(f"[publish] {platform}: {'OK' if res['ok'] else 'FAILED'} — "
              f"{res['detail']}")
    if args.dry_run:
        print("[publish] dry run — nothing published, status unchanged.")
        return 0 if all(r["ok"] for r in results.values()) else 1
    data = library.load_item(config.CONTENT_DIR, args.reel_id)
    data.setdefault("publish", {}).update(results)
    library.save_item(config.CONTENT_DIR, data)
    if all(r["ok"] for r in results.values()):
        if data["status"] != "PUBLISHED":
            library.set_status(config.CONTENT_DIR, args.reel_id, "PUBLISHED",
                               "Published to: " + ", ".join(results))
        print(f"[publish] {args.reel_id} PUBLISHED.")
        return 0
    library.set_status(config.CONTENT_DIR, args.reel_id, "FAILED",
                       "Publish failed on: " +
                       ", ".join(p for p, r in results.items() if not r["ok"]))
    print("[publish] FAILED on some platform(s) — see above.")
    return 1


def cmd_next(args):
    """Print the OLDEST APPROVED reel id (one line, machine-readable).

    Used by the scheduled publish workflow to pick the next reel for the
    09:00 / 14:00 / 19:00 IST slots. Exit 1 (message on stderr, stdout
    stays clean) when no reel is APPROVED.
    """
    items = library.list_items(config.CONTENT_DIR, status="APPROVED")
    if not items:
        print("no APPROVED reel — nothing to publish", file=sys.stderr)
        return 1
    oldest = min(items, key=lambda d: d.get("created_at", ""))
    print(oldest["id"])
    return 0


def cmd_ready(args):
    """Print SCRIPT_READY reel ids, one per line, oldest first.

    Used by Muse's morning build loop (oldest first, up to 3 reels a
    day). Exit 0 with no output when there is nothing ready. (A raw scan
    draft is SCRIPT_READY too but its voiceover is still a TODO — `build`
    rejects it at validation, fast, and the morning loop simply moves on
    to the next id.)
    """
    items = library.list_items(config.CONTENT_DIR, status="SCRIPT_READY")
    for item in reversed(items):  # list_items is newest-first
        print(item["id"])
    return 0


def cmd_status(args):
    if args.reel_id:
        data = library.load_item(config.CONTENT_DIR, args.reel_id)
        print(f"{data['id']} — {data['title']}")
        print(f"  status: {data['status']}  score: {data.get('score')}")
        for h in data.get("history", []):
            print(f"  {h['at'][:19]}  {h.get('from')} -> {h['to']}  {h.get('note', '')}")
        if data.get("publish"):
            for p, r in data["publish"].items():
                print(f"  publish {p}: {'OK' if r.get('ok') else 'FAILED'} — {r.get('detail')}")
    else:
        items = library.list_items(config.CONTENT_DIR)
        if not items:
            print("Library empty — run `pipeline.py scan` first.")
            return 0
        print(f"{'REEL':<28} {'STATUS':<16} SCORE  TITLE")
        for it in items[:30]:
            print(f"{it['id']:<28} {it['status']:<16} {str(it.get('score')):<6} "
                  f"{it['title'][:60]}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pipeline.py",
                                 description="Tech Shot — Hindi news Reels pipeline")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="Discover news, verify, write draft scripts")
    p.add_argument("--limit", type=int, default=config.SCAN_LIMIT)
    p.add_argument("--min-score", type=float, default=config.SCAN_MIN_SCORE)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("build", help="Script -> voiceover -> video -> quality")
    p.add_argument("reel_id")
    p.add_argument("--skip-tts", action="store_true",
                   help="Reuse existing chunk_*.wav in work/")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("approve", help="Human approves a reel for publishing")
    p.add_argument("reel_id")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("reject", help="Send a reel back for rework")
    p.add_argument("reel_id")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_reject)

    p = sub.add_parser("publish", help="Publish an APPROVED reel (needs --approve)")
    p.add_argument("--id", dest="reel_id", required=True)
    p.add_argument("--platform", nargs="+", choices=PLATFORMS, required=True)
    p.add_argument("--approve", action="store_true",
                   help="Explicit human approval for THIS publish run")
    p.add_argument("--video-url", default="",
                   help="Public video URL (Instagram only)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("status", help="Show library / one reel")
    p.add_argument("reel_id", nargs="?")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("next", help="Oldest APPROVED reel id (scheduled publish)")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("ready", help="SCRIPT_READY reel ids, oldest first")
    p.set_defaults(func=cmd_ready)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
