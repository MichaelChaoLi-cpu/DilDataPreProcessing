"""LLM interface — Gemini backend (adapted from HappyToGo)."""
from __future__ import annotations
import os
import time

_GEMINI_CLIENT = None


def _gemini_call(prompt: str, retries: int, backoff: float) -> str:
    from google import genai
    from google.genai import types

    global _GEMINI_CLIENT
    if _GEMINI_CLIENT is None:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set.")
        _GEMINI_CLIENT = genai.Client(api_key=api_key)

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    temperature = float(os.environ.get("GEMINI_TEMPERATURE", "0.2"))
    max_tokens = int(os.environ.get("GEMINI_MAX_TOKENS", "8192"))

    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
    )

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            response = _GEMINI_CLIENT.models.generate_content(
                model=model, contents=prompt, config=config,
            )
            return response.text
        except Exception as e:
            last_exc = e
            wait = backoff * (2 ** attempt)
            time.sleep(wait)
    raise last_exc


def call_llm(prompt: str, retries: int = 3, backoff: float = 5.0) -> str:
    return _gemini_call(prompt, retries, backoff)
