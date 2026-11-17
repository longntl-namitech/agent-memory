"""Token estimator: pure arithmetic, no network, no LLM, no clock."""

from dataclasses import dataclass

from agent_memory.core.llm import BudgetExceeded

SUBSET_THRESHOLD = 5_000_000
LME_QUESTIONS = 50
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


def estimate(eval_name: str, config_names: list[str]) -> Estimate:
    if eval_name == "longmemeval":
        p, c = LME_QUESTIONS * LME_INGEST_TOKENS_PER_QUESTION, 0
    elif eval_name == "simulation":
        p, c = SIM_TASKS * SIM_PROMPT_PER_TASK, SIM_TASKS * SIM_COMPLETION_PER_TASK
    else:
        raise ValueError(f"unknown eval: {eval_name}")
    # Hermes prompts are not ours; T24 measures it with a pilot.
    ours = [n for n in config_names if not n.startswith("hermes")]
    by_config = {n: (0 if n.startswith("hermes") else p + c) for n in config_names}
    return Estimate(p * len(ours), c * len(ours), by_config)


def gate(est: Estimate, max_tokens: int | None, estimate_only: bool = True) -> None:
    if estimate_only:
        raise EstimateOnly(
            f"estimate: prompt={est.prompt} completion={est.completion} "
            f"total={est.total} needs_subset={est.needs_subset}"
        )
    if max_tokens is not None and est.total > max_tokens:
        raise BudgetExceeded(f"estimate {est.total} exceeds max_tokens {max_tokens}")
