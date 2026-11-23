"""Tech Shot — Latin-word fix for Devanagari voiceovers.

Kokoro's Hindi voice mangles Latin-script words left inside a Devanagari
script ("GTA 6" came out as "जिटिये चहे", "Vice City" as "वाए सिटी" in a
Whisper transcript of a finished reel). Rahasya Bharat fixes this the same
way: before TTS, every Latin word is converted to Devanagari.

Two layers:
  1. A dictionary of tech terms (exact, case-insensitive).
  2. A generic letter-by-letter transliteration fallback for unknown
     Latin words (digits pass through unchanged).

Already-Devanagari text, punctuation and digits are never touched.
"""

import re

# Tech terms -> Devanagari (keys are uppercase; lookup is case-insensitive).
LATIN_TO_DEVANAGARI = {
    # Games / consoles
    "GTA": "जीटीए", "GTA6": "जीटीए6", "GTA5": "जीटीए5", "GTA4": "जीटीए4",
    "PS5": "पीएस5", "PS4": "पीएस4", "PS5PRO": "पीएस5प्रो",
    "XBOX": "एक्सबॉक्स", "PLAYSTATION": "प्लेस्टेशन", "NINTENDO": "निन्टेंडो",
    "STEAM": "स्टीम", "EPIC": "एपिक", "ROBLOX": "रोब्लॉक्स",
    "MINECRAFT": "माइनक्राफ्ट", "BGMI": "बीजीएमआई", "PUBG": "पबजी",
    "FORTNITE": "फोर्टनाइट", "CALL OF DUTY": "कॉल ऑफ़ ड्यूटी",
    # Reviews / scores
    "METACRITIC": "मेटाक्रिटिक", "IMDB": "आईएमडीबी", "ROTTEN": "रॉटन",
    # Platforms / apps
    "INSTAGRAM": "इंस्टाग्राम", "YOUTUBE": "यूट्यूब", "FACEBOOK": "फेसबुक",
    "WHATSAPP": "व्हाट्सऐप", "TELEGRAM": "टेलीग्राम", "X": "एक्स",
    "TWITTER": "ट्विटर", "SNAPCHAT": "स्नैपचैट", "THREADS": "थ्रेड्स",
    "NETFLIX": "नेटफ्लिक्स", "SPOTIFY": "स्पॉटिफ़ाई", "DISNEY": "डिज़्नी",
    "HOTSTAR": "हॉटस्टार", "PRIME": "प्राइम", "ZOMATO": "ज़ोमैटो",
    "SWIGGY": "स्विगी", "FLIPKART": "फ्लिपकार्ट",
    # AI / tech
    "AI": "एआई", "CHATGPT": "चैटजीपीटी", "GEMINI": "जेमिनी",
    "COPILOT": "कोपायलट", "CLAUDE": "क्लॉड", "GROK": "ग्रोक",
    "GOOGLE": "गूगल", "MICROSOFT": "माइक्रोसॉफ्ट", "APPLE": "ऐपल",
    "SAMSUNG": "सैमसंग", "NVIDIA": "एनवीडिया", "INTEL": "इंटेल",
    "OPENAI": "ओपनएआई", "META": "मेटा", "ANDROID": "एंड्रॉयड",
    "IPHONE": "आईफोन", "IOS": "आईओएस", "MAC": "मैक", "WINDOWS": "विंडोज़",
    "LINUX": "लिनक्स", "PYTHON": "पाइथन", "CODE": "कोड",
    "ROBOT": "रोबोट", "DRONE": "ड्रोन", "VR": "वीआर", "AR": "एआर",
    "API": "एपीआई", "URL": "यूआरएल", "PDF": "पीडीएफ़", "VPN": "वीपीएन",
    "NASA": "नासा", "ISRO": "इसरो", "SPACEX": "स्पेसएक्स", "TESLA": "टेस्ला",
    "EV": "ईवी", "UPI": "यूपीआई", "OTP": "ओटीपी", "EMI": "ईएमआई",
    "GST": "जीएसटी", "SIM": "सिम", "ESIM": "ईसिम", "USB": "यूएसबी",
    # Connectivity / specs
    "WIFI": "वाईफाई", "BLUETOOTH": "ब्लूटूथ", "5G": "5जी", "4G": "4जी",
    "3G": "3जी", "GB": "जीबी", "MB": "एमबी", "KB": "केबी", "TB": "टीबी",
    "RAM": "रैम", "HD": "एचडी", "4K": "4के", "8K": "8के", "FPS": "एफपीएस",
    "LED": "एलईडी", "OLED": "ओएलईडी", "AMOLED": "एमोलेड",
    "SNAPDRAGON": "स्नैपड्रैगन", "MEDIATEK": "मीडियाटेक",
    "BATTERY": "बैटरी", "CAMERA": "कैमरा", "CHARGING": "चार्जिंग",
    "DISPLAY": "डिस्प्ले", "STORAGE": "स्टोरेज", "INTERNET": "इंटरनेट",
    "ONLINE": "ऑनलाइन", "OFFLINE": "ऑफलाइन", "CYBER": "साइबर",
    "HACK": "हैक", "SCAM": "स्कैम",
    # Social / content words
    "SUBSCRIBE": "सब्सक्राइब", "FOLLOW": "फॉलो", "LIKE": "लाइक",
    "SHARE": "शेयर", "COMMENT": "कमेंट", "REEL": "रील", "REELS": "रील्स",
    "SHORTS": "शॉट्स", "APP": "ऐप", "APPS": "ऐप्स", "PLAY": "प्ले",
    "STORE": "स्टोर", "UPDATE": "अपडेट", "LAUNCH": "लॉन्च",
    "PRICE": "प्राइस", "REVIEW": "रिव्यू", "TRAILER": "ट्रेलर",
    "TEASER": "टीज़र", "LEAK": "लीक", "RUMOR": "रूमर", "VIRAL": "वायरल",
    "TRENDING": "ट्रेंडिंग", "LIVE": "लाइव", "NEWS": "न्यूज़",
    "TECH": "टेक", "NEW": "न्यू", "LATEST": "लेटेस्ट", "BREAKING": "ब्रेकिंग",
    "FREE": "फ्री", "OFFER": "ऑफर", "SALE": "सेल", "DEAL": "डील",
    "BEST": "बेस्ट", "TOP": "टॉप", "INDIA": "इंडिया", "WORLD": "वर्ल्ड",
    "PRO": "प्रो", "PLUS": "प्लस", "ULTRA": "अल्ट्रा", "MAX": "मैक्स",
    "NOTIFICATION": "नोटिफिकेशन", "SETTINGS": "सेटिंग्स",
    "VICE": "वाइस", "CITY": "सिटी", "LUCIA": "लूसिया", "JASON": "जेसन",
}

