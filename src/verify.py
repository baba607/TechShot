"""Tech Shot — verification rules.

The one hard rule of this project: verification FAILS => NO PUBLISH, no
matter how viral the story is. Verification never guesses: a claim is only
"verified" if it appears in a named source with a date.

Rules:
  1. At least one original source (URL + publisher name + publication date).
  2. Big stories (score >= 8, or flagged "big") need a SECOND, independent
     source from a different domain.
  3. Rumor/leak language in the title/summary fails verification outright.
  4. Every claim in the script must trace to a source; claims without a
     source go on the "claims NOT to make" list, never into the script.
"""

from urllib.parse import urlparse

RUMOR_WORDS = ("rumor", "rumour", "leak", "leaked", "allegedly",
               "unconfirmed", "insider claims", "tipster")
BIG_SCORE = 8.0


def _domain(url):
    try:
        return urlparse(url or "").netloc.lower().replace("www.", "")
    except Exception:
        return ""


def verify(item):
    """Verify a news item dict. Returns (verdict, reasons).

    verdict: "VERIFIED" or "UNVERIFIED".
    reasons: list of human-readable strings explaining the verdict.
    `item` fields used: title, summary, score, sources (list of dicts with
    url, name, date), big (bool, optional).
    """
    reasons = []
    title = (item.get("title") or "").lower()
    summary = (item.get("summary") or "").lower()
    sources = item.get("sources") or []
    if item.get("source_url"):
        sources = list(sources) + [{
            "url": item["source_url"],
            "name": item.get("source", "unknown"),
            "date": (item.get("published").isoformat()
                     if item.get("published") else None),
        }]

    for word in RUMOR_WORDS:
        if word in title or word in summary:
            reasons.append(f"Rumor/leak language present ('{word}') — never publish.")
    if not sources:
        reasons.append("No source at all.")
    for src in sources:
        if not src.get("url"):
            reasons.append("A source is missing its URL.")
        if not src.get("date"):
            reasons.append(f"Source {src.get('name', '?')} has no publication date.")
    domains = {_domain(s.get("url")) for s in sources if s.get("url")}
    is_big = bool(item.get("big")) or (item.get("score") or 0) >= BIG_SCORE
    if is_big and len(domains) < 2:
        reasons.append(
            f"Big story (score {item.get('score')}) needs a 2nd independent "
            "source from a different domain — only "
            f"{len(domains)} domain(s) found."
        )
    if reasons:
        return "UNVERIFIED", reasons
    return "VERIFIED", [f"Verified against {len(sources)} source(s), "
                        f"{len(domains)} domain(s)."]
