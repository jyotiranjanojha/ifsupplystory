"""End-to-end ingest pipeline for hybrid structured + RAG architecture."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from .chunking import Chunker, DocumentChunk
from .document_loader import DocumentLoader
from .embedding_service import OpenVINOEmbeddingService
from .retriever import ChunkRetriever, RetrievedChunk
from .vector_store import FaissVectorStore


class HybridRagPipeline:
    def __init__(
        self,
        index_dir: Path,
        embedding_service: OpenVINOEmbeddingService | None = None,
        chunk_size: int = 800,
        overlap: int = 150,
    ):
        self.loader = DocumentLoader()
        self.chunker = Chunker(chunk_size=chunk_size, overlap=overlap)
        self.embedding_service = embedding_service or OpenVINOEmbeddingService()
        self.vector_store = FaissVectorStore(index_dir=index_dir)
        self.retriever = ChunkRetriever(self.embedding_service, self.vector_store)

    def ingest(self, paths: Iterable[Path]) -> List[DocumentChunk]:
        docs = self.loader.load_paths(paths)
        chunks = self.chunker.chunk_documents(docs)
        if not chunks:
            return []

        vectors = self.embedding_service.embed_documents([c.text for c in chunks])
        self.vector_store.add(chunks, vectors)
        self.vector_store.save()
        return chunks

    def retrieve(self, query: str, top_k: int = 5) -> List[RetrievedChunk]:
        return self.retriever.retrieve(query=query, top_k=top_k)
