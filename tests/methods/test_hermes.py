"""HermesAgent against tests/fixtures/fake_hermes.sh: no real Hermes, no model, no network."""

import contextlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from agent_memory.core.eval.checks import check
from agent_memory.core.layout import Entry
from agent_memory.core.llm import BudgetExceeded, LLMClient, TokenBudget
from agent_memory.core.memory import TASK_PROMPT, MemoryAgent, Task
from agent_memory.core.review import Reviewer
from agent_memory.methods.hermes.adapter import REPO, HermesAgent, HermesError, MemoryMdStore

FAKE = str(Path(__file__).resolve().parents[1] / "fixtures" / "fake_hermes.sh")
NOW = datetime(2026, 1, 5, 9)
TASK = Task(id=5, week=1, day=3, lead={"name": "Ann", "company": "Acme", "price": 1200, "deal_status": "open"},
            tags=["acme"], wants_log=False)
MARKER = "never mention prices"
PLANTED = "Never mention prices in follow-up emails, let the lead ask first."
SENTINEL = "sk-SENTINEL-do-not-leak-1234"


@pytest.fixture
def home(tmp_path):
    return tmp_path / "hermes-home"


def install(tmp_path) -> Path:
    """A bootstrapped install home (has installs/), as the repo's .hermes-home is."""
    (tmp_path / "install" / "installs").mkdir(parents=True, exist_ok=True)
    return tmp_path / "install"


def make(home, tmp_path, memory_enabled=True, **env):
    log = tmp_path / "argv.log"
    base = {"HOME": str(tmp_path / "fake-home"), "FAKE_HERMES_LOG": str(log),
            "FAKE_HERMES_HOME_LOG": str(tmp_path / "home.log"), "LAB_KEY": SENTINEL}
    return HermesAgent(home, "gpt-5.4-nano", memory_enabled, binary=FAKE, base_url="https://llm.example/v1",
                       key_env="LAB_KEY", max_turns=7, timeout=10, env={**base, **env},
                       install_home=install(tmp_path))


def calls(tmp_path) -> list[list[str]]:
    raw = (tmp_path / "argv.log").read_text(encoding="utf-8")
    return [rec.split("\x1f")[:-1] for rec in raw.split("\x1e") if rec]


def runs(tmp_path) -> list[list[str]]:
    return [c for c in calls(tmp_path) if "-z" in c]


RUN_STATE = ["memories", "sessions", "state.db", "state.db-wal", "state.db-shm", "logs", "checkpoints",
             "pending_messages", "response_store.db", "workspace", "usage.json", "spawn-ledger.json",
             "spawn-ledger.json.lock"]


def run_state(home) -> list[str]:
    """Run state (memory, sessions, transcripts, logs) left in the data root."""
    return [n for n in RUN_STATE if (home / n).exists()]


def scan(root: Path, needle: str) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file() and needle in p.read_text(errors="ignore")]


def test_command_flags(home, tmp_path):
    with make(home, tmp_path) as agent:
        agent.run_task(TASK, NOW)
    argv = runs(tmp_path)[0]
    assert argv[0] == "-z"
    for flag in ("--usage-file", "-m", "-t"):
        assert flag in argv
    assert argv[argv.index("--provider") + 1] == "custom"
    assert argv[argv.index("-m") + 1] == "gpt-5.4-nano"
    toolsets = argv[argv.index("-t") + 1].split(",")
    assert toolsets == ["memory", "todo"]  # no file (writes outside the wipe, reads the repo), skills, terminal
    assert not {"file", "skills", "terminal"} & set(toolsets)
    every = [a for c in calls(tmp_path) for a in c]
    for banned in ("-p", "--profile", "profile", "--ignore-rules", "--ignore-user-config"):
        assert banned not in every


def test_hermes_home_is_the_dedicated_data_root(home, tmp_path):
    with make(home, tmp_path) as agent:
        agent.version()
        agent.run_task(TASK, NOW)
        config = (home / "config.yaml").read_text()
        assert "max_turns: 7" in config and "provider: custom" in config and 'key_env: "LAB_KEY"' in config
        assert 'default: "gpt-5.4-nano"' in config and 'base_url: "https://llm.example/v1"' in config
        assert agent.memory_path == home.resolve() / "memories" / "MEMORY.md"
    seen = (tmp_path / "home.log").read_text().splitlines()
    assert len(seen) == len(calls(tmp_path)) >= 3
    assert seen[0] == str(install(tmp_path).resolve())  # --version runs under the install home
    assert set(seen[1:]) == {str(home.resolve())}
    assert not (home / "profiles").exists()


