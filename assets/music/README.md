# Tech Shot — background music (bundled)

Same idea as Rahasya Bharat: a few CC0 / public-domain tracks bundled in
the repo, mixed quietly (0.25) under the narration. No downloads at build
time, no API keys, no per-use cost.

## Tracks in this folder

| File | Track | Composer / source | License |
| --- | --- | --- | --- |
| `ancient-power-of-serpents.mp3` | Ancient Power of Serpents | Kevin MacLeod, via FreePD (mirrored on archive.org/details/freepd) | **CC0 / public domain** — OpenGameArt lists it CC0 ("No attribution required. But if you do give any, give it to Kevin MacLeod.") |
| `dark-ambient.mp3` | Dark Ambient | via FreePD (mirrored on archive.org/details/freepd) | **Public domain (FreePD)** — FreePD shared "free-to-use, Public Domain music downloads"; the whole catalogue is public domain |
| `island-mystery.mp3` | Island Mystery | via FreePD (mirrored on archive.org/details/freepd) | **Public domain (FreePD)** — same as above |

FreePD.com itself has since closed (after 17 years); the tracks here come
from the Internet Archive mirror of the FreePD collection, which is why
they are bundled in the repo instead of downloaded per build.

## Deliberately NOT here: "Limit 70" (Kevin MacLeod)

Rahasya Bharat also uses "Limit 70", but its licence on the composer's
own site (incompetech.filmmusic.io/song/5710-limit-70) is
**CC-BY 4.0 — attribution required, NOT CC0**. It was left out of this
bundle on purpose. It is free for commercial use *with* a credit line
("Limit 70 by Kevin MacLeod (incompetech.com), licensed under CC-BY 4.0"),
so if the owner wants it back, drop the mp3 in this folder and add a row
above — the rotation in `src/video.py` picks up any `*.mp3` here.

## How it is used

`src/video.py` picks one track per reel (stable rotation by reel-id hash),
mixes it at volume 0.25 under the voiceover, fades it in over 2s and out
over the last 4s, and caps the mix with a limiter (0.95). Disable with
`TECHSHOT_MUSIC_ENABLED=0`.
