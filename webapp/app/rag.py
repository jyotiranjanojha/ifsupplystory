import csv
import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


INPUT_FOLDER = "by_input"
OUTPUT_FOLDER = "by_output"
RAG_FOLDER = ".rag"
RAG_INDEX_FILE = "index.json"

DEFAULT_MAX_ROWS_PER_FILE = 2000
DEFAULT_MAX_DOCS = 250000
VECTOR_DIM = 256
VECTOR_TOP_COMPONENTS = 20
RAG_VECTOR_BACKEND = os.getenv("RAG_VECTOR_BACKEND", "auto").strip().lower() or "auto"

try:
    import faiss  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    faiss = None

_METADATA_KEYS = [
    "CAPTURE_WK",
    "SIMULATION_NAME",
    "ITEM",
    "DMDITEM",
    "SUPPLYITEM",
    "LOC",
    "DMDLOC",
    "SUPPLYLOC",
    "EXTORDERID",
    "HEADEREXTREF",
]


def _safe_rows(file_path: Path):
    with file_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="|")
        for row in reader:
            yield row


def _list_csv_files(folder: Path) -> List[Path]:
    if not folder.exists():
        return []
    return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".csv"])


def _short_table_name(file_name: str) -> str:
    name = (file_name or "").strip()
    if name.lower().endswith(".csv"):
        name = name[:-4]
    return re.sub(r"-\d{14}$", "", name)


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9_]{2,}", (text or "").lower())


# (base_dir_str -> (fingerprint_dict, checked_monotonic)) — avoids 38 os.stat() calls per query
_FINGERPRINT_CACHE: Dict[str, tuple] = {}
_FINGERPRINT_TTL_SECS = 300  # re-check every 5 minutes


def _build_fingerprint(base_dir: Path) -> Dict[str, Dict[str, int]]:
    import time as _time
    cache_key = str(base_dir)
    cached = _FINGERPRINT_CACHE.get(cache_key)
    if cached and (_time.monotonic() - cached[1]) < _FINGERPRINT_TTL_SECS:
        return cached[0]
    fingerprint: Dict[str, Dict[str, int]] = {}
    for family, folder_name in [("input", INPUT_FOLDER), ("output", OUTPUT_FOLDER)]:
        folder = base_dir / folder_name
        for file_path in _list_csv_files(folder):
            stat = file_path.stat()
            key = f"{family}:{file_path.name}"
            fingerprint[key] = {
                "size": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
            }
    _FINGERPRINT_CACHE[cache_key] = (fingerprint, _time.monotonic())
    return fingerprint


def _index_path(base_dir: Path) -> Path:
    return base_dir / RAG_FOLDER / RAG_INDEX_FILE


def _faiss_path(base_dir: Path) -> Path:
    return base_dir / RAG_FOLDER / "vectors.faiss"


# (path -> (mtime_ns, parsed_dict)) — avoids re-reading the large JSON on every request
_INDEX_CACHE: Dict[str, tuple] = {}


def _load_index(index_path: Path) -> Optional[Dict]:
    if not index_path.exists():
        return None
    try:
        mtime = index_path.stat().st_mtime_ns
        cached = _INDEX_CACHE.get(str(index_path))
        if cached and cached[0] == mtime:
            return cached[1]
        data = json.loads(index_path.read_text(encoding="utf-8"))
        _INDEX_CACHE[str(index_path)] = (mtime, data)
        return data
    except (json.JSONDecodeError, OSError):
        return None


def _save_index(index_path: Path, payload: Dict) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    _INDEX_CACHE.pop(str(index_path), None)  # invalidate cache after write


def _is_stale(built_at_iso: Optional[str], refresh_hours: int) -> bool:
    if not built_at_iso:
        return True
    try:
        built_at = datetime.fromisoformat(built_at_iso)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - built_at > timedelta(hours=refresh_hours)


def _hash_index(token: str, dim: int) -> int:
    return sum(ord(ch) for ch in token) % dim


def _dense_to_sparse_topk(values: List[float], top_k: int = VECTOR_TOP_COMPONENTS) -> List[List[float]]:
    indexed = [(idx, val) for idx, val in enumerate(values) if abs(val) > 1e-12]
    top = sorted(indexed, key=lambda item: abs(item[1]), reverse=True)[:top_k]
    return [[idx, float(val)] for idx, val in top]


def _build_doc_vector(tf: Dict[str, int], idf: Dict[str, float], dim: int = VECTOR_DIM) -> List[float]:
    vec = [0.0] * dim
    for token, freq in tf.items():
        idx = _hash_index(token, dim)
        vec[idx] += float(freq) * float(idf.get(token, 1.0))

    norm_sq = sum(v * v for v in vec)
    norm = math.sqrt(norm_sq) if norm_sq > 0 else 1.0
    return [v / norm for v in vec]


