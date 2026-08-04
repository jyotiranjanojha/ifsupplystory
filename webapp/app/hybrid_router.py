"""Hybrid query router for structured data and document RAG.

Determines whether a question should use:
1) SQL only
2) RAG only
3) SQL + RAG

This module is deterministic and does not call any LLM.
"""

from __future__ import annotations

import operator
import re
from enum import Enum
from typing import Annotated, Dict, List, Optional

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict


class HybridRoute(str, Enum):
    SQL_ONLY = "SQL only"
    RAG_ONLY = "RAG only"
    SQL_AND_RAG = "SQL + RAG"


class HybridRouterState(TypedDict):
    question: str
    question_lower: str

    sql_score: float
    rag_score: float
    both_score: float
    matched_signals: Annotated[List[str], operator.add]

    route: str
    reason: str


_SQL_TERMS = {
    "inventory level",
    "inventory",
    "on hand",
    "on-hand",
    "qty",
    "quantity",
    "count",
    "how many",
    "list",
    "show",
    "rows",
    "orders",
    "demand",
    "supply",
    "capacity",
    "fill rate",
    "service level",
    "by item",
    "by location",
    "by week",
}

_RAG_TERMS = {
    "what is",
    "definition",
    "define",
    "policy",
    "sop",
    "process",
    "guideline",
    "documentation",
    "glossary",
    "meaning",
    "concept",
    "safety stock",
}

_BOTH_TERMS = {
    "why",
    "root cause",
    "under safety stock",
    "below safety stock",
    "policy violation",
    "against policy",
    "as per policy",
    "vs policy",
    "recommend",
    "what should we do",
}


def _contains(ql: str, term: str) -> bool:
    if " " in term or "-" in term:
        return term in ql
    # whole-word match for single tokens
    return bool(re.search(rf"\b{re.escape(term)}\b", ql))


def _score_terms(ql: str, terms: set[str], base_weight: float) -> tuple[float, List[str]]:
    score = 0.0
    matched: List[str] = []
    for term in terms:
        if _contains(ql, term):
            weight = base_weight + (0.5 if len(term.split()) >= 2 else 0.0)
            score += weight
            matched.append(term)
    return score, matched


def _is_definition_question(ql: str) -> bool:
    return ql.startswith("what is ") or ql.startswith("define ") or ql.startswith("meaning of ")


def preprocess(state: HybridRouterState) -> Dict:
    q = (state.get("question") or "").strip()
    return {"question": q, "question_lower": q.lower().strip()}


def score_query(state: HybridRouterState) -> Dict:
    ql = state["question_lower"]

    sql_score, sql_matched = _score_terms(ql, _SQL_TERMS, 1.0)
    rag_score, rag_matched = _score_terms(ql, _RAG_TERMS, 1.0)
    both_score, both_matched = _score_terms(ql, _BOTH_TERMS, 1.5)

    # Definition-first boost for policy/glossary style questions.
    if _is_definition_question(ql):
        rag_score += 1.5
        both_matched.append("definition_pattern")

    # Causal questions tend to need data facts + policy context.
    if "why" in ql:
        both_score += 1.0

    return {
        "sql_score": round(sql_score, 3),
        "rag_score": round(rag_score, 3),
        "both_score": round(both_score, 3),
        "matched_signals": sql_matched + rag_matched + both_matched,
    }


def decide_route(state: HybridRouterState) -> Dict:
    sql_score = float(state.get("sql_score", 0.0))
    rag_score = float(state.get("rag_score", 0.0))
    both_score = float(state.get("both_score", 0.0))
    ql = state.get("question_lower", "")
    numeric_cues = any(x in ql for x in ["how many", "count", "qty", "quantity", "rows", "inventory level"])

    # Definition/policy questions without operational ask should stay RAG-only.
    if _is_definition_question(ql) and not numeric_cues:
        return {
            "route": HybridRoute.RAG_ONLY.value,
            "reason": "Question asks for conceptual or policy definition content.",
        }

    # Strong hybrid indicators or mixed SQL+RAG evidence.
    if both_score >= 1.5 or (sql_score > 0 and rag_score > 0 and ("why" in ql or "policy" in ql)):
        return {
            "route": HybridRoute.SQL_AND_RAG.value,
            "reason": "Question needs structured facts and policy/process context.",
        }

    # RAG-only for conceptual/policy definitions without numeric asks.
    if rag_score >= sql_score and rag_score > 0 and not numeric_cues:
        return {
            "route": HybridRoute.RAG_ONLY.value,
            "reason": "Question is conceptual/documentation-focused.",
        }

    # Default to SQL for operational, measurable planning data asks.
    return {
        "route": HybridRoute.SQL_ONLY.value,
        "reason": "Question is operational and best answered from structured planning data.",
    }


def _build_graph():
    builder: StateGraph = StateGraph(HybridRouterState)
    builder.add_node("preprocess", preprocess)
    builder.add_node("score_query", score_query)
    builder.add_node("decide_route", decide_route)
    builder.set_entry_point("preprocess")
    builder.add_edge("preprocess", "score_query")
    builder.add_edge("score_query", "decide_route")
    builder.add_edge("decide_route", END)
    return builder.compile()


_graph = _build_graph()


def route_hybrid_query(question: str) -> Dict[str, object]:
    """Route a user question to SQL-only, RAG-only, or SQL+RAG."""
    initial: HybridRouterState = {
        "question": question or "",
        "question_lower": "",
        "sql_score": 0.0,
        "rag_score": 0.0,
        "both_score": 0.0,
        "matched_signals": [],
        "route": HybridRoute.SQL_ONLY.value,
        "reason": "",
    }
    result = dict(_graph.invoke(initial))
    return {
        "question": result.get("question", question),
        "route": result.get("route"),
        "reason": result.get("reason"),
        "scores": {
            "sql_score": result.get("sql_score", 0.0),
            "rag_score": result.get("rag_score", 0.0),
            "both_score": result.get("both_score", 0.0),
        },
        "matched_signals": result.get("matched_signals", []),
    }


__all__ = ["HybridRoute", "route_hybrid_query"]
