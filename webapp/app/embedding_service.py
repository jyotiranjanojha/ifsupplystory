"""Embedding services for hybrid RAG.

Primary: OpenVINO-compatible BGE embeddings.
Secondary: deterministic hash embeddings for local tests.
"""

from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import List, Sequence


class OpenVINOEmbeddingService:
    def __init__(self, model_path: str | None = None, device: str | None = None):
        default_model = Path(__file__).resolve().parents[2] / "embedding_model" / "bge-small-en-v1.5"
        self.model_path = model_path or os.getenv("OPENVINO_EMBEDDING_MODEL_PATH", str(default_model))
        self.device = device or os.getenv("OPENVINO_DEVICE", "GPU")
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        from langchain_community.embeddings import OpenVINOBgeEmbeddings

        model = OpenVINOBgeEmbeddings(
            model_name_or_path=self.model_path,
            model_kwargs={"device": self.device, "compile": False},
            encode_kwargs={"mean_pooling": False, "normalize_embeddings": True, "batch_size": 8},
        )
        model.ov_model.compile()
        self._model = model
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        model = self._load()
        return [list(map(float, vec)) for vec in model.embed_documents(list(texts))]

    def embed_query(self, text: str) -> List[float]:
        model = self._load()
        return list(map(float, model.embed_query(text)))


class DeterministicHashEmbeddingService:
    """Fast deterministic embedding for tests and offline local checks."""

    def __init__(self, dim: int = 128):
        self.dim = dim

    @staticmethod
    def _tokens(text: str) -> List[str]:
        return re.findall(r"[a-z0-9_]{2,}", (text or "").lower())

    def _embed(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        for tok in self._tokens(text):
            idx = sum(ord(c) for c in tok) % self.dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm <= 0:
            return vec
        return [v / norm for v in vec]

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._embed(text)
