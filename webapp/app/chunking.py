"""Chunking strategy for RAG documents.

Default strategy:
- chunk size: 800
- overlap: 150
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from .document_loader import LoadedDocument


@dataclass
class DocumentChunk:
    chunk_id: str
    text: str
    metadata: dict


class Chunker:
    def __init__(self, chunk_size: int = 800, overlap: int = 150):
        if chunk_size <= 0:
            raise ValueError("chunk_size must be > 0")
        if overlap < 0:
            raise ValueError("overlap must be >= 0")
        if overlap >= chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_documents(self, docs: Iterable[LoadedDocument]) -> List[DocumentChunk]:
        chunks: List[DocumentChunk] = []
        for doc in docs:
            chunks.extend(self.chunk_document(doc))
        return chunks

    def chunk_document(self, doc: LoadedDocument) -> List[DocumentChunk]:
        text = (doc.text or "").strip()
        if not text:
            return []

        chunks: List[DocumentChunk] = []
        start = 0
        n = len(text)
        idx = 0

        while start < n:
            end = min(start + self.chunk_size, n)
            piece = text[start:end]
            piece = piece.strip()
            if piece:
                md = dict(doc.metadata)
                md["chunk_index"] = idx
                md["start_char"] = start
                md["end_char"] = end
                chunk_id = f"{md.get('document', 'unknown')}::{md.get('page', 1)}::{md.get('section', 'default')}::{idx}"
                chunks.append(DocumentChunk(chunk_id=chunk_id, text=piece, metadata=md))

            idx += 1
            if end >= n:
                break
            start = end - self.overlap

        return chunks
