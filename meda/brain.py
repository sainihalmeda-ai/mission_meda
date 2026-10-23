"""The Mindspace: takes a message, sends it through Jyothi's gate to the right
agent, runs that agent's tools, and pauses for your approval when Lochu wants
to touch the computer.
"""

import threading
import uuid
from datetime import datetime

from . import agents, config, health, memory, providers, router, tools


def _context_block() -> str:
    facts = memory.recall("", limit=15)
    lines = [f"- #{f['id']} [{f['topic']}] {f['text']}" for f in facts]
    now = datetime.now().strftime("%A %d %B %Y, %I:%M %p")
    return (f"[Mindspace context, not from {config.OWNER_NAME}]\nNow: {now}\n"
            "Latest shared memory:\n" + ("\n".join(lines) if lines else "- (nothing yet)"))


class Crew:
    def __init__(self, provider=None):
        self.ai = provider or providers.make()
        self.last_agent: str | None = None
        self.pending: dict[str, dict] = {}
        self.locks = {k: threading.Lock() for k in agents.CREW}

    def _room_key(self, key: str) -> str:
        # Each brain keeps its own history format, so switching brains starts fresh rooms.
        return f"{key}@{self.ai.name}"

    # ---------- public API used by the web server ----------

    def handle(self, text: str, agent_key: str | None = None) -> dict:
        key = agent_key if agent_key in agents.CREW else router.pick(self.ai, text, self.last_agent)
        self.last_agent = key
        with self.locks[key]:
            blocked = health.gate(key)
            if blocked:
                return {"agent": "jyothi", "text": blocked, "routed_to": key}
            if any(p["agent"] == key for p in self.pending.values()):
                return {"agent": key, "text": "I'm still waiting for your answer on the action above. "
                                              "Approve or deny it first.", "pending": self._pending_for(key)}
            room = memory.load_room(self._room_key(key))
            dangling = bool(room) and self.ai.pending_calls(room[-1])
            if dangling or len(room) > config.MAX_ROOM_MESSAGES:
                room = []  # fresh room; shared memory carries what matters
            room.append(self.ai.user_message([_context_block(), text]))
            return self._run(key, room)

    def decide(self, approval_id: str, decisions: dict[str, bool]) -> dict:
        """Continue after you approve or deny Lochu's actions."""
        pend = self.pending.pop(approval_id, None)
        if not pend:
            return {"agent": "jyothi", "text": "That approval has already been handled or expired."}
        key = pend["agent"]
        with self.locks[key]:
            room, results = pend["room"], pend["results"]
            for call in pend["calls"]:
                if decisions.get(call["id"], False):
                    output = tools.execute(call["name"], call["input"], key)
                    results.append({"id": call["id"], "name": call["name"], "output": output})
                else:
                    results.append({"id": call["id"], "name": call["name"], "is_error": True,
                                    "output": f"{config.OWNER_NAME} denied this action. Don't retry it; ask what they'd prefer."})
            room.append(self.ai.tool_results(results))
            return self._run(key, room)

    def reset(self, key: str) -> None:
        memory.clear_room(self._room_key(key))
        for pid in [p for p, v in self.pending.items() if v["agent"] == key]:
            self.pending.pop(pid)

    # ---------- the agent loop ----------

    def _run(self, key: str, room: list[dict]) -> dict:
        agent = agents.CREW[key]
        spoken: list[str] = []
        actions: list[dict] = []
        for _ in range(12):  # hard stop so a confused agent can't loop forever
            try:
                turn = self.ai.call(agents.system_prompt(agent), agent.tool_defs, room, agent.effort, agent.web_search)
            except providers.ProviderError as e:
                return {"agent": "jyothi", "text": f"Jyothi here. {e}"}
            health.book(key, turn.input_tokens, turn.output_tokens)

            if turn.stop == "refusal":
                memory.clear_room(self._room_key(key))  # start clean so the declined turn isn't replayed
                return {"agent": key, "text": "I can't help with that one. Let's try it another way.", "actions": actions}

            room.append(turn.content)
            if turn.text:
                spoken.append(turn.text)
            if turn.searched:
                actions.append({"tool": "web_search", "summary": "searched the web", "done": True})
            if turn.stop == "pause":
                continue  # web search paused mid-turn; send it back to carry on
            if turn.stop != "tool":
                break

            results, waiting = [], []
            for call in turn.calls:
                name, args = call["name"], call["input"]
                if name in tools.NEEDS_APPROVAL:
                    reason = tools.blocked_reason(name, args)
                    if reason:
                        results.append({"id": call["id"], "name": name, "is_error": True, "output": reason})
                        actions.append({"tool": name, "summary": reason, "done": False})
                    else:
                        waiting.append(call)
                    continue
                results.append({"id": call["id"], "name": name, "output": tools.execute(name, args, key)})
                actions.append({"tool": name, "summary": name.replace("_", " "), "done": True})

            if waiting:
                approval_id = uuid.uuid4().hex[:12]
                self.pending[approval_id] = {"agent": key, "room": room, "calls": waiting, "results": results}
                memory.save_room(self._room_key(key), room)
                return {"agent": key, "text": "\n\n".join(spoken), "actions": actions,
                        "pending": self._pending_for(key)}
            room.append(self.ai.tool_results(results))
        else:
            spoken.append("I've been going in circles, so I stopped here. Tell me how you'd like to continue.")

        memory.save_room(self._room_key(key), room)
        return {"agent": key, "text": "\n\n".join(spoken), "actions": actions}

    def _pending_for(self, key: str) -> dict | None:
        for pid, p in self.pending.items():
            if p["agent"] == key:
                return {"id": pid, "agent": key, "actions": [
                    {"id": c["id"], "tool": c["name"], "description": tools.describe_action(c["name"], c["input"]),
                     "why": c["input"].get("why", "")} for c in p["calls"]]}
        return None

    def all_pending(self) -> list[dict]:
        return [self._pending_for(p["agent"]) for p in self.pending.values()]
