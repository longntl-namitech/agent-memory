"""LLM and embedder factories for the demo, plus failure classification and redaction."""

import re
from typing import Literal
from urllib.parse import quote

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


def make_llm(mode: Mode, paths: DemoPaths, budget: TokenBudget, *, base_url: str, model: str, transport=None) -> LLMClient:
    if mode == "replay":
        return LLMClient(base_url, model, budget, paths.llm_rehearsed, replay_transport, read_cache=True)
    cache = paths.llm_live if mode == "live" else paths.llm_rehearsed
    return LLMClient(base_url, model, budget, cache, transport, read_cache=False)


def make_embedder(mode: Mode, paths: DemoPaths, *, base_url: str | None = None, model: str | None = None,
                  api_key: str | None = None, transport=None) -> OpenAICompatEmbedder:
    if mode == "replay":
        transport = _replay_embed_transport  # never reach the network from replay
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


_PATTERNS = re.compile(r"sk-[A-Za-z0-9_\-]{8,}|Bearer [A-Za-z0-9._\-]{8,}")


def redact(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "[redacted]").replace(quote(s, safe=""), "[redacted]")
    return _PATTERNS.sub("[redacted]", text)
