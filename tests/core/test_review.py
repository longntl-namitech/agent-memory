from datetime import datetime

from agent_memory.cli import main
from agent_memory.core.layout import Entry, Store
from agent_memory.core.review import Reviewer, remove_blocklisted

T = datetime(2026, 1, 5, 9)


def rule(id, text, created=T):
    return Entry(id=id, kind="rule", key=None, tags=["global"], text=text, importance=5,
                 created_at=created, last_used_at=created, expires_at=None, status="active")


def test_reviewer_matches_edited_rule(tmp_path):
    s = Store(tmp_path)
    s.add(rule("planted", "  NEVER   mention\nPrices in follow-ups, let the lead ask first."))
    s.add(rule("keep", "Keep every email under 90 words."))
    assert remove_blocklisted(s, ["never mention prices"]) == ["planted"]
    assert [r.id for r in s.rules()] == ["keep"]
    assert remove_blocklisted(s, ["Never  Mention Prices"]) == []  # nothing left to remove


def test_reviewer_records_archive_time(tmp_path):
    s = Store(tmp_path)
    s.add(rule("planted", "Never mention prices."))
    monday = datetime(2026, 1, 19, 8)
    assert Reviewer(["never mention prices"]).review(s, monday) == ["planted"]
    (e,) = [e for e in Store(tmp_path).all_rules() if e.id == "planted"]
    assert (e.status, e.archived_at) == ("archived", monday)


def test_review_diff_cli(tmp_path, capsys):
    s = Store(tmp_path)
    s.add(rule("old", "Use the old booking link.", datetime(2026, 1, 5)))
    s.add(rule("kept", "Keep every email under 90 words.", datetime(2026, 1, 5)))
    s.add(rule("new", "Use the new booking link.", datetime(2026, 1, 14)))
    s.add(rule("late", "Added after the window.", datetime(2026, 2, 1)))
    s.archive("old", datetime(2026, 1, 13))
    code = main(["review", "diff", "--store", str(tmp_path), "--from", "2026-01-06", "--to", "2026-01-20"])
    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert out == [
        "--- RULES at 2026-01-06T00:00:00",
        "+++ RULES at 2026-01-20T00:00:00",
        "- Use the old booking link.",
        "+ Use the new booking link.",
    ]
