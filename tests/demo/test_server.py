import http.client
import json
import logging
import threading
from pathlib import Path

import pytest

from agent_memory.demo.paths import DEFAULT_ROOT, DemoPaths
from agent_memory.demo.server import make_server
from agent_memory.demo.session import Session

CONFIGS = Path(__file__).resolve().parents[2] / "configs" / "demo"
T1 = "I'm An, I live in Ho Chi Minh City. Remind me to call the dentist on Friday."


def transport(model, messages):
    sys, user = messages[0]["content"], messages[-1]["content"]
    if "personal assistant" in sys and messages[0]["role"] == "system":
        return json.dumps({"reply": "A reply that is longer than one chunk of text.", "todo": []}), 10, 5
    return json.dumps({"entries": [{"kind": "fact", "key": "city", "text": "Lives in HCMC", "importance": 5}]}), 10, 5


def embed(model, texts):
    return [[float(len(t)), 1.0] for t in texts]


@pytest.fixture
def paths(tmp_path):
    p = DemoPaths(DEFAULT_ROOT / f"test-{tmp_path.name}")
    yield p
    p.wipe()
    if p.root.is_dir():
        p.root.rmdir()


class Ctx:
    def __init__(self, paths, tmp_path, tr):
        self.session = Session(paths, mode="live", max_tokens=100_000, base_url="http://x", model="m",
                               config_dir=CONFIGS, transport=tr, embed_transport=embed)
        (tmp_path / "static").mkdir()
        (tmp_path / "static" / "index.html").write_text("<p>hi</p>")
        (tmp_path / "secret.txt").write_text("top secret")
        self.static = tmp_path / "static"
        self.srv = make_server(self.session, 0, self.static)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def req(self, method, path, body=None, headers=None, raw=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = dict(headers or {})
        data = raw if raw is not None else (json.dumps(body) if body is not None else None)
        if data is not None:
            h.setdefault("Content-Type", "application/json")
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = r.status, r.read().decode()
        c.close()
        return out


@pytest.fixture
def ctx(paths, tmp_path):
    c = Ctx(paths, tmp_path, transport)
    yield c
    c.srv.shutdown()
    c.srv.server_close()


JSON = {"Content-Type": "application/json"}


def events(text):
    out = []
    for block in text.strip().split("\n\n"):
        name, data = block.split("\n", 1)
        out.append((name[len("event: "):], json.loads(data[len("data: "):])))
    return out


def test_state_endpoint_shape(ctx):
    status, body = ctx.req("GET", "/api/state")
    d = json.loads(body)
    assert status == 200 and set(d) >= {"date", "mode", "cap", "notice", "prompts", "columns", "busy"}
    assert set(d["columns"]) == {"none", "full"} and d["prompts"]["script"][0] == T1


def test_turn_sse_event_order(ctx):
    status, body = ctx.req("POST", "/api/turn", {"text": T1})
    ev = events(body)
    names = [n for n, _ in ev]
    assert status == 200 and names[-2:] == ["snapshot", "done"] and set(names[:-2]) == {"delta"}
    for col in ("none", "full"):
        assert "".join(d["text"] for n, d in ev if n == "delta" and d["column"] == col).startswith("A reply")
    assert sum(1 for n in names if n == "delta") > 2  # chunked
    assert ev[-2][1]["columns"]["full"]["entries"]["facts"]


def test_non_local_host_rejected_403(ctx):
    assert ctx.req("GET", "/api/state", headers={"Host": "evil.example:80"})[0] == 403
    assert ctx.req("POST", "/api/turn", {"text": "x"}, headers={"Host": "evil.example"})[0] == 403
    assert ctx.req("GET", "/api/state", headers={"Host": f"localhost:{ctx.port}"})[0] == 200


def test_oversized_body_400(ctx):
    status, body = ctx.req("POST", "/api/turn", raw="x" * 70000)
    assert status == 400 and "error" in json.loads(body)


def test_malformed_json_400(ctx):
    for raw in ("{nope", "[1]"):
        status, body = ctx.req("POST", "/api/forget", raw=raw, headers=JSON)
        assert status == 400 and "Traceback" not in body
    assert ctx.req("POST", "/api/turn", {"text": 5})[0] == 400


def test_path_traversal_blocked(ctx, tmp_path):
    assert ctx.req("GET", "/")[0] == 200
    for p in ("/static/../secret.txt", "/static/%2e%2e/secret.txt", "/static/%2e%2e%2fsecret.txt",
              "/static//etc/passwd", "/static/nope.txt"):
        assert ctx.req("GET", p)[0] == 404
    (ctx.static / "link.txt").symlink_to(tmp_path / "secret.txt")
    status, body = ctx.req("GET", "/static/link.txt")
    assert status == 404 and "top secret" not in body


def test_forget_unknown_404_and_known_200(ctx):
    ctx.req("POST", "/api/turn", {"text": T1})
    fid = ctx.session.snapshot()["columns"]["full"]["entries"]["facts"][0]["id"]
    assert ctx.req("POST", "/api/forget", {"column": "full", "entry_id": "nope"})[0] == 404
    assert ctx.req("POST", "/api/forget", {"column": "full", "entry_id": fid})[0] == 200
    assert ctx.req("POST", "/api/forget", {"column": "full", "entry_id": fid})[0] == 404
    assert ctx.req("POST", "/api/forget", {"column": "full"})[0] == 400
    assert ctx.req("POST", "/api/advance")[0] == 200 and ctx.req("POST", "/api/reflect")[0] == 200


def test_error_event_never_contains_the_key(paths, tmp_path, monkeypatch, caplog):
    key = "hunter2-plainkey"  # does not look like an sk- token, so only the exact-secret masking can catch it
    monkeypatch.setenv("OPENAI_API_KEY", key)

    def leaky(model, messages):
        raise RuntimeError(f"boom {key} Bearer abcdefghijklmnop")

    c = Ctx(paths, tmp_path, leaky)
    try:
        with caplog.at_level(logging.DEBUG):
            status, body = c.req("POST", "/api/turn", {"text": T1})
            _, state = c.req("GET", "/api/state")
            s404, b404 = c.req("GET", f"/static/{key}")
            c.req("GET", f"/static/{key}?q={key}")
        assert status == 200 and "error" in body and s404 == 404
        for text in (body, state, b404, caplog.text):
            assert key not in text and "abcdefghijklmnop" not in text
        assert "[redacted]" in caplog.text  # the request line was logged, masked
    finally:
        c.srv.shutdown()
        c.srv.server_close()


def test_cross_origin_post_refused_and_content_type_checked(ctx):
    ctx.req("POST", "/api/turn", {"text": T1})
    evil = {"Origin": "http://evil.example"}
    assert ctx.req("POST", "/api/mode", {"mode": "replay"}, headers=evil)[0] == 403
    assert ctx.session.snapshot()["mode"] == "live"
    assert ctx.req("POST", "/api/wipe", headers=evil)[0] == 403
    assert ctx.session.snapshot()["columns"]["full"]["entries"]["facts"]
    assert ctx.req("POST", "/api/mode", raw='{"mode": "replay"}', headers={"Content-Type": "text/plain"})[0] == 415
    ok = {"Origin": f"http://127.0.0.1:{ctx.port}", "Content-Type": "application/json; charset=utf-8"}
    assert ctx.req("POST", "/api/mode", {"mode": "replay"}, headers=ok)[0] == 200
    assert ctx.req("POST", "/api/advance", headers={"Origin": f"http://localhost:{ctx.port}"})[0] == 403  # Host differs


def test_mode_switch_and_notice(ctx):
    ctx.req("POST", "/api/turn", {"text": T1})
    status, body = ctx.req("POST", "/api/mode", {"mode": "replay"})
    d = json.loads(body)
    assert status == 200 and d["mode"] == "replay"
    assert ctx.req("POST", "/api/mode", {"mode": "bogus"})[0] == 400
    assert json.loads(ctx.req("POST", "/api/mode", {"mode": "live"})[1])["mode"] == "live"
    assert ctx.req("POST", "/api/reset")[0] == 200 and ctx.req("POST", "/api/wipe")[0] == 200
    assert ctx.req("POST", "/api/nowhere")[0] == 404


def test_failover_notice_is_a_recovered_error_event(paths, tmp_path):
    def down(model, messages):
        raise OSError("network down")

    c = Ctx(paths, tmp_path, down)
    try:
        ev = events(c.req("POST", "/api/turn", {"text": T1})[1])
        rec = [d for n, d in ev if n == "error" and d.get("recovered")]
        assert rec and "switched to replay" in rec[0]["message"] and ev[-1][0] == "done"
    finally:
        c.srv.shutdown()
        c.srv.server_close()
