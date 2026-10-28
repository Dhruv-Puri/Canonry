"""Imported first by every suite: the tests never reach a real AI provider.

A developer's .env (or shell) may hold real free-tier keys; a test run must not
spend them. This reads no .env file and clears every provider setting, so AI
checks are "no provider" unless a suite fakes one (test_gateway, test_quota).
"""
import os

os.environ["CANONRY_ENV_FILE"] = ""
for _key in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "OLLAMA_URL"):
    os.environ.pop(_key, None)
