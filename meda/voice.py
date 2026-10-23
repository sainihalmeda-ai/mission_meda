"""Natural Telugu, Hindi and English voices for the crew.

Uses Microsoft Edge's free online voices (the same ones behind Edge's Read
Aloud), so nothing needs installing on your computer. If they can't be
reached, the web app falls back to whatever voices your browser has.
"""

import hashlib
import re
from collections import OrderedDict

from . import agents

# Two neural voices per language: one female, one male.
VOICES = {
    "te": {"female": "te-IN-ShrutiNeural", "male": "te-IN-MohanNeural"},
    "hi": {"female": "hi-IN-SwaraNeural", "male": "hi-IN-MadhurNeural"},
    "en": {"female": "en-IN-NeerjaNeural", "male": "en-IN-PrabhatNeural"},
}

_cache: "OrderedDict[str, bytes]" = OrderedDict()
CACHE_SIZE = 40


def language_of(text: str) -> str:
    telugu = len(re.findall(r"[ఀ-౿]", text))
    hindi = len(re.findall(r"[ऀ-ॿ]", text))
    if telugu >= hindi and telugu > 0:
        return "te"
    if hindi > 0:
        return "hi"
    return "en"


def speakable(text: str) -> str:
    text = re.sub(r"```.*?```", " Code is on screen. ", text, flags=re.S)
    text = re.sub(r"https?://\S+", " link on screen ", text)
    text = re.sub(r"[*_#>`|]", "", text)
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️‍]", "", text)  # emoji
    return re.sub(r"\s+", " ", text).strip()[:3000]


def pick(agent_key: str, text: str) -> tuple[str, str, str]:
    """Voice name plus rate and pitch tweaks so each agent sounds a bit different."""
    agent = agents.CREW.get(agent_key)
    v = agent.voice if agent else {}
    voice = VOICES[language_of(text)][v.get("gender", "female")]
    rate = round((v.get("rate", 1.0) - 1.0) * 100)
    pitch = round((v.get("pitch", 1.0) - 1.0) * 50)
    return voice, f"{rate:+d}%", f"{pitch:+d}Hz"


async def synthesize(agent_key: str, text: str) -> bytes:
    import edge_tts

    clean = speakable(text)
    if not clean:
        return b""
    voice, rate, pitch = pick(agent_key, clean)
    key = hashlib.sha1(f"{voice}{rate}{pitch}{clean}".encode()).hexdigest()
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    audio = bytearray()
    async for chunk in edge_tts.Communicate(clean, voice, rate=rate, pitch=pitch).stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    data = bytes(audio)
    _cache[key] = data
    if len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return data