def test_gateway_stopped_on_close(home, tmp_path):
    with make(home, tmp_path) as agent:
        agent.run_task(TASK, NOW)
        assert "running" in (home / "gateway_state.json").read_text()
    assert calls(tmp_path)[-1] == ["gateway", "stop"]
    assert "stopped" in (home / "gateway_state.json").read_text()


@pytest.mark.parametrize("env", [{"FAKE_HERMES_GATEWAY_EXIT": "1"}, {"FAKE_HERMES_GATEWAY_SLEEP": "5"}])
def test_gateway_stop_failure_or_timeout_is_ignored(home, tmp_path, env):
    agent = make(home, tmp_path, FAKE_HERMES_MEMORY_ADD="Prices go excl. VAT.", **env)
    agent.timeout = 2
    with agent:
        agent.run_task(TASK, NOW)
    assert ["gateway", "stop"] in calls(tmp_path) and run_state(home) == []


def test_reset_wipes_memory_between_runs_and_keeps_runtime(home, tmp_path):
    with make(home, tmp_path, FAKE_HERMES_MEMORY_ADD="Prices go excl. VAT.") as agent:
        agent.plant_rule("Always sign off as Sam.")
        agent.run_task(TASK, NOW)
        assert agent.memory_entries() == ["Always sign off as Sam.", "Prices go excl. VAT."]
        assert (home / "sessions").is_dir() and (home / "state.db").exists()
        assert "Acme" in (home / "spawn-ledger.json").read_text()  # the argv, prompt included
    assert run_state(home) == []
    (home / "cache").mkdir()
    (home / "cache" / "keep.bin").write_text("runtime")
    # a crash that skipped close(): the next run must still start from empty memory
    (home / "memories").mkdir()
    (home / "memories" / "MEMORY.md").write_text("stale entry from a killed run")
    (home / "state.db-wal").write_text("stale")
    (home / "spawn-ledger.json").write_text('[{"argv": ["-z", "stale prompt about Acme"]}]')
    (home / "spawn-ledger.json.lock").write_text("")
    with make(home, tmp_path) as agent:
        assert agent.memory_entries() == [] and agent.memory_size() == 0
        agent.start()
        assert agent.memory_entries() == [] and not (home / "state.db-wal").exists()
        assert not (home / "spawn-ledger.json").exists() and not (home / "spawn-ledger.json.lock").exists()
        agent.run_task(TASK, NOW)
        assert agent.memory_entries() == []
    assert (home / "cache" / "keep.bin").read_text() == "runtime"
    assert (home / "installs" / "bootstrap.log").read_text() == "bootstrap\n"  # the runtime was built once
    assert (home / "config.yaml").exists()


@pytest.mark.parametrize("env, raises", [({}, None), ({"FAKE_HERMES_EXIT": "2"}, None),
                                         ({"FAKE_HERMES_EXIT": "130"}, HermesError),
                                         ({"FAKE_HERMES_SLEEP": "5"}, HermesError),
                                         ({"FAKE_HERMES_INPUT_TOKENS": "5000"}, BudgetExceeded)])
def test_no_memory_or_session_content_left_behind(home, tmp_path, env, raises):
    """Success, failed attempt, raise, timeout and BudgetExceeded all leave no run state in the data root."""
    agent = make(home, tmp_path, FAKE_HERMES_MEMORY_ADD="Prices go excl. VAT.", **env)
    agent.timeout, agent.budget = 2, TokenBudget(4000)
    with pytest.raises(raises) if raises else contextlib.nullcontext():
        with agent:
            agent.plant_rule(PLANTED)
            agent.run_task(TASK, NOW)
    assert run_state(home) == []
    assert scan(home, "Acme") == [] and scan(home, "excl. VAT") == [] and scan(home, "Never mention") == []
    assert ["gateway", "stop"] in calls(tmp_path)


def test_memory_persists_across_tasks_within_a_run(home, tmp_path):
    with make(home, tmp_path, FAKE_HERMES_MEMORY_ADD="Prices go excl. VAT.") as agent:
        agent.run_task(TASK, NOW)
        agent.run_task(TASK, NOW)
        assert len(agent.store.rules()) == 2


