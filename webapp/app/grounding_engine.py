"""Answer grounding engine.

Builds a strict evidence-backed response envelope and prevents unsupported answers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


_CONFIDENCE_SCORE_MAP = {
    "high": 0.9,
    "medium": 0.6,
    "low": 0.2,
}


def _confidence_to_score(confidence: Optional[Dict[str, str]]) -> float:
    if not confidence:
        return 0.0
    level = str(confidence.get("level", "")).strip().lower()
    return _CONFIDENCE_SCORE_MAP.get(level, 0.0)


def _extract_retrieved_documents(rag_evidence: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for hit in ((rag_evidence or {}).get("hits") or []):
        docs.append(
            {
                "document": hit.get("file"),
                "table": hit.get("table"),
                "row_number": hit.get("row_number"),
                "citation": hit.get("citation"),
                "score": hit.get("score"),
                "snippet": (hit.get("text") or hit.get("snippet") or "")[:240],
            }
        )
    return docs


def _extract_source_tables(workflow_result: Optional[Dict[str, Any]], rag_docs: List[Dict[str, Any]]) -> List[str]:
    tables = set()
    if isinstance(workflow_result, dict):
        for t in (workflow_result.get("Selected Tables") or []):
            if t:
                tables.add(str(t))
        if workflow_result.get("table"):
            tables.add(str(workflow_result.get("table")))
    for d in rag_docs:
        table = d.get("table")
        if table:
            tables.add(str(table))
    return sorted(tables)


def _extract_sql_result(workflow_result: Optional[Dict[str, Any]]) -> Any:
    if not isinstance(workflow_result, dict):
        return []
    if isinstance(workflow_result.get("Result Rows"), list):
        return workflow_result.get("Result Rows")
    # Fallback: for non-Text-to-SQL workflows, return grounded structured payload.
    return workflow_result


def build_grounded_answer(
    answer_text: str,
    workflow_result: Optional[Dict[str, Any]],
    rag_evidence: Optional[Dict[str, Any]],
    confidence: Optional[Dict[str, str]],
) -> Dict[str, Any]:
    retrieved_docs = _extract_retrieved_documents(rag_evidence)
    sql_result = _extract_sql_result(workflow_result)

    documents_referenced = []
    for d in retrieved_docs:
        c = (d.get("citation") or "")
        if c and c not in documents_referenced:
            documents_referenced.append(c)

    source_tables = _extract_source_tables(workflow_result, retrieved_docs)

    data_sources: List[str] = []
    if isinstance(sql_result, list) and len(sql_result) > 0:
        data_sources.append("Structured Data (SQL)")
    elif isinstance(sql_result, dict) and len(sql_result) > 0:
        data_sources.append("Structured Workflow Data")
    if retrieved_docs:
        data_sources.append("Retrieved Documents")

    confidence_score = _confidence_to_score(confidence)

    has_sufficient_evidence = bool(data_sources)
    if not has_sufficient_evidence:
        return {
            "Answer": "I do not have enough data to answer.",
            "Evidence": {
                "Data Source": [],
                "Retrieved Documents": [],
                "SQL Result": [],
                "Confidence Score": 0.0,
            },
            "Source Tables": [],
            "Documents Referenced": [],
        }

    return {
        "Answer": answer_text,
        "Evidence": {
            "Data Source": data_sources,
            "Retrieved Documents": retrieved_docs,
            "SQL Result": sql_result,
            "Confidence Score": confidence_score,
        },
        "Source Tables": source_tables,
        "Documents Referenced": documents_referenced,
    }
