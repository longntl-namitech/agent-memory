"""Token estimator: pure arithmetic, no network, no LLM, no clock."""

from dataclasses import dataclass

from agent_memory.core.llm import BudgetExceeded

SUBSET_THRESHOLD = 5_000_000
LME_QUESTIONS = 50
LME_FULL_CONTEXT_QUESTIONS = 10  # spec: full_context runs on about 10 questions
LME_INGEST_TOKENS_PER_QUESTION = 115_000  # spec: about 115k tokens of history per question
# UNVERIFIED placeholders, per question, re-check against the first subset run:
LME_INGEST_COMPLETION_PER_QUESTION = 3_000  # write_filter replies, about 50 sessions x 60 tokens
LME_ANSWER_TOKENS_PER_QUESTION = 2_500  # answer call: recalled memory + question + reply (not full_context)
LME_JUDGE_TOKENS_PER_QUESTION = 400  # judge call: prompt + yes/no
LME_NO_INGEST_LLM = ("write_raw", "full_context", "naive_rag")  # their writes make no LLM call
LME_NOTE = (f"note: longmemeval estimate is an approximation: ingestion counted once per distinct write stage "
            f"(cached), full_context as its answer prompt; per-question overheads are UNVERIFIED placeholders "
            f"(ingestion completion {LME_INGEST_COMPLETION_PER_QUESTION:,}, answer {LME_ANSWER_TOKENS_PER_QUESTION:,}, "
            f"judge {LME_JUDGE_TOKENS_PER_QUESTION:,})")
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
    overhead: int = 0  # LongMemEval answer and judge calls (placeholders)

    @property
    def total(self) -> int:
        return self.prompt + self.completion + self.overhead

    @property
    def needs_subset(self) -> bool:
        return self.total > SUBSET_THRESHOLD


def _lme_stage(name: str) -> str:
    """Fallback when the caller passes no stages: guess from the config name."""
    return next((m for m in ("full_context", "naive_rag") if m in name), "write_filter")


def estimate(eval_name: str, config_names: list[str], questions: int | None = None,
             full_context_questions: int = LME_FULL_CONTEXT_QUESTIONS,
             stages: dict[str, str] | None = None) -> Estimate:
    """LongMemEval: `questions` is the subset size (default 50); full_context runs on min(questions,
    full_context_questions). `stages` maps a config to its write stage or whole memory (guessed from the name
    when absent). Ingestion is cached and shared, so each distinct write stage is counted once, charged to the
    first config that has it; full_context costs its answer prompt (the whole history) instead."""
    if eval_name not in ("longmemeval", "simulation"):
        raise ValueError(f"unknown eval: {eval_name}")
    ours = [n for n in config_names if not n.startswith("hermes")]  # Hermes: T24 measures it with a pilot
    by_config = dict.fromkeys(config_names, 0)
    if eval_name == "simulation":
        p, c = SIM_TASKS * SIM_PROMPT_PER_TASK, SIM_TASKS * SIM_COMPLETION_PER_TASK
        by_config |= dict.fromkeys(ours, p + c)
        return Estimate(p * len(ours), c * len(ours), by_config)
    n = questions or LME_QUESTIONS
    prompt = completion = overhead = 0
    seen: set[str] = set()
    for name in ours:
        stage = (stages or {}).get(name) or _lme_stage(name)
        q = min(n, full_context_questions) if stage == "full_context" else n
        p = c = 0
        if stage == "full_context":
            p = q * LME_INGEST_TOKENS_PER_QUESTION
        elif stage not in LME_NO_INGEST_LLM and stage not in seen:
            seen.add(stage)
            p, c = q * LME_INGEST_TOKENS_PER_QUESTION, q * LME_INGEST_COMPLETION_PER_QUESTION
        o = q * (LME_ANSWER_TOKENS_PER_QUESTION + LME_JUDGE_TOKENS_PER_QUESTION)
        prompt, completion, overhead = prompt + p, completion + c, overhead + o
        by_config[name] = p + c + o
    return Estimate(prompt, completion, by_config, overhead)


def gate(est: Estimate, max_tokens: int | None, estimate_only: bool = True) -> None:
    if estimate_only:
        raise EstimateOnly(
            f"estimate: prompt={est.prompt} completion={est.completion} "
            f"total={est.total} needs_subset={est.needs_subset}"
        )
    if max_tokens is not None and est.total > max_tokens:
        raise BudgetExceeded(f"estimate {est.total} exceeds max_tokens {max_tokens}")
