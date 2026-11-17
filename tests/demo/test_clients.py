import numpy as np
import pytest

from agent_memory.core.llm import BudgetExceeded, TokenBudget
from agent_memory.demo.clients import ReplayMiss, is_live_failure, make_embedder, make_llm, redact
from agent_memory.demo.paths import DemoPaths

MSG = [{"role": "user", "content": "hi"}]


def _paths(tmp_path):
    return DemoPaths(tmp_path / "demo")


def _stub():
    calls = []

    def t(model, messages):
        calls.append(1)
        return "ok", 1, 1

    return t, calls


def _llm(mode, paths, transport=None):
    return make_llm(mode, paths, TokenBudget(None), base_url="http://x", model="m", transport=transport)


def test_live_never_reads_cache(tmp_path):
    t, calls = _stub()
    c = _llm("live", _paths(tmp_path), t)
    c.chat(MSG, purpose="a")
    c.chat(MSG, purpose="a")
    assert len(calls) == 2


def test_warmup_writes_rehearsed_replay_reads_it(tmp_path):
    p = _paths(tmp_path)
    t, calls = _stub()
    assert _llm("warmup", p, t).chat(MSG, purpose="a").text == "ok"
    assert _llm("replay", p).chat(MSG, purpose="a").text == "ok"
    assert len(calls) == 1
    with pytest.raises(ReplayMiss):
        _llm("replay", p).chat([{"role": "user", "content": "other"}], purpose="a")


def test_replay_miss_raises(tmp_path):
    with pytest.raises(ReplayMiss):
        _llm("replay", _paths(tmp_path)).chat(MSG, purpose="a")


def test_replay_ignores_given_transport(tmp_path):
    t, calls = _stub()
    with pytest.raises(ReplayMiss):
        _llm("replay", _paths(tmp_path), t).chat(MSG, purpose="a")
    assert calls == []


def test_is_live_failure_classification():
    assert is_live_failure(OSError()) and is_live_failure(TimeoutError())
    assert not is_live_failure(BudgetExceeded("x"))
    assert not is_live_failure(ReplayMiss("x"))
    assert not is_live_failure(ValueError("x"))
    openai = pytest.importorskip("openai")

    def make(cls, status=None):  # skip __init__: its httpx types vary by openai version
        e = cls.__new__(cls)
        if status:
            e.status_code = status
        return e

    assert is_live_failure(make(openai.APIConnectionError))
    assert is_live_failure(make(openai.APITimeoutError))
    assert is_live_failure(make(openai.RateLimitError, 429))
    assert is_live_failure(make(openai.InternalServerError, 503))
    assert not is_live_failure(make(openai.BadRequestError, 400))


def test_redact_removes_key():
    key = "sk-test-123456789"
    out = redact(f"fail {key} Bearer abcdef.123456 enc x", [key, "", "a/b"])
    assert "123456789" not in out and "abcdef" not in out
    assert redact("plain", [key]) == "plain"
    from urllib.parse import quote

    assert "a%2Fb" not in redact(quote("a/b", safe=""), ["a/b"])


def test_replay_embedder_miss_raises(tmp_path):
    p = _paths(tmp_path)
    with pytest.raises(ReplayMiss):
        make_embedder("replay", p, base_url="http://x", model="e").embed(["x"])
    calls = []

    def t(model, texts):
        calls.append(1)
        return [[1.0, 0.0] for _ in texts]

    warm = make_embedder("warmup", p, base_url="http://x", model="e", transport=t).embed(["x"])
    again = make_embedder("replay", p, base_url="http://x", model="e").embed(["x"])
    assert np.allclose(warm, again) and len(calls) == 1
