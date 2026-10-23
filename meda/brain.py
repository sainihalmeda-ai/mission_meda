"""The Mindspace: takes a message, sends it through Jyothi's gate to the right
agent, runs that agent's tools, and pauses for your approval when Lochu wants
to touch the computer.
"""

import threading
import uuid
from datetime import datetime

import anthropic

from . import agents, config, health, memory, router, tools

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _to_dict(block) -> dict:
    """Store content blocks exactly as the API returned them, so history can be replayed."""
    return block.model_dump(mode="json", by_alias=True, exclude_none=True)


def _text_of(content: list[dict]) -> str:
    return "\n".join(b["text"] for b in content if b.get("type") == "text").strip()


def _context_block() -> str:
    facts = memory.recall("", limit=15)
    lines = [f"- #{f['id']} [{f['topic']}] {f['text']}" for f in facts]
    now = datetime.now().strftime("%A %d %B %Y, %I:%M %p")
    return (f"[Mindspace context, not from {config.OWNER_NAME}]\nNow: {now}\n"
            "Latest shared memory:\n" + ("\n".join(lines) if lines else "- (nothing yet)"))


class Crew:
    def __init__(self, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic()
        self.last_agent: str | None = None
        self.pending: dict[str, dict] = {}
        self.locks = {k: threading.Lock() for k in agents.CREW}

    # ---------- public API used by the web server ----------

    def handle(self, text: str, agent_key: str | None = None) -> dict:
        key = agent_key if agent_key in agents.CREW else router.pick(self.client, text, self.last_agent)
        self.last_agent = key
        with self.locks[key]:
            blocked = health.gate(key)
            if blocked:
                return {"agent": "jyothi", "text": blocked, "routed_to": key}
            if any(p["agent"] == key for p in self.pending.values()):
                return {"agent": key, "text": "I'm still waiting for your answer on the action above. "
                                              "Approve or deny it first.", "pending": self._pending_for(key)}
            room = memory.load_room(key)
            dangling = room and room[-1]["role"] == "assistant" and any(
                b.get("type") == "tool_use" for b in room[-1]["content"])
            if dangling or len(room) > config.MAX_ROOM_MESSAGES:
                room = []  # fresh room; shared memory carries what matters
            room.append({"role": "user", "content": [
                {"type": "text", "text": _context_block()},
                {"type": "text", "text": text},
            ]})
            return self._run(key, room)

    def decide(self, approval_id: str, decisions: dict[str, bool]) -> dict:
        """Continue after you approve or deny Lochu's actions."""
        pend = self.pending.pop(approval_id, None)
        if not pend:
            return {"agent": "jyothi", "text": "That approval has already been handled or expired."}
        key = pend["agent"]
        with self.locks[key]:
            room = pend["room"]
            results = pend["results"]
            for call in pend["calls"]:
                if decisions.get(call["id"], False):
                    output = tools.execute(call["name"], call["input"], key)
                    results.append({"type": "tool_result", "tool_use_id": call["id"], "content": output})
                else:
                    results.append({"type": "tool_result", "tool_use_id": call["id"], "is_error": True,
                                    "content": f"{config.OWNER_NAME} denied this action. Don't retry it; ask what they'd prefer."})
            room.append({"role": "user", "content": results})
            return self._run(key, room)

    def reset(self, key: str) -> None:
        memory.clear_room(key)
        for pid in [p for p, v in self.pending.items() if v["agent"] == key]:
            self.pending.pop(pid)

    # ---------- the agent loop ----------

    def _call(self, agent: agents.Agent, room: list[dict]):
        return self.client.beta.messages.create(
            model=config.MODEL,
            max_tokens=16000,
            system=agents.system_prompt(agent),
            tools=agent.tool_defs,
            messages=room,
            thinking={"type": "adaptive"},
            output_config={"effort": agent.effort},
            cache_control={"type": "ephemeral"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )

    def _run(self, key: str, room: list[dict]) -> dict:
        agent = agents.CREW[key]
        spoken: list[str] = []
        actions: list[dict] = []
        for _ in range(12):  # hard stop so a confused agent can't loop forever
            try:
                resp = self._call(agent, room)
            except anthropic.AuthenticationError:
                return {"agent": "jyothi", "text": "Jyothi here. The Claude API key is missing or wrong. Check ANTHROPIC_API_KEY in .env."}
            except anthropic.RateLimitError:
                return {"agent": "jyothi", "text": f"Jyothi here. Claude is rate limiting us, so {agent.name} is taking a short breather. Try again in a minute."}
            except anthropic.APIConnectionError:
                return {"agent": "jyothi", "text": "Jyothi here. I can't reach the internet right now. Check your connection."}
            except anthropic.APIStatusError as e:
                return {"agent": "jyothi", "text": f"Jyothi here. Claude returned an error ({e.status_code}). Try again shortly."}

            u = resp.usage
            input_equiv = (u.input_tokens + int(1.25 * (u.cache_creation_input_tokens or 0))
                           + int(0.1 * (u.cache_read_input_tokens or 0)))
            health.book(key, input_equiv, u.output_tokens)

            if resp.stop_reason == "refusal":
                memory.clear_room(key)  # start clean so the declined turn isn't replayed
                return {"agent": key, "text": "I can't help with that one. Let's try it another way.", "actions": actions}

            content = [_to_dict(b) for b in resp.content]
            room.append({"role": "assistant", "content": content})
            said = _text_of(content)
            if said:
                spoken.append(said)
            for b in content:
                if b.get("type") == "server_tool_use":
                    actions.append({"tool": b.get("name"), "summary": "searched the web", "done": True})

            if resp.stop_reason == "pause_turn":
                continue  # web search paused mid-turn; send it back to carry on
            if resp.stop_reason != "tool_use":
                break

            calls = [b for b in content if b.get("type") == "tool_use"]
            results, waiting = [], []
            for call in calls:
                name, args = call["name"], call.get("input") or {}
                if name in tools.NEEDS_APPROVAL:
                    reason = tools.blocked_reason(name, args)
                    if reason:
                        results.append({"type": "tool_result", "tool_use_id": call["id"], "is_error": True, "content": reason})
                        actions.append({"tool": name, "summary": reason, "done": False})
                    else:
                        waiting.append(call)
                    continue
                output = tools.execute(name, args, key)
                results.append({"type": "tool_result", "tool_use_id": call["id"], "content": output})
                actions.append({"tool": name, "summary": name.replace("_", " "), "done": True})

            if waiting:
                approval_id = uuid.uuid4().hex[:12]
                self.pending[approval_id] = {"agent": key, "room": room, "calls": waiting, "results": results}
                memory.save_room(key, room)
                return {"agent": key, "text": "\n\n".join(spoken), "actions": actions,
                        "pending": self._pending_for(key)}
            room.append({"role": "user", "content": results})
        else:
            spoken.append("I've been going in circles, so I stopped here. Tell me how you'd like to continue.")

        memory.save_room(key, room)
        return {"agent": key, "text": "\n\n".join(spoken), "actions": actions}

    def _pending_for(self, key: str) -> dict | None:
        for pid, p in self.pending.items():
            if p["agent"] == key:
                return {"id": pid, "agent": key, "actions": [
                    {"id": c["id"], "tool": c["name"], "description": tools.describe_action(c["name"], c.get("input") or {}),
                     "why": (c.get("input") or {}).get("why", "")} for c in p["calls"]]}
        return None

    def all_pending(self) -> list[dict]:
        return [self._pending_for(p["agent"]) for p in self.pending.values()]
