"""Tech Shot — pronunciation fix for Kokoro's Hindi voice.

Kokoro's Hindi (hm_omega) mispronounces some Devanagari spellings so badly
that Whisper hears a different word — the "robotic" sound the user
reported on the v6 GTA 6 reel (2026-11-24):

  script           Whisper heard      problem
  इंतज़ार          इंद्दार            ज़ read as द
  जीटीए 6          जीटीए चहाया        digit merges into the next word
  पीएस5            प्येस पांग          acronym + digit garbled
  एक्सबॉक्स        एकसबोक            क्स conjunct + बॉ
  एक्स/एस          एक सलाश एस         "/" read aloud as "slash"
  लॉन्च            लांज               ॉ (aw) mangled
  फॉलो            पालो               फॉ mangled
  मेटाक्रिटिक      मेटाक्रितिक         क्रि conjunct slurred
  लूसिया          लॉस्या              लू + सि mangled

Fix: rewrite those spellings into forms Kokoro pronounces cleanly, right
before synthesis (after latin_fix, in src/voice.py). The script file and
the on-screen subtitles are NOT touched — subtitles come from the scene
text, so they keep the clean spellings (GTA 6, PS5, ...).

Two layers:
  1. A word dictionary (longest match first) for the known-bad words.
  2. General rules that are safe for colloquial Hindi TTS:
     - nukta consonants -> base (ज़->ज, फ़->फ, क़->क, ख़->ख, ग़->ग):
       Kokoro reads ज़ as द/ज inconsistently; the base consonant is how
       most Hindi speakers say these words anyway. (Caveat: राज़ "secret"
       and राज "kingdom" would merge — राज़ is poetic and near-absent
       from tech news, and an unintelligible ज़ is worse.)
     - ॉ/ऑ (aw) -> ो/ओ: Kokoro mangles the aw sound in loanwords
       (लॉन्च, शॉट, फॉलो, कॉल); "ो" is the colloquial pronunciation.
     - "/" -> space: Kokoro reads it aloud as "slash".
"""

import re

# Devanagari -> Kokoro-friendly Devanagari. Longest first at apply time.
PRON_MAP = {
    # Acronyms + digits: Kokoro reads the joined form as one garbled word.
    # Spaced letters + the number as a word is how Indians say them.
    "जीटीए 6": "जी टी ए सिक्स",
    "जीटीए 5": "जी टी ए पाँच",
    "जीटीए 4": "जी टी ए चार",
    "जीटीए": "जी टी ए",
    "पीएस5": "पी एस पाँच",
    "पीएस4": "पी एस चार",
    "पीएस": "पी एस",
    "एक्सबॉक्स": "एक्स बॉक्स",
    "मेटाक्रिटिक": "मेटा क्रिटिक",
    # Names / Hindi words Kokoro mangles.
    "लूसिया": "लुसिया",
    "इंतज़ार": "इन्तजार",
    "रिव्यूज़": "रिव्यूज",
}

# Nukta consonant -> base consonant (see module docstring).
_NUKTA = {"ज़": "ज", "फ़": "फ", "क़": "क", "ख़": "ख", "ग़": "ग"}
# "aw" vowel -> "o" (sign and independent forms).
_AW = {"ॉ": "ो", "ऑ": "ओ"}


def fix_pronunciation(text):
    """Rewrite Devanagari `text` into forms Kokoro pronounces cleanly."""
    if not text:
        return text
    # Dictionary first (longest match first so "जीटीए 6" wins over "जीटीए").
    for src in sorted(PRON_MAP, key=len, reverse=True):
        if src in text:
            text = text.replace(src, PRON_MAP[src])
    # General rules.
    for src, dst in _NUKTA.items():
        text = text.replace(src, dst)
    for src, dst in _AW.items():
        text = text.replace(src, dst)
    text = text.replace("/", " ")
    # Tidy up any double spaces the replacements created.
    text = re.sub(r" {2,}", " ", text)
    return text
