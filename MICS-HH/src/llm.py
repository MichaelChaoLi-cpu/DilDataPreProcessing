"""LLM and embedding interface — Gemini backend."""
from __future__ import annotations
import os
import time
from typing import NamedTuple

_GEMINI_CLIENT = None


class LLMResult(NamedTuple):
    text: str
    input_tokens: int
    output_tokens: int
    thoughts_tokens: int
    total_tokens: int


def _get_client():
    from google import genai

    global _GEMINI_CLIENT
    if _GEMINI_CLIENT is None:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set.")
        _GEMINI_CLIENT = genai.Client(api_key=api_key)
    return _GEMINI_CLIENT


def call_llm(prompt: str, retries: int = 3, backoff: float = 5.0) -> LLMResult:
    from google.genai import types

    client = _get_client()
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
            response = client.models.generate_content(
                model=model, contents=prompt, config=config,
            )
            usage = response.usage_metadata
            input_tokens   = usage.prompt_token_count or 0
            output_tokens  = usage.candidates_token_count or 0
            thoughts_tokens = usage.thoughts_token_count or 0
            total_tokens   = usage.total_token_count or 0
            return LLMResult(response.text, input_tokens, output_tokens, thoughts_tokens, total_tokens)
        except Exception as e:
            last_exc = e
            time.sleep(backoff * (2 ** attempt))
    raise last_exc


def embed_text(text: str, retries: int = 3, backoff: float = 5.0) -> list[float]:
    client = _get_client()
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            response = client.models.embed_content(
                model="models/gemini-embedding-001",
                contents=text,
            )
            return list(response.embeddings[0].values)
        except Exception as e:
            last_exc = e
            time.sleep(backoff * (2 ** attempt))
    raise last_exc
