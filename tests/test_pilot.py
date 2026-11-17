"""`agent-memory pilot` with the fake Hermes binary: no real Hermes, model or network."""

from pathlib import Path

import pytest

from agent_memory import cli

FAKE_HERMES = str(Path(__file__).resolve().parent / "fixtures" / "fake_hermes.sh")
SECRET = "sk-sentinel-12345"


def setup(monkeypatch, tmp_path, **env):
    home = tmp_path / "hermes-home"
    log = tmp_path / "calls.log"
    (tmp_path / "install" / "installs").mkdir(parents=True)  # a bootstrapped install home
    deps = {"binary": FAKE_HERMES, "profile_root": home, "install_home": tmp_path / "install",
            "env": {"HOME": str(tmp_path / "fake-home"), "FAKE_HERMES_LOG": str(log),
                    "FAKE_HERMES_INPUT_TOKENS": "800", "FAKE_HERMES_OUTPUT_TOKENS": "150",
                    "FAKE_HERMES_AUX_TOKENS": "50", "OPENAI_API_KEY": SECRET, **env}}
    monkeypatch.setattr(cli, "hermes_deps", lambda: deps)
    monkeypatch.setattr(cli, "make_llm", lambda *_a: pytest.fail("no LLM client may be built"))
    return home, log


def args(tmp_path, *extra):
    return ["pilot", "--results-dir", str(tmp_path / "results"), *extra]


def no_run_state(home) -> bool:
    """No memory, session or log content left in the Hermes data root, and no named profile."""
    left = ["memories", "sessions", "state.db", "logs", "workspace", "usage.json", "profiles"]
    return not any((home / n).exists() for n in left)


def log_calls(log) -> list[list[str]]:
    return [rec.split("\x1f")[:-1] for rec in log.read_text(encoding="utf-8").split("\x1e") if rec]


def test_extrapolation():
    r = cli.extrapolate([1000, 1000, 1000])
    assert r["mean"] == 1000 and r["per_run"] == 40_000
    assert r["all_runs"] == 240_000 and r["one_run_per_config"] == 80_000


def test_extrapolation_rounds_mean():
    assert cli.extrapolate([1, 2])["per_run"] == 60  # mean 1.5 x 40


def test_run_prints_table_and_extrapolation(monkeypatch, tmp_path, capsys):
    home, log = setup(monkeypatch, tmp_path, FAKE_HERMES_OUTPUT="one two three")
    assert cli.main(args(tmp_path, "--run", "--max-tokens", "50000")) == 0
    out = capsys.readouterr().out
    calls = log_calls(log)
    assert calls[-1] == ["gateway", "stop"] and not any("-p" in c or "profile" in c for c in calls)
    assert "--per-config-cap" in out and "690 MB" in out
    assert "task, tokens, words, failed" in out and "0, 1000, 3, no" in out and "2, 1000, 3, no" in out
    assert "mean tokens per task: 1000" in out and "40,000 per run" in out
    assert "240,000" in out and "6 runs = 2 configs x 3 runs" in out and "80,000" in out
    assert "stay under" in out and "100,000" in out
    assert "extrapolation from 3 tasks" in out and "nothing beyond the pilot was run" in out
    text = (tmp_path / "results" / "pilot_hermes_default.md").read_text()
    assert "- hermes_version: 0.23.2" in text and "- mean_tokens_per_task: 1000" in text
    assert "- reproducibility: not cache-reproducible" in text and "- tokens: 3000" in text
    assert "one two three" not in text
    for needle in ("biased downward", "hermes_no_memory", "overshoot it", "6,301 tokens"):
        assert needle in out and needle in text
    assert no_run_state(home)


def test_failing_version_does_not_stop_the_pilot(monkeypatch, tmp_path, capsys):
    home, _ = setup(monkeypatch, tmp_path)
    (tmp_path / "install" / "installs").rmdir()  # --version exits 1 ("no dependency environment")
    assert cli.main(args(tmp_path, "--run", "--max-tokens", "50000")) == 0
    text = (tmp_path / "results" / "pilot_hermes_default.md").read_text()
    assert "- hermes_version: unknown (hermes --version exited 1)" in text and "- tokens: 3000" in text
    assert no_run_state(home)


def test_dry_run_calls_nothing(monkeypatch, tmp_path, capsys):
    home, log = setup(monkeypatch, tmp_path)
    assert cli.main(args(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "dry run" in out and "OPENAI_API_KEY" in out and "gpt-5.4-nano" in out and SECRET not in out
    assert "HERMES_HOME=" in out and " -p " not in out and "690 MB" in out and "minutes" in out
    assert not log.exists() and not home.exists() and not (tmp_path / "results").exists()


def test_run_without_max_tokens_exits_2_before_building(monkeypatch, tmp_path, capsys):
    home, log = setup(monkeypatch, tmp_path)
    assert cli.main(args(tmp_path, "--run")) == 2
    assert "--max-tokens" in capsys.readouterr().err
    assert not log.exists() and not home.exists()


def test_non_hermes_config_rejected(monkeypatch, tmp_path, capsys):
    _, log = setup(monkeypatch, tmp_path)
    assert cli.main(args(tmp_path, "--config", "full")) == 2
    assert "hermes" in capsys.readouterr().err and not log.exists()


@pytest.mark.parametrize("n", ["0", "41"])
def test_tasks_out_of_range_rejected(monkeypatch, tmp_path, n):
    _, log = setup(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as e:
        cli.main(args(tmp_path, "--tasks", n))
    assert e.value.code == 2 and not log.exists()


def test_budget_stop_prints_partial_and_leaves_no_run_state(monkeypatch, tmp_path, capsys):
    home, _ = setup(monkeypatch, tmp_path)
    assert cli.main(args(tmp_path, "--run", "--max-tokens", "1500")) == 1
    out = capsys.readouterr().out
    assert "stopped: token budget" in out and "mean tokens per task: 1000" in out
    assert "overshoot: 500 tokens over the cap" in out
    text = (tmp_path / "results" / "pilot_hermes_default.md").read_text()
    assert "PARTIAL" in text and "- budget_overshoot: 500" in text
    assert no_run_state(home)


def test_no_key_value_in_output_or_results(monkeypatch, tmp_path, capsys):
    setup(monkeypatch, tmp_path)
    assert cli.main(args(tmp_path, "--run", "--max-tokens", "50000")) == 0
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    assert SECRET not in (tmp_path / "results" / "pilot_hermes_default.md").read_text()


def test_overwrite_guard(monkeypatch, tmp_path, capsys):
    _, log = setup(monkeypatch, tmp_path)
    run = args(tmp_path, "--run", "--max-tokens", "50000")
    assert cli.main(run) == 0
    log.unlink()
    assert cli.main(run) == 2 and "--overwrite" in capsys.readouterr().err and not log.exists()
    assert cli.main([*run, "--overwrite"]) == 0


def test_hermes_crash_exits_1_without_result_or_run_state(monkeypatch, tmp_path, capsys):
    home, _ = setup(monkeypatch, tmp_path, FAKE_HERMES_EXIT="130")
    assert cli.main(args(tmp_path, "--run", "--max-tokens", "50000")) == 1
    captured = capsys.readouterr()
    assert "pilot crashed" in captured.err and "130" in captured.err
    assert not (tmp_path / "results").exists() and no_run_state(home)
