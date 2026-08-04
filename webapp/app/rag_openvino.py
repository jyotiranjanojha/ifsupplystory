"""
IFSP RAG system backed by OpenVINO GenAI + LangChain.

Replace the TF-IDF/FAISS custom RAG with:
  - OpenVINO BGE embeddings (bge-small-en-v1.5, GPU)
  - LangChain FAISS vector store (persisted under .rag/faiss_openvino/)
  - openvino_genai.LLMPipeline for generation (DeepSeek-R1, GPU, LATENCY)
  - create_retrieval_chain for the RAG loop
"""

from __future__ import annotations

import csv
import re
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

warnings.filterwarnings("ignore")

INPUT_FOLDER  = "by_input"
OUTPUT_FOLDER = "by_output"
FAISS_DIR     = ".rag/faiss_openvino"
MAX_ROWS_PER_FILE = 500

# Paths
_OV_LLM_PATH = r"C:\Users\jojha\OneDrive - Intel Corporation\Documents\NoLlama\model"
_OV_EMBEDDING_DIR = Path(__file__).resolve().parents[2] / "embedding_model" / "bge-small-en-v1.5"


# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------

_embedding_model = None
_vectorstore     = None
_rag_chain       = None


def _get_embedding():
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model

    from langchain_community.embeddings import OpenVINOBgeEmbeddings
    import os

    device = os.getenv("OPENVINO_DEVICE", "GPU")
    model  = OpenVINOBgeEmbeddings(
        model_name_or_path=str(_OV_EMBEDDING_DIR),
        model_kwargs={"device": device, "compile": False},
        encode_kwargs={"mean_pooling": False, "normalize_embeddings": True, "batch_size": 4},
    )
    model.ov_model.compile()
    _embedding_model = model
    return _embedding_model


def _get_vectorstore(base_dir: Path):
    global _vectorstore
    if _vectorstore is not None:
        return _vectorstore

    from langchain_community.vectorstores import FAISS

    faiss_path = base_dir / FAISS_DIR
    embedding  = _get_embedding()

    if faiss_path.exists():
        _vectorstore = FAISS.load_local(
            str(faiss_path), embedding, allow_dangerous_deserialization=True
        )
    else:
        docs = _load_csv_documents(base_dir)
        _vectorstore = FAISS.from_documents(docs, embedding)
        faiss_path.mkdir(parents=True, exist_ok=True)
        _vectorstore.save_local(str(faiss_path))

    return _vectorstore


def _get_rag_chain(base_dir: Path):
    global _rag_chain
    if _rag_chain is not None:
        return _rag_chain

    from langchain_core.prompts import PromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.runnables import RunnablePassthrough, RunnableParallel

    llm         = _get_openvino_llm()
    vectorstore = _get_vectorstore(base_dir)
    retriever   = vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 6})

    prompt = PromptTemplate.from_template(
        "You are an Intel Foundry Supply Planning assistant.\n\n"
        "Use the following planning data context to answer the question.\n"
        "Only use information from the context. If the context is insufficient, say so.\n\n"
        "Context:\n{context}\n\n"
        "Question: {question}\n\n"
        "Answer:"
    )

    def _format_docs(docs):
        return "\n\n".join(d.page_content for d in docs)

    # LCEL chain: retrieve → format → prompt → llm → parse
    # Returns dict with 'answer' and 'context' keys
    _rag_chain = (
        RunnableParallel(
            context=retriever | _format_docs,
            question=RunnablePassthrough(),
            docs=retriever,            # kept separately for source attribution
        )
        | RunnableParallel(
            answer=(
                RunnablePassthrough.assign(context=lambda x: x["context"])
                | (lambda x: prompt.format(context=x["context"], question=x["question"]))
                | (lambda text: llm.invoke(text))
                | StrOutputParser()
            ),
            context=lambda x: x["docs"],
        )
    )
    return _rag_chain


# ---------------------------------------------------------------------------
# OpenVINO GenAI LangChain LLM wrapper
# ---------------------------------------------------------------------------

