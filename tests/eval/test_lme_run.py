import json
from datetime import datetime
from pathlib import Path

import pytest

import agent_memory.methods  # noqa: F401  registers the stages
from agent_memory import cli
from agent_memory.core import registry
from agent_memory.core.clock import SimClock
from agent_memory.core.config import Config, build, load_config
from agent_memory.core.eval import longmemeval as lme
from agent_memory.core.eval.estimate import estimate
from agent_memory.core.eval.judge import judge
from agent_memory.core.eval.lme_run import LMEAborted, check_lme_config, parse_date, run_longmemeval
from agent_memory.core.layout import Store
from agent_memory.core.llm import LLMClient, TokenBudget
from agent_memory.core.registry import ConfigError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "longmemeval_mini.json"
LME_CONFIGS = ["lme_baseline_full_context", "lme_baseline_naive_rag", "lme_b1_write_filter",
               "lme_b2_coala_stores", "lme_b3_scored_recall", "lme_full"]


class ToyEmbedder:
    name = "toy"

    def embed(self, texts):
        import numpy as np
        return np.array([[len(t), 1.0] for t in texts])


def reply_for(messages) -> str:
    text = messages[-1]["content"]
    if "write filter" in text:
        return '{"kind": "fact", "key": "pet", "importance": 5, "text": "the user has a dog"}'
    if "Answer yes or no only" in text:
        return "yes"
    return "A0"


def counting_llm(tmp_path, calls=None, budget=None, cache="llm"):
    calls = calls if calls is not None else []

    def transport(model, messages):
        calls.append(messages[-1]["content"])
        return reply_for(messages), 10, 5

    return LLMClient("stub", "stub-model", budget or TokenBudget(None), tmp_path / cache, transport=transport)


def row(qid="q1", qtype="single-session-user", dates=("2023/05/01 (Mon) 09:00",), qdate="2023/05/30 (Tue) 10:00"):
    return {"question_id": qid, "question_type": qtype, "question": "What pet?", "answer": "A0",
            "question_date": qdate, "haystack_dates": list(dates),
            "haystack_session_ids": [f"s{i}" for i in range(len(dates))],
            "haystack_sessions": [[{"role": "user", "content": f"{qid} session {i}"},
                                   {"role": "assistant", "content": "ok"}] for i in range(len(dates))]}


class RecMemory:
    """A whole memory that records every call."""

    log: list = []

    def __init__(self, store, llm=None, **_deps):
        self.store = store

    def write(self, event, now):
        RecMemory.log.append(("write", event, now))

    def recall(self, task, now):
        RecMemory.log.append(("recall", task, now))
        return ""

    def reflect(self, now):
        RecMemory.log.append(("reflect", now))

    def forget(self, now):
        RecMemory.log.append(("forget", now))


# --- date parser ---

def test_parse_date_dataset_format_and_variants():
    assert parse_date("2023/05/20 (Sat) 02:21") == datetime(2023, 5, 20, 2, 21)
    assert parse_date("  2023/05/20  (Sat)  02:21 ") == datetime(2023, 5, 20, 2, 21)
    assert parse_date("2023/05/20") == datetime(2023, 5, 20)
    assert parse_date("2023-05-20 02:21") == datetime(2023, 5, 20, 2, 21)


def test_parse_date_unparseable_is_clear():
    with pytest.raises(ValueError, match="unparseable LongMemEval date.*yesterday"):
        parse_date("yesterday")


# --- judge ---

def judge_llm(tmp_path, reply, seen=None):
    def transport(model, messages):
        if seen is not None:
            seen.append(messages[-1]["content"])
        return reply, 1, 1
    return LLMClient("stub", "stub-model", TokenBudget(None), tmp_path / reply.replace(" ", "_")[:20],
                     transport=transport)


@pytest.mark.parametrize("reply,expected", [("yes", True), ("Yes.", True), ("YES, it is", True),
                                            ("no", False), ("", False), ("maybe yes", False)])
def test_judge_parses_first_token(tmp_path, reply, expected):
    assert judge(judge_llm(tmp_path, reply), "Q?", "gold", "answer", "multi-session") is expected


