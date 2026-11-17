from datetime import datetime

import pytest

from agent_memory.core.layout import Entry, RulesFull, Store, slug

T = datetime(2026, 1, 1, 9, 0, 0)


def mk(id, kind="fact", key=None, text="t", status="active", **kw):
    return Entry(id=id, kind=kind, key=key, tags=kw.get("tags", []), text=text,
                 importance=3, created_at=T, last_used_at=T,
                 expires_at=kw.get("expires_at"), status=status)


def test_one_line_per_fact_key(tmp_path):
    s = Store(tmp_path)
    s.upsert_fact(mk("a", key="booking-link", text="old"))
    s.upsert_fact(mk("b", key="booking-link", text="new"))
    facts = s.facts()
    assert len(facts) == 1 and facts[0].text == "new"


def test_key_normalised(tmp_path):
    assert slug("Booking Link") == slug("booking-link") == "booking-link"
    s = Store(tmp_path)
    s.upsert_fact(mk("a", key="Booking Link", text="old"))
    s.upsert_fact(mk("b", key="booking-link", text="new"))
    assert len(s.facts()) == 1


def test_rules_cap_20(tmp_path):
    s = Store(tmp_path)
    for i in range(20):
        s.add(mk(f"r{i}", kind="rule"))
    with pytest.raises(RulesFull):
        s.add(mk("r20", kind="rule"))


def test_roundtrip_jsonl(tmp_path):
    s = Store(tmp_path)
    s.add(mk("r1", kind="rule", text="be nice"))
    s.upsert_fact(mk("f1", key="k", tags=["x"], expires_at=T))
    s.add(mk("l1", kind="log"))
    s.archive("l1")
    s2 = Store(tmp_path)
    assert s2.rules() == s.rules()
    assert s2.facts() == s.facts()
    assert s2.log() == s.log()
    assert "2026-01-01T09:00:00" in (tmp_path / "facts.jsonl").read_text()


def test_markdown_has_three_sections(tmp_path):
    s = Store(tmp_path)
    s.add(mk("r1", kind="rule", text="be nice"))
    md = s.render_markdown()
    for h in ("RULES", "FACTS", "LOG"):
        assert h in md
    assert "be nice" in md
    assert (tmp_path / "MEMORY.md").read_text() == md
