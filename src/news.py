"""Tech Shot — news discovery (free RSS only, no paid news API).

Sources: Google News RSS + official blogs (Google, OpenAI, etc.).
Each item is scored 0-10 (importance / audience fit / trending / visual /
credibility) so the daily scan can pick the top stories. Nothing here
publishes anything — scoring only ranks candidates for verification.
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

USER_AGENT = "TechShot/1.0 (free RSS reader; contact: Tech Shot)"
REQUEST_TIMEOUT = 20

# Free RSS feeds. Google News RSS needs no key; official blogs are the
# credibility anchor (a story from an official blog outranks an aggregator).
FEEDS = [
    ("Google News — AI", "https://news.google.com/rss/search?q=artificial%20intelligence&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News — Tech", "https://news.google.com/rss/search?q=technology&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News — Gemini", "https://news.google.com/rss/search?q=Gemini%20Google&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News — ChatGPT", "https://news.google.com/rss/search?q=ChatGPT%20OpenAI&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Gadgets360 — AI", "https://www.gadgets360.com/ai/rss"),
    ("Google Blog", "https://blog.google/rss/"),
    ("OpenAI News", "https://openai.com/news/rss.xml"),
]

# Keyword weights for scoring (Hindi audience: India + free + mobile first).
KEYWORDS = {
    "gemini": 2.0, "chatgpt": 2.0, "openai": 1.5, "google ai": 1.5,
    "launch": 1.5, "launched": 1.5, "rollout": 1.5, "free": 2.0,
    "india": 2.0, "indian": 1.5, "android": 1.0, "iphone": 0.5,
    "update": 1.0, "feature": 1.0, "app": 0.5, "security": 1.5,
    "cyber": 1.0, "scam": 1.5, "fraud": 1.5, "ai": 1.0,
    "whatsapp": 1.0, "instagram": 0.5, "youtube": 0.5, "5g": 0.5,
}
NEGATIVE_KEYWORDS = {
    "rumor": -3.0, "rumour": -3.0, "leak": -3.0, "leaked": -3.0,
    "allegedly": -2.0, "unconfirmed": -3.0, "may launch": -1.0,
    "expected": -1.0, "price in india": -0.5,
}

# Credibility anchor: official sources score higher than aggregators.
SOURCE_CREDIBILITY = {
    "blog.google": 2.0, "openai.com": 2.0, "developers.googleblog.com": 2.0,
    "gadgets360.com": 1.0, "news.google.com": 0.5,
}


def _parse_date(text):
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def parse_rss(xml_text, feed_name):
    """Parse RSS 2.0 or Atom XML into a list of item dicts (stdlib only)."""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    def _text(elem, tag):
        child = elem.find(tag)
        return (child.text or "").strip() if child is not None else ""

    def _atom_text(elem, tag):
        ns = "{http://www.w3.org/2005/Atom}"
        child = elem.find(ns + tag)
        return (child.text or "").strip() if child is not None else ""

    entries = []
    if root.tag == "rss" or root.find("channel") is not None:
        channel = root.find("channel")
        entries = channel.findall("item") if channel is not None else []
        for e in entries:
            link = _text(e, "link")
            items.append({
                "title": _text(e, "title"),
                "link": link,
                "published": _parse_date(_text(e, "pubDate")),
                "summary": re.sub(r"<[^>]+>", "", _text(e, "description"))[:500],
                "source": feed_name,
                "source_url": link,
            })
    else:  # Atom
        ns = "{http://www.w3.org/2005/Atom}"
        for e in root.findall(ns + "entry"):
            link_el = e.find(ns + "link")
            link = link_el.get("href", "") if link_el is not None else ""
            items.append({
                "title": _atom_text(e, "title"),
                "link": link,
                "published": _parse_date(_atom_text(e, "published") or _atom_text(e, "updated")),
                "summary": re.sub(r"<[^>]+>", "", _atom_text(e, "summary"))[:500],
                "source": feed_name,
                "source_url": link,
            })
    return [i for i in items if i["title"] and i["link"]]


def fetch_feed(url, feed_name):
    """Fetch one RSS feed; returns [] on any failure (never raises)."""
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT},
                            timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return parse_rss(resp.text, feed_name)
    except Exception as exc:  # network down, feed moved, bad XML — skip feed
        print(f"[news] feed failed ({feed_name}): {exc}")
        return []


def _domain(url):
    m = re.search(r"https?://([^/]+)", url or "")
    return m.group(1).lower().replace("www.", "") if m else ""


def score(item, now=None):
    """Score an item 0-10. Deterministic; same input always gives same score."""
    now = now or datetime.now(timezone.utc)
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    s = 3.0  # base: it made it into a feed at all
    for kw, w in KEYWORDS.items():
        if kw in text:
            s += w
    for kw, w in NEGATIVE_KEYWORDS.items():
        if kw in text:
            s += w  # negative weights — rumors/leaks sink
    s += SOURCE_CREDIBILITY.get(_domain(item.get("source_url", "")), 0.0)
    pub = item.get("published")
    if pub:
        age_h = max(0.0, (now - pub).total_seconds() / 3600.0)
        if age_h <= 24:
            s += 1.5
        elif age_h <= 72:
            s += 0.5
        elif age_h > 168:  # older than a week — stale for a news reel
            s -= 2.0
    else:
        s -= 1.0  # no date = cannot verify recency
    return round(max(0.0, min(10.0, s)), 1)


def discover(feeds=None, limit=10, min_score=6.0, fetch=None):
    """Fetch feeds, dedupe by URL, score, return top items above min_score.

    `fetch` is injectable so tests can pass a mocked feed (resolved at call
    time so monkeypatching news.fetch_feed works).
    """
    fetch = fetch or fetch_feed
    feeds = feeds if feeds is not None else FEEDS
    seen, items = set(), []
    for name, url in feeds:
        for item in fetch(url, name):
            if item["link"] in seen:
                continue
            seen.add(item["link"])
            item["score"] = score(item)
            items.append(item)
    items.sort(key=lambda i: i["score"], reverse=True)
    return [i for i in items if i["score"] >= min_score][:limit]
