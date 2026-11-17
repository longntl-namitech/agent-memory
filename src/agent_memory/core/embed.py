"""Embedders (OpenAI-compatible with a disk cache, or local fastembed) and a cosine top-k index."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

# transport(model, texts) -> one vector per text
Transport = Callable[[str, list[str]], list[list[float]]]


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> np.ndarray: ...


class OpenAICompatEmbedder:
    def __init__(self, base_url: str | None = None, model: str | None = None, *, cache_dir,
                 api_key: str | None = None, transport: Transport | None = None):
        self.base_url = base_url or os.environ["EMBEDDING_BASE_URL"]
        self.name = model or os.environ["EMBEDDING_MODEL"]
        self.api_key = api_key or os.environ.get("EMBEDDING_API_KEY", "none")
        self.cache_dir = Path(cache_dir)
        self._transport = transport or self._openai_transport

    def _openai_transport(self, model: str, texts: list[str]) -> list[list[float]]:
        from openai import OpenAI

        r = OpenAI(base_url=self.base_url, api_key=self.api_key).embeddings.create(model=model, input=texts)
        return [d.embedding for d in r.data]

    def _path(self, text: str) -> Path:
        key = json.dumps([self.name, text], ensure_ascii=False)
        return self.cache_dir / (hashlib.sha256(key.encode()).hexdigest() + ".json")

    def embed(self, texts: list[str]) -> np.ndarray:
        missing = list(dict.fromkeys(t for t in texts if not self._path(t).exists()))
        if missing:
            vectors = self._transport(self.name, missing)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            for text, vec in zip(missing, vectors, strict=True):
                fd, tmp = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(list(vec), f)
                os.replace(tmp, self._path(text))  # atomic: a crash never leaves a half-written entry
        return np.array([json.loads(self._path(t).read_text(encoding="utf-8")) for t in texts], dtype=float)


class FastembedEmbedder:
    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        self.name = model
        self._model = None

    def embed(self, texts: list[str]) -> np.ndarray:
        if self._model is None:
            try:
                from fastembed import TextEmbedding
            except ImportError as exc:
                raise ImportError(
                    "fastembed is not installed; run: pip install 'agent-memory[fastembed]'"
                ) from exc
            self._model = TextEmbedding(self.name)
        return np.array(list(self._model.embed(texts)), dtype=float)


def _unit(a: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(a, axis=-1, keepdims=True)
    return a / np.where(norm == 0, 1.0, norm)  # zero vectors stay zero, no NaN


def cosine_index(vectors: np.ndarray) -> Callable[[np.ndarray, int], list[tuple[int, float]]]:
    unit = _unit(np.asarray(vectors, dtype=float))

    def top_k(query: np.ndarray, k: int) -> list[tuple[int, float]]:
        scores = unit @ _unit(np.asarray(query, dtype=float))
        order = np.argsort(-scores, kind="stable")[:k]
        return [(int(i), float(scores[i])) for i in order]

    return top_k
