from dataclasses import dataclass

from agent_memory.core.eval.report import write_result

KW = dict(
    eval_name="simulation", config="memory", model="gpt-5.4-nano", embedding_model="emb-small",
    subset="40 tasks", seed=7, tokens=12345, metrics={"w1": {"corrections": 3}},
)


def read(tmp_path, **over):
    p = tmp_path / "r.md"
    write_result(p, **{**KW, **over})
    return p.read_text()


def test_header_fields(tmp_path):
    t = read(tmp_path, run_date="2026-11-17")
    for s in ("2026-11-17", "gpt-5.4-nano", "emb-small", "40 tasks", "7", "12345", "corrections"):
        assert s in t
    assert "PARTIAL" not in t
    assert "date: unknown" in read(tmp_path)


def test_hermes_extra_fields(tmp_path):
    t = read(tmp_path, extra={"hermes_version": "v0.9.1", "runs": 3, "spread": "+-2"})
    assert "v0.9.1" in t and "runs: 3" in t and "spread: +-2" in t


def test_partial_marker(tmp_path):
    t = read(tmp_path, extra={"partial": True, "crashed_tokens": 99})
    assert t.startswith("PARTIAL RESULT")
    assert "crashed_tokens: 99" in t


def test_dataclass_metrics_stable_and_parent_dirs(tmp_path):
    @dataclass
    class M:
        corrections: int

    p = tmp_path / "a" / "b" / "r.md"
    for _ in range(2):
        write_result(p, **{**KW, "metrics": {"w1": M(2)}, "extra": {"b": 1, "a": 2}})
    first = p.read_bytes()
    write_result(p, **{**KW, "metrics": {"w1": M(2)}, "extra": {"a": 2, "b": 1}})
    assert p.read_bytes() == first
    assert b"corrections: 2" in first and b"\xe2\x80\x94" not in first
    assert list(p.parent.iterdir()) == [p]
