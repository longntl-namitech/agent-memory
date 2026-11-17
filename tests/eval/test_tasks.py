import json
from pathlib import Path

from agent_memory.core.eval.tasks import generate, write_jsonl

SIM = Path(__file__).resolve().parents[2] / "data" / "simulation"


def test_deterministic(tmp_path):
    write_jsonl(generate(7), tmp_path / "a.jsonl")
    write_jsonl(generate(7), tmp_path / "b.jsonl")
    assert (tmp_path / "a.jsonl").read_bytes() == (tmp_path / "b.jsonl").read_bytes()


def test_shape():
    tasks = generate()
    assert len(tasks) == 40
    for week in (1, 2, 3, 4):
        assert sum(t.week == week for t in tasks) == 10
    for t in tasks:
        for key in ("name", "company", "price", "deal_status"):
            assert t.lead.get(key) not in (None, "")


def test_committed_file_matches_generator(tmp_path):
    write_jsonl(generate(7), tmp_path / "t.jsonl")
    assert (tmp_path / "t.jsonl").read_bytes() == (SIM / "tasks.jsonl").read_bytes()


def test_booking_link_correction_at_task_20():
    rows = {r["id"]: r for r in json.loads((SIM / "corrections.json").read_text())}
    assert set(rows) == {"vat", "sign_off", "under_90_words", "booking_link", "closed_deals"}
    assert rows["booking_link"]["active_from_task"] == 20  # start of week 3 (ids 0-39)
    assert generate()[20].week == 3 and generate()[19].week == 2
    block = json.loads((SIM / "blocklist.json").read_text())
    assert block["plant_at_task"] == 10 and generate()[10].week == 2
    assert block["marker"] in block["planted_rule"].lower()


def test_closed_deals_exist():
    tasks = generate()
    start = {r["id"]: r for r in json.loads((SIM / "corrections.json").read_text())}["closed_deals"]["active_from_task"]
    assert any(t.lead["deal_status"] == "closed" for t in tasks[start:])