def _build_query_vector(question: str, idf: Dict[str, float], dim: int = VECTOR_DIM) -> List[float]:
    tokens = _tokenize(question)
    if not tokens:
        return [0.0] * dim

    q_tf: Dict[str, int] = {}
    for token in tokens:
        q_tf[token] = q_tf.get(token, 0) + 1

    vec = [0.0] * dim
    for token, freq in q_tf.items():
        idx = _hash_index(token, dim)
        vec[idx] += float(freq) * float(idf.get(token, 1.0))

    norm_sq = sum(v * v for v in vec)
    norm = math.sqrt(norm_sq) if norm_sq > 0 else 1.0
    return [v / norm for v in vec]


def _dot_sparse_dense(sparse: List[List[float]], dense: List[float]) -> float:
    score = 0.0
    for pair in sparse:
        if len(pair) != 2:
            continue
        idx = int(pair[0])
        val = float(pair[1])
        if 0 <= idx < len(dense):
            score += val * dense[idx]
    return score


def _resolve_vector_backend() -> str:
    if RAG_VECTOR_BACKEND == "faiss":
        return "faiss" if faiss is not None else "sparse"
    if RAG_VECTOR_BACKEND == "sparse":
        return "sparse"
    # auto
    return "faiss" if faiss is not None else "sparse"


def build_rag_index(
    base_dir: Path,
    force: bool = False,
    max_rows_per_file: int = DEFAULT_MAX_ROWS_PER_FILE,
    max_docs: int = DEFAULT_MAX_DOCS,
) -> Dict:
    index_path = _index_path(base_dir)
    current_fingerprint = _build_fingerprint(base_dir)
    existing = _load_index(index_path)

    if not force and existing and existing.get("fingerprint") == current_fingerprint:
        return {
            "status": "up_to_date",
            "index_path": str(index_path),
            "doc_count": existing.get("doc_count", 0),
            "file_count": existing.get("file_count", 0),
            "built_at": existing.get("built_at"),
        }

    docs: List[Dict] = []
    postings: Dict[str, List[List[float]]] = {}
    df: Dict[str, int] = {}

    ingested_files = 0
    truncated_files: List[Dict] = []

    for family, folder_name in [("input", INPUT_FOLDER), ("output", OUTPUT_FOLDER)]:
        folder = base_dir / folder_name
        for file_path in _list_csv_files(folder):
            ingested_files += 1
            table = _short_table_name(file_path.name)
            row_count = 0
            rows_added = 0
            for row in _safe_rows(file_path):
                row_count += 1
                if rows_added >= max_rows_per_file:
                    continue
                if len(docs) >= max_docs:
                    break

                non_empty = [(k, (v or "").strip()) for k, v in row.items() if (v or "").strip()]
                if not non_empty:
                    continue

                # Keep chunks concise and dense by limiting to first 30 populated fields.
                pairs = non_empty[:30]
                text = " | ".join([f"{k}={v}" for k, v in pairs])
                text = text[:900]
                tokens = _tokenize(text)
                if not tokens:
                    continue

                tf: Dict[str, int] = {}
                for token in tokens:
                    tf[token] = tf.get(token, 0) + 1

                metadata = {}
                for key in _METADATA_KEYS:
                    value = (row.get(key) or "").strip()
                    if value:
                        metadata[key] = value

                doc_id = len(docs)
                docs.append(
                    {
                        "id": doc_id,
                        "family": family,
                        "file": file_path.name,
                        "table": table,
                        "row_number": row_count,
                        "text": text,
                        "metadata": metadata,
                        "tf": tf,
                    }
                )
                rows_added += 1

                unique_terms = set(tf.keys())
                for term in unique_terms:
                    df[term] = df.get(term, 0) + 1
                    postings.setdefault(term, []).append([doc_id, tf[term]])

            if row_count > rows_added:
                truncated_files.append(
                    {
                        "file": file_path.name,
                        "rows_seen": row_count,
                        "rows_indexed": rows_added,
                    }
                )

            if len(docs) >= max_docs:
                break

        if len(docs) >= max_docs:
            break

    doc_count = len(docs)
    idf: Dict[str, float] = {}
    for term, count in df.items():
        idf[term] = math.log((doc_count + 1.0) / (count + 1.0)) + 1.0

    doc_norms: List[float] = [0.0] * doc_count
    for doc in docs:
        norm_sq = 0.0
        for term, freq in doc["tf"].items():
            weight = float(freq) * idf.get(term, 1.0)
            norm_sq += weight * weight
        doc_norms[doc["id"]] = math.sqrt(norm_sq) if norm_sq > 0 else 1.0

    backend = _resolve_vector_backend()
    sparse_vectors: List[List[List[float]]] = []
    dense_vectors: List[List[float]] = []
    for doc in docs:
        dense = _build_doc_vector(doc.get("tf", {}), idf, dim=VECTOR_DIM)
        sparse_vectors.append(_dense_to_sparse_topk(dense, top_k=VECTOR_TOP_COMPONENTS))
        if backend == "faiss":
            dense_vectors.append(dense)

    faiss_status = "disabled"
    faiss_path = _faiss_path(base_dir)
    if backend == "faiss" and faiss is not None:
        try:
            import numpy as np  # type: ignore

            if dense_vectors:
                matrix = np.asarray(dense_vectors, dtype="float32")
                index = faiss.IndexFlatIP(VECTOR_DIM)
                index.add(matrix)
                faiss_path.parent.mkdir(parents=True, exist_ok=True)
                faiss.write_index(index, str(faiss_path))
            faiss_status = "ready"
        except Exception:
            faiss_status = "error"

    # Keep documents compact by removing term-frequency map after vector + postings are built.
    for doc in docs:
        doc.pop("tf", None)

    payload = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "fingerprint": current_fingerprint,
        "doc_count": doc_count,
        "file_count": ingested_files,
        "max_rows_per_file": max_rows_per_file,
        "max_docs": max_docs,
        "vector_dim": VECTOR_DIM,
        "vector_backend": backend,
        "faiss_status": faiss_status,
        "idf": idf,
        "doc_norms": doc_norms,
        "docs": docs,
        "postings": postings,
        "sparse_vectors": sparse_vectors,
        "truncated_files": truncated_files,
    }
    _save_index(index_path, payload)

    return {
        "status": "rebuilt",
        "index_path": str(index_path),
        "doc_count": doc_count,
        "file_count": ingested_files,
        "built_at": payload["built_at"],
        "vector_backend": backend,
        "faiss_status": faiss_status,
        "truncated_files": truncated_files[:20],
    }


