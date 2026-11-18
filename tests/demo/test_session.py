import json
import threading
from pathlib import Path

import pytest

from agent_memory.demo.paths import DEFAULT_ROOT, DemoPaths
from agent_memory.demo.session import Session

CONFIGS = Path(__file__).resolve().parents[2] / "configs" / "demo"
T1 = "I'm An, I live in Ho Chi Minh City. Remind me to call the dentist on Friday."
T2 = "I just moved to Hanoi."
T3 = "This week I'm on a diet."


def make_transport(fail_on=None, barrier=None):
    def transport(model, messages):
        sys, user = messages[0]["content"], messages[-1]["content"]
        if "personal assistant" in sys and messages[0]["role"] == "system":
            if barrier is not None:
                barrier.wait(5)  # both columns must be inside their answer call at once
            if fail_on and fail_on in user:
                raise OSError("network down")
            todo = [{"action": "add", "text": "call the dentist"}] if "dentist" in user else []
            return json.dumps({"reply": f"re: {user}", "todo": todo}), 10, 5
        if "memory writer" in user:
            if "Hanoi" in user:
                e = [{"kind": "fact", "key": "city", "text": "Lives in Hanoi", "importance": 7}]
            elif "Ho Chi Minh" in user:
                e = [{"kind": "fact", "key": "city", "text": "Lives in Ho Chi Minh City", "importance": 7}]
            elif "diet" in user:
                e = [{"kind": "log", "key": "", "text": "On a diet this week", "importance": 4}]
            else:
                e = []
            return json.dumps({"entries": e}), 10, 5
        if "weekly reflection" in user:
            return json.dumps({"rules": [{"text": "Keep answers short", "importance": 6, "sources": []}]}), 10, 5
        raise AssertionError(user)
    return transport


def embed(model, texts):
    return [[float(len(t)), 1.0] for t in texts]


@pytest.fixture
def paths(tmp_path):
    return DemoPaths(DEFAULT_ROOT / f"test-{tmp_path.name}")


@pytest.fixture(autouse=True)
def _cleanup(paths):
    yield
    paths.wipe()
    paths.root.rmdir() if paths.root.is_dir() else None


def make(paths, mode="live", transport=None, max_tokens=100_000):
    return Session(paths, mode=mode, max_tokens=max_tokens, base_url="http://x", model="m", config_dir=CONFIGS,
                   transport=transport or make_transport(), embed_transport=embed)


def test_turn_runs_both_columns_concurrently(paths):
    s = make(paths, transport=make_transport(barrier=threading.Barrier(2)))
    out = s.turn(T1)
    assert out["none"].error is None and out["full"].error is None
    assert out["none"].reply == out["full"].reply == f"re: {T1}"


def test_full_column_stores_none_column_stores_nothing(paths):
    s = make(paths)
    s.turn(T1)
    cols = s.snapshot()["columns"]
    assert [e["text"] for e in cols["full"]["entries"]["facts"]] == ["Lives in Ho Chi Minh City"]
    assert all(e["new"] for e in cols["full"]["entries"]["facts"])
    assert [t.text for t in cols["full"]["todos"]] == ["call the dentist"]
    assert cols["none"]["entries"] == {"rules": [], "facts": [], "log": []} and cols["none"]["todos"] == []
    assert cols["none"]["tokens"] > 0 and cols["full"]["tokens"] > cols["none"]["tokens"]


def test_fact_update_marks_replaced_from(paths):
    s = make(paths)
    s.turn(T1)
    s.turn(T2)
    (f,) = s.snapshot()["columns"]["full"]["entries"]["facts"]
    assert f["text"] == "Lives in Hanoi" and f["new"] and f["replaced_from"] == "Lives in Ho Chi Minh City"


def test_forget_unknown_returns_false(paths):
    s = make(paths)
    s.turn(T1)
    fid = s.snapshot()["columns"]["full"]["entries"]["facts"][0]["id"]
    assert s.forget("full", "nope") is False and s.forget("bogus", fid) is False
    assert s.forget("full", fid) is True
    assert s.forget("full", fid) is False  # already archived
    assert s.snapshot()["columns"]["full"]["entries"]["facts"] == []


