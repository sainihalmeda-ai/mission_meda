"""The Mindspace: takes a message, sends it through Jyothi's gate to the right
agent (or the whole crew for a huddle), runs tools, lets agents consult each
other, and pauses for your approval when Lochu wants to touch the computer.

Every reply comes back as a list of messages, because one question can get
answers from several crew members.
"""

import re
import threading
import uuid
from datetime import datetime

from . import agents, config, health, memory, providers, router, tools

HUDDLE_WORDS = re.compile(
    r"\b(everyone|everybody|all of you|crew|team|guys|huddle)\b|అందరూ|అందరు|అందరికీ|మీరందరూ|సబ్|सब|सभी|सारे",
    re.IGNORECASE)


def _context_block() -> str:
    facts = memory.recall("", limit=15)
    lines = [f"- #{f['id']} [{f['topic']}] {f['text']}" for f in facts]
    now = datetime.now().strftime("%A %d %B %Y, %I:%M %p")
    return (f"[Mindspace context, not from {config.OWNER_NAME}]\nNow: {now}\n"
            "Latest shared memory:\n" + ("\n".join(lines) if lines else "- (nothing yet)"))


def _reply(messages: list[dict], pending=None) -> dict:
    """Bundle messages for the app. 'agent' and 'text' mirror the last message for simple callers."""
    last = messages[-1] if messages else {"agent": "jyothi", "text": ""}
    out = {"messages": messages, "agent": last["agent"], "text": last["text"], "actions": last.get("actions", [])}
    if pending:
        out["pending"] = pending
    return out


