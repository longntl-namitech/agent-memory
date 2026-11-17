"""HermesAgent against tests/fixtures/fake_hermes.sh: no real Hermes, no model, no network."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from agent_memory.core.eval.checks import check
from agent_memory.core.layout import Entry
from agent_memory.core.llm import BudgetExceeded, TokenBudget
from agent_memory.core.memory import Task
from agent_memory.core.review import Reviewer
from agent_memory.methods.hermes.adapter import HermesAgent, HermesError, MemoryMdStore

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


def make(home, tmp_path, memory_enabled=True, **env):
    log = tmp_path / "argv.log"
    base = {"HOME": str(tmp_path / "fake-home"), "FAKE_HERMES_LOG": str(log), "LAB_KEY": SENTINEL}
    return HermesAgent(home, "gpt-5.4-nano", memory_enabled, binary=FAKE, base_url="https://llm.example/v1",
                       key_env="LAB_KEY", max_turns=7, timeout=10, env={**base, **env})


def calls(tmp_path) -> list[list[str]]:
    raw = (tmp_path / "argv.log").read_text(encoding="utf-8")
    return [rec.split("\x1f")[:-1] for rec in raw.split("\x1e") if rec]


def runs(tmp_path) -> list[list[str]]:
    return [c for c in calls(tmp_path) if "-z" in c]


def profiles(home) -> list[Path]:
    return list((home / "profiles").glob("*")) if (home / "profiles").exists() else []


def test_command_flags(home, tmp_path):
    with make(home, tmp_path) as agent:
        agent.run_task(TASK, NOW)
    argv = runs(tmp_path)[0]
    assert argv[:2] == ["-p", agent.name]
    for flag in ("-z", "--usage-file", "-m", "-t"):
        assert flag in argv
    assert argv[argv.index("-m") + 1] == "gpt-5.4-nano"
    toolsets = argv[argv.index("-t") + 1].split(",")
    assert "memory" in toolsets and "terminal" not in toolsets
    assert "--ignore-rules" not in argv and "--ignore-user-config" not in argv
    create = calls(tmp_path)[0]
    assert create == ["profile", "create", agent.name, "--no-alias", "--no-skills", "--no-credentials"]


def test_profile_created_and_deleted(home, tmp_path):
    with make(home, tmp_path) as agent:
        agent.run_task(TASK, NOW)
        assert agent.profile_dir.is_dir()
        config = (agent.profile_dir / "config.yaml").read_text()
        assert "max_turns: 7" in config and "provider: custom" in config and "key_env: \"LAB_KEY\"" in config
    assert profiles(home) == []
    assert ["profile", "delete", agent.name, "-y"] in calls(tmp_path)


def test_profile_deleted_after_failed_attempt(home, tmp_path):
    with make(home, tmp_path, FAKE_HERMES_EXIT="2") as agent:
        agent.run_task(TASK, NOW)
    assert profiles(home) == []


def test_profile_deleted_after_raised_error(home, tmp_path):
    with pytest.raises(HermesError):
        with make(home, tmp_path, FAKE_HERMES_EXIT="130") as agent:
            agent.run_task(TASK, NOW)
    assert profiles(home) == []


def test_one_profile_per_run_memory_persists(home, tmp_path):
    with make(home, tmp_path, FAKE_HERMES_MEMORY_ADD="Prices go excl. VAT.") as agent:
        agent.run_task(TASK, NOW)
        agent.run_task(TASK, NOW)
        assert len(agent.store.rules()) == 2
    assert len({c[1] for c in runs(tmp_path)}) == 1  # same profile both sessions


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
    assert profiles(home) == []


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


@pytest.mark.parametrize("env", [{"FAKE_HERMES_EXIT": "130"}, {"FAKE_HERMES_SLEEP": "5"}])
def test_interrupt_and_timeout_raise_and_leave_no_profile(home, tmp_path, env):
    agent = make(home, tmp_path, **env)
    agent.timeout = 0.5
    with pytest.raises(HermesError):
        with agent:
            agent.run_task(TASK, NOW)
    assert profiles(home) == []


def test_tokens_from_usage_file(home, tmp_path):
    with make(home, tmp_path) as agent:
        assert agent.run_task(TASK, NOW).tokens == 1250  # total_including_auxiliary
        assert agent.tokens_used == 1250 and agent.llm is None
    usage = {"input_tokens": 30, "output_tokens": 12, "total_tokens": 42}
    with make(home, tmp_path, FAKE_HERMES_USAGE_JSON=json.dumps(usage)) as agent:
        assert agent.run_task(TASK, NOW).tokens == 42
    with make(home, tmp_path, FAKE_HERMES_USAGE_JSON='{"input_tokens": 30, "output_tokens": 12}') as agent:
        assert agent.run_task(TASK, NOW).tokens == 42


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
    assert agent.tokens_used == 2500 and profiles(home) == []


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


def test_plant_over_cap_raises(home, tmp_path):
    with make(home, tmp_path) as agent:
        agent.plant_rule("x" * 2000)
        with pytest.raises(ValueError, match="2,200"):
            agent.plant_rule("y" * 300)


def test_store_surface_works_with_reviewer(home, tmp_path):
    """run_simulation plants with store.add and the Monday Reviewer archives through rules()/archive()."""
    with make(home, tmp_path) as agent:
        store = agent.store
        assert isinstance(store, MemoryMdStore) and store.rules() == []  # before the profile exists
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
        config = (agent.profile_dir / "config.yaml").read_text()
    assert "memory_enabled: false" in config and "user_profile_enabled: false" in config
    toolsets = runs(tmp_path)[0][runs(tmp_path)[0].index("-t") + 1].split(",")
    assert "memory" not in toolsets and "terminal" not in toolsets


def test_memory_config_enables_stores(home, tmp_path):
    with make(home, tmp_path) as agent:
        agent.start()
        config = (agent.profile_dir / "config.yaml").read_text()
    assert "memory_enabled: true" in config and "user_profile_enabled: true" in config


def test_version_parses_hermes_version(home, tmp_path):
    assert make(home, tmp_path).version() == "0.23.2"


def test_api_key_never_in_argv_or_on_disk(home, tmp_path):
    with make(home, tmp_path) as agent:
        agent.plant_rule("Keep emails short.")
        agent.run_task(TASK, NOW)
        on_disk = [p for p in tmp_path.rglob("*") if p.is_file()]
        assert any(p.name == "config.yaml" for p in on_disk)
        for p in on_disk:
            assert SENTINEL not in p.read_text(errors="ignore"), p
    assert all(SENTINEL not in a for c in calls(tmp_path) for a in c)
