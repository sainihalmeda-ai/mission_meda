"""Decides which crew member hears each message.

Say a name ("Indu, I can't sleep" / "లోచు, build fail అయింది") and that agent answers.
Otherwise keywords pick the best fit for free, and only when they can't tell
does a quick AI call decide. Short follow-ups stay with whoever you were just
talking to. This keeps most messages to one free request.
"""

import re

from . import agents, health

ROUTER_PROMPT = """You route messages to one of five assistants. Pick exactly one.
sonu: academics, classes, exams, study plans, daily schedule, job or internship applications, resumes,
  career, earning pocket money, open source contributions for money.
indu: feelings, stress, sadness, loneliness, sleep, food, health, fitness, calming down, self-care.
lochu: code, projects, errors, debugging, building, deploying, running or stopping programs, servers,
  credentials, anything to do on the computer.
jyothi: how the AI crew is doing, budget, token usage, cooldowns, computer CPU, memory, battery, heat.
ramu: anger, fights, arguments, heated or sentimental moments, needing courage right now, a tough
  situation that needs a quick decision.
The message may be in Telugu, Hindi, English, or a mix. If it is a short follow-up like "ok", "next?",
"inka cheppu", or "thanks", choose the previous assistant."""

SCHEMA = {
    "type": "object",
    "properties": {"agent": {"type": "string", "enum": list(agents.CREW)}},
    "required": ["agent"],
    "additionalProperties": False,
}


def by_name(text: str) -> str | None:
    """Return the agent whose name the message starts with or clearly addresses."""
    # Look at the first few words only, so "tell Indu later" deep in a sentence doesn't count.
    words = [w for w in re.split(r"[\s,.!?:;]+", text.strip().lower()) if w][:3]
    for key, agent in agents.CREW.items():
        for alias in agent.aliases:
            # startswith lets Telugu and Hindi suffixes through, e.g. "సోనుకి", "इंदु जी".
            if any(w == alias or (not alias.isascii() and w.startswith(alias)) for w in words):
                return key
    return None


# Topic words in English, Telugu typed in English letters, Telugu script, and Hindi.
KEYWORDS = {
    "sonu": r"exam|study|studies|class|college|semester|assignment|homework|syllabus|marks|result|timetable|schedule"
            r"|plan|today|tomorrow|deadline|job|intern|resume|cv|interview|career|placement|apply|application|gsoc"
            r"|open ?source|earn|money|pocket|paise|dabbulu|chaduv|parikshal|pareeksha|పరీక్ష|చదువ|క్లాస్|ఉద్యోగ|డబ్బు"
            r"|ప్లాన్|परीक्षा|पढ़ाई|नौकरी|पैसे",
    "indu": r"sad|stress|anxious|anxiety|lonely|alone|cry|tired|sleep|insomnia|headache|sick|fever|health|food|eat"
            r"|water|gym|exercise|calm|relax|mood|feel|bhayam|badha|nidra|nidra|alasata|ఒత్తిడి|నిద్ర|బాధ|భయం|ఆరోగ్య"
            r"|ఒంటరి|उदास|तनाव|नींद|डर|अकेला|सेहत",
    "lochu": r"code|coding|bug|error|exception|debug|build|deploy|server|run|test|crash|python|java|node|npm|pip|git"
             r"|github|repo|project|script|install|terminal|command|port|api|credential|token|restart|relaunch|stop"
             r"|kill|simulat|లోపం|ఎర్రర్|कोड|एरर",
    "jyothi": r"cpu|ram|memory|battery|disk|heat|hot|temperature|fan|laptop slow|slow|budget|limit|quota|usage|tokens"
              r"|cooldown|cool down|crew health|system health|బ్యాటరీ|बैटरी",
    "ramu": r"angry|anger|fight|argu|shout|furious|hate|break ?up|insult|revenge|courage|scared to|confront|decision"
            r"|kopam|kopam|godava|ధైర్యం|కోపం|గొడవ|गुस्सा|लड़ाई|हिम्मत",
}


def _word(w: str) -> str:
    # English words match at a word start ("exams", "debugging"); very short ones must be whole words ("ram", not "program").
    if not w.isascii():
        return w
    return rf"\b{w}\b" if len(w) <= 3 else rf"\b{w}"


_KW = {k: re.compile("|".join(_word(w) for w in v.split("|")), re.IGNORECASE) for k, v in KEYWORDS.items()}
FOLLOW_UP = re.compile(r"^\W*(ok|okay|k|hmm+|yes|no|haa|ha|avunu|ledu|sare|sari|thanks|thank you|thx|next|then|inka"
                       r"|inka cheppu|cheppu|continue|go on|more|and|why|how|enti|ela|సరే|అవును|లేదు|ఇంకా|ठीक|हाँ|और)\W*$",
                       re.IGNORECASE)


def scores(text: str) -> dict[str, int]:
    return {k: len(rx.findall(text)) for k, rx in _KW.items()}


def by_keywords(text: str) -> str | None:
    """The agent whose topic words clearly win, or None when it's a tie or no match."""
    ranked = sorted(scores(text).items(), key=lambda kv: -kv[1])
    (top, n1), (_, n2) = ranked[0], ranked[1]
    return top if n1 > n2 else None


def pick(provider, text: str, last_agent: str | None) -> str:
    named = by_name(text)
    if named:
        return named
    if last_agent and (FOLLOW_UP.match(text) or len(text.split()) <= 2):
        return last_agent
    guessed = by_keywords(text)
    if guessed:
        return guessed
    if not any(scores(text).values()):
        return last_agent or "sonu"  # no topic words at all: keep talking to the same person, no request spent
    try:
        data, tin, tout = provider.classify(
            ROUTER_PROMPT, f"Previous assistant: {last_agent or 'none'}\nMessage: {text}", SCHEMA)
        health.book("jyothi", tin, tout)
        choice = data.get("agent")
        return choice if choice in agents.CREW else (last_agent or "sonu")
    except Exception:
        return last_agent or "sonu"


GROUP_PROMPT = ROUTER_PROMPT.split("The message may be")[0] + """The user is asking the whole crew. Pick the 2 or 3
assistants whose views matter most for this message, most relevant first. The message may be in Telugu, Hindi,
English, or a mix."""

GROUP_SCHEMA = {
    "type": "object",
    "properties": {"agents": {"type": "array", "items": {"type": "string", "enum": list(agents.CREW)}}},
    "required": ["agents"],
    "additionalProperties": False,
}


def pick_group(provider, text: str) -> list[str]:
    """Choose who joins a huddle: keywords first (free), then an AI call, then Sonu, Indu and Ramu."""
    hits = [k for k, n in sorted(scores(text).items(), key=lambda kv: -kv[1]) if n > 0]
    if hits:
        # Two voices unless three topics really came up, so a huddle doesn't eat the free requests.
        return (hits + [a for a in ("indu", "sonu", "ramu") if a not in hits])[:max(2, min(3, len(hits)))]
    try:
        data, tin, tout = provider.classify(GROUP_PROMPT, f"Message: {text}", GROUP_SCHEMA)
        health.book("jyothi", tin, tout)
        chosen = [a for a in dict.fromkeys(data.get("agents", [])) if a in agents.CREW][:3]
        if len(chosen) >= 2:
            return chosen
    except Exception:
        pass
    return ["sonu", "indu", "ramu"]
