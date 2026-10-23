"""Decides which crew member hears each message.

Say a name ("Indu, I can't sleep" / "లోచు, build fail అయింది") and that agent answers.
Otherwise a quick Claude call picks the best fit, leaning toward whoever you were
just talking to.
"""

import json
import re

from . import agents, config, health

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


def pick(client, text: str, last_agent: str | None) -> str:
    named = by_name(text)
    if named:
        return named
    try:
        resp = client.messages.create(
            model=config.MODEL,
            max_tokens=2000,
            system=ROUTER_PROMPT,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": f"Previous assistant: {last_agent or 'none'}\nMessage: {text}"}],
        )
        health.book("jyothi", resp.usage.input_tokens, resp.usage.output_tokens)
        if resp.stop_reason == "refusal":
            return last_agent or "sonu"
        raw = next(b.text for b in resp.content if b.type == "text")
        choice = json.loads(raw)["agent"]
        return choice if choice in agents.CREW else (last_agent or "sonu")
    except Exception:
        return last_agent or "sonu"
