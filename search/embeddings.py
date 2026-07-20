"""Embedder abstraction: local (fastembed) model + gateway client + hash fallback.

``LocalEmbedder`` (default) runs a small ONNX sentence-embedding model via
``fastembed`` — no network at query time, data stays on the machine. The
``GatewayEmbedder`` targets an OpenAI-compatible ``/embeddings`` endpoint and is
kept for a future gateway embedding model (the Celonis AI Gateway currently
serves chat models only). The ``HashEmbedder`` is deterministic and network-free
so the pipeline can be exercised without any model — it is NOT semantic.
"""

from __future__ import annotations

import hashlib
import math
import sys
import time
from typing import Protocol

from . import config


class Embedder(Protocol):
    model: str

    @property
    def dim(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    def __init__(self, dim: int = 256):
        self._dim = dim
        self.model = f"hash-{dim}"

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self._dim
            for token in text.lower().split():
                h = int(hashlib.md5(token.encode()).hexdigest(), 16)
                vec[h % self._dim] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


class LocalEmbedder:
    """Local sentence-embedding model via fastembed (ONNX, CPU, no network calls
    after the one-time model download). Uses model-specific query vs. passage
    prefixes so query and document vectors live in the same space."""

    def __init__(self, model_name: str, batch: int = 64):
        from fastembed import TextEmbedding

        self.model = model_name
        self.batch = batch
        self._model = TextEmbedding(model_name=model_name)
        self._dim = 0

    @property
    def dim(self) -> int:
        if not self._dim:
            self._dim = len(next(iter(self._model.embed(["dimension probe"]))))
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [v.tolist() for v in self._model.embed(texts, batch_size=self.batch)]

    def embed_query(self, text: str) -> list[float]:
        # bge-style models benefit from a query prefix; fastembed handles it.
        try:
            return next(iter(self._model.query_embed(text))).tolist()
        except Exception:  # noqa: BLE001 — fall back to plain embedding
            return self.embed([text])[0]


class GatewayEmbedder:
    def __init__(self, base_url, api_key, model, embed_path="/embeddings", dim=0, batch=64):
        import requests

        self._requests = requests
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.embed_path = embed_path
        self.batch = batch
        self._dim = dim

    @property
    def dim(self) -> int:
        if not self._dim:
            self._dim = len(self._post(["dimension probe"])[0])
        return self._dim

    def _post(self, inputs: list[str]) -> list[list[float]]:
        url = self.base_url + self.embed_path
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {"model": self.model, "input": inputs}
        last_err = None
        for attempt in range(5):
            try:
                resp = self._requests.post(url, json=payload, headers=headers, timeout=90)
                resp.raise_for_status()
                data = resp.json()["data"]
                return [row["embedding"] for row in data]
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(min(2 ** attempt, 30))
        raise RuntimeError(f"gateway embedding request failed after retries: {last_err}")

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            out.extend(self._post(texts[i : i + self.batch]))
        return out


def get_embedder() -> Embedder:
    choice = config.EMBEDDER or "local"
    if choice == "local":
        return LocalEmbedder(config.LOCAL_MODEL)
    if choice == "gateway":
        if not config.GATEWAY_BASE_URL:
            raise SystemExit(
                "SEARCH_EMBEDDER=gateway but CELONIS_AI_GATEWAY_BASE_URL is not set."
            )
        return GatewayEmbedder(
            config.GATEWAY_BASE_URL,
            config.GATEWAY_API_KEY,
            config.EMBEDDING_MODEL,
            config.GATEWAY_EMBED_PATH,
            config.EMBEDDING_DIM,
        )
    if choice == "hash":
        print(
            "[warn] using HashEmbedder (dev only, not semantic). "
            "Unset SEARCH_EMBEDDER to use the local model for real embeddings.",
            file=sys.stderr,
        )
        return HashEmbedder(config.HASH_DIM)
    raise SystemExit(f"unknown SEARCH_EMBEDDER: {choice!r} (use 'local', 'gateway', or 'hash')")
