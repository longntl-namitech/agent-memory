import os
from pathlib import Path

import pytest

from agent_memory.demo.paths import DEFAULT_ROOT, REPO_ROOT, DemoPaths


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


def test_refuses_root_containing_repo():
    with pytest.raises(ValueError):
        DemoPaths(REPO_ROOT.parent)
    works = Path.home() / "Works"
    if works.exists():
        with pytest.raises(ValueError):
            DemoPaths(works)


def test_refuses_root_containing_cwd(tmp_path, monkeypatch):
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    with pytest.raises(ValueError):
        DemoPaths(tmp_path)


def test_refuses_home_and_ancestor_case_insensitively():
    for real in (Path.home().resolve(), Path.home().resolve().parent):
        swapped = Path(str(real).swapcase())
        if not (swapped.exists() and os.path.samefile(swapped, real)):
            pytest.skip("case-sensitive filesystem")
        with pytest.raises(ValueError):
            DemoPaths(swapped)


def test_store_rejects_traversal_and_absolute(tmp_path):
    p = DemoPaths(tmp_path / "demo")
    for bad in ("../x", "/etc", "", ".", "..", "a/b"):
        with pytest.raises(ValueError):
            p.store(bad)
    assert p.store("full") == p.root / "stores" / "full"


def test_wipe_unlinks_symlink_not_target(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("k")
    p = DemoPaths(tmp_path / "demo")
    p.ensure()
    (p.root / "link").symlink_to(outside, target_is_directory=True)
    p.wipe()
    assert not (p.root / "link").exists() and not (p.root / "link").is_symlink()
    assert (outside / "keep.txt").read_text() == "k"


def test_refuses_repo_subdirectories():
    for sub in ("src", ".git", "tests"):
        with pytest.raises(ValueError):
            DemoPaths(REPO_ROOT / sub)
    DemoPaths(DEFAULT_ROOT)
    DemoPaths(DEFAULT_ROOT / "x")


def test_symlinked_root_to_repo_refused(tmp_path):
    link = tmp_path / "link"
    link.symlink_to(REPO_ROOT, target_is_directory=True)
    with pytest.raises(ValueError):
        DemoPaths(link)


def test_wipe_rechecks_after_cwd_change(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "f.txt").write_text("x")
    p = DemoPaths(root)
    monkeypatch.chdir(root)
    with pytest.raises(ValueError):
        p.wipe()
    assert (root / "f.txt").exists()


def test_wipe_rechecks_after_symlink_swap(tmp_path, monkeypatch):
    # stand-in repo inside tmp_path so nothing real can be deleted if the guard fails
    fake_repo = tmp_path / "fakerepo"
    fake_repo.mkdir()
    (fake_repo / "keep.txt").write_text("k")
    monkeypatch.setattr("agent_memory.demo.paths.REPO_ROOT", fake_repo.resolve())
    root = tmp_path / "root"
    p = DemoPaths(root)
    root.symlink_to(fake_repo, target_is_directory=True)
    with pytest.raises(ValueError):
        p.wipe()
    assert (fake_repo / "keep.txt").exists()
