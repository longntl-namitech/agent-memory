import json
import random
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import openai
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_story import CONFIGS, embed, fake_model  # noqa: E402

from agent_memory import cli  # noqa: E402
from agent_memory.core.llm import TokenBudget  # noqa: E402
from agent_memory.demo import clients  # noqa: E402
from agent_memory.demo.paths import DEFAULT_ROOT, DemoPaths  # noqa: E402
from agent_memory.demo.script import PROMPTS, run_script  # noqa: E402
from agent_memory.demo.session import Session  # noqa: E402


@pytest.fixture
def paths(tmp_path):
    p = DemoPaths(DEFAULT_ROOT / f"test-{tmp_path.name}")
    yield p
    p.wipe()
    if p.root.is_dir():
        p.root.rmdir()


def session(paths, mode, transport=None, model="m"):
    return Session(paths, mode=mode, max_tokens=10**6, base_url="http://x", model=model, config_dir=CONFIGS,
                   transport=transport, embed_transport=embed)


def varying(calls=None):
    """Like a real model: every answer differs per call, and calls overlap in time."""
    base, lock = fake_model(), threading.Lock()

    def transport(model, messages):
        text, a, b = base(model, messages)
        d = json.loads(text)
        if "reply" in d:
            time.sleep(random.random() * 0.02)
            d["reply"] += f" [{random.random():.6f}]"
        if calls is not None:
            with lock:
                calls.append(1)
        return json.dumps(d), a, b
    return transport


def test_replay_never_misses_when_replies_vary_per_call_and_column(paths):
    for _ in range(20):
        paths.wipe()
        w = session(paths, "warmup", varying())
        run_script(w, True)
        calls = []
        r = session(paths, "replay", varying(calls))
        outs = [r.turn(t) for t in PROMPTS]
        assert calls == [] and all(o[c].error is None for o in outs for c in o)


def test_replay_uses_warmup_model_names_not_the_env(paths, monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "emb-v1")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://e")
    run_script(session(paths, "warmup", varying(), model="llm-v1"))
    assert paths.read_meta() == {"model": "llm-v1", "embedding_model": "emb-v1"}
    monkeypatch.delenv("EMBEDDING_MODEL")
    monkeypatch.delenv("EMBEDDING_BASE_URL")
    r = session(paths, "replay", model="something-else")
    outs = [r.turn(t) for t in PROMPTS]
    assert all(o[c].error is None for o in outs for c in o)


def test_session_wipe_keeps_foreign_file(paths):
    s = session(paths, "live", varying())
    s.turn(PROMPTS[0])
    (paths.root / "mine.txt").write_text("keep")
    s.wipe()
    assert (paths.root / "mine.txt").read_text() == "keep"
    (paths.root / "mine.txt").unlink()


def test_cli_replay_without_warmup_exits_2(paths, capsys):
    assert cli.main(["demo", "--mode", "replay", "--data-dir", str(paths.root)]) == 2
    assert "--warmup" in capsys.readouterr().err


def test_live_transports_use_short_timeout_and_one_retry(monkeypatch):
    seen = []

    class Fake:
        def __init__(self, **kw):
            seen.append(kw)
            msg = SimpleNamespace(content="hi")
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **k: SimpleNamespace(
                choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2))))
            self.embeddings = SimpleNamespace(create=lambda **k: SimpleNamespace(
                data=[SimpleNamespace(embedding=[1.0])]))

    monkeypatch.setattr(openai, "OpenAI", Fake)
    assert clients.live_llm_transport("http://x")("m", []) == ("hi", 1, 2)
    assert clients.live_embed_transport("http://e", "k")("e", ["t"]) == [[1.0]]
    assert all(kw["timeout"] <= 30 and kw["max_retries"] == 1 for kw in seen) and len(seen) == 2


def test_timeout_error_triggers_failover(paths):
    def slow(model, messages):
        raise openai.APITimeoutError.__new__(openai.APITimeoutError)  # skip __init__: httpx types vary by version

    s = session(paths, "live", slow)
    s.turn(PROMPTS[0])
    snap = s.snapshot()
    assert snap["mode"] == "replay" and "switched to replay" in snap["notice"]


def test_make_llm_default_builds_the_short_timeout_transport(paths):
    llm = clients.make_llm("live", paths, TokenBudget(None), base_url="http://x", model="m", column="full")
    assert llm._transport.__qualname__.startswith("live_llm_transport")
