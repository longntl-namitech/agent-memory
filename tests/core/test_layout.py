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


def test_archived_log_hidden(tmp_path):
    s = Store(tmp_path)
    s.add(mk("l1", kind="log", text="gone-line"))
    s.add(mk("l2", kind="log", text="kept-line"))
    s.archive("l1")
    assert [e.id for e in s.log()] == ["l2"]
    md = s.render_markdown()
    assert "gone-line" not in md and "kept-line" in md


def test_upsert_requires_key(tmp_path):
    s = Store(tmp_path)
    for bad in (None, "", "  !! "):
        with pytest.raises(ValueError):
            s.upsert_fact(mk("a", key=bad))


def test_upsert_overwrites_fields_keeps_identity(tmp_path):
    s = Store(tmp_path)
    s.upsert_fact(mk("a", key="k", tags=["x"], expires_at=T))
    later = datetime(2026, 2, 1)
    new = mk("b", key="k", text="n", tags=["y"], expires_at=later)
    new.importance, new.last_used_at, new.created_at = 5, later, later
    s.upsert_fact(new)
    (f,) = s.facts()
    assert (f.id, f.created_at) == ("a", T)
    assert (f.text, f.tags, f.importance, f.expires_at, f.last_used_at) == ("n", ["y"], 5, later, later)


def test_archived_rule_frees_slot(tmp_path):
    s = Store(tmp_path)
    for i in range(20):
        s.add(mk(f"r{i}", kind="rule"))
    s.archive("r0")
    s.add(mk("r20", kind="rule"))
    assert len(s.rules()) == 20


def test_facts_filter_by_tag(tmp_path):
    s = Store(tmp_path)
    s.upsert_fact(mk("a", key="k1", tags=["x"]))
    s.upsert_fact(mk("b", key="k2", tags=["y"]))
    assert [e.id for e in s.facts("x")] == ["a"]
    assert len(s.facts()) == 2


def test_all_log_includes_archived(tmp_path):
    s = Store(tmp_path)
    s.add(mk("l1", kind="log"))
    s.add(mk("l2", kind="log"))
    s.archive("l1", T)
    assert [e.id for e in s.all_log()] == ["l1", "l2"]
    assert [e.id for e in s.log()] == ["l2"]
