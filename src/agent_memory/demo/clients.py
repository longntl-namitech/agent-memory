"""LLM and embedder factories for the demo, plus failure classification and redaction."""

import os
import re
from typing import Literal
from urllib.parse import quote, quote_plus

from agent_memory.core.embed import OpenAICompatEmbedder
from agent_memory.core.llm import BudgetExceeded, LLMClient, TokenBudget
from agent_memory.demo.paths import DemoPaths

Mode = Literal["live", "warmup", "replay"]


class ReplayMiss(Exception):
    pass


def replay_transport(model, messages):
    raise ReplayMiss("Not in the rehearsed script, replay cannot answer")


def _replay_embed_transport(model, texts):
    raise ReplayMiss("Not in the rehearsed script, replay cannot answer")


TIMEOUT = 20  # seconds: a stalled provider must fail over to replay, not hang the page
MAX_RETRIES = 1


def live_llm_transport(base_url: str | None):
    """Same call as the lab's LLMClient transport, with a short timeout and one retry."""
    def transport(model, messages):
        from openai import OpenAI

        client = OpenAI(base_url=base_url, api_key=os.environ.get("OPENAI_API_KEY", "none"),
                        timeout=TIMEOUT, max_retries=MAX_RETRIES)
        r = client.chat.completions.create(model=model, messages=messages)
        usage = r.usage
        return (r.choices[0].message.content or "",
                usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0)
    return transport


def live_embed_transport(base_url: str | None, api_key: str | None):
    def transport(model, texts):
        from openai import OpenAI

        client = OpenAI(base_url=base_url, api_key=api_key or os.environ.get("EMBEDDING_API_KEY", "none"),
                        timeout=TIMEOUT, max_retries=MAX_RETRIES)
        return [d.embedding for d in client.embeddings.create(model=model, input=texts).data]
    return transport


def make_llm(mode: Mode, paths: DemoPaths, budget: TokenBudget, *, base_url: str, model: str, transport=None,
             column: str | None = None) -> LLMClient:
    live = paths.live_cache(column) if column else paths.llm_live
    rehearsed = paths.rehearsed_cache(column) if column else paths.llm_rehearsed
    if mode == "replay":
        return LLMClient(base_url, model, budget, rehearsed, replay_transport, read_cache=True)
    cache = live if mode == "live" else rehearsed
    return LLMClient(base_url, model, budget, cache, transport or live_llm_transport(base_url), read_cache=False)


def make_embedder(mode: Mode, paths: DemoPaths, *, base_url: str | None = None, model: str | None = None,
                  api_key: str | None = None, transport=None) -> OpenAICompatEmbedder:
    if mode == "replay":
        transport = _replay_embed_transport  # never reach the network from replay
    elif transport is None:
        transport = live_embed_transport(base_url, api_key)
    return OpenAICompatEmbedder(base_url, model, cache_dir=paths.embeddings, api_key=api_key, transport=transport)


def is_live_failure(exc: BaseException) -> bool:
    if isinstance(exc, (BudgetExceeded, ReplayMiss)):
        return False
    if isinstance(exc, (OSError, TimeoutError)):
        return True
    try:
        import openai
    except ImportError:
        return False
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError)):
        return True
    return isinstance(exc, openai.APIStatusError) and exc.status_code >= 500


_SK = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")
_BEARER = re.compile(r"Bearer [A-Za-z0-9._\-/+=]{8,}", re.I)


def redact(text: str, secrets: list[str]) -> str:
    """Mask secrets (longest first, plain and URL-encoded forms) and key-like tokens.

    Secrets shorter than 4 characters are ignored by design: masking a 1 to 3
    character secret would destroy the text.
    """
    for s in sorted({s for s in secrets if len(s) >= 4}, key=len, reverse=True):
        for form in (s, quote(s, safe=""), quote_plus(s)):
            text = text.replace(form, "[redacted]")
    return _BEARER.sub("[redacted]", _SK.sub("[redacted]", text))
