"""Token estimator: pure arithmetic, no network, no LLM, no clock."""

from dataclasses import dataclass

from agent_memory.core.llm import BudgetExceeded

SUBSET_THRESHOLD = 5_000_000
LME_QUESTIONS = 50
LME_FULL_CONTEXT_QUESTIONS = 10  # spec: full_context runs on about 10 questions
LME_INGEST_TOKENS_PER_QUESTION = 115_000  # spec: ingestion is all prompt tokens
SIM_TASKS = 40
# Spec gives no simulation per-task figure; 2,500 = the 100k per-config cap / 40 tasks.
SIM_PROMPT_PER_TASK = 2_000
SIM_COMPLETION_PER_TASK = 500


class EstimateOnly(Exception):
    pass


@dataclass
class Estimate:
    prompt: int
    completion: int
    by_config: dict[str, int]

    @property
    def total(self) -> int:
        return self.prompt + self.completion

    @property
    def needs_subset(self) -> bool:
        return self.total > SUBSET_THRESHOLD


def estimate(eval_name: str, config_names: list[str], questions: int | None = None,
             full_context_questions: int = LME_FULL_CONTEXT_QUESTIONS) -> Estimate:
    """`questions` (LongMemEval only) is the subset size; full_context configs run on at most
    `full_context_questions` of them. Each config is counted in full, though configs sharing a write stage
    share the ingestion cache: an upper bound."""
    def cost(name: str) -> tuple[int, int]:
        if name.startswith("hermes"):
            return 0, 0  # Hermes prompts are not ours; T24 measures it with a pilot.
        if eval_name == "longmemeval":
            n = questions or LME_QUESTIONS
            if "full_context" in name:
                n = min(n, full_context_questions)
            return n * LME_INGEST_TOKENS_PER_QUESTION, 0
        return SIM_TASKS * SIM_PROMPT_PER_TASK, SIM_TASKS * SIM_COMPLETION_PER_TASK

    if eval_name not in ("longmemeval", "simulation"):
        raise ValueError(f"unknown eval: {eval_name}")
    costs = {n: cost(n) for n in config_names}
    return Estimate(sum(p for p, _ in costs.values()), sum(c for _, c in costs.values()),
                    {n: p + c for n, (p, c) in costs.items()})


def gate(est: Estimate, max_tokens: int | None, estimate_only: bool = True) -> None:
    if estimate_only:
        raise EstimateOnly(
            f"estimate: prompt={est.prompt} completion={est.completion} "
            f"total={est.total} needs_subset={est.needs_subset}"
        )
    if max_tokens is not None and est.total > max_tokens:
        raise BudgetExceeded(f"estimate {est.total} exceeds max_tokens {max_tokens}")
