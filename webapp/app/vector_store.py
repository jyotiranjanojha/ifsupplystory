"""FAISS vector store for document chunks with metadata persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Sequence

from .chunking import DocumentChunk


class FaissVectorStore:
    def __init__(self, index_dir: Path):
        self.index_dir = Path(index_dir)
        self.index = None
        self.dim = None
        self.chunks: List[DocumentChunk] = []

    def _ensure_faiss(self):
        try:
            import faiss
            return faiss
        except Exception as exc:
            raise ImportError("faiss-cpu is required for FaissVectorStore") from exc

    def add(self, chunks: Sequence[DocumentChunk], embeddings: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")
        if not chunks:
            return

        faiss = self._ensure_faiss()
        import numpy as np

        vectors = np.asarray(embeddings, dtype="float32")
        if vectors.ndim != 2:
            raise ValueError("embeddings must be 2D")

        dim = int(vectors.shape[1])
        if self.index is None:
            self.index = faiss.IndexFlatIP(dim)
            self.dim = dim
        elif self.dim != dim:
            raise ValueError("embedding dimension mismatch")

        self.index.add(vectors)
        self.chunks.extend(list(chunks))

    def search(self, query_embedding: Sequence[float], top_k: int = 5) -> List[dict]:
        if self.index is None or not self.chunks:
            return []
        if top_k <= 0:
            return []

        import numpy as np

        vec = np.asarray([query_embedding], dtype="float32")
        k = min(top_k, len(self.chunks))
        scores, indices = self.index.search(vec, k)

        out = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            chunk = self.chunks[int(idx)]
            out.append(
                {
                    "score": float(score),
                    "chunk_id": chunk.chunk_id,
                    "text": chunk.text,
                    "metadata": dict(chunk.metadata),
                }
            )
        return out

    def save(self) -> None:
        if self.index is None:
            return
        faiss = self._ensure_faiss()
        self.index_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(self.index_dir / "index.faiss"))

        payload = {
            "dim": self.dim,
            "chunks": [
                {"chunk_id": c.chunk_id, "text": c.text, "metadata": c.metadata}
                for c in self.chunks
            ],
        }
        (self.index_dir / "metadata.json").write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")

    def load(self) -> None:
        faiss = self._ensure_faiss()
        index_path = self.index_dir / "index.faiss"
        meta_path = self.index_dir / "metadata.json"
        if not index_path.exists() or not meta_path.exists():
            raise FileNotFoundError("Vector store files not found")

        self.index = faiss.read_index(str(index_path))
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        self.dim = int(payload.get("dim", 0))
        self.chunks = [
            DocumentChunk(chunk_id=x["chunk_id"], text=x["text"], metadata=x.get("metadata") or {})
            for x in payload.get("chunks", [])
        ]
