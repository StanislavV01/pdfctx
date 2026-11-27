"""Embedders and rerankers. Local by default (fastembed, ONNX on CPU); API providers are optional.

API providers use only the standard library, so they add no dependencies. Keys come from
OPENAI_API_KEY, VOYAGE_API_KEY and COHERE_API_KEY.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request
from typing import Protocol

from .errors import PdfctxError

_TOKEN = re.compile(r"\w+", re.UNICODE)


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class Reranker(Protocol):
    name: str

    def score(self, query: str, texts: list[str]) -> list[float]: ...


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class HashEmbedder:
    """Deterministic hashed bag-of-words vectors: no model, no download. For tests and as a fallback."""

    def __init__(self, dim: int = 256):
        self.dim = dim
        self.name = f"hash-{dim}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in _TOKEN.findall(t.lower()):
                h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "little")
                v[h % self.dim] += 1.0 if (h >> 32) & 1 else -1.0
            out.append(_normalize(v))
        return out


def _need(module: str):
    try:
        return __import__(module, fromlist=["*"])
    except ImportError as e:
        raise PdfctxError(f"{module} is not installed; install with: pip install 'pdfctx[embed]'") from e


class FastEmbedder:
    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        fe = _need("fastembed")
        self._model = fe.TextEmbedding(model_name=model)
        self.name = f"fastembed:{model}"
        self.dim = len(next(iter(self._model.embed(["dim"]))))

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_normalize(list(map(float, v))) for v in self._model.embed(texts, batch_size=64)]


class FastReranker:
    def __init__(self, model: str = "BAAI/bge-reranker-base"):
        _need("fastembed")
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self._model = TextCrossEncoder(model_name=model)
        self.name = f"fastembed:{model}"

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [float(s) for s in self._model.rerank(query, texts)]


def _post(url: str, key_env: str, payload: dict) -> dict:
    key = os.environ.get(key_env)
    if not key:
        raise PdfctxError(f"{key_env} is not set")
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise PdfctxError(f"{url} returned HTTP {e.code}: {e.read()[:200]!r}") from e
    except urllib.error.URLError as e:
        raise PdfctxError(f"cannot reach {url}: {e.reason}") from e


class OpenAIEmbedder:
    def __init__(self, model: str = "text-embedding-3-small", dim: int = 1536):
        self.model, self.dim, self.name = model, dim, f"openai:{model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            r = _post(
                "https://api.openai.com/v1/embeddings",
                "OPENAI_API_KEY",
                {"model": self.model, "input": texts[i : i + 64]},
            )
            out += [_normalize(d["embedding"]) for d in sorted(r["data"], key=lambda d: d["index"])]
        return out


class VoyageEmbedder:
    def __init__(self, model: str = "voyage-3.5-lite", dim: int = 1024):
        self.model, self.dim, self.name = model, dim, f"voyage:{model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            r = _post(
                "https://api.voyageai.com/v1/embeddings",
                "VOYAGE_API_KEY",
                {"model": self.model, "input": texts[i : i + 64]},
            )
            out += [_normalize(d["embedding"]) for d in sorted(r["data"], key=lambda d: d["index"])]
        return out


class CohereReranker:
    def __init__(self, model: str = "rerank-v3.5"):
        self.model, self.name = model, f"cohere:{model}"

    def score(self, query: str, texts: list[str]) -> list[float]:
        r = _post(
            "https://api.cohere.com/v2/rerank",
            "COHERE_API_KEY",
            {"model": self.model, "query": query, "documents": texts},
        )
        scores = [0.0] * len(texts)
        for item in r["results"]:
            scores[item["index"]] = float(item["relevance_score"])
        return scores


class VoyageReranker:
    def __init__(self, model: str = "rerank-2.5-lite"):
        self.model, self.name = model, f"voyage:{model}"

    def score(self, query: str, texts: list[str]) -> list[float]:
        r = _post(
            "https://api.voyageai.com/v1/rerank",
            "VOYAGE_API_KEY",
            {"model": self.model, "query": query, "documents": texts},
        )
        scores = [0.0] * len(texts)
        for item in r["data"]:
            scores[item["index"]] = float(item["relevance_score"])
        return scores


def get_embedder(name: str | None) -> Embedder | None:
    match name:
        case None | "" | "none":
            return None
        case "hash":
            return HashEmbedder()
        case "fastembed":
            return FastEmbedder()
        case "openai":
            return OpenAIEmbedder()
        case "voyage":
            return VoyageEmbedder()
    raise PdfctxError(f"unknown embedder '{name}' (hash, fastembed, openai, voyage)")


def get_reranker(name: str | None) -> Reranker | None:
    match name:
        case None | "" | "none":
            return None
        case "fastembed":
            return FastReranker()
        case "cohere":
            return CohereReranker()
        case "voyage":
            return VoyageReranker()
    raise PdfctxError(f"unknown reranker '{name}' (fastembed, cohere, voyage)")
