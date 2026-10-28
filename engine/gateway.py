"""One controlled AI gateway (doc Sections 9.1, 9.2, 9.8).

- provider adapters behind one interface: Gemini, any OpenAI-compatible API
  (Groq, OpenRouter) and a local Ollama model, tried in that order
- the Gemini primary keeps its model; free-tier fallback models are tried when
  it is rate-limited, busy, or has used its daily allowance, each with its own
  RPM window and cooldown
- an answer counts only if the provider returned usable text; rate limits,
  server errors and empty replies fall through to the next provider
- every attempt is written to the ai_calls ledger (ok or not), with the prompt
  version of the task
- no provider configured: callers get None, rule-based findings still arrive
  and AI checks are marked "pending" — never silently skipped

Keys come from the environment or the project-root .env; models can be changed
per provider without code changes (CANONRY_<PROVIDER>_MODEL).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

import httpx

from db import _now, connect

PROMPT_VERSION = "claims@4"
TIMEOUT = httpx.Timeout(90.0, connect=10.0)
AI_DEADLINE_SECONDS = 120.0
RETRYABLE = {408, 429, 500, 502, 503, 504}

# The free Gemini tiers are per-model, including their daily request allowance.
# Keep the primary first and fall through to these when it is busy, rate-limited
# or out of daily requests. 3.5 Flash-Lite has the largest free daily allowance;
# the others add fresh quotas when that runs out. "off" disables the fallbacks.
GEMINI_FALLBACK_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3-flash-preview",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
)
GEMINI_RPM = {
    "gemini-3.1-flash-lite": 15,
    "gemini-3.5-flash-lite": 15,
    "gemini-flash-lite-latest": 15,
    "gemini-3-flash-preview": 5,
    "gemini-3.8-flash": 5,
    "gemini-3.6-flash": 5,
}
COOLDOWN_SECONDS = 45.0


class ProviderError(Exception):
    """A provider did not produce a usable answer."""

    def __init__(self, message: str, retryable: bool = False, status: Optional[int] = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


# ---- configuration ------------------------------------------------------------

def _read_env_file() -> Dict[str, str]:
    """The project-root .env, or the file CANONRY_ENV_FILE names ("" = read none;
    the test suites run that way so they never spend a real key). Values are
    never printed or logged."""
    path = os.environ.get("CANONRY_ENV_FILE")
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", ".env")
    data: Dict[str, str] = {}
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    data[k.strip()] = v.strip()
    return data


_env: Optional[Dict[str, str]] = None
_transport: Optional[httpx.BaseTransport] = None


def configure(env: Optional[Dict[str, str]] = None, transport: Optional[httpx.BaseTransport] = None) -> None:
    """Replace the settings the gateway reads (tests; embedding). `env=None`
    goes back to .env + process environment; `transport` swaps the HTTP layer."""
    global _env, _transport
    _env = dict(env) if env is not None else None
    _transport = transport


def _setting(name: str) -> Optional[str]:
    global _env
    if _env is None:
        _env = {**_read_env_file(), **os.environ}
    value = _env.get(name)
    return value.strip() if value and value.strip() else None


def ai_deadline() -> float:
    """The time.monotonic() moment by which one check's AI phase must finish.

    Slow providers and retries must never hold a check open forever: the web
    proxy in front of the engine gives up after a few minutes, and a check that
    is still running then cannot show its findings. The rule-based checks are
    unaffected; only the optional AI calls are cut off.
    """
    raw = _setting("CANONRY_AI_DEADLINE_SECONDS")
    if raw:
        try:
            seconds = float(raw)
        except ValueError:
            raise RuntimeError("CANONRY_AI_DEADLINE_SECONDS must be a number of seconds.")
        if seconds < 10:
            raise RuntimeError("CANONRY_AI_DEADLINE_SECONDS must be at least 10 seconds.")
    else:
        seconds = AI_DEADLINE_SECONDS
    return time.monotonic() + seconds


# ---- providers ------------------------------------------------------------------

class Provider:
    """One AI service. Subclasses turn chat messages into a request and the
    response into text; everything else (fallback, retries, logging) is shared."""

    name = ""
    key_setting: Optional[str] = None   # None = no key needed (local)
    default_model = ""

    def available(self) -> bool:
        return bool(_setting(self.key_setting)) if self.key_setting else False

    def model(self) -> str:
        return _setting(f"CANONRY_{self.name.upper()}_MODEL") or self.default_model

    def models(self) -> List[str]:
        """Models this provider may try, primary first. Most have exactly one."""
        return [self.model()]

    def chat(self, client: httpx.Client, messages: List[Dict[str, str]],
             model: Optional[str] = None) -> Dict[str, str]:
        raise NotImplementedError

    @staticmethod
    def _check(r: httpx.Response) -> Dict[str, Any]:
        if r.status_code >= 400:
            raise ProviderError(f"HTTP {r.status_code}", retryable=r.status_code in RETRYABLE,
                                status=r.status_code)
        try:
            return r.json()
        except ValueError:
            raise ProviderError("response is not JSON")


class Gemini(Provider):
    name, key_setting, default_model = "gemini", "GEMINI_API_KEY", "gemini-3.1-flash-lite"
    fallback_models = GEMINI_FALLBACK_MODELS

    def models(self) -> List[str]:
        primary = self.model()
        raw = _setting("CANONRY_GEMINI_FALLBACK_MODELS")
        if raw and raw.lower() in ("off", "none", "-"):
            return [primary]
        fallbacks = [m.strip() for m in raw.split(",")] if raw else list(self.fallback_models)
        out: List[str] = []
        for candidate in [primary, *fallbacks]:
            if candidate and candidate not in out:
                out.append(candidate)
        return out

    @staticmethod
    def _answer_text(data: Dict[str, Any]) -> str:
        """The answer text, skipping any thinking parts that come before it."""
        for cand in data.get("candidates") or []:
            texts = [p.get("text") for p in ((cand.get("content") or {}).get("parts") or [])
                     if p.get("text") and not p.get("thought")]
            if texts:
                return "".join(texts)
        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise ProviderError(f"blocked by the provider ({block})")
        finish = next((c.get("finishReason") for c in data.get("candidates") or []), None)
        raise ProviderError(f"no answer in the response (finishReason={finish})")

    def chat(self, client, messages, model=None):
        model = model or self.model()
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": m["content"]}]}
                         for m in messages if m["role"] != "system"],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        data = self._check(client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": _setting(self.key_setting) or ""}, json=payload))
        return {"text": self._answer_text(data), "model": model}


class OpenAICompatible(Provider):
    """Any /v1/chat/completions API (Groq, OpenRouter, Ollama, ...)."""

    def __init__(self, name: str, url: str, key_setting: Optional[str], default_model: str,
                 url_setting: Optional[str] = None):
        self.name, self.url, self.key_setting = name, url, key_setting
        self.default_model, self.url_setting = default_model, url_setting

    def available(self) -> bool:
        if self.url_setting:
            return bool(_setting(self.url_setting))
        return super().available()

    def chat(self, client, messages, model=None):
        model = model or self.model()
        base = _setting(self.url_setting).rstrip("/") if self.url_setting else self.url
        headers = {"Authorization": f"Bearer {_setting(self.key_setting)}"} if self.key_setting else {}
        data = self._check(client.post(
            base + "/v1/chat/completions" if self.url_setting else base, headers=headers,
            json={"model": model, "messages": messages, "temperature": 0.1, "max_tokens": 1500,
                  "response_format": {"type": "json_object"}}))
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("no answer in the response")
        if not text:
            raise ProviderError("empty answer")
        return {"text": text, "model": data.get("model") or model}


PROVIDERS: List[Provider] = [
    Gemini(),
    OpenAICompatible("groq", "https://api.groq.com/openai/v1/chat/completions",
                     "GROQ_API_KEY", "llama-3.1-8b-instant"),
    OpenAICompatible("openrouter", "https://openrouter.ai/api/v1/chat/completions",
                     "OPENROUTER_API_KEY", "meta-llama/llama-3.3-70b-instruct:free"),
    OpenAICompatible("ollama", "", None, "llama3.1:8b", url_setting="OLLAMA_URL"),
]


# ---- per-model rate guard -------------------------------------------------------

_limit_lock = threading.Lock()
_model_calls: Dict[str, List[float]] = {}
_model_cooldowns: Dict[str, float] = {}


def _cooldown_seconds() -> float:
    raw = _setting("CANONRY_GEMINI_COOLDOWN_SECONDS")
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            raise RuntimeError("CANONRY_GEMINI_COOLDOWN_SECONDS must be a number of seconds.")
    return COOLDOWN_SECONDS


def _rpm_for(provider: Provider, model: str) -> int:
    """Requests per minute allowed for this model; 0 = no local limit.
    Gemini's free tiers differ by model, so its limits are kept per model."""
    if provider.name != "gemini":
        return 0
    raw = _setting("CANONRY_GEMINI_RPM")
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            raise RuntimeError("CANONRY_GEMINI_RPM must be a whole number.")
    limits = dict(GEMINI_RPM)
    raw_limits = _setting("CANONRY_GEMINI_RPM_LIMITS")
    if raw_limits:
        for part in raw_limits.split(","):
            name, sep, value = part.partition(":")
            if not sep:
                raise RuntimeError("CANONRY_GEMINI_RPM_LIMITS must be comma-separated model:rpm pairs.")
            try:
                limits[name.strip()] = max(0, int(value))
            except ValueError:
                raise RuntimeError("CANONRY_GEMINI_RPM_LIMITS must be comma-separated model:rpm pairs.")
    return limits.get(model, 10)


