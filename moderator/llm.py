"""The LLM call: an async OpenAI-compatible client, a JSON-schema answer and strict validation."""
import asyncio
import json
import logging
import time
import weakref
from dataclasses import dataclass
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError

from . import config
from .prompts import CATEGORIES, DECISIONS, SYSTEM_PROMPT, VERDICT_SCHEMA, build_user_message

log = logging.getLogger("moderator.llm")


class Verdict(BaseModel):
    decision: Literal[DECISIONS]
    category: Literal[CATEGORIES]
    toxicity_score: int = Field(ge=0, le=100)
    reason: str = Field(max_length=500)


@dataclass
class LLMResult:
    verdict: Verdict
    raw: str
    latency_ms: int
    reasoning_tokens: int | None


class LLMError(Exception):
    """The model could not be reached or did not return a valid verdict."""


# One client per event loop: an httpx connection pool must not be shared across loops
# (tests and the eval runner start new loops).
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, AsyncOpenAI]" = weakref.WeakKeyDictionary()


def _client() -> AsyncOpenAI:
    loop = asyncio.get_running_loop()
    if loop not in _clients:
        _clients[loop] = AsyncOpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY,
                                     timeout=config.LLM_TIMEOUT_S, max_retries=1)
    return _clients[loop]


def parse_verdict(raw: str) -> Verdict:
    text = raw.strip()
    if text.startswith("```"):  # tolerate a markdown fence if a model adds one anyway
        text = text.strip("`").removeprefix("json").strip()
    try:
        return Verdict.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as e:
        raise LLMError(f"invalid verdict: {e}") from e


async def classify(author: str, content: str) -> LLMResult:
    kwargs = {}
    if config.REASONING_EFFORT:
        kwargs["reasoning_effort"] = config.REASONING_EFFORT
    start = time.perf_counter()
    try:
        response = await _client().chat.completions.create(
            model=config.MODEL_NAME,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": build_user_message(author, content)}],
            temperature=0.1,
            response_format={"type": "json_schema",
                             "json_schema": {"name": "moderation_verdict", "strict": True, "schema": VERDICT_SCHEMA}},
            **kwargs,
        )
    except Exception as e:
        raise LLMError(f"request failed: {type(e).__name__}") from e
    latency_ms = int((time.perf_counter() - start) * 1000)
    raw = response.choices[0].message.content or ""
    details = response.usage.completion_tokens_details if response.usage else None
    return LLMResult(verdict=parse_verdict(raw), raw=raw, latency_ms=latency_ms,
                     reasoning_tokens=getattr(details, "reasoning_tokens", None) if details else None)
