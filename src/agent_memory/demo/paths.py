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

    def ensure(self) -> None:
        for d in (self.llm_live, self.llm_rehearsed, self.embeddings):
            d.mkdir(parents=True, exist_ok=True)

    def wipe(self) -> None:
        self.root = self.root.resolve()
        if _is_unsafe(self.root):
            raise ValueError(f"refusing unsafe demo root: {self.root}")
        if not self.root.is_dir():
            return
        for child in self.root.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
