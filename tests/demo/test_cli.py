import http.client
import json
import threading

import pytest

from agent_memory import cli
from agent_memory.demo.paths import DEFAULT_ROOT, DemoPaths

ENV = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "EMBEDDING_BASE_URL", "EMBEDDING_MODEL", "EMBEDDING_API_KEY")


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    for v in ENV:
        monkeypatch.delenv(v, raising=False)


@pytest.fixture
def data_dir(tmp_path):
    p = DemoPaths(DEFAULT_ROOT / f"test-{tmp_path.name}")
    yield p.root
    p.wipe()
    if p.root.is_dir():
        p.root.rmdir()


def transport(model, messages):
    if messages[0]["role"] == "system" and "personal assistant" in messages[0]["content"]:
        return json.dumps({"reply": "ok", "todo": []}), 10, 5
    return json.dumps({"entries": []}), 10, 5


def embed(model, texts):
    return [[1.0, float(len(t))] for t in texts]


def test_estimate_only_prints_and_exits_zero_without_key(capsys, data_dir):
    assert cli.main(["demo", "--estimate-only", "--data-dir", str(data_dir)]) == 0
    out = capsys.readouterr().out
    assert "estimated tokens" in out and str(data_dir) in out and "http://" not in out


def test_warmup_without_key_exits_2(capsys, data_dir, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert cli.main(["demo", "--warmup", "--data-dir", str(data_dir)]) == 2
    err = capsys.readouterr().err
    assert "OPENAI_API_KEY" in err and "EMBEDDING_MODEL" in err
    assert cli.main(["demo", "--data-dir", str(data_dir)]) == 2  # live mode too, before any call


def test_embedding_endpoint_and_key_default_to_the_llm_ones(data_dir, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("EMBEDDING_MODEL", "m")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://llm")
    assert cli.main(["demo", "--warmup", "--data-dir", str(data_dir)], demo_transport=transport,
                    demo_embed_transport=embed) == 0
    assert cli.os.environ["EMBEDDING_BASE_URL"] == "http://llm" and cli.os.environ["EMBEDDING_API_KEY"] == "k"


def test_unsafe_data_dir_exits_2(capsys):
    assert cli.main(["demo", "--estimate-only", "--data-dir", "/"]) == 2
    assert "refusing unsafe demo root" in capsys.readouterr().err


def test_warmup_with_stub_fills_rehearsed_cache(capsys, data_dir):
    assert cli.main(["demo", "--warmup", "--data-dir", str(data_dir)], demo_transport=transport,
                    demo_embed_transport=embed) == 0
    assert "warm-up tokens used" in capsys.readouterr().out
    assert any((data_dir / "llm-cache-rehearsed").iterdir())


def test_serve_starts_and_stops(capsys, data_dir):
    box, up = {}, threading.Event()

    def ready(server):
        box["server"] = server
        up.set()

    t = threading.Thread(target=lambda: box.setdefault("code", cli.main(
        ["demo", "--port", "0", "--data-dir", str(data_dir)], demo_transport=transport,
        demo_embed_transport=embed, demo_ready=ready)))
    t.start()
    assert up.wait(10)
    server = box["server"]
    port = server.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", "/api/state")
    assert c.getresponse().status == 200
    server.shutdown()
    t.join(10)
    assert box["code"] == 0 and f"http://127.0.0.1:{port}/" in capsys.readouterr().out


def test_default_mode_is_live_and_bind_is_localhost(data_dir):
    box, up = {}, threading.Event()

    def ready(server):
        box["server"] = server
        up.set()

    t = threading.Thread(target=lambda: cli.main(["demo", "--port", "0", "--data-dir", str(data_dir)],
                                                  demo_transport=transport, demo_embed_transport=embed,
                                                  demo_ready=ready))
    t.start()
    assert up.wait(10)
    s = box["server"]
    assert s.session.mode == "live" and s.session.max_tokens == 100_000 and s.server_address[0] == "127.0.0.1"
    s.shutdown()
    t.join(10)