def _allow_model(key: str, rpm: int) -> bool:
    """False when the model is cooling down or has used its per-minute allowance."""
    now = time.monotonic()
    with _limit_lock:
        if _model_cooldowns.get(key, 0.0) > now:
            return False
        calls = [t for t in _model_calls.get(key, []) if now - t < 60.0]
        if rpm > 0 and len(calls) >= rpm:
            _model_calls[key] = calls
            return False
        calls.append(now)
        _model_calls[key] = calls
        return True


def _cool_model(key: str) -> None:
    with _limit_lock:
        _model_cooldowns[key] = time.monotonic() + _cooldown_seconds()


def reset_limits() -> None:
    """Clear the in-process RPM/cooldown state (tests, and a manual reset)."""
    with _limit_lock:
        _model_calls.clear()
        _model_cooldowns.clear()


def provider_list() -> List[Dict[str, Any]]:
    return [{"provider": p.name, "available": p.available(), "model": p.model(),
             "fallback_models": p.models()[1:]} for p in PROVIDERS]


def any_available() -> bool:
    return any(p.available() for p in PROVIDERS)


def call_budget_ok(revision_words: int, calls_so_far: int) -> bool:
    """<=3 batched LLM calls per 1,000-word check (doc 9.6/9.8)."""
    return calls_so_far < max(3, (revision_words // 1000) * 3)


def successful_calls(conn: sqlite3.Connection) -> int:
    """Answered calls so far (the budget counts answers, not failed attempts)."""
    return conn.execute("SELECT COUNT(*) FROM ai_calls WHERE ok = 1").fetchone()[0]


# ---- the call -------------------------------------------------------------------

def _log(conn: sqlite3.Connection, task: str, provider: Provider, model: str, prompt_version: str,
         started: float, ok: bool) -> None:
    conn.execute(
        "INSERT INTO ai_calls (at, task, provider, model, prompt_version, latency_ms, ok, cache_hit) "
        "VALUES (?,?,?,?,?,?,?,0)",
        (_now(), task, provider.name, model, prompt_version, int((time.perf_counter() - started) * 1000), int(ok)),
    )


def gateway_call(task: str, messages: List[Dict[str, str]], conn: Optional[sqlite3.Connection] = None,
                 budget_ok: bool = True, prompt_version: str = PROMPT_VERSION,
                 deadline: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Run one AI task through the fallback chain. Returns
    {'text', 'model', 'provider'}, or None when over budget, out of time, or no
    provider answered. `deadline` is a time.monotonic() moment; no attempt runs
    past it. A model that returns 429/503 is cooled down and skipped."""
    providers = [p for p in PROVIDERS if p.available()]
    if not budget_ok or not providers:
        return None
    own = conn is None
    conn = conn or connect()
    try:
        for provider in providers:
            models = provider.models()
            for round_no in range(2):  # one retry after a transient failure
                retryable_seen = False
                for model in models:
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 3:
                            return None
                        timeout = httpx.Timeout(min(TIMEOUT.read, remaining),
                                                connect=min(TIMEOUT.connect, remaining))
                    else:
                        timeout = TIMEOUT
                    key = f"{provider.name}:{model}"
                    if not _allow_model(key, _rpm_for(provider, model)):
                        continue
                    started = time.perf_counter()
                    try:
                        with httpx.Client(timeout=timeout, transport=_transport) as client:
                            out = provider.chat(client, messages, model=model)
                    except (ProviderError, httpx.HTTPError) as e:
                        _log(conn, task, provider, model, prompt_version, started, ok=False)
                        retryable = isinstance(e, httpx.TransportError) or getattr(e, "retryable", False)
                        if retryable:
                            retryable_seen = True
                        if getattr(e, "status", None) in (429, 503):
                            _cool_model(key)
                        continue
                    _log(conn, task, provider, out["model"], prompt_version, started, ok=True)
                    return {"text": out["text"], "model": out["model"], "provider": provider.name}
                if not retryable_seen:
                    break
                if round_no == 0:
                    time.sleep(1.0)
        return None
    finally:
        if own:
            conn.commit()
            conn.close()


def parse_json_out(text: str) -> Any:
    """Force AI output into a fixed format; content is data, never instructions."""
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        if start >= 0:
            try:
                return json.loads(text[start: text.rfind("}") + 1])
            except Exception:
                return None
        return None