class _OpenVINOGenAILLM:
    """Minimal LangChain-compatible LLM wrapping openvino_genai.LLMPipeline."""

    _pipeline = None
    _CHAT_TMPL = (
        "<|im_start|>system\n"
        "You are an Intel Foundry Supply Planning assistant. "
        "Answer concisely and only use the supplied context.\n"
        "<|im_end|>\n"
        "<|im_start|>user\n{text}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )

    def _load(self):
        if self._pipeline is None:
            import openvino_genai as ov_genai
            import os
            device = os.getenv("OPENVINO_DEVICE", "GPU")
            hint   = os.getenv("OPENVINO_PERFORMANCE_HINT", "LATENCY")
            self._pipeline = ov_genai.LLMPipeline(_OV_LLM_PATH, device, {"PERFORMANCE_HINT": hint})

    def invoke(self, text: str) -> str:
        self._load()
        prompt   = self._CHAT_TMPL.format(text=text)
        response = self._pipeline.generate(prompt, max_new_tokens=900, temperature=0.1, do_sample=False)
        # DeepSeek-R1: strip chain-of-thought, keep final answer
        if "</think>" in response:
            response = response.split("</think>", 1)[-1]
        return response.split("<|im_end|>")[0].strip()

    # LangChain compatibility shim
    def __call__(self, prompt: str, **_: Any) -> str:
        return self.invoke(prompt)

    # Required by LangChain combine_documents_chain
    def predict(self, text: str) -> str:
        return self.invoke(text)


_llm_singleton = None

def _get_openvino_llm() -> _OpenVINOGenAILLM:
    global _llm_singleton
    if _llm_singleton is None:
        _llm_singleton = _OpenVINOGenAILLM()
    return _llm_singleton


# ---------------------------------------------------------------------------
# Document loading
# ---------------------------------------------------------------------------

def _load_csv_documents(base_dir: Path):
    """Load pipe-delimited CSV files into LangChain Documents."""
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    docs: List[Document] = []
    for source, folder_name in [("input", INPUT_FOLDER), ("output", OUTPUT_FOLDER)]:
        folder = base_dir / folder_name
        if not folder.exists():
            continue
        for csv_file in sorted(folder.glob("*.csv")):
            table_name = re.sub(r"-\d{14}$", "", csv_file.stem)
            rows_loaded = 0
            try:
                with csv_file.open(encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f, delimiter="|")
                    for row in reader:
                        if rows_loaded >= MAX_ROWS_PER_FILE:
                            break
                        text = f"[{table_name}] " + " | ".join(
                            f"{k}: {v}" for k, v in row.items() if v and str(v).strip()
                        )
                        docs.append(Document(
                            page_content=text,
                            metadata={"source": source, "table": table_name},
                        ))
                        rows_loaded += 1
            except Exception:
                continue

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=400, chunk_overlap=50, separators=[" | ", "\n", " ", ""]
    )
    return splitter.split_documents(docs)


# ---------------------------------------------------------------------------
# Public API — drop-in replacement for rag.py's query_rag / build_rag_index
# ---------------------------------------------------------------------------

def export_embedding_model(device: str = "GPU") -> Dict:
    """Export bge-small-en-v1.5 to OpenVINO IR. Run once before first index build."""
    if _OV_EMBEDDING_DIR.exists():
        return {"status": "already_exported", "path": str(_OV_EMBEDDING_DIR)}

    import subprocess, sys, os
    _OV_EMBEDDING_DIR.parent.mkdir(parents=True, exist_ok=True)

    # Intel corporate environment sets ALL_PROXY=socks://... which breaks httpx
    env = os.environ.copy()
    env.pop("ALL_PROXY", None)
    env.pop("all_proxy", None)

    try:
        subprocess.run(
            [
                sys.executable, "-m", "optimum.commands.optimum_cli",
                "export", "openvino",
                "--model", "BAAI/bge-small-en-v1.5",
                "--task", "feature-extraction",
                str(_OV_EMBEDDING_DIR),
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        return {"status": "exported", "path": str(_OV_EMBEDDING_DIR)}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "error": e.stderr[:500]}


def build_openvino_rag_index(base_dir: Path, force: bool = False) -> Dict:
    """Build (or rebuild) the OpenVINO FAISS RAG index from CSV data."""
    global _vectorstore, _rag_chain

    faiss_path = base_dir / FAISS_DIR
    if force and faiss_path.exists():
        import shutil
        shutil.rmtree(faiss_path)
        _vectorstore = None
        _rag_chain   = None

    vs = _get_vectorstore(base_dir)
    return {
        "status": "ready",
        "backend": "openvino+faiss",
        "doc_count": vs.index.ntotal,
        "index_path": str(base_dir / FAISS_DIR),
    }


def query_openvino_rag(
    base_dir: Path,
    question: str,
    week_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    top_k: int = 6,
) -> Dict:
    """Run RAG over IFSP CSV data using OpenVINO embeddings and LLM."""
    if not question or not question.strip():
        return {"query": question, "hits": [], "answer": None, "backend": "openvino+faiss"}

    chain  = _get_rag_chain(base_dir)
    result = chain.invoke(question)

    hits = [
        {
            "table":   doc.metadata.get("table", ""),
            "source":  doc.metadata.get("source", ""),
            "snippet": doc.page_content[:200],
        }
        for doc in result.get("context", [])
    ]

    return {
        "query":   question,
        "answer":  result.get("answer", ""),
        "hits":    hits,
        "backend": "openvino+faiss",
        "top_k":   top_k,
    }


def get_openvino_rag_status(base_dir: Path) -> Dict:
    """Return status of the OpenVINO FAISS index."""
    from langchain_community.vectorstores import FAISS

    faiss_path = base_dir / FAISS_DIR
    embedding_ready = _OV_EMBEDDING_DIR.exists()

    if not faiss_path.exists():
        return {
            "backend": "openvino+faiss",
            "status":  "missing",
            "index_path": str(faiss_path),
            "embedding_model_ready": embedding_ready,
        }

    try:
        vs = FAISS.load_local(str(faiss_path), _get_embedding(), allow_dangerous_deserialization=True)
        return {
            "backend":   "openvino+faiss",
            "status":    "ready",
            "doc_count": vs.index.ntotal,
            "index_path": str(faiss_path),
            "embedding_model": str(_OV_EMBEDDING_DIR),
            "llm_model": _OV_LLM_PATH,
            "embedding_model_ready": embedding_ready,
        }
    except Exception as e:
        return {"backend": "openvino+faiss", "status": "error", "error": str(e)}
