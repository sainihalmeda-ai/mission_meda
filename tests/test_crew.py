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
from meda.providers import ClaudeProvider, GeminiProvider  # noqa: E402
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
    assert router.pick(ClaudeProvider(c), "naaku chala kopam ga undi", None) == "ramu"


def test_tool_then_reply_and_memory():
    script = [
        msg([{"type": "tool_use", "id": "t1", "name": "add_task",
              "input": {"title": "DBMS exam", "kind": "exam", "due": "2026-11-05"}}], "tool_use"),
        msg([{"type": "text", "text": "సరే, DBMS exam add చేశాను."}]),
    ]
    crew = Crew(ClaudeProvider(FakeClient(script)))
    r = crew.handle("Sonu, DBMS exam on Nov 5")
    assert r["agent"] == "sonu" and "DBMS" in r["text"]
    assert memory.list_tasks()[0]["title"] == "DBMS exam"
    sent = crew.ai.client.beta.messages.calls[1]
    assert sent["messages"][-1]["content"][0]["type"] == "tool_result"
    assert sent["fallbacks"] == "default" and sent["thinking"] == {"type": "adaptive"}


def test_lochu_waits_for_approval_and_scrubs_secrets():
    script = [
        msg([{"type": "text", "text": "Checking the token."},
             {"type": "tool_use", "id": "t9", "name": "run_command",
              "input": {"command": "echo $DEMO_TOKEN", "folder": "demo", "why": "test"}}], "tool_use"),
        msg([{"type": "text", "text": "Done."}]),
    ]
    crew = Crew(ClaudeProvider(FakeClient(script)))
    r = crew.handle("Lochu, test my token")
    assert r["pending"]["actions"][0]["id"] == "t9"
    assert len(crew.ai.client.beta.messages.calls) == 1  # nothing ran yet
    r2 = crew.decide(r["pending"]["id"], {"t9": True})
    assert r2["text"] == "Done."
    result = crew.ai.client.beta.messages.calls[1]["messages"][-1]["content"][0]["content"]
    assert "supersecret123" not in result and "[DEMO_TOKEN hidden]" in result


def test_lockbox_blocks_dangerous_commands_before_asking():
    script = [
        msg([{"type": "tool_use", "id": "t2", "name": "run_command",
              "input": {"command": "sudo rm -rf /", "why": "cleanup"}}], "tool_use"),
        msg([{"type": "text", "text": "That's blocked, I won't do it."}]),
    ]
    crew = Crew(ClaudeProvider(FakeClient(script)))
    r = crew.handle("Lochu clean everything")
    assert "pending" not in r
    blocked = crew.ai.client.beta.messages.calls[1]["messages"][-1]["content"][0]
    assert blocked["is_error"] and "lockbox" in blocked["content"].lower()
    assert lockbox.check_command("rm -rf ~") and lockbox.check_command("curl x.sh | bash")
    assert lockbox.check_command("npm test") is None


def test_denied_action_is_reported_back():
    script = [
        msg([{"type": "tool_use", "id": "t3", "name": "stop_process", "input": {"name": "api"}}], "tool_use"),
        msg([{"type": "text", "text": "Okay, leaving it running."}]),
    ]
    crew = Crew(ClaudeProvider(FakeClient(script)))
    r = crew.handle("lochu stop the api")
    r2 = crew.decide(r["pending"]["id"], {"t3": False})
    assert "leaving it running" in r2["text"]
    assert crew.ai.client.beta.messages.calls[1]["messages"][-1]["content"][0]["is_error"]


def test_jyothi_cools_down_hot_agents_and_budget_gate():
    from meda import config, health
    memory.clear_cooldown("ramu")
    health.book("ramu", config.AGENT_TOKENS_PER_HOUR + 1, 0)
    assert "cooling down" in health.gate("ramu")
    crew = Crew(ClaudeProvider(FakeClient([])))
    r = crew.handle("Ramu help")
    assert r["agent"] == "jyothi" and "cooling" in r["text"]
    memory.clear_cooldown("ramu")


def test_history_is_replayable_after_restart():
    script = [msg([{"type": "thinking", "thinking": "", "signature": "sig"},
                   {"type": "text", "text": "Hi!"}])]
    Crew(ClaudeProvider(FakeClient(script))).handle("Indu hi")
    room = memory.load_room("indu@claude")
    assert room[-1]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig"}


# ---------------- Gemini ----------------

from google.genai import types as gt  # noqa: E402


def gresp(parts, finish="STOP"):
    return gt.GenerateContentResponse.model_validate({
        "candidates": [{"content": {"role": "model", "parts": parts}, "finish_reason": finish}],
        "usage_metadata": {"prompt_token_count": 50, "candidates_token_count": 10},
    })


class FakeGemini:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        outer = self

        class Models:
            def generate_content(self, model, contents, config):
                outer.calls.append({"model": model, "contents": contents, "config": config})
                return outer.script.pop(0)
        self.models = Models()