class Crew:
    def __init__(self, provider=None):
        self.ai = provider or providers.make()
        self.last_agent: str | None = None
        self.pending: dict[str, dict] = {}
        self.locks = {k: threading.RLock() for k in agents.CREW}

    def _room_key(self, key: str) -> str:
        # Each brain keeps its own history format, so switching brains starts fresh rooms.
        return f"{key}@{self.ai.name}"

    # ---------- public API used by the web server ----------

    def handle(self, text: str, agent_key: str | None = None) -> dict:
        if agent_key not in agents.CREW and not router.by_name(text) and HUDDLE_WORDS.search(text):
            return self.huddle(text)
        key = agent_key if agent_key in agents.CREW else router.pick(self.ai, text, self.last_agent)
        self.last_agent = key
        msgs, pending = self._turn(key, [_context_block(), text])
        return _reply(msgs, pending)

    def huddle(self, text: str) -> dict:
        """The whole crew talks it over: two or three agents answer in turn, each seeing the others."""
        members = router.pick_group(self.ai, text)
        said: list[dict] = []
        for key in members:
            notes = "\n".join(f"{agents.CREW[m['agent']].name}: {m['text']}" for m in said
                              if m["agent"] in agents.CREW and m["text"])
            prompt = (f"[Huddle] {config.OWNER_NAME} asked the whole crew this. Crewmates answering with you: "
                      f"{', '.join(agents.CREW[k].name for k in members)}.\n"
                      + (f"Said so far:\n{notes}\n" if notes else "You go first.\n")
                      + "Add your own angle in 2 to 4 sentences. Agree, build on, or kindly push back.")
            msgs, pending = self._turn(key, [_context_block(), prompt, text])
            said += msgs
            if pending:
                return _reply(said, pending)
        self.last_agent = members[0]
        return _reply(said)

    def decide(self, approval_id: str, decisions: dict[str, bool]) -> dict:
        """Continue after you approve or deny Lochu's actions."""
        pend = self.pending.pop(approval_id, None)
        if not pend:
            return _reply([{"agent": "jyothi", "text": "That approval has already been handled or expired."}])
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
            msgs, pending = self._run(key, room)
            return _reply(msgs, pending)

    def reset(self, key: str) -> None:
        memory.clear_room(self._room_key(key))
        for pid in [p for p, v in self.pending.items() if v["agent"] == key]:
            self.pending.pop(pid)

    # ---------- one agent's turn ----------

    def _turn(self, key: str, texts: list[str]) -> tuple[list[dict], dict | None]:
        with self.locks[key]:
            blocked = health.gate(key)
            if blocked:
                return [{"agent": "jyothi", "text": blocked, "routed_to": key}], None
            if any(p["agent"] == key for p in self.pending.values()):
                return ([{"agent": key, "text": "I'm still waiting for your answer on the action above. "
                                                "Approve or deny it first."}], self._pending_for(key))
            room = memory.load_room(self._room_key(key))
            dangling = bool(room) and self.ai.pending_calls(room[-1])
            if dangling or len(room) > config.MAX_ROOM_MESSAGES:
                room = []  # fresh room; shared memory carries what matters
            room.append(self.ai.user_message(texts))
            return self._run(key, room)

    def _run(self, key: str, room: list[dict], consult_depth: int = 0) -> tuple[list[dict], dict | None]:
        """Agent loop. Returns the messages to show (crewmate answers first, then this agent) and any pending approval."""
        agent = agents.CREW[key]
        tool_defs = agent.tool_defs if consult_depth == 0 else [
            t for t in agent.tool_defs if t["name"] not in tools.NEEDS_APPROVAL and t["name"] != "ask_crewmate"]
        shown: list[dict] = []
        spoken: list[str] = []
        actions: list[dict] = []

        def finish(pending=None):
            if consult_depth == 0:
                memory.save_room(self._room_key(key), room)
            text = "\n\n".join(spoken)
            if text or not shown:
                shown.append({"agent": key, "text": text, "actions": actions})
            return shown, pending

        for _ in range(12):  # hard stop so a confused agent can't loop forever
            try:
                turn = self.ai.call(agents.system_prompt(agent), tool_defs, room, agent.effort, agent.web_search)
            except providers.ProviderError as e:
                shown.append({"agent": "jyothi", "text": f"Jyothi here. {e}"})
                return shown, None
            health.book(key, turn.input_tokens, turn.output_tokens)

            if turn.stop == "refusal":
                if consult_depth == 0:
                    memory.clear_room(self._room_key(key))  # start clean so the declined turn isn't replayed
                shown.append({"agent": key, "text": "I can't help with that one. Let's try it another way.", "actions": actions})
                return shown, None

            room.append(turn.content)
            if turn.text:
                spoken.append(turn.text)
            if turn.searched:
                actions.append({"tool": "web_search", "summary": "searched the web", "done": True})
            if turn.stop == "pause":
                continue  # web search paused mid-turn; send it back to carry on
            if turn.stop != "tool":
                return finish()

            results, waiting = [], []
            for call in turn.calls:
                name, args = call["name"], call["input"]
                if name == "ask_crewmate":
                    answer = self._consult(key, args.get("agent", ""), args.get("question", ""))
                    if answer["agent"] != "jyothi" or answer["text"]:
                        shown.append(answer)
                    results.append({"id": call["id"], "name": name, "output": answer["text"] or "(no answer)"})
                    actions.append({"tool": name, "summary": f"asked {agents.CREW.get(args.get('agent'), agent).name}", "done": True})
                    continue
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
                return finish(self._pending_for(key))
            room.append(self.ai.tool_results(results))

        spoken.append("I've been going in circles, so I stopped here. Tell me how you'd like to continue.")
        return finish()

    def _consult(self, asker: str, target: str, question: str) -> dict:
        """One crew member asks another. The answer is a one-off that both the asker and the user see."""
        if target not in agents.CREW or target == asker:
            return {"agent": "jyothi", "text": f"There's no crewmate called '{target}' to ask."}
        blocked = health.gate(target)
        if blocked:
            return {"agent": "jyothi", "text": blocked}
        a = agents.CREW[asker]
        room = [self.ai.user_message([
            _context_block(),
            f"[Crew talk] {a.name} is asking you this while helping {config.OWNER_NAME}. Answer {a.name} directly "
            f"in 2 to 4 sentences. {config.OWNER_NAME} will hear your answer too.",
            question,
        ])]
        msgs, _ = self._run(target, room, consult_depth=1)
        answer = msgs[-1]
        answer["to"] = asker
        return answer

    def _pending_for(self, key: str) -> dict | None:
        for pid, p in self.pending.items():
            if p["agent"] == key:
                return {"id": pid, "agent": key, "actions": [
                    {"id": c["id"], "tool": c["name"], "description": tools.describe_action(c["name"], c["input"]),
                     "why": c["input"].get("why", "")} for c in p["calls"]]}
        return None

    def all_pending(self) -> list[dict]:
        return [self._pending_for(p["agent"]) for p in self.pending.values()]