def test_judge_prompt_variants(tmp_path):
    seen = []
    llm = judge_llm(tmp_path, "yes", seen)
    for qtype in ("abstention", "temporal-reasoning", "knowledge-update", "single-session-preference",
                  "multi-session"):
        judge(llm, f"Q {qtype}?", "gold", "answer", qtype)
    abst, temporal, update, pref, default = seen
    assert "unanswerable" in abst
    assert "off-by-one" in temporal
    assert "updated answer" in update
    assert "Rubric" in pref
    assert "Correct Answer: gold" in default and "Model Response: answer" in default


# --- runner ---

def test_session_timestamps_drive_clock(tmp_path, monkeypatch):
    monkeypatch.setitem(registry._REGISTRY, ("memory", "rec_mem"), RecMemory)
    RecMemory.log = []
    dates = ("2023/05/03 (Wed) 12:00", "2023/05/01 (Mon) 09:00", "2023/05/02 (Tue) 08:30")
    clock = SimClock(datetime(2000, 1, 1))
    run_longmemeval(Config(name="rec", memory="rec_mem"), [row(dates=dates)], counting_llm(tmp_path),
                    clock=clock, store_dir=tmp_path / "s")
    writes = [(e, now) for kind, e, now in (x for x in RecMemory.log if x[0] == "write")]
    assert [now for _, now in writes] == [datetime(2023, 5, 1, 9), datetime(2023, 5, 2, 8, 30),
                                          datetime(2023, 5, 3, 12)]
    assert [e.text for e, _ in writes] == ["user: q1 session 1\nassistant: ok", "user: q1 session 2\nassistant: ok",
                                           "user: q1 session 0\nassistant: ok"]
    assert all(e.kind == "session" and e.tags == [] and e.source == "longmemeval" for e, _ in writes)
    recall = [x for x in RecMemory.log if x[0] == "recall"]
    assert len(recall) == 1 and recall[0][2] == datetime(2023, 5, 30, 10)
    task = recall[0][1]
    assert task.lead == {"question": "What pet?"} and task.tags == [] and task.wants_log is True
    assert clock.now() == datetime(2023, 5, 30, 10)
    assert not [x for x in RecMemory.log if x[0] in ("reflect", "forget")]


def test_cadence_stages_do_not_run(tmp_path, monkeypatch):
    calls = []

    def recorder(name):
        class Rec:
            def __init__(self, *a, **k):
                calls.append((name, "init"))

            def reflect(self, *a):
                calls.append((name, "reflect"))

            def retry(self, *a):
                calls.append((name, "retry"))

            def forget(self, *a):
                calls.append((name, "forget"))
        return Rec

    for kind, name in [("reflect", "reflect"), ("retry", "reflexion"), ("forget", "expire"), ("forget", "archive")]:
        monkeypatch.setitem(registry._REGISTRY, (kind, name), recorder(name))
    for reflect, forget in [(["reflect"], []), (["reflexion"], []), ([], ["overwrite", "expire"]),
                            ([], ["archive"]), (["reflect", "reflexion"], ["overwrite", "expire", "archive"])]:
        cfg = Config(name="bad", write="write_filter", reflect=reflect, forget=forget)
        with pytest.raises(ConfigError, match="longmemeval"):
            run_longmemeval(cfg, [row()], counting_llm(tmp_path), store_dir=tmp_path / "s")
    assert calls == []
    # overwrite alone is allowed and runs
    res = run_longmemeval(Config(name="ok", write="write_filter", forget=["overwrite"]), [row()],
                          counting_llm(tmp_path), store_dir=tmp_path / "ok")
    assert res["total"] == 1 and calls == []


def test_hermes_not_allowed_here(tmp_path):
    with pytest.raises(ConfigError, match="hermes"):
        run_longmemeval(Config(name="hermes_default", agent="hermes"), [row()], counting_llm(tmp_path),
                        store_dir=tmp_path / "s")


def test_ingestion_cached_across_configs(tmp_path):
    rows = [row("q1", dates=("2023/05/01 (Mon) 09:00", "2023/05/02 (Tue) 09:00")), row("q2")]
    calls = []
    llm = counting_llm(tmp_path, calls)
    b1 = load_config(cli.CONFIGS / "lme_b1_write_filter.toml")
    b2 = load_config(cli.CONFIGS / "lme_b2_coala_stores.toml")
    assert b1.write == b2.write == "write_filter" and b1.sort != b2.sort
    run_longmemeval(b1, rows, llm, store_dir=tmp_path / "b1")
    first = sum("write filter" in c for c in calls)
    assert first == 3
    calls.clear()
    run_longmemeval(b2, rows, llm, store_dir=tmp_path / "b2")
    assert sum("write filter" in c for c in calls) == 0


