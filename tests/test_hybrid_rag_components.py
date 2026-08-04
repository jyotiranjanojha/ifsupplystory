import tempfile
import unittest
from pathlib import Path

from webapp.app.chunking import Chunker
from webapp.app.document_loader import DocumentLoader, LoadedDocument
from webapp.app.document_ingest_pipeline import HybridRagPipeline
from webapp.app.embedding_service import DeterministicHashEmbeddingService
from webapp.app.retriever import build_citation
from webapp.app.vector_store import FaissVectorStore


class TestHybridRagComponents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_text_loading_metadata(self):
        p = self.base / "policy.txt"
        p.write_text("Policy text for planning constraints", encoding="utf-8")
        loader = DocumentLoader(base_timestamp="2026-08-04T00:00:00+00:00")
        docs = loader.load_path(p)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].metadata["document"], "policy.txt")
        self.assertEqual(docs[0].metadata["page"], 1)
        self.assertEqual(docs[0].metadata["section"], "default")
        self.assertEqual(docs[0].metadata["timestamp"], "2026-08-04T00:00:00+00:00")

    def test_markdown_loading_sections(self):
        p = self.base / "glossary.md"
        p.write_text("# Fill Rate\nDefinition A\n# Service Level\nDefinition B", encoding="utf-8")
        loader = DocumentLoader(base_timestamp="2026-08-04T00:00:00+00:00")
        docs = loader.load_path(p)
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0].metadata["section"], "Fill Rate")
        self.assertEqual(docs[1].metadata["section"], "Service Level")

    def test_chunking_strategy_size_and_overlap(self):
        doc = LoadedDocument(
            text=("A" * 1100),
            metadata={"document": "a.txt", "page": 1, "section": "default", "timestamp": "t"},
        )
        chunker = Chunker(chunk_size=800, overlap=150)
        chunks = chunker.chunk_document(doc)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertLessEqual(len(chunks[0].text), 800)
        self.assertEqual(chunks[0].metadata["start_char"], 0)
        self.assertEqual(chunks[1].metadata["start_char"], 650)

    def test_chunk_metadata_fields_present(self):
        doc = LoadedDocument(
            text="Planning policy and SOP details.",
            metadata={"document": "sop.txt", "page": 3, "section": "Capacity", "timestamp": "2026-08-04T00:00:00+00:00"},
        )
        chunk = Chunker().chunk_document(doc)[0]
        self.assertIn("document", chunk.metadata)
        self.assertIn("page", chunk.metadata)
        self.assertIn("section", chunk.metadata)
        self.assertIn("timestamp", chunk.metadata)

    def test_faiss_store_add_search_save_load(self):
        try:
            import faiss  # noqa: F401
        except Exception:
            self.skipTest("faiss not available")

        chunks = [
            LoadedDocument(
                text="Fill rate policy for customer orders",
                metadata={"document": "a.txt", "page": 1, "section": "Fill", "timestamp": "t"},
            ),
            LoadedDocument(
                text="Capacity overload mitigation procedure",
                metadata={"document": "b.txt", "page": 2, "section": "Capacity", "timestamp": "t"},
            ),
        ]
        c = Chunker()
        chunk_list = c.chunk_documents(chunks)
        emb = DeterministicHashEmbeddingService(dim=128)
        vectors = emb.embed_documents([x.text for x in chunk_list])

        store = FaissVectorStore(self.base / "faiss")
        store.add(chunk_list, vectors)
        hits = store.search(emb.embed_query("capacity overload"), top_k=2)
        self.assertGreaterEqual(len(hits), 1)

        store.save()
        reloaded = FaissVectorStore(self.base / "faiss")
        reloaded.load()
        hits2 = reloaded.search(emb.embed_query("fill rate"), top_k=1)
        self.assertEqual(len(hits2), 1)

    def test_retriever_top_k_and_citation(self):
        try:
            import faiss  # noqa: F401
        except Exception:
            self.skipTest("faiss not available")

        (self.base / "sop.md").write_text("# Capacity\nCapacity constraint procedure\n", encoding="utf-8")
        (self.base / "kpi.txt").write_text("Fill rate is fulfilled divided by demand.", encoding="utf-8")

        pipeline = HybridRagPipeline(
            index_dir=self.base / "index",
            embedding_service=DeterministicHashEmbeddingService(dim=128),
            chunk_size=800,
            overlap=150,
        )
        pipeline.ingest([self.base / "sop.md", self.base / "kpi.txt"])

        hits = pipeline.retrieve("What is fill rate?", top_k=2)
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(h.citation for h in hits))
        self.assertIn("page=", hits[0].citation)
        self.assertIn("section=", hits[0].citation)
        self.assertIn("ts=", hits[0].citation)

    def test_build_citation_uses_required_fields(self):
        cite = build_citation(
            {
                "document": "policy.pdf",
                "page": 7,
                "section": "Service Level",
                "timestamp": "2026-08-04T00:00:00+00:00",
            }
        )
        self.assertIn("policy.pdf", cite)
        self.assertIn("page=7", cite)
        self.assertIn("section=Service Level", cite)
        self.assertIn("ts=2026-08-04T00:00:00+00:00", cite)


if __name__ == "__main__":
    unittest.main()