def test_never_touches_real_home(home, tmp_path):
    real = Path.home() / ".hermes"
    existed = real.exists()
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    with make(home, tmp_path) as agent:
        agent.run_task(TASK, NOW)
        agent.version()
    assert list(fake_home.iterdir()) == []
    assert real.exists() == existed
    assert run_state(home) == []


def test_exit_code_2_is_failed_attempt(home, tmp_path):
    with make(home, tmp_path, FAKE_HERMES_EXIT="2", FAKE_HERMES_OUTPUT="partial draft") as agent:
        r = agent.run_task(TASK, NOW)
    assert r.output == "" and r.first_output == "" and r.failed_check == "hermes_failed"
    assert agent.failed_attempts == 1 and r.tokens == 1250
    assert check(TASK, r.output, {"vat", "sign_off"}) == ["vat", "sign_off"]  # scored as violations


def test_exit_code_1_no_text_is_failed(home, tmp_path):
    with make(home, tmp_path, FAKE_HERMES_EXIT="1") as agent:
        r = agent.run_task(TASK, NOW)
    assert r.output == "" and r.failed_check == "hermes_failed" and agent.failed_attempts == 1


def test_exit_0_returns_output(home, tmp_path):
    with make(home, tmp_path, FAKE_HERMES_OUTPUT="Hi Ann") as agent:
        r = agent.run_task(TASK, NOW)
    assert (r.output, r.first_output, r.retries, r.failed_check) == ("Hi Ann", "Hi Ann", 0, None)
    assert agent.failed_attempts == 0


def test_tokens_from_usage_file(home, tmp_path):
    with make(home, tmp_path) as agent:
        assert agent.run_task(TASK, NOW).tokens == 1250  # total_including_auxiliary
        assert agent.tokens_used == 1250 and agent.llm is None
    usage = {"input_tokens": 30, "output_tokens": 12, "total_tokens": 42}
    with make(home, tmp_path, FAKE_HERMES_USAGE_JSON=json.dumps(usage)) as agent:
        assert agent.run_task(TASK, NOW).tokens == 42
    with make(home, tmp_path, FAKE_HERMES_USAGE_JSON='{"input_tokens": 30, "output_tokens": 12}') as agent:
        assert agent.run_task(TASK, NOW).tokens == 42


def test_null_usage_failed_attempt_counts_zero_tokens(home, tmp_path):
    """The first real call: exit 2 with every token field null. A failed attempt, not a crash."""
    null = {"input_tokens": None, "output_tokens": None, "total_tokens": None, "api_calls": 0,
            "completed": False, "failed": True, "auxiliary": {"total_tokens": None},
            "total_including_auxiliary": {"total_tokens": None}}
    with make(home, tmp_path, FAKE_HERMES_EXIT="2", FAKE_HERMES_USAGE_JSON=json.dumps(null)) as agent:
        r = agent.run_task(TASK, NOW)
        assert (r.output, r.failed_check, r.tokens) == ("", "hermes_failed", 0)
        assert agent.failed_attempts == 1 and agent.tokens_used == 0
    no_total = '{"total_including_auxiliary": null}'
    with make(home, tmp_path, FAKE_HERMES_EXIT="1", FAKE_HERMES_USAGE_JSON=no_total) as agent:
        assert agent.run_task(TASK, NOW).tokens == 0 and agent.failed_attempts == 1


def test_unset_key_env_is_a_failed_attempt(home, tmp_path):
    """The key comes only from the environment: with it unset Hermes exits 2 with null usage, as for real."""
    agent = make(home, tmp_path)
    agent.env.pop("LAB_KEY")
    with agent:
        r = agent.run_task(TASK, NOW)
    assert r.failed_check == "hermes_failed" and r.tokens == 0 and agent.failed_attempts == 1


def test_timed_out_call_still_records_its_usage(home, tmp_path):
    agent = make(home, tmp_path, FAKE_HERMES_SLEEP_AFTER_USAGE="5")
    agent.timeout = 1
    with pytest.raises(HermesError, match="timed out"):
        with agent:
            agent.run_task(TASK, NOW)
    assert agent.tokens_used == 1250  # the spend counts toward the budget before the raise


