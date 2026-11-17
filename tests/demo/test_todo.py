from datetime import datetime

from agent_memory.core.layout import Entry, Store
from agent_memory.demo.todo import apply_actions, parse_reply, todos

NOW = datetime(2026, 1, 5, 9)
LATER = datetime(2026, 1, 5, 10)


def add(store, text):
    return apply_actions(store, [{"action": "add", "text": text}], NOW)


def test_parse_fenced_json():
    raw = 'Sure!\n```json\n{"reply": "ok", "todo": [{"action": "add", "text": "buy milk"}]}\n```'
    assert parse_reply(raw) == ("ok", [{"action": "add", "text": "buy milk"}])


def test_parse_invalid_returns_raw():
    assert parse_reply("  not json ") == ("not json", [])
    assert parse_reply('{"reply": 3}') == ('{"reply": 3}', [])


def test_parse_drops_malformed_actions():
    raw = ('{"reply": "r", "todo": [{"action": "nope", "text": "x"}, {"action": "add", "text": ""}, '
           '"junk", {"action": "done", "text": "y"}]}')
    assert parse_reply(raw) == ("r", [{"action": "done", "text": "y"}])
    assert parse_reply('{"reply": "r", "todo": "x"}') == ("r", [])


def test_add_then_done_keeps_one_item(tmp_path):
    s = Store(tmp_path)
    assert add(s, "Buy milk") == ["todo-buy-milk"]
    eid = s.facts()[0].id
    assert apply_actions(s, [{"action": "done", "text": "Buy milk"}], LATER) == ["todo-buy-milk"]
    assert len(s.facts()) == 1 and s.facts()[0].id == eid
    assert [(t.text, t.done) for t in todos(s)] == [("Buy milk", True)]


def test_remove_archives_and_card_updates(tmp_path):
    s = Store(tmp_path)
    add(s, "Buy milk")
    eid = s.facts()[0].id
    assert apply_actions(s, [{"action": "remove", "text": "buy milk"}], LATER) == ["todo-buy-milk"]
    assert todos(s) == [] and s.facts() == []
    assert any(e.id == eid and e.status == "archived" for es in s._entries.values() for e in es)


def test_done_matches_slightly_different_wording_when_unique(tmp_path):
    s = Store(tmp_path)
    add(s, "Buy milk")
    add(s, "Call mom")
    assert apply_actions(s, [{"action": "done", "text": "milk"}], LATER) == ["todo-buy-milk"]
    assert [t.done for t in todos(s)] == [True, False]


def test_ambiguous_match_is_ignored(tmp_path):
    s = Store(tmp_path)
    add(s, "Buy milk")
    add(s, "Buy bread")
    assert apply_actions(s, [{"action": "done", "text": "buy"}, {"action": "remove", "text": "buy"}], LATER) == []
    assert [t.done for t in todos(s)] == [False, False]


def test_unknown_action_and_unknown_item_ignored(tmp_path):
    s = Store(tmp_path)
    add(s, "Buy milk")
    acts = [{"action": "explode", "text": "x"}, {"action": "done", "text": "walk dog"},
            {"action": "remove", "text": "walk dog"}]
    assert apply_actions(s, acts, LATER) == []
    assert [(t.text, t.done) for t in todos(s)] == [("Buy milk", False)]


def test_todos_ignore_non_todo_facts(tmp_path):
    s = Store(tmp_path)
    s.upsert_fact(Entry(id="fact-city-0", kind="fact", key="city", tags=["global"], text="Hanoi", importance=5,
                        created_at=NOW, last_used_at=NOW, expires_at=None, status="active"))
    add(s, "Buy milk")
    assert [t.text for t in todos(s)] == ["Buy milk"]
