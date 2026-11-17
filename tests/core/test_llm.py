import pytest

from agent_memory.core.llm import BudgetExceeded, LLMClient, TokenBudget

MSGS = [{"role": "user", "content": "hi"}]


class Fake:
    def __init__(self, prompt=3, completion=4):
        self.calls = 0
        self.tokens = (prompt, completion)

    def __call__(self, model, messages):
        self.calls += 1
        return f"reply-{model}", *self.tokens


def client(tmp_path, fake, model="m", limit=None):
    budget = TokenBudget(limit)
    return LLMClient("http://x", model, budget, tmp_path, transport=fake), budget


def test_cache_hit_costs_zero(tmp_path):
    fake = Fake()
    llm, budget = client(tmp_path, fake)
    first = llm.chat(MSGS, purpose="t")
    assert budget.used == 7
    assert llm.chat(MSGS, purpose="t") == first
    assert fake.calls == 1
    assert budget.used == 7


def test_cache_persists_across_clients(tmp_path):
    fake = Fake()
    client(tmp_path, fake)[0].chat(MSGS, purpose="t")
    client(tmp_path, fake)[0].chat(MSGS, purpose="t")
    assert fake.calls == 1


def test_budget_exceeded_raises(tmp_path):
    llm, budget = client(tmp_path, Fake(5, 45), limit=10)
    with pytest.raises(BudgetExceeded):
        llm.chat(MSGS, purpose="t")
    assert budget.used == 50
    with pytest.raises(BudgetExceeded):  # exhausted budget blocks further calls
        llm.chat([{"role": "user", "content": "other"}], purpose="t")


def test_overshooting_reply_is_cached(tmp_path):
    fake = Fake(5, 45)
    llm, _ = client(tmp_path, fake, limit=10)
    with pytest.raises(BudgetExceeded):
        llm.chat(MSGS, purpose="t")
    assert client(tmp_path, fake)[0].chat(MSGS, purpose="t").text == "reply-m"
    assert fake.calls == 1


def test_unlimited_budget(tmp_path):
    llm, budget = client(tmp_path, Fake(10**6, 10**6), limit=None)
    llm.chat(MSGS, purpose="t")
    assert budget.used == 2 * 10**6


def test_cache_key_includes_model(tmp_path):
    fake = Fake()
    a = client(tmp_path, fake, model="a")[0].chat(MSGS, purpose="t")
    b = client(tmp_path, fake, model="b")[0].chat(MSGS, purpose="t")
    assert fake.calls == 2
    assert a.text != b.text
