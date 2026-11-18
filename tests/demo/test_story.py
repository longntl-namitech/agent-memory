import json
from pathlib import Path

import pytest

from agent_memory.demo.paths import DEFAULT_ROOT, DemoPaths
from agent_memory.demo.script import PROMPTS, SECOND_ACT, estimate_tokens, run_script
from agent_memory.demo.session import Session

CONFIGS = Path(__file__).resolve().parents[2] / "configs" / "demo"


def fake_model(calls=None):
    """Answers only from the MEMORY block of the prompt; writes entries from what the user said."""
    def transport(model, messages):
        if calls is not None:
            calls.append(1)
        sys, user = messages[0]["content"], messages[-1]["content"]
        if messages[0]["role"] == "system" and "personal assistant" in sys:
            mem = sys.split("## MEMORY\n", 1)[1]
            todo = [{"action": "add", "text": "call the dentist"}] if "dentist" in user else []
            if user.startswith("Where do I live"):
                city = "Hanoi" if "Hanoi" in mem else "Ho Chi Minh City" if "Ho Chi Minh" in mem else None
                item = "call the dentist" if "call the dentist" in mem else None
                reply = f"You live in {city} and your list has: {item}." if city else "I don't know."
            else:
                reply = "Noted."
            return json.dumps({"reply": reply, "todo": todo}), 10, 5
        if "memory writer" in user:
            said = user.split("Chat turn:")[1].split("Assistant:")[0]  # the prompt preamble has an example diet line
            if "Hanoi" in said:
                e = [{"kind": "fact", "key": "city", "text": "Lives in Hanoi", "importance": 7}]
            elif "Ho Chi Minh" in said:
                e = [{"kind": "fact", "key": "name", "text": "Name is An", "importance": 7},
                     {"kind": "fact", "key": "city", "text": "Lives in Ho Chi Minh City", "importance": 7}]
            elif "diet" in said:
                e = [{"kind": "log", "key": "", "text": "On a diet this week", "importance": 4}]
            else:
                e = []
            return json.dumps({"entries": e}), 10, 5
        raise AssertionError(user)
    return transport


def embed(model, texts):
    return [[float(len(t)), 1.0] for t in texts]


@pytest.fixture
def paths(tmp_path):
    p = DemoPaths(DEFAULT_ROOT / f"test-{tmp_path.name}")
    yield p
    p.wipe()
    if p.root.is_dir():
        p.root.rmdir()


def make(paths, mode="live", transport=None):
    return Session(paths, mode=mode, max_tokens=100_000, base_url="http://x", model="m", config_dir=CONFIGS,
                   transport=transport or fake_model(), embed_transport=embed)


def test_story_end_to_end(paths):
    s = make(paths)
    s.turn(PROMPTS[0])
    s.turn(PROMPTS[1])
    full = s.snapshot()["columns"]["full"]["entries"]["facts"]
    (city,) = [f for f in full if f["key"] == "city"]
    assert city["text"] == "Lives in Hanoi" and city["replaced_from"] == "Lives in Ho Chi Minh City"
    out = s.turn(PROMPTS[2])
    assert "Hanoi" in out["full"].reply and "call the dentist" in out["full"].reply
    assert "don't know" in out["none"].reply
    none = s.snapshot()["columns"]["none"]
    assert none["entries"] == {"rules": [], "facts": [], "log": []} and none["todos"] == []


def test_warmup_then_replay_makes_zero_provider_calls(paths):
    warm = make(paths, mode="warmup")
    run_script(warm)
    replies = [warm.snapshot()["columns"]["full"]["recalled"]]
    calls = []
    s = make(paths, mode="replay", transport=fake_model(calls))
    outs = []
    for t in PROMPTS:
        outs.append(s.turn(t))
    assert calls == []
    assert all(o[c].error is None for o in outs for c in o)
    assert "Hanoi" in outs[2]["full"].reply and "don't know" in outs[2]["none"].reply
    assert s.snapshot()["columns"]["full"]["recalled"] == replies[0]


def test_second_act_log_expires_after_seven_advances(paths):
    s = make(paths)
    run_script(s, include_second_act=True)
    assert [e["text"] for e in s.snapshot()["columns"]["full"]["entries"]["log"]] == ["On a diet this week"]
    for _ in range(7):
        s.advance()
    c = s.snapshot()["columns"]["full"]
    assert c["entries"]["log"] == [] and c["entries"]["facts"] and c["todos"]


def test_estimate_tokens():
    assert estimate_tokens(True) > estimate_tokens() > 0
    assert SECOND_ACT