# --- Generic transliteration fallback ---------------------------------------
# Vowels: full form (word start / after a vowel) and sign (after a consonant).
_VOWELS = {  # token -> (standalone, sign after consonant)
    "aa": ("आ", "ा"), "ee": ("ई", "ी"), "oo": ("ऊ", "ू"),
    "ai": ("ऐ", "ै"), "au": ("औ", "ौ"), "ou": ("औ", "ौ"),
    "ei": ("ए", "े"),
    "a": ("अ", ""), "e": ("ए", "े"), "i": ("इ", "ि"),
    "o": ("ओ", "ो"), "u": ("उ", "ु"),
}
# Consonants: base form (inherent 'a'). Digraphs first — longest match wins.
_CONSONANTS = {
    "chh": "छ", "kh": "ख", "gh": "घ", "ch": "च", "jh": "झ",
    "th": "थ", "dh": "ध", "ph": "फ", "bh": "भ", "sh": "श", "ng": "ङ",
    "k": "क", "g": "ग", "c": "क", "j": "ज", "t": "त", "d": "द",
    "n": "न", "p": "प", "b": "ब", "m": "म", "y": "य", "r": "र",
    "l": "ल", "v": "व", "w": "व", "s": "स", "h": "ह", "f": "फ़",
    "q": "क़", "x": "क्स", "z": "ज़",
}
_HALANT = "्"
_ANUSVARA = "ं"

# Any token containing at least one Latin letter.
_LATIN_WORD = re.compile(r"[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*")


def _tokenize(word):
    """Split a lowercased Latin word into (kind, text) units.

    kind is 'vowel', 'cons' or 'digit'. Longest match wins at each step.
    """
    units = []
    i = 0
    while i < len(word):
        ch = word[i]
        if ch.isdigit():
            units.append(("digit", ch))
            i += 1
            continue
        two = word[i:i + 2]
        if two in _VOWELS:
            units.append(("vowel", two))
            i += 2
        elif two in _CONSONANTS:
            units.append(("cons", two))
            i += 2
        elif ch in _VOWELS:
            units.append(("vowel", ch))
            i += 1
        elif ch in _CONSONANTS:
            units.append(("cons", ch))
            i += 1
        else:
            # Unknown character (e.g. '_'): keep it, it breaks the cluster.
            units.append(("other", ch))
            i += 1
    return units


def transliterate_word(word):
    """Best-effort Latin -> Devanagari for one unknown word.

    Digits pass through unchanged. A nasal (n/m) before a consonant
    becomes anusvara, a consonant before another consonant takes a halant,
    and a vowel after a consonant becomes a vowel sign. A vowel after a
    vowel (or after a consonant whose inherent 'a' was already used)
    renders standalone.
    """
    units = _tokenize(word.lower())
    out = []
    pending_cons = False  # last emitted char is a bare consonant awaiting a vowel sign
    for idx, (kind, tok) in enumerate(units):
        if kind == "digit" or kind == "other":
            out.append(tok)
            pending_cons = False
            continue
        if kind == "vowel":
            standalone, sign = _VOWELS[tok]
            out.append(sign if pending_cons else standalone)
            pending_cons = False
            continue
        # consonant
        base = _CONSONANTS[tok]
        nxt = units[idx + 1] if idx + 1 < len(units) else None
        if tok in ("n", "m") and nxt and nxt[0] == "cons":
            out.append(_ANUSVARA)
            pending_cons = False
        elif nxt and nxt[0] == "cons":
            out.append(base + _HALANT)
            pending_cons = False
        else:
            out.append(base)  # vowel sign may follow, or inherent 'a'
            pending_cons = True
    return "".join(out)


def fix_latin_words(text):
    """Convert Latin-script words in `text` to Devanagari.

    Dictionary hits first, generic transliteration for the rest.
    Devanagari text, punctuation and digits are left untouched.
    """
    if not text:
        return text

    def _replace(match):
        word = match.group(0)
        hit = LATIN_TO_DEVANAGARI.get(word.upper())
        if hit:
            return hit
        return transliterate_word(word)

    return _LATIN_WORD.sub(_replace, text)
