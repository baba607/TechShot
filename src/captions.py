"""Tech Shot — captions & hashtags (Instagram + YouTube Shorts)."""

BRAND_TAGS = ["#TechShot", "#TechNewsHindi", "#AINews"]
MAX_YT_TITLE = 100


def instagram_caption(script):
    """IG caption: hook + question + CTA + hashtags (from the script dict)."""
    base = (script.get("caption_instagram") or "").strip()
    if base:
        caption = base
    else:
        caption = (script.get("title", "") + "\n\n"
                   "Aapko ye update kaisa laga? Comment me batao 👇\n"
                   "Aisi hi Tech Updates ke liye Tech Shot ko follow karo!")
    tags = list(dict.fromkeys(list(script.get("hashtags") or []) + BRAND_TAGS))
    if not any(t in caption for t in tags):
        caption = caption.rstrip() + "\n" + " ".join(tags)
    return caption


def youtube_title(script):
    title = (script.get("caption_youtube_title") or script.get("title", "")).strip()
    if len(title) > MAX_YT_TITLE:
        title = title[: MAX_YT_TITLE - 3].rstrip() + "..."
    return title


def youtube_description(script):
    desc = (script.get("caption_youtube_description") or "").strip()
    tags = list(dict.fromkeys(list(script.get("hashtags") or []) + BRAND_TAGS))
    tail = " ".join(tags)
    if tail not in desc:
        desc = (desc + "\n\n" + tail).strip()
    return desc


def youtube_tags(script):
    tags = [t.lstrip("#") for t in
            list(dict.fromkeys(list(script.get("hashtags") or []) + BRAND_TAGS))]
    return [t for t in tags if t][:15]  # YouTube allows max 15 tags / 500 chars