def test_missing_usage_file_raises(home, tmp_path):
    with pytest.raises(HermesError, match="usage"):
        with make(home, tmp_path, FAKE_HERMES_NO_USAGE="1") as agent:
            agent.run_task(TASK, NOW)


def test_budget_exceeded_after_task(home, tmp_path):
    agent = make(home, tmp_path)
    agent.budget = TokenBudget(2000)
    with pytest.raises(BudgetExceeded):
        with agent:
            agent.run_task(TASK, NOW)
            agent.run_task(TASK, NOW)
    assert agent.tokens_used == 2500 and run_state(home) == []


def test_other_protocol_calls_spend_nothing(home, tmp_path):
    with make(home, tmp_path) as agent:
        assert agent.receive_correction("Quote prices excl. VAT.", NOW) == 0
        r = agent.run_task(TASK, NOW)
        assert agent.end_task(TASK, r, NOW) == 0 and agent.reflect(NOW) == 0


def test_corrections_arrive_as_user_text_in_next_prompt(home, tmp_path):
    with make(home, tmp_path) as agent:
        agent.run_task(TASK, NOW)
        agent.receive_correction("Quote prices excl. VAT.", NOW)
        agent.run_task(TASK, NOW)
        agent.run_task(TASK, NOW)
    prompts = [c[c.index("-z") + 1] for c in runs(tmp_path)]
    assert "Acme" in prompts[0] and "excl. VAT" not in prompts[0]
    assert "Quote prices excl. VAT." in prompts[1]
    assert "excl. VAT" not in prompts[2]  # said once, then it is up to Hermes to remember


def test_plant_and_review(home, tmp_path):
    with make(home, tmp_path) as agent:
        agent.plant_rule("Always sign off as Sam.")
        agent.plant_rule(PLANTED)
        assert agent.review([MARKER]) == ["1"]
        assert agent.memory_path.read_text() == "Always sign off as Sam."
        # Hermes rewrites the planted rule with a `patch` that changes case and spacing
        agent.plant_rule(PLANTED)
        agent.env |= {"FAKE_HERMES_PATCH_OLD": "Never mention prices", "FAKE_HERMES_PATCH_NEW": "NEVER  mention\tPrices"}
        agent.run_task(TASK, NOW)
        assert "NEVER  mention\tPrices" in agent.memory_path.read_text()
        assert agent.review([MARKER]) == ["1"]
        assert agent.memory_path.read_text() == "Always sign off as Sam."


def test_plant_over_cap_plants_anyway_and_flags(home, tmp_path):
    with make(home, tmp_path) as agent:
        agent.plant_rule("x" * 2150)
        assert agent.planted_over_cap is False
        agent.plant_rule(PLANTED)  # would pass 2,200: planted, nothing of Hermes' own deleted, flagged
        assert agent.memory_entries() == ["x" * 2150, PLANTED] and agent.memory_size() > 2200
        assert agent.planted_over_cap is True


def test_lab_and_hermes_get_the_same_task_text(home, tmp_path):
    seen = []
    llm = LLMClient("stub", "stub-model", TokenBudget(None), tmp_path / "llm",
                    transport=lambda model, messages: (seen.append(messages) or "Hi", 1, 1))

    class NoMemory:
        def recall(self, task, now):
            return ""

    MemoryAgent(NoMemory(), llm).run_task(TASK, NOW)
    lab = seen[0][-1]["content"]
    with make(home, tmp_path) as agent:
        agent.receive_correction("Quote prices excl. VAT.", NOW)
        agent.run_task(TASK, NOW)
    hermes = runs(tmp_path)[0][runs(tmp_path)[0].index("-z") + 1]
    lead = json.dumps({"lead": TASK.lead, "tags": TASK.tags}, ensure_ascii=False)
    assert lab == TASK_PROMPT + "\n\n" + lead
    assert hermes.startswith(lab) and "Quote prices excl. VAT." in hermes[len(lab):]


def test_relative_profile_root_is_taken_from_the_repo_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agent = HermesAgent(Path(".hermes-lab/hermes_default"), "m", True, binary=FAKE)
    assert agent.profile_root == REPO / ".hermes-lab" / "hermes_default" and REPO == Path(__file__).resolve().parents[2]
    assert HermesAgent(tmp_path / "hh", "m", True).profile_root == (tmp_path / "hh").resolve()


