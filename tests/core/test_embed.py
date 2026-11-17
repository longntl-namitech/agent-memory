import sys

import numpy as np
import pytest

from agent_memory.core.embed import FastembedEmbedder, OpenAICompatEmbedder, cosine_index


class Fake:
    def __init__(self):
        self.calls = []

    def __call__(self, model, texts):
        self.calls.append(list(texts))
        return [[float(len(t)), 1.0] for t in texts]


def test_disk_cache_skips_reembed(tmp_path):
    fake = Fake()
    emb = OpenAICompatEmbedder("http://x", "m", cache_dir=tmp_path, transport=fake)
    first = emb.embed(["a", "bb"])
    assert first.shape == (2, 2)
    again = OpenAICompatEmbedder("http://x", "m", cache_dir=tmp_path, transport=fake)
    assert np.array_equal(again.embed(["bb", "a"]), first[::-1])
    assert len(fake.calls) == 1
    again.embed(["a", "ccc"])  # only the uncached text goes over the wire
    assert fake.calls[1] == ["ccc"]


def test_cache_is_per_model(tmp_path):
    fake = Fake()
    OpenAICompatEmbedder("http://x", "m1", cache_dir=tmp_path, transport=fake).embed(["a"])
    OpenAICompatEmbedder("http://x", "m2", cache_dir=tmp_path, transport=fake).embed(["a"])
    assert len(fake.calls) == 2


def test_env_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://env")
    monkeypatch.setenv("EMBEDDING_MODEL", "env-model")
    emb = OpenAICompatEmbedder(cache_dir=tmp_path, transport=Fake())
    assert (emb.base_url, emb.name) == ("http://env", "env-model")


def test_cosine_top_k_order():
    vecs = np.array([[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]])
    top = cosine_index(vecs)(np.array([0.0, 2.0]), 2)
    assert [i for i, _ in top] == [1, 2]
    assert top[0][1] == pytest.approx(1.0)


def test_cosine_zero_vectors_no_nan():
    top = cosine_index(np.array([[0.0, 0.0], [1.0, 0.0]]))(np.array([0.0, 0.0]), 2)
    assert all(np.isfinite(s) for _, s in top)


def test_fastembed_missing_gives_clear_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "fastembed", None)
    with pytest.raises(ImportError, match=r"agent-memory\[fastembed\]"):
        FastembedEmbedder().embed(["x"])