def test_result_aggregates_per_ability_and_tokens(tmp_path):
    rows = json.loads(FIXTURE.read_text())[:6]
    llm = counting_llm(tmp_path, budget=TokenBudget(None))
    llm.budget.used = 100  # tokens are a delta, not the running total
    res = run_longmemeval(Config(name="fc", memory="full_context"), rows, llm, store_dir=tmp_path / "s")
    assert res["config"] == "fc" and res["total"] == 6 and res["correct"] == 6
    assert res["by_ability"]["information extraction"] == {"correct": 3, "total": 3}
    assert res["by_ability"]["abstention"] == {"correct": 1, "total": 1}
    # 6 questions x (answer + judge) x 15 tokens each
    assert res["tokens"] == 6 * 2 * 15


def test_budget_exceeded_raises_with_partial(tmp_path):
    rows = json.loads(FIXTURE.read_text())[:6]
    llm = counting_llm(tmp_path, budget=TokenBudget(50))
    with pytest.raises(LMEAborted) as exc:
        run_longmemeval(Config(name="fc", memory="full_context"), rows, llm, store_dir=tmp_path / "s")
    assert exc.value.completed == 1 and exc.value.result["total"] == 1


def test_every_lme_config_validates(tmp_path):
    names = sorted(p.stem for p in cli.CONFIGS.glob("lme_*.toml"))
    assert names == sorted(LME_CONFIGS)
    for name in names:
        cfg = load_config(cli.CONFIGS / f"{name}.toml")
        assert cfg.name == name and cfg.agent is None
        assert not cfg.reflect and set(cfg.forget) <= {"overwrite"}
        check_lme_config(cfg)
        build(cfg, llm=counting_llm(tmp_path), store=Store(tmp_path / name), embedder=ToyEmbedder())
    full = load_config(cli.CONFIGS / "lme_full.toml")
    assert (full.write, full.sort, full.recall, full.forget) == (
        "write_filter", "coala_stores", "scored_recall", ["overwrite"])


# --- data helpers ---

def test_load_selected_writes_small_file_and_reuses_it(tmp_path):
    cache = tmp_path / "cache"
    with pytest.raises(FileNotFoundError, match="longmemeval_s_cleaned.json.*--download"):
        lme.load_selected(cache, 2, 7)
    downloads = []

    def fake_download(c):
        downloads.append(c)
        c.mkdir(parents=True, exist_ok=True)
        (c / "longmemeval_s_cleaned.json").write_bytes(FIXTURE.read_bytes())
        return c / "longmemeval_s_cleaned.json"

    sel = lme.load_selected(cache, 2, 7, download_fn=fake_download)
    assert len(sel) == 10 and len(downloads) == 1
    assert (cache / "longmemeval_selected_2_7.json").exists()
    (cache / "longmemeval_s_cleaned.json").unlink()  # the selected file is enough afterwards
    assert lme.load_selected(cache, 2, 7) == sel


def test_first_questions_stratified_evenly():
    sel = lme.select_subset(json.loads(FIXTURE.read_text()), per_ability=4)
    sub = lme.first_questions(sel, 8)
    counts = [sum(lme.ability(r) == a for r in sub) for a in lme.ABILITIES]
    assert len(sub) == 8 and counts == [2, 2, 2, 1, 1]
    assert lme.first_questions(sel, 8) == lme.first_questions(list(reversed(sel)), 8)


def test_estimate_honors_question_count():
    assert estimate("longmemeval", ["lme_full"], 8).prompt == 8 * 115_000
    assert estimate("longmemeval", ["lme_full"]).prompt == 50 * 115_000
    assert estimate("longmemeval", ["lme_baseline_full_context"]).prompt == 10 * 115_000
    assert estimate("longmemeval", ["lme_baseline_full_context"], 8).prompt == 8 * 115_000
    assert estimate("longmemeval", ["lme_baseline_full_context"], None, 4).prompt == 4 * 115_000
    assert estimate("simulation", ["full"], 8).prompt == estimate("simulation", ["full"]).prompt


# --- CLI ---

def no_llm(*_a, **_k):
    raise AssertionError("no LLM may be built")