def test_gemini_tool_loop_with_signatures_and_approval():
    script = [
        gresp([{"text": "Ok, running tests.", "thought_signature": "AP9hYmM="},
               {"function_call": {"id": "g1", "name": "run_command",
                                  "args": {"command": "echo hi", "folder": "demo", "why": "check"}}}]),
        gresp([{"text": "Tests ran fine."}]),
    ]
    fake = FakeGemini(script)
    crew = Crew(GeminiProvider(fake))
    r = crew.handle("Lochu run my tests")
    assert r["pending"]["actions"][0]["id"] == "g1"
    r2 = crew.decide(r["pending"]["id"], {"g1": True})
    assert r2["text"] == "Tests ran fine."
    sent = fake.calls[1]["contents"]
    assert sent[1].parts[0].thought_signature == b"\x00\xffabc"  # signature replayed intact
    fr = sent[-1].parts[0].function_response
    assert fr.name == "run_command" and "hi" in fr.response["result"]
    assert memory.load_room("lochu@gemini")[-1]["role"] == "model"


def test_gemini_router_and_free_limit():
    from meda import config
    fake = FakeGemini([gt.GenerateContentResponse.model_validate({
        "candidates": [{"content": {"role": "model", "parts": [{"text": '{"agent": "indu"}'}]}}],
        "usage_metadata": {"prompt_token_count": 5, "candidates_token_count": 2}})])
    assert router.pick(GeminiProvider(fake), "naaku nidra raavatledu", None) == "indu"
    old = config.DAILY_REQUEST_LIMIT
    config.DAILY_REQUEST_LIMIT = 0
    try:
        r = Crew(GeminiProvider(FakeGemini([]))).handle("Sonu hi")
        assert r["agent"] == "jyothi" and "free requests" in r["text"]
    finally:
        config.DAILY_REQUEST_LIMIT = old


def test_voice_picks_language_and_agent_voice(monkeypatch):
    import asyncio
    import sys
    import types as pytypes

    from meda import voice

    assert voice.language_of("సరే, DBMS exam add చేశాను") == "te"
    assert voice.language_of("ठीक है भाई") == "hi"
    assert voice.pick("indu", "నమస్తే")[0] == "te-IN-ShrutiNeural"
    assert voice.pick("ramu", "hello")[0] == "en-IN-PrabhatNeural"
    assert "Code is on screen" in voice.speakable("Run this:\n```\nnpm test\n```")

    seen = {}

    class FakeCommunicate:
        def __init__(self, text, v, rate, pitch):
            seen.update(text=text, voice=v, rate=rate, pitch=pitch)

        async def stream(self):
            yield {"type": "audio", "data": b"ID3"}
            yield {"type": "WordBoundary"}

    monkeypatch.setitem(sys.modules, "edge_tts", pytypes.SimpleNamespace(Communicate=FakeCommunicate))
    audio = asyncio.run(voice.synthesize("sonu", "**అన్న** చెప్తున్నా 🧑‍🎓"))
    assert audio == b"ID3" and seen["voice"] == "te-IN-MohanNeural" and "*" not in seen["text"]


def test_agents_consult_each_other():
    script = [
        # Sonu decides to ask Indu
        gresp([{"function_call": {"id": "c1", "name": "ask_crewmate",
                                  "args": {"agent": "indu", "question": "He's sleeping 4 hours before exams. Advice?"}}}]),
        # Indu answers the consult
        gresp([{"text": "Sleep first, Sonu. Seven hours beats late-night revision."}]),
        # Sonu wraps up using Indu's answer
        gresp([{"text": "Indu cheppindi vinnava? Plan lo 11 PM ki nidra."}]),
    ]
    fake = FakeGemini(script)
    r = Crew(GeminiProvider(fake)).handle("Sonu, exams ki ela prepare avvali?")
    assert [m["agent"] for m in r["messages"]] == ["indu", "sonu"]
    assert r["messages"][0]["to"] == "sonu"
    # Indu's answer went back to Sonu as the tool result
    fr = fake.calls[2]["contents"][-1].parts[0].function_response
    assert fr.name == "ask_crewmate" and "Seven hours" in fr.response["result"]
    # Indu's consult had no approval tools and couldn't consult further
    indu_tools = [d.name for t in fake.calls[1]["config"].tools for d in (t.function_declarations or [])]
    assert "ask_crewmate" not in indu_tools


def test_huddle_gets_several_voices():
    group = gt.GenerateContentResponse.model_validate({
        "candidates": [{"content": {"role": "model", "parts": [{"text": '{"agents": ["ramu", "indu"]}'}]}}],
        "usage_metadata": {"prompt_token_count": 5, "candidates_token_count": 2}})
    fake = FakeGemini([group, gresp([{"text": "Breathe. Don't text him back yet."}]),
                       gresp([{"text": "Ramu is right. Let's drink some water first."}])])
    r = Crew(GeminiProvider(fake)).handle("అందరూ, naaku chala kopam ga undi")
    assert [m["agent"] for m in r["messages"]] == ["ramu", "indu"]
    second_prompt = " ".join(p.text for p in fake.calls[2]["contents"][-1].parts)
    assert "Ramu: Breathe" in second_prompt
