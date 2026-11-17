import pytest

from agent_memory.core.eval.estimate import Estimate, EstimateOnly, estimate, gate
from agent_memory.core.llm import BudgetExceeded


def test_longmemeval_warning():
    est = estimate("longmemeval", ["full_lme"])
    assert est.prompt == 5_750_000
    assert est.needs_subset


def test_estimate_only_is_default():
    with pytest.raises(EstimateOnly):
        gate(estimate("simulation", ["baseline"]), None)


def test_max_tokens_cap():
    est = estimate("simulation", ["baseline"])
    total = est.prompt + est.completion
    with pytest.raises(BudgetExceeded):
        gate(est, total - 1, estimate_only=False)
    assert gate(est, total, estimate_only=False) is None
    assert gate(est, None, estimate_only=False) is None


def test_hermes_excluded():
    base = estimate("simulation", ["baseline"])
    both = estimate("simulation", ["baseline", "hermes_default"])
    assert (both.prompt, both.completion) == (base.prompt, base.completion)
    assert both.by_config["hermes_default"] == 0
    assert estimate("longmemeval", ["hermes"]).by_config == {"hermes": 0}


def test_unknown_eval():
    with pytest.raises(ValueError):
        estimate("nope", ["a"])


def test_exactly_5m_needs_no_subset():
    assert not Estimate(5_000_000, 0, {}).needs_subset
    assert Estimate(5_000_000, 1, {}).needs_subset


ALL_SIX = {"lme_baseline_full_context": "full_context", "lme_baseline_naive_rag": "naive_rag",
           "lme_b1_write_filter": "write_filter", "lme_b2_coala_stores": "write_filter",
           "lme_b3_scored_recall": "write_filter", "lme_full": "write_filter"}


def test_lme_same_write_stage_counts_ingestion_once():
    one = estimate("longmemeval", ["a"], 8, 10, {"a": "write_filter"})
    two = estimate("longmemeval", ["a", "b"], 8, 10, {"a": "write_filter", "b": "write_filter"})
    assert one.prompt == two.prompt == 8 * 115_000
    assert one.completion == two.completion
    assert two.overhead == 2 * one.overhead > 0
    assert two.by_config["b"] == one.overhead  # the shared ingestion is charged to the first config
    raw = estimate("longmemeval", ["a", "c"], 8, 10, {"a": "write_filter", "c": "write_raw"})
    assert raw.prompt == one.prompt  # write_raw is its own stage but makes no LLM call


def test_lme_naive_rag_adds_no_ingestion():
    est = estimate("longmemeval", ["r"], 8, 10, {"r": "naive_rag"})
    assert est.prompt == est.completion == 0 and est.overhead > 0


def test_lme_full_context_is_its_answer_prompt():
    est = estimate("longmemeval", ["f"], None, 10, {"f": "full_context"})
    assert est.prompt == 10 * 115_000 and est.completion == 0
    assert estimate("longmemeval", ["f"], 8, 10, {"f": "full_context"}).prompt == 8 * 115_000


def test_lme_subset_under_1m_and_full_set_above_5m():
    assert estimate("longmemeval", ["lme_b1_write_filter"], 8, 10, ALL_SIX).total < 1_000_000
    full = estimate("longmemeval", list(ALL_SIX), None, 10, ALL_SIX)
    assert full.total > 5_000_000 and full.needs_subset
