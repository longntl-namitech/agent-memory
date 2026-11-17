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
    out = redact(f"fail {key} Bearer abcdef.123456 x", [key, ""])
    assert "123456789" not in out and "abcdef" not in out
    assert redact("plain", [key]) == "plain"
    from urllib.parse import quote

    secret = "pa/ss+word"
    text = quote(secret, safe="")
    inp = f"url?k={text}"
    assert text != secret and text in inp  # the encoded form really appears in the input
    out = redact(inp, [secret])
    assert text not in out and "[redacted]" in out


def test_redact_longest_secret_first():
    out = redact("x abcdef y", ["abc", "abcdef"])
    assert "def" not in out and out == "x [redacted] y"


def test_redact_bearer_case_insensitive_and_base64():
    for word in ("bearer", "BEARER"):
        out = redact(f"h: {word} abcDEF123+/==xyz end", [])
        assert "abcDEF" not in out and "xyz" not in out


def test_redact_plus_form():
    from urllib.parse import quote_plus

    secret = "my secret key"
    text = quote_plus(secret)
    assert "+" in text and text in f"q={text}"
    assert text not in redact(f"q={text}", [secret])


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