def ensure_rag_index(base_dir: Path, refresh_hours: int = 24, max_rows_per_file: int = DEFAULT_MAX_ROWS_PER_FILE) -> Dict:
    index_path = _index_path(base_dir)
    existing = _load_index(index_path)
    current_fingerprint = _build_fingerprint(base_dir)

    if not existing:
        return build_rag_index(base_dir, force=True, max_rows_per_file=max_rows_per_file)

    if existing.get("fingerprint") != current_fingerprint:
        return build_rag_index(base_dir, force=True, max_rows_per_file=max_rows_per_file)

    if _is_stale(existing.get("built_at"), refresh_hours):
        return build_rag_index(base_dir, force=True, max_rows_per_file=max_rows_per_file)

    return {
        "status": "ready",
        "index_path": str(index_path),
        "doc_count": existing.get("doc_count", 0),
        "file_count": existing.get("file_count", 0),
        "built_at": existing.get("built_at"),
    }


def get_rag_status(base_dir: Path, refresh_hours: int = 24) -> Dict:
    index_path = _index_path(base_dir)
    existing = _load_index(index_path)
    if not existing:
        return {
            "enabled": True,
            "index_exists": False,
            "index_path": str(index_path),
            "status": "missing",
        }

    stale = _is_stale(existing.get("built_at"), refresh_hours)
    return {
        "enabled": True,
        "index_exists": True,
        "index_path": str(index_path),
        "status": "stale" if stale else "ready",
        "built_at": existing.get("built_at"),
        "doc_count": existing.get("doc_count", 0),
        "file_count": existing.get("file_count", 0),
        "max_rows_per_file": existing.get("max_rows_per_file"),
        "vector_backend": existing.get("vector_backend", "sparse"),
        "vector_dim": existing.get("vector_dim", VECTOR_DIM),
        "faiss_status": existing.get("faiss_status", "disabled"),
        "truncated_files": (existing.get("truncated_files") or [])[:20],
    }


def _context_boost(doc: Dict, week_id: Optional[str], scenario_id: Optional[str], site: Optional[str], item_id: Optional[str]) -> float:
    sim = 0.0
    metadata = doc.get("metadata") or {}
    if week_id and metadata.get("CAPTURE_WK") == week_id:
        sim += 0.25
    if scenario_id and metadata.get("SIMULATION_NAME") == scenario_id:
        sim += 0.25
    if site and site in {
        metadata.get("LOC"),
        metadata.get("DMDLOC"),
        metadata.get("SUPPLYLOC"),
    }:
        sim += 0.20
    if item_id and item_id in {
        metadata.get("ITEM"),
        metadata.get("DMDITEM"),
        metadata.get("SUPPLYITEM"),
    }:
        sim += 0.30
    return sim


