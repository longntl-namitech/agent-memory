from pathlib import Path

import pytest

from agent_memory.demo.paths import DEFAULT_ROOT, DemoPaths


def test_ensure_creates_layout(tmp_path):
    p = DemoPaths(tmp_path / "demo")
    p.ensure()
    assert p.root.is_dir()
    assert p.llm_live.is_dir() and p.llm_rehearsed.is_dir() and p.embeddings.is_dir()
    assert p.store("a") == p.root / "stores" / "a"
    assert not p.store("a").exists()


def test_wipe_removes_all_files_keeps_root(tmp_path):
    p = DemoPaths(tmp_path / "demo")
    p.ensure()
    (p.store("a")).mkdir(parents=True)
    (p.store("a") / "f.txt").write_text("x")
    (p.root / "top.txt").write_text("y")
    p.wipe()
    assert p.root.is_dir()
    assert list(p.root.iterdir()) == []


def test_wipe_refuses_outside_root():
    with pytest.raises(ValueError):
        DemoPaths(Path("/"))
    with pytest.raises(ValueError):
        DemoPaths(Path.home())


def test_wipe_when_root_missing_is_noop(tmp_path):
    p = DemoPaths(tmp_path / "missing")
    p.wipe()
    assert not p.root.exists()


def test_default_root_is_dot_demo_under_repo():
    assert DEFAULT_ROOT.name == ".demo"
    assert (DEFAULT_ROOT.parent / "pyproject.toml").is_file()
