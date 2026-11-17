import json

import pytest

import agent_memory.methods  # noqa: F401  registers the stages
from agent_memory import cli
from agent_memory.core.config import Config, build, load_config
from agent_memory.core.eval.checks import check
from agent_memory.core.eval.simulation import DATA, active_rules
from agent_memory.core.layout import Store
from agent_memory.core.llm import LLMClient, TokenBudget
from agent_memory.core.memory import Task

BASELINES = ["baseline_full_context", "baseline_naive_rag"]
BUILD_UP = ["b1_write_filter", "b2_coala_stores", "b3_recall", "b4_reflect", "b5_forget", "full"]
LEAVE_ONE_OUT = {"no_write_filter": "write", "no_coala_stores": "sort", "no_recall": "recall",
                 "no_reflect": "reflect", "no_reflexion": "reflexion", "no_forget": "forget"}
ALL = BASELINES + BUILD_UP + list(LEAVE_ONE_OUT)


def units(c: Config) -> dict:
    """One entry per ablatable stage; the whole forget list counts as one."""
    return {"memory": c.memory, "write": c.write, "sort": c.sort, "recall": c.recall,
            "reflect": "reflect" in c.reflect, "reflexion": "reflexion" in c.reflect, "forget": tuple(c.forget)}


def stub_llm(tmp_path, budget=None, reply="SKIP", cost=15, cache="llm"):
    return LLMClient("stub", "stub-model", budget or TokenBudget(None), tmp_path / cache,
                     transport=lambda model, messages: (reply, cost - 5, 5))


class ToyEmbedder:
    name = "toy"

    def embed(self, texts):
        import numpy as np
        return np.array([[len(t), 1.0] for t in texts])


def test_simulation_config_count_is_14():
    sim = [p.stem for p in cli.CONFIGS.glob("*.toml") if not p.stem.startswith("lme_")]
    assert sorted(sim) == sorted(ALL)


def test_every_config_validates(tmp_path):
    for name in ALL:
        cfg = load_config(cli.CONFIGS / f"{name}.toml")
        assert cfg.name == name and cfg.agent is None
        build(cfg, llm=stub_llm(tmp_path), store=Store(tmp_path / name), embedder=ToyEmbedder())


def test_leave_one_out_each_differs_from_full_by_one_stage():
    full = units(load_config(cli.CONFIGS / "full.toml"))
    stand_in = units(Config())
    for name, unit in LEAVE_ONE_OUT.items():
        other = units(load_config(cli.CONFIGS / f"{name}.toml"))
        assert [k for k in full if full[k] != other[k]] == [unit], name
        assert other[unit] == stand_in[unit], name  # the removed stage falls back to the A1 stand-in


def test_build_up_chain_adds_one_stage_each():
    chain = [units(Config())] + [units(load_config(cli.CONFIGS / f"{n}.toml")) for n in BUILD_UP]
    for prev, cur, name in zip(chain, chain[1:], BUILD_UP):
        assert len([k for k in cur if cur[k] != prev[k]]) == 1, name
    assert chain[-1]["recall"] == "tag_recall"  # tag_recall is the simulation recall


def test_sim_check_uses_active_rules_of_the_task():
    corrections = json.loads((DATA / "corrections.json").read_text())
    sim_check = cli.sim_check(corrections)
    lead = {"price": 1200, "deal_status": "open"}
    for tid in range(40):
        task = Task(id=tid, week=1, day=1, lead=lead, tags=["x"], wants_log=False)
        expected = check(task, "Hello", active_rules(tid, corrections))
        assert sim_check(task, "Hello") == (expected[0] if expected else None)
    assert sim_check(Task(0, 1, 1, lead, ["x"], False), "Hello") is None  # no rule active yet


def no_llm(*_a, **_k):
    raise AssertionError("no LLM may be built")


def test_estimate_only_is_default_and_calls_no_llm(monkeypatch, capsys):
    monkeypatch.setattr(cli, "make_llm", no_llm)
    assert cli.main(["run", "--eval", "simulation", "--configs", ",".join(ALL)]) == 0
    out = capsys.readouterr().out
    assert "full: 100000" in out and "total: 1400000" in out
    assert "above 5,000,000: no" in out and "placeholder" in out
    assert "estimate only, nothing was run" in out
    assert "per-config cap: 100,000" in out