def lme_args(tmp_path, configs, *extra):
    return ["run", "--eval", "longmemeval", "--configs", configs, "--no-estimate-only",
            "--out", str(tmp_path / "stores"), "--results-dir", str(tmp_path / "results"), *extra]


def seed_cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "longmemeval_s_cleaned.json").write_bytes(FIXTURE.read_bytes())
    monkeypatch.setattr(cli, "LME_CACHE", cache)
    return cache


def test_cli_lme_estimate_with_questions(monkeypatch, capsys):
    monkeypatch.setattr(cli, "make_llm", no_llm)
    assert cli.main(["run", "--eval", "longmemeval", "--configs", "lme_full", "--questions", "8"]) == 0
    out = capsys.readouterr().out
    assert "total: 920000" in out and "estimate only" in out


def test_cli_lme_refuses_full_set_without_confirm(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "make_llm", no_llm)
    seed_cache(tmp_path, monkeypatch)
    assert cli.main(lme_args(tmp_path, "lme_full", "--max-tokens", "9000000")) == 2
    err = capsys.readouterr().err
    assert "--questions" in err and "--confirm-full" in err


def test_cli_lme_requires_max_tokens(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "make_llm", no_llm)
    seed_cache(tmp_path, monkeypatch)
    assert cli.main(lme_args(tmp_path, "lme_full", "--questions", "8")) == 2
    assert "--max-tokens" in capsys.readouterr().err


def test_cli_lme_missing_dataset_names_file_and_flag(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "make_llm", no_llm)
    monkeypatch.setattr(cli, "LME_CACHE", tmp_path / "empty")
    monkeypatch.setattr(lme, "_stream", no_llm)  # no network either
    assert cli.main(lme_args(tmp_path, "lme_full", "--questions", "8", "--max-tokens", "1000000")) == 2
    err = capsys.readouterr().err
    assert "longmemeval_s_cleaned.json" in err and "--download" in err


def test_cli_lme_rejects_non_lme_config(monkeypatch, capsys):
    monkeypatch.setattr(cli, "make_llm", no_llm)
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--eval", "longmemeval", "--configs", "full"])
    assert exc.value.code == 2 and "lme_" in capsys.readouterr().err


def test_cli_lme_run_writes_result(monkeypatch, tmp_path):
    seed_cache(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "make_llm", lambda budget: counting_llm(tmp_path, budget=budget))
    assert cli.main(lme_args(tmp_path, "lme_baseline_full_context,lme_b1_write_filter", "--questions", "8",
                             "--full-context-questions", "5", "--max-tokens", "2000000")) == 0
    fc = (tmp_path / "results" / "longmemeval_lme_baseline_full_context.md").read_text()
    b1 = (tmp_path / "results" / "longmemeval_lme_b1_write_filter.md").read_text()
    assert "# longmemeval - lme_baseline_full_context" in fc and "PARTIAL" not in fc
    assert "- subset: 5 questions" in fc and "- subset: 8 questions" in b1
    assert "- seed: 7" in b1 and "- judge: stub-model LLM judge" in b1 and "not comparable with the official GPT-4o judge" in b1
    assert "| information extraction | 2 | 2 | 100% |" in b1


def test_cli_lme_existing_result_refused(monkeypatch, tmp_path, capsys):
    seed_cache(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "make_llm", no_llm)
    target = tmp_path / "results" / "longmemeval_lme_full.md"
    target.parent.mkdir()
    target.write_text("done")
    assert cli.main(lme_args(tmp_path, "lme_full", "--questions", "8", "--max-tokens", "1000000")) == 2
    assert str(target) in capsys.readouterr().err and target.read_text() == "done"


def test_cli_lme_partial_on_budget(monkeypatch, tmp_path):
    seed_cache(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "make_llm", lambda budget: counting_llm(tmp_path, budget=budget))
    real = cli.estimate
    monkeypatch.setattr(cli, "estimate", lambda *_a: real("simulation", []))  # estimate 0 passes the gate
    assert cli.main(lme_args(tmp_path, "lme_baseline_full_context", "--questions", "8",
                             "--max-tokens", "40")) == 1
    text = (tmp_path / "results" / "longmemeval_lme_baseline_full_context.md").read_text()
    assert text.startswith("PARTIAL RESULT") and "- completed_questions: 1" in text
