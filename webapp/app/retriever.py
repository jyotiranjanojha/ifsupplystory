"""Retriever with citation support for hybrid RAG."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .embedding_service import OpenVINOEmbeddingService
from .vector_store import FaissVectorStore


@dataclass
class RetrievedChunk:
    chunk_id: str
    score: float
    text: str
    metadata: dict
    citation: str


def build_citation(metadata: dict) -> str:
    document = metadata.get("document", "unknown")
    page = metadata.get("page", "n/a")
    section = metadata.get("section", "default")
    timestamp = metadata.get("timestamp", "n/a")
    return f"{document} | page={page} | section={section} | ts={timestamp}"


class ChunkRetriever:
    def __init__(self, embedding_service: OpenVINOEmbeddingService, vector_store: FaissVectorStore):
        self.embedding_service = embedding_service
        self.vector_store = vector_store

    def retrieve(self, query: str, top_k: int = 5) -> List[RetrievedChunk]:
        if not query or not query.strip():
            return []
        query_vec = self.embedding_service.embed_query(query)
        rows = self.vector_store.search(query_vec, top_k=top_k)
        out: List[RetrievedChunk] = []
        for row in rows:
            md = row.get("metadata") or {}
            out.append(
                RetrievedChunk(
                    chunk_id=row.get("chunk_id", ""),
                    score=float(row.get("score", 0.0)),
                    text=row.get("text", ""),
                    metadata=md,
                    citation=build_citation(md),
                )
            )
        return out
