"""Offline tests: a fake Claude client stands in for the real API."""

import json
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ["MEDA_DATA_DIR"] = os.path.join(tmp, "data")
os.environ["MEDA_PROJECTS_DIR"] = os.path.join(tmp, "projects")
os.environ["MEDA_VAULT"] = os.path.join(tmp, "vault.env")
os.makedirs(os.environ["MEDA_PROJECTS_DIR"] + "/demo")
with open(os.environ["MEDA_VAULT"], "w") as f:
    f.write("DEMO_TOKEN=supersecret123\n")

from anthropic.types.beta import BetaMessage  # noqa: E402

from meda import lockbox, memory, router  # noqa: E402
from meda.brain import Crew  # noqa: E402


def msg(content, stop="end_turn"):
    return BetaMessage.model_validate({
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": content, "stop_reason": stop, "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 20},
    })


class FakeAPI:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw, default=str)))
        return self.script.pop(0)


class FakeClient:
    def __init__(self, beta_script, router_script=()):
        self.beta = type("B", (), {})()
        self.beta.messages = FakeAPI(beta_script)
        self.messages = FakeAPI(router_script)


def test_name_routing_in_three_languages():
    assert router.by_name("Sonu, ee roju plan enti?") == "sonu"
    assert router.by_name("ఇందు నాకు బాధగా ఉంది") == "indu"
    assert router.by_name("लोचू build fail ho gaya") == "lochu"
    assert router.by_name("hey jyoti how is everyone") == "jyothi"
    assert router.by_name("what's the plan today") is None


def test_router_falls_back_to_claude():
    c = FakeClient([], [msg([{"type": "text", "text": '{"agent": "ramu"}'}])])
    assert router.pick(c, "naaku chala kopam ga undi", None) == "ramu"


def test_tool_then_reply_and_memory():
    script = [
        msg([{"type": "tool_use", "id": "t1", "name": "add_task",
              "input": {"title": "DBMS exam", "kind": "exam", "due": "2026-11-05"}}], "tool_use"),
        msg([{"type": "text", "text": "సరే, DBMS exam add చేశాను."}]),
    ]
    crew = Crew(FakeClient(script))
    r = crew.handle("Sonu, DBMS exam on Nov 5")
    assert r["agent"] == "sonu" and "DBMS" in r["text"]
    assert memory.list_tasks()[0]["title"] == "DBMS exam"
    sent = crew.client.beta.messages.calls[1]
    assert sent["messages"][-1]["content"][0]["type"] == "tool_result"
    assert sent["fallbacks"] == "default" and sent["thinking"] == {"type": "adaptive"}


def test_lochu_waits_for_approval_and_scrubs_secrets():
    script = [
        msg([{"type": "text", "text": "Checking the token."},
             {"type": "tool_use", "id": "t9", "name": "run_command",
              "input": {"command": "echo $DEMO_TOKEN", "folder": "demo", "why": "test"}}], "tool_use"),
        msg([{"type": "text", "text": "Done."}]),
    ]
    crew = Crew(FakeClient(script))
    r = crew.handle("Lochu, test my token")
    assert r["pending"]["actions"][0]["id"] == "t9"
    assert len(crew.client.beta.messages.calls) == 1  # nothing ran yet
    r2 = crew.decide(r["pending"]["id"], {"t9": True})
    assert r2["text"] == "Done."
    result = crew.client.beta.messages.calls[1]["messages"][-1]["content"][0]["content"]
    assert "supersecret123" not in result and "[DEMO_TOKEN hidden]" in result


def test_lockbox_blocks_dangerous_commands_before_asking():
    script = [
        msg([{"type": "tool_use", "id": "t2", "name": "run_command",
              "input": {"command": "sudo rm -rf /", "why": "cleanup"}}], "tool_use"),
        msg([{"type": "text", "text": "That's blocked, I won't do it."}]),
    ]
    crew = Crew(FakeClient(script))
    r = crew.handle("Lochu clean everything")
    assert "pending" not in r
    blocked = crew.client.beta.messages.calls[1]["messages"][-1]["content"][0]
    assert blocked["is_error"] and "lockbox" in blocked["content"].lower()
    assert lockbox.check_command("rm -rf ~") and lockbox.check_command("curl x.sh | bash")
    assert lockbox.check_command("npm test") is None


def test_denied_action_is_reported_back():
    script = [
        msg([{"type": "tool_use", "id": "t3", "name": "stop_process", "input": {"name": "api"}}], "tool_use"),
        msg([{"type": "text", "text": "Okay, leaving it running."}]),
    ]
    crew = Crew(FakeClient(script))
    r = crew.handle("lochu stop the api")
    r2 = crew.decide(r["pending"]["id"], {"t3": False})
    assert "leaving it running" in r2["text"]
    assert crew.client.beta.messages.calls[1]["messages"][-1]["content"][0]["is_error"]


def test_jyothi_cools_down_hot_agents_and_budget_gate():
    from meda import config, health
    memory.clear_cooldown("ramu")
    health.book("ramu", config.AGENT_TOKENS_PER_HOUR + 1, 0)
    assert "cooling down" in health.gate("ramu")
    crew = Crew(FakeClient([]))
    r = crew.handle("Ramu help")
    assert r["agent"] == "jyothi" and "cooling" in r["text"]
    memory.clear_cooldown("ramu")


def test_history_is_replayable_after_restart():
    script = [msg([{"type": "thinking", "thinking": "", "signature": "sig"},
                   {"type": "text", "text": "Hi!"}])]
    Crew(FakeClient(script)).handle("Indu hi")
    room = memory.load_room("indu")
    assert room[-1]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig"}