def test_unknown_config_lists_available(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--eval", "simulation", "--configs", "full,nope"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "nope" in err and "baseline_naive_rag" in err


def test_max_tokens_below_estimate_refused_before_llm(monkeypatch, capsys):
    monkeypatch.setattr(cli, "make_llm", no_llm)
    assert cli.main(["run", "--eval", "simulation", "--configs", "full",
                     "--no-estimate-only", "--max-tokens", "1000"]) != 0
    assert "exceeds max_tokens" in capsys.readouterr().err


def test_longmemeval_estimates_without_llm(monkeypatch, capsys):
    monkeypatch.setattr(cli, "make_llm", no_llm)
    assert cli.main(["run", "--eval", "longmemeval", "--configs", "lme_full"]) == 0
    assert "(prompt 5750000," in capsys.readouterr().out


def test_run_writes_result_with_stub_llm(monkeypatch, tmp_path):
    budget_seen = []

    def make(budget):
        budget_seen.append(budget)
        return stub_llm(tmp_path, budget)

    monkeypatch.setattr(cli, "make_llm", make)
    results = tmp_path / "results"
    assert cli.main(["run", "--eval", "simulation", "--configs", "full", "--no-estimate-only",
                     "--max-tokens", "500000", "--out", str(tmp_path / "stores"),
                     "--results-dir", str(results)]) == 0
    assert budget_seen[0].max_tokens == cli.PER_CONFIG_CAP  # min(cap, 500000)
    text = (results / "simulation_full.md").read_text()
    assert "# simulation - full" in text and "PARTIAL" not in text
    assert "- model: stub-model" in text and "- seed: 7" in text
    # "SKIP" fails VAT once that rule is active, so reflexion ran: proof the retry check is wired
    reflexion = int(text.split("- reflexion_fallbacks: ")[1].split("\n")[0])
    assert reflexion > 0 and "- write_filter_fallbacks: " in text and "- write_filter_dropped_rules: " in text and "- reflect_failures: " in text
    assert "week 4" in text
    assert "- llm_cache: shared across configs" in text
    assert "- per_config_cap: 100000" in text


def test_budget_blown_mid_run_writes_partial(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "make_llm", lambda budget: stub_llm(tmp_path, budget))
    real = cli.estimate
    monkeypatch.setattr(cli, "estimate", lambda *_a: real("simulation", []))  # estimate 0 passes the gate
    results = tmp_path / "results"
    code = cli.main(["run", "--eval", "simulation", "--configs", "baseline_full_context", "--no-estimate-only",
                     "--max-tokens", "100", "--out", str(tmp_path / "stores"), "--results-dir", str(results)])
    assert code != 0
    text = (results / "simulation_baseline_full_context.md").read_text()
    assert text.startswith("PARTIAL RESULT") and "- crashed_tokens: " in text and "- completed_tasks: " in text


def run_args(tmp_path, configs, *extra):
    return ["run", "--eval", "simulation", "--configs", configs, "--no-estimate-only",
            "--out", str(tmp_path / "stores"), "--results-dir", str(tmp_path / "results"), *extra]


def test_no_estimate_only_requires_max_tokens(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "make_llm", no_llm)
    assert cli.main(run_args(tmp_path, "full")) == 2
    assert "--max-tokens" in capsys.readouterr().err
    assert not (tmp_path / "results").exists() and not (tmp_path / "stores").exists()


def test_existing_result_refused_before_llm(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "make_llm", no_llm)
    target = tmp_path / "results" / "simulation_full.md"
    target.parent.mkdir()
    target.write_text("complete result")
    assert cli.main(run_args(tmp_path, "full", "--max-tokens", "500000")) == 2
    assert str(target) in capsys.readouterr().err
    assert target.read_text() == "complete result"


def test_existing_result_replaced_with_overwrite(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "make_llm", lambda budget: stub_llm(tmp_path, budget))
    target = tmp_path / "results" / "simulation_full.md"
    target.parent.mkdir()
    target.write_text("old")
    assert cli.main(run_args(tmp_path, "full", "--max-tokens", "500000", "--overwrite")) == 0
    assert target.read_text().startswith("# simulation - full")


def costly_then_cheap(tmp_path, costs):
    """make_llm stand-in: the n-th config gets a stub costing costs[n] per call, with its own cache."""
    built = []

    def make(budget):
        built.append(budget)
        return stub_llm(tmp_path, budget, cost=costs[len(built) - 1], cache=f"llm{len(built)}")

    return make, built


def test_runaway_config_stops_at_its_cap_and_next_runs(monkeypatch, tmp_path):
    make, built = costly_then_cheap(tmp_path, [20_000, 15])
    monkeypatch.setattr(cli, "make_llm", make)
    code = cli.main(run_args(tmp_path, "baseline_full_context,full", "--max-tokens", "1000000"))
    assert code == 1  # a partial result makes the run exit non-zero
    assert built[0].max_tokens == cli.PER_CONFIG_CAP and built[0].used > cli.PER_CONFIG_CAP
    assert built[1].max_tokens == cli.PER_CONFIG_CAP
    first = (tmp_path / "results" / "simulation_baseline_full_context.md").read_text()
    second = (tmp_path / "results" / "simulation_full.md").read_text()
    assert first.startswith("PARTIAL RESULT") and not second.startswith("PARTIAL")


def test_run_stops_when_run_budget_spent(monkeypatch, tmp_path):
    make, built = costly_then_cheap(tmp_path, [20_000, 20_000, 15])
    monkeypatch.setattr(cli, "make_llm", make)
    real = cli.estimate
    monkeypatch.setattr(cli, "estimate", lambda *_a: real("simulation", []))  # estimate 0 passes the gate
    code = cli.main(run_args(tmp_path, "baseline_full_context,full,b1_write_filter", "--max-tokens", "150000"))
    assert code == 1
    assert built[1].max_tokens == 150_000 - built[0].used  # the remainder, below the per-config cap
    assert len(built) == 2
    assert not (tmp_path / "results" / "simulation_b1_write_filter.md").exists()


def test_larger_per_config_cap_lets_heavy_config_finish(monkeypatch, tmp_path):
    make, built = costly_then_cheap(tmp_path, [20_000])
    monkeypatch.setattr(cli, "make_llm", make)
    code = cli.main(run_args(tmp_path, "baseline_full_context", "--max-tokens", "10000000",
                             "--per-config-cap", "5000000"))
    assert code == 0
    assert built[0].max_tokens == 5_000_000 and built[0].used > cli.PER_CONFIG_CAP
    text = (tmp_path / "results" / "simulation_baseline_full_context.md").read_text()
    assert not text.startswith("PARTIAL") and "- per_config_cap: 5000000" in text


@pytest.mark.parametrize("n", ["0", "-5"])
def test_per_config_cap_must_be_positive(monkeypatch, capsys, n):
    monkeypatch.setattr(cli, "make_llm", no_llm)
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--eval", "simulation", "--configs", "full", "--per-config-cap", n])
    assert exc.value.code == 2 and "--per-config-cap" in capsys.readouterr().err


def test_results_mark_baseline_and_reflexion_metrics(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "make_llm", lambda budget: stub_llm(tmp_path, budget))
    monkeypatch.setattr(cli, "make_embedder", ToyEmbedder)
    names = ["full", "no_reflect", "no_reflexion", "baseline_full_context", "baseline_naive_rag"]
    assert cli.main(run_args(tmp_path, ",".join(names), "--max-tokens", "1000000")) == 0
    text = {n: (tmp_path / "results" / f"simulation_{n}.md").read_text() for n in names}
    note = "- note: corrections are counted after an oracle-guided retry; compare memory methods on first_attempt_failures"
    assert [note in text[n] for n in names] == [True, True, False, False, False]
    for n in names:
        values = [ln.split(": ", 1)[1] for ln in text[n].splitlines() if "- extra_from_wrong_rule: " in ln]
        assert len(values) == 4
        if n.startswith("baseline"):
            assert values == ["n/a (baseline has no RULES)"] * 4
        else:
            assert all(v.isdigit() for v in values)


def test_counters_empty_for_agent_without_memory_or_retries():
    assert cli._counters(object()) == {}
