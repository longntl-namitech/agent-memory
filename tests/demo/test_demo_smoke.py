from pathlib import Path


def test_import():
    import agent_memory.demo  # noqa: F401


def test_demo_dir_ignored():
    gitignore = Path(__file__).resolve().parents[2] / ".gitignore"
    assert ".demo/" in gitignore.read_text().splitlines()