def test_forget_todo_updates_card(paths):
    s = make(paths)
    s.turn(T1)
    (t,) = s.snapshot()["columns"]["full"]["todos"]
    assert s.forget("full", t.key) is True
    assert s.snapshot()["columns"]["full"]["todos"] == []


def test_advance_expires_log_after_seven_days_keeps_facts(paths):
    s = make(paths)
    s.turn(T1)
    s.turn(T3)
    assert len(s.snapshot()["columns"]["full"]["entries"]["log"]) == 1
    for _ in range(6):
        s.advance()
    assert len(s.snapshot()["columns"]["full"]["entries"]["log"]) == 1
    s.advance()
    snap = s.snapshot()
    assert snap["columns"]["full"]["entries"]["log"] == []
    assert len(snap["columns"]["full"]["entries"]["facts"]) == 1 and len(snap["columns"]["full"]["todos"]) == 1
    assert snap["date"] == "Mon 2026-01-12"


def test_reflect_writes_a_rule(paths):
    s = make(paths)
    s.turn(T3)
    s.reflect()
    rules = s.snapshot()["columns"]["full"]["entries"]["rules"]
    assert [r["text"] for r in rules] == ["Keep answers short"] and rules[0]["new"]


def test_replay_miss_is_per_column_error(paths):
    s = make(paths, mode="replay")
    out = s.turn("free typed")
    for c in ("none", "full"):
        assert out[c].reply is None and out[c].error == "Not in the rehearsed script, replay cannot answer"
    assert s.snapshot()["columns"]["full"]["error"] == out["full"].error


def test_one_column_budget_exhausted_other_continues(paths):
    s = make(paths)
    s.cols["none"].budget.max_tokens = 1
    out = s.turn(T1)
    assert out["none"].error == "Token cap reached" and out["none"].reply is None
    assert out["full"].error is None and out["full"].reply
    assert s.snapshot()["columns"]["full"]["entries"]["facts"]
    assert s.turn(T2)["full"].error is None  # the session stays usable


def test_failover_replays_user_turns_from_rehearsed_cache(paths):
    warm = make(paths, mode="warmup")
    warm.turn(T1)
    warm.turn(T2)
    s = make(paths, transport=make_transport(fail_on="Hanoi"))
    assert s.turn(T1)["full"].error is None
    out = s.turn(T2)  # live call raises OSError
    snap = s.snapshot()
    assert snap["mode"] == "replay"
    assert snap["notice"] == "Live call failed, switched to replay, replaying your last 2 turns"
    assert out["full"].error is None and out["full"].reply == f"re: {T2}"
    assert [e["text"] for e in snap["columns"]["full"]["entries"]["facts"]] == ["Lives in Hanoi"]
    assert s.turn("free typed")["full"].error == "Not in the rehearsed script, replay cannot answer"


def test_reset_restores_initial_state(paths):
    s = make(paths)
    s.turn(T1)
    s.advance()
    s.reset()
    snap = s.snapshot()
    assert snap["date"] == "Mon 2026-01-05" and snap["notice"] is None
    assert all(c["entries"] == {"rules": [], "facts": [], "log": []} and c["tokens"] == 0
               for c in snap["columns"].values())
    assert snap["prompts"]["script"][0] == T1


def test_wipe_clears_data_dir(paths):
    s = make(paths)
    s.turn(T1)
    assert any(paths.llm_live.iterdir())
    s.wipe()
    assert not any(paths.llm_live.iterdir()) and not any(paths.embeddings.iterdir())
    assert s.snapshot()["columns"]["full"]["entries"]["facts"] == []


def test_snapshot_never_waits_for_a_running_turn(paths):
    gate, inside = threading.Event(), threading.Event()
    inner = make_transport()

    def slow(model, messages):
        inside.set()
        gate.wait(5)
        return inner(model, messages)

    s = make(paths, transport=slow)
    assert s.snapshot()["busy"] is False
    t = threading.Thread(target=s.turn, args=(T1,))
    t.start()
    assert inside.wait(5)
    got = []
    r = threading.Thread(target=lambda: got.append(s.snapshot()))
    r.start()
    r.join(1)
    assert not r.is_alive() and got[0]["busy"] is True
    assert got[0]["columns"]["full"]["entries"]["facts"] == []  # last completed state
    gate.set()
    t.join(5)
    snap = s.snapshot()
    assert snap["busy"] is False and snap["columns"]["full"]["entries"]["facts"]


