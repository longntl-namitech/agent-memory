import json
import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = REPO_ROOT / ".demo"


def _same(a: Path, b: Path) -> bool:
    if a.exists() and b.exists():
        return os.path.samefile(a, b)
    return str(a).lower() == str(b).lower()


def _is_unsafe(root: Path) -> bool:
    # repo subdirectories (src, .git, ...) are unsafe too, except the demo dir itself
    if root.is_relative_to(REPO_ROOT) and not root.is_relative_to(DEFAULT_ROOT):
        return True
    # unsafe if root is, or contains, the repo, the home dir or the cwd ("/" contains all)
    for protected in (REPO_ROOT, Path.home().resolve(), Path.cwd().resolve()):
        if any(_same(root, p) for p in (protected, *protected.parents)):
            return True
    return False


OWN_ENTRIES = ("stores", "llm-cache-live", "llm-cache-rehearsed", "embedding-cache")  # meta.json lives in the third


class DemoPaths:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        if _is_unsafe(self.root):
            raise ValueError(f"refusing unsafe demo root: {self.root}")

    def store(self, column: str) -> Path:
        if not column or Path(column).name != column or column in (".", ".."):
            raise ValueError(f"invalid column name: {column!r}")
        return self.root / "stores" / column

    @property
    def llm_live(self) -> Path:
        return self.root / "llm-cache-live"

    @property
    def llm_rehearsed(self) -> Path:
        return self.root / "llm-cache-rehearsed"

    @property
    def embeddings(self) -> Path:
        return self.root / "embedding-cache"

    def live_cache(self, column: str) -> Path:
        # one cache dir per column: both columns can send identical requests, which a real model answers differently
        return self.llm_live / self.store(column).name

    def rehearsed_cache(self, column: str) -> Path:
        return self.llm_rehearsed / self.store(column).name

    @property
    def meta(self) -> Path:
        return self.llm_rehearsed / "meta.json"

    def write_meta(self, model: str, embedding_model: str) -> None:
        """Names only (never keys or URLs): the cache keys depend on them, so replay must reuse the warm-up's."""
        self.meta.parent.mkdir(parents=True, exist_ok=True)
        self.meta.write_text(json.dumps({"model": model, "embedding_model": embedding_model}))

    def read_meta(self) -> dict | None:
        try:
            d = json.loads(self.meta.read_text())
        except (OSError, ValueError):
            return None
        return d if isinstance(d, dict) and isinstance(d.get("model"), str) \
            and isinstance(d.get("embedding_model"), str) else None

    def ensure(self) -> None:
        for d in (self.llm_live, self.llm_rehearsed, self.embeddings):
            d.mkdir(parents=True, exist_ok=True)

    def wipe(self) -> None:
        self.root = self.root.resolve()
        if _is_unsafe(self.root):
            raise ValueError(f"refusing unsafe demo root: {self.root}")
        if not self.root.is_dir():
            return
        # only the demo's own entries: a foreign file in a user-chosen --data-dir is never touched
        for name in OWN_ENTRIES:
            child = self.root / name
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            elif child.is_symlink() or child.exists():
                child.unlink()
