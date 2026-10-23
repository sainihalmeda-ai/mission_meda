"""The AI "brains" Mission MEDA can run on.

  gemini  free tier from Google AI Studio (default)
  claude  paid, smartest (Anthropic API)

Both speak the same small interface, so the rest of the app doesn't care which
one is plugged in. Pick one with MEDA_PROVIDER in .env.
"""

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import config


@dataclass
class Turn:
    """One model response, translated into plain Python."""
    content: dict                      # stored in the room exactly as the API returned it
    text: str = ""
    calls: list = field(default_factory=list)  # [{"id", "name", "input"}]
    stop: str = "end"                  # end | tool | pause | refusal
    input_tokens: int = 0
    output_tokens: int = 0
    searched: bool = False


class ProviderError(Exception):
    """A friendly message for the user, spoken by Jyothi."""


# ---------------------------------------------------------------- Claude

class ClaudeProvider:
    name = "claude"
    FALLBACK_BETA = "server-side-fallback-2026-07-01"
    WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}

    def __init__(self, client=None):
        import anthropic
        self.anthropic = anthropic
        self._client = client
        self.model = config.MODEL or "claude-opus-5-5"

    @property
    def client(self):
        if self._client is None:
            if not config.ANTHROPIC_API_KEY:
                raise ProviderError("There's no Claude API key yet. Add ANTHROPIC_API_KEY to the .env file.")
            self._client = self.anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        return self._client

    def user_message(self, texts: list[str]) -> dict:
        return {"role": "user", "content": [{"type": "text", "text": t} for t in texts]}

    def tool_results(self, results: list[dict]) -> dict:
        blocks = []
        for r in results:
            b = {"type": "tool_result", "tool_use_id": r["id"], "content": r["output"]}
            if r.get("is_error"):
                b["is_error"] = True
            blocks.append(b)
        return {"role": "user", "content": blocks}

    def pending_calls(self, message: dict) -> bool:
        return message["role"] == "assistant" and any(b.get("type") == "tool_use" for b in message["content"])

    def call(self, system: str, tool_defs: list, room: list, effort: str, web_search: bool) -> Turn:
        a = self.anthropic
        tools = tool_defs + ([self.WEB_SEARCH] if web_search else [])
        client = self.client  # raises ProviderError if there's no key
        stripped = False
        try:
            resp = client.beta.messages.create(
                model=self.model, max_tokens=16000, system=system, tools=tools, messages=room,
                thinking={"type": "adaptive"}, output_config={"effort": effort},
                cache_control={"type": "ephemeral"}, betas=[self.FALLBACK_BETA], fallbacks="default",
            )
        except a.AuthenticationError:
            raise ProviderError("The Claude API key is missing or wrong. Check ANTHROPIC_API_KEY in .env.")
        except a.RateLimitError:
            raise ProviderError("Claude is rate limiting us. Try again in a minute.")
        except a.APIConnectionError:
            raise ProviderError("I can't reach the internet right now. Check your connection.")
        except a.APIStatusError as e:
            raise ProviderError(f"Claude returned an error ({e.status_code}). Try again shortly.")

        u = resp.usage
        input_equiv = (u.input_tokens + int(1.25 * (u.cache_creation_input_tokens or 0))
                       + int(0.1 * (u.cache_read_input_tokens or 0)))
        content = [b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in resp.content]
        stop = {"tool_use": "tool", "pause_turn": "pause", "refusal": "refusal"}.get(resp.stop_reason, "end")
        return Turn(
            content={"role": "assistant", "content": content},
            text="\n".join(b["text"] for b in content if b.get("type") == "text").strip(),
            calls=[{"id": b["id"], "name": b["name"], "input": b.get("input") or {}}
                   for b in content if b.get("type") == "tool_use"],
            stop=stop, input_tokens=input_equiv, output_tokens=u.output_tokens,
            searched=any(b.get("type") == "server_tool_use" for b in content),
        )

    def classify(self, system: str, prompt: str, schema: dict) -> tuple[dict, int, int]:
        resp = self.client.messages.create(
            model=self.model, max_tokens=2000, system=system,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
        if resp.stop_reason == "refusal":
            raise ValueError("refused")
        raw = next(b.text for b in resp.content if b.type == "text")
        return json.loads(raw), resp.usage.input_tokens, resp.usage.output_tokens


# ---------------------------------------------------------------- Gemini

def key_problem(err) -> bool:
    """Google reports a bad API key as a 400, so look at the message too."""
    return "api key" in (err.message or "").lower() or "API_KEY" in str(getattr(err, "details", "") or err)


def _unsigned(message: dict) -> dict:
    """A copy of a Gemini message without thought signatures."""
    return {**message, "parts": [{k: v for k, v in p.items() if k != "thought_signature"}
                                 for p in message.get("parts", [])]}


class GeminiProvider:
    name = "gemini"

    def __init__(self, client=None):
        from google import genai
        from google.genai import errors, types
        self.genai, self.types, self.errors = genai, types, errors
        self._client = client
        self.model = config.MODEL or "gemini-3.5-flash-lite"
        # Each free model has its own daily quota, so the crew rotates through several.
        self.pool: list[str] = [self.model]
        self.model_in_use = self.model
        self.discovered = False
        self.resting: dict[str, float] = {}  # model -> time it can be used again
        self.search_ok = True    # switched off if the model refuses search mixed with our tools
        self.thinking_ok = True  # switched off if the model refuses our thinking setting

    # ---------- free-tier model rotation ----------

    SKIP = ("tts", "image", "live", "audio", "embed", "transcribe", "translate", "native", "robotics", "computer")

    def _discover(self) -> None:
        """Find every free-looking Flash model this key can use. Listing models costs no quota."""
        self.discovered = True
        try:
            names = []
            for m in self.client.models.list():
                name = (m.name or "").removeprefix("models/")
                actions = m.supported_actions or []
                if ("gemini" in name and "flash" in name and "generateContent" in actions
                        and not any(x in name for x in self.SKIP)):
                    names.append(name)
        except Exception as e:
            print(f"[gemini] couldn't list models: {type(e).__name__}: {e}")
            return

        def rank(n: str):
            version = [int(x) for x in re.findall(r"\d+", n)[:2]] or [0]
            return ("lite" not in n, "preview" in n or "exp" in n, [-v for v in version])

        extra = sorted((n for n in names if n not in self.pool), key=rank)[:6]
        self.pool += extra
        if extra:
            print(f"[gemini] free models in rotation: {', '.join(self.pool)}")

    @staticmethod
    def _rest_seconds(err) -> float:
        """How long a model must rest after a 429: a short wait for per-minute limits, until reset for daily ones."""
        raw = str(err)
        delay = re.search(r"retryDelay['\"]?:\s*['\"]?(\d+(?:\.\d+)?)s", raw)
        if "PerDay" not in raw and (delay or "PerMinute" in raw):
            return float(delay.group(1)) + 1 if delay else 61.0
        try:  # daily quotas reset at midnight Pacific time
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo("America/Los_Angeles"))
            reset = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
            return (reset - now).total_seconds()
        except Exception:
            return 6 * 3600.0

    def _with_rotation(self, fn):
        """Run fn(model) on the first model that isn't resting, moving on when one hits its free limit."""
        waited = False
        for _ in range(12):  # a hard stop; the pool holds at most 7 models
            ready = [m for m in self.pool if self.resting.get(m, 0) <= time.time()]
            if not ready and not self.discovered:
                self._discover()
                continue
            if not ready:
                soonest = min(self.resting.values(), default=0) - time.time()
                if waited or not 0 < soonest <= 65:
                    break
                time.sleep(soonest)  # only a per-minute limit; worth one short wait
                waited = True
                continue
            model = ready[0]
            try:
                result = fn(model)
                self.model_in_use = model
                return result
            except self.errors.ClientError as e:
                if e.code != 429:
                    raise
                wait = self._rest_seconds(e)
                self.resting[model] = time.time() + wait
                print(f"[gemini] {model} hit its free limit; resting {round(wait / 60)} min")
        until = datetime.fromtimestamp(min(self.resting.values(), default=time.time() + 3600))
        raise ProviderError("All of Gemini's free models are resting after hitting today's free limits. "
                            f"They come back around {until.strftime('%I:%M %p')}. Until then, the crew is resting.")

    def status(self) -> dict:
        now = time.time()
        return {"in_rotation": self.pool,
                "resting": {m: round((u - now) / 60) for m, u in self.resting.items() if u > now}}

    @property
    def client(self):
        if self._client is None:
            if not config.GEMINI_API_KEY:
                raise ProviderError("There's no Gemini key yet. Get a free one at aistudio.google.com/apikey "
                                    "and put it in the .env file as GEMINI_API_KEY.")
            self._client = self.genai.Client(api_key=config.GEMINI_API_KEY)
        return self._client

    def user_message(self, texts: list[str]) -> dict:
        return {"role": "user", "parts": [{"text": t} for t in texts]}

    def tool_results(self, results: list[dict]) -> dict:
        parts = []
        for r in results:
            key = "error" if r.get("is_error") else "result"
            parts.append({"function_response": {"id": r["id"], "name": r["name"], "response": {key: r["output"]}}})
        return {"role": "user", "parts": parts}

    def pending_calls(self, message: dict) -> bool:
        return message["role"] == "model" and any("function_call" in p for p in message.get("parts", []))

    def _tools(self, tool_defs: list, web_search: bool) -> list:
        t = self.types
        decls = [t.FunctionDeclaration(name=d["name"], description=d["description"],
                                       parameters_json_schema=d["input_schema"] if d["input_schema"]["properties"] else None)
                 for d in tool_defs]
        tools = [t.Tool(function_declarations=decls)] if decls else []
        if web_search and self.search_ok:
            tools.append(t.Tool(google_search=t.GoogleSearch()))
        return tools

    def call(self, system: str, tool_defs: list, room: list, effort: str, web_search: bool) -> Turn:
        t = self.types
        contents = [t.Content.model_validate(m) for m in room]
        level = t.ThinkingLevel[{"medium": "MEDIUM", "high": "HIGH"}.get(effort, "LOW")]

        client = self.client  # raises ProviderError if there's no key

        def go(search: bool, thinking: bool = True):
            cfg = t.GenerateContentConfig(
                system_instruction=system, tools=self._tools(tool_defs, search),
                automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
                thinking_config=t.ThinkingConfig(thinking_level=level) if thinking and self.thinking_ok else None,
            )
            return self._with_rotation(
                lambda model: client.models.generate_content(model=model, contents=contents, config=cfg))

        try:
            resp = None
            for attempt in range(4):
                try:
                    resp = go(web_search and self.search_ok, thinking=self.thinking_ok)
                    break
                except self.errors.ClientError as e:
                    if e.code != 400 or key_problem(e) or attempt == 3:
                        raise
                    print(f"[gemini] 400 from {self.model_in_use}: {e.message}. Retrying with fewer features.")
                    if "signature" in str(e.message).lower() and not stripped:
                        # History came from another free model after a switch; its thought signatures don't carry over.
                        contents[:] = [t.Content.model_validate(_unsigned(m)) for m in room]
                        stripped = True
                    elif web_search and self.search_ok:
                        self.search_ok = False  # some models reject search; drop the extras one at a time
                    elif self.thinking_ok:
                        self.thinking_ok = False
                    else:
                        raise
        except self.errors.ClientError as e:
            print(f"[gemini] error {e.code}: {e.message}")
            if e.code in (401, 403) or key_problem(e):
                raise ProviderError("Google says the Gemini key isn't valid. Close this window, delete the .env file "
                                    "in the Mission MEDA folder, and start again to paste a fresh key from "
                                    "aistudio.google.com/apikey.")
            if e.code == 404:
                raise ProviderError(f"Gemini doesn't know the model '{self.model}'. Set MEDA_MODEL in .env to one "
                                    "listed in Google AI Studio.")
            raise ProviderError(f"Gemini returned an error ({e.code}): {e.message}")
        except ProviderError:
            raise
        except self.errors.ServerError as e:
            print(f"[gemini] server error {e.code}: {e.message}")
            raise ProviderError("Gemini is having trouble right now. Try again in a minute.")
        except Exception as e:  # network trouble and anything unexpected
            print(f"[gemini] {type(e).__name__}: {e}")
            raise ProviderError(f"I couldn't reach Gemini ({type(e).__name__}). Check your internet connection.")

        cand = (resp.candidates or [None])[0]
        usage = resp.usage_metadata
        tin = getattr(usage, "prompt_token_count", 0) or 0
        tout = (getattr(usage, "candidates_token_count", 0) or 0) + (getattr(usage, "thoughts_token_count", 0) or 0)
        if cand is None or cand.content is None:
            reason = str(getattr(cand, "finish_reason", "") or getattr(resp.prompt_feedback, "block_reason", ""))
            return Turn(content={"role": "model", "parts": [{"text": "…"}]}, stop="refusal" if reason else "end",
                        input_tokens=tin, output_tokens=tout)

        content = cand.content.model_dump(mode="json", exclude_none=True)
        content["role"] = "model"
        calls = []
        for i, p in enumerate(content.get("parts", [])):
            fc = p.get("function_call")
            if fc:
                fc.setdefault("id", f"call_{len(room)}_{i}")  # older models omit ids; we need one to match results
                calls.append({"id": fc["id"], "name": fc["name"], "input": fc.get("args") or {}})
        text = "\n".join(p["text"] for p in content.get("parts", []) if p.get("text") and not p.get("thought")).strip()
        searched = bool(getattr(cand, "grounding_metadata", None))
        finish = str(getattr(cand, "finish_reason", "") or "")
        stop = "tool" if calls else ("refusal" if "SAFETY" in finish or "PROHIBITED" in finish else "end")
        return Turn(content=content, text=text, calls=calls, stop=stop,
                    input_tokens=tin, output_tokens=tout, searched=searched)

    def classify(self, system: str, prompt: str, schema: dict) -> tuple[dict, int, int]:
        t = self.types
        cfg = t.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                      response_json_schema=schema,
                                      thinking_config=t.ThinkingConfig(thinking_level=t.ThinkingLevel.LOW))
        client = self.client
        resp = self._with_rotation(lambda model: client.models.generate_content(model=model, contents=prompt, config=cfg))
        u = resp.usage_metadata
        return json.loads(resp.text), (u.prompt_token_count or 0), (u.candidates_token_count or 0)


def make(client=None):
    if config.PROVIDER == "claude":
        return ClaudeProvider(client)
    return GeminiProvider(client)