def test_secrets_never_reach_error_notice_or_snapshot(paths, monkeypatch):
    k1, k2 = "sk-fakeOPENAIkey1234567890", "embed-secret-ABCDEF"
    monkeypatch.setenv("OPENAI_API_KEY", k1)
    monkeypatch.setenv("EMBEDDING_API_KEY", k2)

    def leaky(model, messages):
        raise RuntimeError(f"boom key={k1} emb={k2} Authorization: Bearer tok_abcdefghijkl")

    s = make(paths, transport=leaky)
    out = s.turn(T1)  # RuntimeError is not a live failure: stays a per-column error
    blob = json.dumps(s.snapshot(), default=lambda o: o.__dict__)
    for text in (out["none"].error, out["full"].error, blob):
        assert k1 not in text and k2 not in text and "tok_abcdefghijkl" not in text
    assert "[redacted]" in out["full"].error and s.snapshot()["mode"] == "live"

    def leaky_net(model, messages):
        raise OSError(f"connect failed {k1} Bearer tok_abcdefghijkl")

    s2 = make(paths, transport=leaky_net)
    s2.turn(T1)  # live failure: failover, replay miss errors
    blob = json.dumps(s2.snapshot(), default=lambda o: o.__dict__)
    assert k1 not in blob and k2 not in blob and "tok_abcdefghijkl" not in blob and s2.snapshot()["notice"]

    s3 = make(paths)  # _guard path: reflect raises with secrets in the text
    s3.turn(T3)
    s3.cols["full"].assistant.memory.reflectors[0].reflect = lambda *a: (_ for _ in ()).throw(RuntimeError(k1 + k2))
    s3.reflect()
    err = s3.snapshot()["columns"]["full"]["error"]
    assert err and k1 not in err and k2 not in err


def test_live_after_warmup_still_calls_transport_and_writes_live_cache(paths):
    make(paths, mode="warmup").turn(T1)
    calls = []
    inner = make_transport()
    s = make(paths, transport=lambda m, msgs: (calls.append(1), inner(m, msgs))[1])
    s.turn(T1)
    assert calls and any(paths.llm_live.iterdir())


def test_set_mode_keeps_budgets_both_ways(paths):
    make(paths, mode="warmup").turn(T1)
    s = make(paths)
    s.turn(T1)
    used = {c: v["tokens"] for c, v in s.snapshot()["columns"].items()}
    assert used["full"] > 0
    s.set_mode("replay")
    assert {c: v["tokens"] for c, v in s.snapshot()["columns"].items()} == used
    s.set_mode("live")
    assert {c: v["tokens"] for c, v in s.snapshot()["columns"].items()} == used


def test_failover_resets_clock_and_handles_one_failing_column(paths):
    warm = make(paths, mode="warmup")
    warm.turn(T1)
    warm.turn(T2)
    # only the full column's prompt carries remembered text, so only it raises
    inner = make_transport()

    def one_col(model, messages):
        if "Lives in" in messages[0]["content"]:
            raise OSError("down")
        return inner(model, messages)

    s = make(paths, transport=one_col)
    s.turn(T1)
    s.advance()
    assert s.snapshot()["date"] == "Tue 2026-01-06"
    out = s.turn(T2)
    snap = s.snapshot()
    assert snap["mode"] == "replay" and snap["date"] == "Mon 2026-01-05"
    assert out["none"].error is None and out["full"].error is None


def test_new_and_replaced_flags_clear_after_next_action(paths):
    s = make(paths)
    s.turn(T1)
    s.turn(T2)
    s.advance()
    (f,) = s.snapshot()["columns"]["full"]["entries"]["facts"]
    assert f["new"] is False and f["replaced_from"] is None