def test_missing_binary_gives_clear_error(home, tmp_path):
    agent = HermesAgent(home, "m", True, binary="no-such-hermes-binary", env={"PATH": "/nowhere"})
    assert "unknown" in agent.version()  # the version never stops a run
    with pytest.raises(HermesError, match="no-such-hermes-binary"):
        with agent:
            agent.run_task(TASK, NOW)
    assert run_state(home) == []


def test_store_surface_works_with_reviewer(home, tmp_path):
    """run_simulation plants with store.add and the Monday Reviewer archives through rules()/archive()."""
    with make(home, tmp_path) as agent:
        store = agent.store
        assert isinstance(store, MemoryMdStore) and store.rules() == []  # before the run starts
        agent.plant_rule("Keep emails short.")
        store.add(Entry(id="planted-wrong-rule", kind="rule", key=None, tags=["global"], text=PLANTED,
                        importance=5, created_at=NOW, last_used_at=NOW, expires_at=None, status="active"))
        agent.env |= {"FAKE_HERMES_PATCH_OLD": "Never mention", "FAKE_HERMES_PATCH_NEW": "never   MENTION"}
        agent.run_task(TASK, NOW)
        removed = Reviewer([MARKER]).review(store, NOW)
        assert len(removed) == 1
        assert [r.text for r in store.rules()] == ["Keep emails short."]
        archived = [r for r in store.all_rules() if r.status == "archived"]
        assert len(archived) == 1 and archived[0].archived_at == NOW
        assert agent.memory_path.read_text() == "Keep emails short."


def test_memory_size_reported(home, tmp_path):
    with make(home, tmp_path, FAKE_HERMES_MEMORY_ADD="Prices go excl. VAT.") as agent:
        assert agent.memory_size() == 0
        agent.plant_rule("abc")
        assert agent.memory_size() == 3
        agent.run_task(TASK, NOW)
        assert agent.memory_size() == len("abc\n§\nPrices go excl. VAT.")
        agent.reflect(NOW)
        assert agent.memory_sizes == [agent.memory_size()]


def test_no_memory_config_disables_stores(home, tmp_path):
    with make(home, tmp_path, memory_enabled=False) as agent:
        agent.run_task(TASK, NOW)
        config = (home / "config.yaml").read_text()
    assert "memory_enabled: false" in config and "user_profile_enabled: false" in config
    toolsets = runs(tmp_path)[0][runs(tmp_path)[0].index("-t") + 1].split(",")
    assert toolsets == ["todo"] and not {"memory", "file", "skills", "terminal"} & set(toolsets)


def test_memory_config_enables_stores(home, tmp_path):
    with make(home, tmp_path) as agent:
        agent.start()
        config = (home / "config.yaml").read_text()
    assert "memory_enabled: true" in config and "user_profile_enabled: true" in config


def test_version_reads_the_install_home_not_the_fresh_data_root(home, tmp_path):
    agent = make(home, tmp_path)
    assert agent.version() == "0.23.2"
    assert not home.exists()  # the data root is neither needed nor touched for the version
    agent.install_home = home  # a data root -z has not bootstrapped yet: real Hermes exits 1 there
    assert agent.version() == "unknown (hermes --version exited 1)"  # never raises
    with agent:
        assert agent.run_task(TASK, NOW).output  # -z bootstraps the fresh data root by itself


def test_install_home_defaults_to_the_repo_hermes_home(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert HermesAgent(tmp_path / "hh", "m", True).install_home == REPO / ".hermes-home"
    assert HermesAgent(tmp_path / "hh", "m", True, install_home=Path("x")).install_home == REPO / "x"


def test_version_parses_hermes_version(home, tmp_path):
    assert make(home, tmp_path).version() == "0.23.2"


def test_api_key_never_in_argv_or_on_disk(home, tmp_path):
    with make(home, tmp_path, FAKE_HERMES_MEMORY_ADD="Prices go excl. VAT.") as agent:
        agent.plant_rule("Keep emails short.")
        r = agent.run_task(TASK, NOW)
        assert (home / "config.yaml").exists() and (home / "sessions").is_dir()
        assert scan(tmp_path, SENTINEL) == []  # the whole data root and the logs, mid-run
    assert scan(tmp_path, SENTINEL) == []
    assert all(SENTINEL not in a for c in calls(tmp_path) for a in c)
    assert SENTINEL not in r.output + r.first_output
