"""One controlled AI gateway (doc Sections 9.1, 9.2, 9.8).

- provider adapters behind one interface: Gemini, any OpenAI-compatible API
  (Groq, OpenRouter) and a local Ollama model, tried in that order
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
import time
from typing import Any, Dict, List, Optional

import httpx

from db import _now, connect

PROMPT_VERSION = "claims@4"
TIMEOUT = httpx.Timeout(20.0, connect=5.0)
RETRYABLE = {408, 429, 500, 502, 503, 504}


class ProviderError(Exception):
    """A provider did not produce a usable answer."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


# ---- configuration ------------------------------------------------------------

def _read_env_file() -> Dict[str, str]:
    """The project-root .env (values are never printed or logged)."""
    path = os.path.join(os.path.dirname(__file__), "..", ".env")
    data: Dict[str, str] = {}
    if os.path.exists(path):
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

    def chat(self, client: httpx.Client, messages: List[Dict[str, str]]) -> Dict[str, str]:
        raise NotImplementedError

    @staticmethod
    def _check(r: httpx.Response) -> Dict[str, Any]:
        if r.status_code >= 400:
            raise ProviderError(f"HTTP {r.status_code}", retryable=r.status_code in RETRYABLE)
        try:
            return r.json()
        except ValueError:
            raise ProviderError("response is not JSON")


class Gemini(Provider):
    name, key_setting, default_model = "gemini", "GEMINI_API_KEY", "gemini-2.5-flash"

    def chat(self, client, messages):
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": m["content"]}]}
                         for m in messages if m["role"] != "system"],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        data = self._check(client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model()}:generateContent",
            headers={"x-goog-api-key": _setting(self.key_setting) or ""}, json=payload))
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("no answer in the response")
        return {"text": text, "model": self.model()}


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

    def chat(self, client, messages):
        base = _setting(self.url_setting).rstrip("/") if self.url_setting else self.url
        headers = {"Authorization": f"Bearer {_setting(self.key_setting)}"} if self.key_setting else {}
        data = self._check(client.post(
            base + "/v1/chat/completions" if self.url_setting else base, headers=headers,
            json={"model": self.model(), "messages": messages, "temperature": 0.1, "max_tokens": 1500,
                  "response_format": {"type": "json_object"}}))
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("no answer in the response")
        if not text:
            raise ProviderError("empty answer")
        return {"text": text, "model": data.get("model") or self.model()}


PROVIDERS: List[Provider] = [
    Gemini(),
    OpenAICompatible("groq", "https://api.groq.com/openai/v1/chat/completions",
                     "GROQ_API_KEY", "llama-3.1-8b-instant"),
    OpenAICompatible("openrouter", "https://openrouter.ai/api/v1/chat/completions",
                     "OPENROUTER_API_KEY", "meta-llama/llama-3.3-70b-instruct:free"),
    OpenAICompatible("ollama", "", None, "llama3.1:8b", url_setting="OLLAMA_URL"),
]


def provider_list() -> List[Dict[str, Any]]:
    return [{"provider": p.name, "available": p.available(), "model": p.model()} for p in PROVIDERS]


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
                 budget_ok: bool = True, prompt_version: str = PROMPT_VERSION) -> Optional[Dict[str, Any]]:
    """Run one AI task through the fallback chain. Returns
    {'text', 'model', 'provider'}, or None when over budget or no provider answered."""
    providers = [p for p in PROVIDERS if p.available()]
    if not budget_ok or not providers:
        return None
    own = conn is None
    conn = conn or connect()
    try:
        with httpx.Client(timeout=TIMEOUT, transport=_transport) as client:
            for provider in providers:
                for attempt in range(2):  # one retry, only for rate limits / server errors
                    started = time.perf_counter()
                    try:
                        out = provider.chat(client, messages)
                    except (ProviderError, httpx.HTTPError) as e:
                        _log(conn, task, provider, provider.model(), prompt_version, started, ok=False)
                        retryable = isinstance(e, httpx.TransportError) or getattr(e, "retryable", False)
                        if retryable and attempt == 0:
                            time.sleep(1.0)
                            continue
                        break
                    _log(conn, task, provider, out["model"], prompt_version, started, ok=True)
                    return {"text": out["text"], "model": out["model"], "provider": provider.name}
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