def query_rag(
    base_dir: Path,
    question: str,
    top_k: int = 8,
    week_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    site: Optional[str] = None,
    item_id: Optional[str] = None,
) -> Dict:
    ensure_rag_index(base_dir)
    index = _load_index(_index_path(base_dir)) or {}

    docs = index.get("docs") or []
    idf = index.get("idf") or {}
    doc_norms = index.get("doc_norms") or []
    postings = index.get("postings") or {}
    sparse_vectors = index.get("sparse_vectors") or []
    vector_backend = index.get("vector_backend", "sparse")
    vector_dim = int(index.get("vector_dim", VECTOR_DIM))

    q_tokens = _tokenize(question)
    if not q_tokens:
        return {
            "query": question,
            "top_k": top_k,
            "hits": [],
            "note": "No query tokens were found.",
        }

    q_tf: Dict[str, int] = {}
    for token in q_tokens:
        q_tf[token] = q_tf.get(token, 0) + 1

    q_weights: Dict[str, float] = {}
    q_norm_sq = 0.0
    for token, freq in q_tf.items():
        weight = float(freq) * float(idf.get(token, 1.0))
        q_weights[token] = weight
        q_norm_sq += weight * weight
    q_norm = math.sqrt(q_norm_sq) if q_norm_sq > 0 else 1.0

    scores: Dict[int, float] = {}
    for token, q_weight in q_weights.items():
        for doc_id, tf in postings.get(token, []):
            d_weight = float(tf) * float(idf.get(token, 1.0))
            scores[doc_id] = scores.get(doc_id, 0.0) + (q_weight * d_weight)

    normalized_scores: List[Tuple[int, float]] = []
    for doc_id, dot in scores.items():
        d_norm = float(doc_norms[doc_id]) if doc_id < len(doc_norms) else 1.0
        sim = dot / max(q_norm * d_norm, 1e-9)
        doc = docs[doc_id]
        sim += _context_boost(doc, week_id, scenario_id, site, item_id)
        normalized_scores.append((doc_id, sim))

    lexical_scores = {doc_id: score for doc_id, score in normalized_scores}

    # Vector-search contribution (persistent local vector store, optional FAISS acceleration).
    query_vec = _build_query_vector(question, idf, dim=vector_dim)
    vector_scores: Dict[int, float] = {}

    if vector_backend == "faiss" and faiss is not None and _faiss_path(base_dir).exists():
        try:
            import numpy as np  # type: ignore

            faiss_index = faiss.read_index(str(_faiss_path(base_dir)))
            q = np.asarray([query_vec], dtype="float32")
            search_k = min(max(top_k * 6, 24), len(docs))
            sims, ids = faiss_index.search(q, search_k)
            for sim, doc_id in zip(sims[0], ids[0]):
                if int(doc_id) < 0:
                    continue
                doc_idx = int(doc_id)
                boost = _context_boost(docs[doc_idx], week_id, scenario_id, site, item_id)
                vector_scores[doc_idx] = float(sim) + boost
        except Exception:
            vector_scores = {}

    if not vector_scores:
        for doc_id in range(min(len(docs), len(sparse_vectors))):
            sim = _dot_sparse_dense(sparse_vectors[doc_id], query_vec)
            if sim <= 0:
                continue
            sim += _context_boost(docs[doc_id], week_id, scenario_id, site, item_id)
            vector_scores[doc_id] = sim

    combined: Dict[int, float] = {}
    for doc_id, score in lexical_scores.items():
        combined[doc_id] = combined.get(doc_id, 0.0) + score
    for doc_id, score in vector_scores.items():
        combined[doc_id] = combined.get(doc_id, 0.0) + (0.75 * score)

    if not combined:
        combined = lexical_scores or vector_scores

    top_hits = sorted(combined.items(), key=lambda x: x[1], reverse=True)[: max(top_k, 1)]

    hits = []
    for doc_id, score in top_hits:
        doc = docs[doc_id]
        hits.append(
            {
                "score": round(score, 4),
                "family": doc.get("family"),
                "file": doc.get("file"),
                "table": doc.get("table"),
                "row_number": doc.get("row_number"),
                "metadata": doc.get("metadata"),
                "text": doc.get("text"),
                "citation": f"{doc.get('file')}#row{doc.get('row_number')}",
            }
        )

    return {
        "query": question,
        "top_k": top_k,
        "filters": {
            "week_id": week_id,
            "scenario_id": scenario_id,
            "site": site,
            "item_id": item_id,
        },
        "retrieval": {
            "mode": "hybrid",
            "vector_backend": vector_backend,
            "vector_dim": vector_dim,
        },
        "hits": hits,
        "doc_count": index.get("doc_count", 0),
        "built_at": index.get("built_at"),
    }
