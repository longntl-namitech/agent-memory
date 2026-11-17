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
