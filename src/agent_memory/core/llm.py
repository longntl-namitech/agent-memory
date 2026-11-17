"""OpenAI-compatible chat client with a disk cache and a shared token budget."""

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

# transport(model, messages) -> (text, prompt_tokens, completion_tokens)
Transport = Callable[[str, list[dict]], tuple[str, int, int]]


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int


class TokenBudget:
    def __init__(self, max_tokens: int | None):
        self.max_tokens = max_tokens  # None means unlimited
        self.used = 0

    def spend(self, n: int) -> None:
        # Overshoot is recorded before raising so `used` shows the true cost.
        self.used += n
        if self.max_tokens is not None and self.used > self.max_tokens:
            raise BudgetExceeded(f"token budget exceeded ({self.used}/{self.max_tokens})")


class LLMClient:
    def __init__(self, base_url: str, model: str, budget: TokenBudget, cache_dir, transport: Transport | None = None, *, read_cache: bool = True):
        self.base_url = base_url
        self.model = model
        self.budget = budget
        self.cache_dir = Path(cache_dir)
        self.read_cache = read_cache
        self._transport = transport or self._openai_transport

    def _openai_transport(self, model: str, messages: list[dict]) -> tuple[str, int, int]:
        from openai import OpenAI

        client = OpenAI(base_url=self.base_url, api_key=os.environ.get("OPENAI_API_KEY", "none"))
        r = client.chat.completions.create(model=model, messages=messages)
        usage = r.usage
        return (
            r.choices[0].message.content or "",
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
        )

    def _path(self, messages: list[dict]) -> Path:
        key = json.dumps([self.model, messages], sort_keys=True, ensure_ascii=False)
        return self.cache_dir / (hashlib.sha256(key.encode()).hexdigest() + ".json")

    def chat(self, messages: list[dict], *, purpose: str) -> Completion:
        path = self._path(messages)
        if self.read_cache and path.exists():
            return Completion(**json.loads(path.read_text(encoding="utf-8")))
        self.budget.spend(0)  # refuse new calls once the budget is already blown
        text, prompt, completion = self._transport(self.model, messages)
        result = Completion(text, prompt, completion)
        # Cache before spending: an overshooting reply is already paid for, keep it.
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(result), f)
        os.replace(tmp, path)  # atomic: a crash never leaves a half-written entry
        try:
            self.budget.spend(prompt + completion)
        except BudgetExceeded as exc:
            raise BudgetExceeded(f"{exc} (purpose: {purpose})") from None
        return result
