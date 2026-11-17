import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ROOT = REPO_ROOT / ".demo"


class DemoPaths:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        home = Path.home().resolve()
        if self.root == Path("/") or self.root == REPO_ROOT or self.root in home.parents or self.root == home:
            raise ValueError(f"refusing unsafe demo root: {self.root}")

    def store(self, column: str) -> Path:
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
        if not self.root.is_dir():
            return
        for child in self.root.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
