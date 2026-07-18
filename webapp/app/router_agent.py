"""
RouterAgent — LangGraph-based intent classifier and slot resolver.

Acts as the traffic cop for every planner question. Produces a structured
IntentMetadata dict before any workflow is dispatched.

Graph
-----
    classify_intent ──► resolve_entities ──► check_slots ──► END

Outputs
-------
The final state is the IntentMetadata.  The dispatcher in analyzer.py
reads meta["intent"] and meta["entities"] to decide which workflow to call.
No workflow functions are imported here — this module is dispatcher-agnostic
to avoid circular imports.
"""

import json
import operator
import os
import re
from typing import Annotated, Any, Dict, List, Optional
from urllib import error, request as urllib_request

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

# ── Ollama LLM router config (used only as low-confidence fallback) ──────────
_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
_OLLAMA_ROUTER_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:latest")
_ROUTER_CONFIDENCE_THRESHOLD = float(os.getenv("OLLAMA_ROUTER_CONFIDENCE_THRESHOLD", "0.3"))

# ---------------------------------------------------------------------------
# Intent catalog
# ---------------------------------------------------------------------------

INTENT_CATALOG: Dict[str, Dict[str, Any]] = {
    "bom_drill": {
        "description": "Multi-level BOM traversal to find component supply gaps",
        "terms": [
            "bom drill", "bom traverse", "bom traversal", "traverse bom",
            "drill down bom", "drill bom", "component supply", "why no components",
            "component shortage", "bom component", "multi-level bom",
            "multilevel bom", "deep bom",
        ],
        "required_slots": ["item"],
        "optional_slots": ["site", "week_id", "scenario_id"],
        "priority": 10,
        "workflow": "BomDrill",
        "domain": None,
    },
    "root_cause": {
        "description": "Demand-supply root cause and lineage analysis for an item",
        "terms": [
            "root cause", "why unmet", "unmet", "why demand", "why did demand",
            "demand miss", "missed demand", "explain demand", "lineage",
            "genealogy", "pegging",
        ],
        "required_slots": ["item"],
        "optional_slots": ["site", "week_id", "scenario_id"],
        "priority": 9,
        "workflow": "RootCause",
        "domain": None,
    },
    "item_demand_supply": {
        "description": "Demand vs supply details for a specific item",
        "terms": [
            "demand and supply", "demand vs supply", "supply situation",
            "demand situation", "share more details about demand vs supply",
        ],
        "required_slots": ["item"],
        "optional_slots": ["site", "week_id", "scenario_id"],
        "priority": 8,
        "workflow": "ItemDemandSupply",
        "domain": None,
    },
    "table_explain": {
        "description": "Explain a planning table schema, columns, and linkages",
        "terms": [
            "explain table", "describe table", "table definition",
            "table schema", "column definition",
        ],
        "required_slots": ["table_name"],
        "optional_slots": [],
        "priority": 8,
        "workflow": "TableExplain",
        "domain": None,
    },
    "domain_fulfillment": {
        "description": "Fulfillment domain: unmet demand, OTIF, fill rate, backorders",
        "terms": [
            "fulfillment", "why didn't we ship", "why did not we ship",
            "why not shipped", "customer order not met", "fill rate", "otif",
            "stockout", "backorder", "shortage", "lost sales",
        ],
        "required_slots": [],
        "optional_slots": ["site", "week_id", "scenario_id"],
        "priority": 7,
        "workflow": "DomainFocus",
        "domain": "Fulfillment",
    },
    "domain_generation": {
        "description": "Generation domain: why no planned orders, capacity, lead time",
        "terms": [
            "generation", "why didn't we build", "why did not we build",
            "why didn't we buy", "why did not we buy", "no planned orders",
            "planned order not generated", "lead time", "active forecast",
        ],
        "required_slots": [],
        "optional_slots": ["site", "week_id", "scenario_id"],
        "priority": 7,
        "workflow": "DomainFocus",
        "domain": "Generation",
    },
    "domain_data_hygiene": {
        "description": "Data Hygiene: master data errors, BOM issues, parameter gaps",
        "terms": [
            "data hygiene", "garbage in garbage out", "data input error",
            "master data error", "master data", "data quality",
            "sudden drop in planned supply", "routing master",
            "calendar issue", "moq", "lot size",
        ],
        "required_slots": [],
        "optional_slots": ["site", "week_id", "scenario_id"],
        "priority": 7,
        "workflow": "DomainFocus",
        "domain": "DataHygiene",
    },
    "validation": {
        "description": "Data quality, referential integrity, and planning readiness checks",
        "terms": [
            "validate", "validation", "quality", "readiness",
            "referential", "integrity", "orphan",
        ],
        "required_slots": [],
        "optional_slots": ["site", "week_id", "scenario_id"],
        "priority": 6,
        "workflow": "Validation",
        "domain": None,
    },
    "compare": {
        "description": "Scenario comparison and delta analysis",
        "terms": [
            "compare", "difference", "delta", "scenario compare", "versus", "vs",
        ],
        "required_slots": [],
        "optional_slots": ["week_id", "base_scenario", "compare_scenario", "site"],
        "priority": 5,
        "workflow": "ScenarioCompare",
        "domain": None,
    },
    "insights": {
        "description": "Analytics insights: trends, fill rate, capacity utilization",
        "terms": [
            "insight", "fill rate", "capacity", "trend",
            "demand supply", "analytics",
        ],
        "required_slots": [],
        "optional_slots": ["site", "week_id", "scenario_id"],
        "priority": 4,
        "workflow": "Insights",
        "domain": None,
    },
    "sql_query": {
        "description": "Natural language to SQL query against planning tables",
        "terms": [
            "sql", "query", "select from", "show me rows", "list all rows",
            "how many rows", "count rows", "filter rows", "retrieve rows",
            "find records", "show records", "run query", "database query",
            "top 10", "top 5", "show all", "find all items",
        ],
        "required_slots": [],
        "optional_slots": ["week_id", "scenario_id", "site"],
        "priority": 8,
        "workflow": "SqlQuery",
        "domain": None,
    },
    "log_reader": {
        "description": "Parse and summarize planning logs, solver outputs, and exception reports",
        "terms": [
            "read log", "parse log", "analyze log", "planning log", "solver log",
            "exception log", "error log", "solver output", "log file",
            "explain this output", "what does this log", "summarize log",
            "log analysis", "read this log",
        ],
        "required_slots": [],
        "optional_slots": [],
        "priority": 7,
        "workflow": "LogReader",
        "domain": None,
    },
    "vision_query": {
        "description": "Analyze planning screenshots, charts, tables, or visual reports",
        "terms": [
            "image", "screenshot", "chart", "picture", "visual", "photo",
            "analyze this image", "read this chart", "look at this",
            "describe this chart", "what is in this image", "planning chart",
        ],
        "required_slots": [],
        "optional_slots": [],
        "priority": 7,
        "workflow": "VisionQuery",
        "domain": None,
    },
    "summary": {
        "description": "Dataset inventory and summary",
        "terms": [
            "summary", "dataset", "datasets", "files", "inventory",
            "what is available", "table list", "tables are available",
            "available tables",
        ],
        "required_slots": [],
        "optional_slots": [],
        "priority": 3,
        "workflow": "DatasetSummary",
        "domain": None,
    },
    "conversational": {
        "description": "General or unclassified planning question",
        "terms": [],
        "required_slots": [],
        "optional_slots": [],
        "priority": 1,
        "workflow": "ConversationalCopilot",
        "domain": None,
    },
}

# Slot clarification templates
SLOT_CLARIFICATION: Dict[str, Dict[str, Any]] = {
    "item": {
        "question": "Which demand ITEM should I use for this analysis?",
        "examples": [
            "Use ITEM 100000000004",
            "Use ITEM 100000000004 for plant 1004",
        ],
    },
    "table_name": {
        "question": "Which planning table should I explain?",
        "examples": [
            "Explain table by_if_snop_out_inddmdview",
            "Describe table if_snop_billofmaterials",
        ],
    },
}


# ---------------------------------------------------------------------------
# Router state
# ---------------------------------------------------------------------------

class RouterState(TypedDict):
    # ── inputs ──────────────────────────────────────────────────────────────
    question: str
    question_lower: str
    history: List[Dict[str, str]]
    context_week_id: Optional[str]
    context_scenario_id: Optional[str]
    context_scope: Dict[str, Any]

    # ── filled by classify_intent ────────────────────────────────────────────
    intent_scores: Dict[str, float]
    intent: str
    domain: Optional[str]
    workflow: str
    matched_terms: Annotated[List[str], operator.add]
    confidence: float
    conflict: bool
    conflicting_intents: List[str]
    llm_fallback_used: bool

    # ── filled by resolve_entities ───────────────────────────────────────────
    entities: Dict[str, Optional[str]]   # item, site, week_id, scenario_id, table_name
    entity_sources: Dict[str, str]        # entity -> "question" | "history" | "context"

    # ── filled by check_slots ────────────────────────────────────────────────
    missing_slots: List[str]
    needs_clarification: bool
    clarification: Optional[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Entity extraction helpers (no imports from analyzer to avoid circular deps)
# ---------------------------------------------------------------------------

_ITEM_PATTERNS = [
    r"\bdemand\s+(?:for|item)\s*[:=]?\s*([A-Za-z0-9\-]+)",
    r"\bitem\s*[:=]?\s*([A-Za-z0-9\-]+)",
    r"\bfor\s+([A-Za-z0-9\-]{6,})\b",
]
_NUMERIC_ITEM_RE = re.compile(r"\b\d{6,}\b")
_SITE_RE = re.compile(r"\b(?:plant|site|loc|location)\s*[:=]?\s*([A-Za-z0-9\-]+)", re.IGNORECASE)
_WEEK_RE = re.compile(r"\b(?:week|wk|capture_wk)\s*[:=]?\s*(\d{6,})", re.IGNORECASE)
_SCENARIO_RE = re.compile(r"\b(?:scenario|simulation|sim|sc)\s*[:=]?\s*([A-Za-z0-9_\-]+)", re.IGNORECASE)
_TABLE_NAME_RE = re.compile(
    r"\b((?:by_)?if_snop_(?:out_)?[a-z_]+(?:-\d{14})?)", re.IGNORECASE
)


def _extract_item(text: str) -> Optional[str]:
    for pattern in _ITEM_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip(" .,:;!?()[]{}")
            if val:
                return val
    m = _NUMERIC_ITEM_RE.search(text)
    return m.group(0) if m else None


def _extract_from_history(history: List[Dict[str, str]]) -> Optional[str]:
    """Scan prior user messages newest-first for a mentioned ITEM."""
    for msg in reversed(history or []):
        if (msg.get("role") or "").lower() != "user":
            continue
        item = _extract_item(msg.get("content") or "")
        if item:
            return item
    return None


def _extract_table_name(text: str) -> Optional[str]:
    m = _TABLE_NAME_RE.search(text)
    if m:
        # Strip trailing timestamp
        name = re.sub(r"-\d{14}$", "", m.group(1)).lower()
        return name
    # fallback: words after "table" keyword
    m2 = re.search(r"\btable\s+([a-z_][a-z0-9_]*)", text, re.IGNORECASE)
    return m2.group(1).lower() if m2 else None


# ---------------------------------------------------------------------------
# Ollama LLM fallback classifier
# ---------------------------------------------------------------------------

def _call_ollama_router(question: str) -> Optional[str]:
    """
    Ask Ollama to classify intent when keyword confidence is low.

    Strategy (version-safe):
      1. Try with JSON schema `format` (Ollama >= 0.3.9) — enum-constrained,
         guarantees response is exactly one valid intent name.
      2. On any failure (older Ollama, parse error, network) — retry without
         format and fall back to substring matching.

    The enum is built dynamically from INTENT_CATALOG so it never goes stale.
    """
    valid_intents = list(INTENT_CATALOG.keys())
    intent_lines = "\n".join(
        f"- {name}: {spec['description']}"
        for name, spec in INTENT_CATALOG.items()
    )
    # With format: no need to say "return only" — schema enforces it
    prompt_structured = (
        f"Classify this planning question into exactly one intent.\n\n"
        f"Intents:\n{intent_lines}\n\n"
        f"Question: {question}"
    )
    # Without format: explicit instruction needed
    prompt_plain = (
        f"Classify this planning question into exactly one intent.\n"
        f"Return ONLY the intent name, nothing else.\n\n"
        f"Intents:\n{intent_lines}\n\n"
        f"Question: {question}\nIntent:"
    )

    format_schema = {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": valid_intents,
            }
        },
        "required": ["intent"],
    }

    for use_format in (True, False):
        base = {
            "model": _OLLAMA_ROUTER_MODEL,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a planning query classifier.",
                },
                {
                    "role": "user",
                    "content": prompt_structured if use_format else prompt_plain,
                },
            ],
            "options": {"temperature": 0.0},
        }
        if use_format:
            base["format"] = format_schema

        data = json.dumps(base).encode("utf-8")
        req = urllib_request.Request(
            f"{_OLLAMA_BASE_URL}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=20) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            content = ((body.get("message") or {}).get("content") or "").strip()
            if not content:
                continue

            if use_format:
                # Schema-constrained path — parse JSON and trust the enum
                parsed = json.loads(content)
                intent = (parsed.get("intent") or "").strip().lower()
                if intent in INTENT_CATALOG:
                    return intent          # clean, validated result
                # Ollama returned JSON but intent not in catalog (shouldn't happen)
                continue                   # retry without format
            else:
                # Plain-text fallback path — substring match
                raw = content.lower()
                if raw in INTENT_CATALOG:
                    return raw
                return next((k for k in INTENT_CATALOG if k in raw), None)

        except (error.URLError, TimeoutError, json.JSONDecodeError, OSError, KeyError):
            if use_format:
                continue   # schema not supported — retry without format
            return None    # both attempts failed

    return None


def llm_classify(state: RouterState) -> Dict[str, Any]:
    """LLM fallback node — fires when keyword confidence is below threshold."""
    matched_intent = _call_ollama_router(state["question"])
    # _call_ollama_router already validates against INTENT_CATALOG
    # so no additional substring matching needed here

    if not matched_intent or matched_intent == "conversational":
        return {
            "llm_fallback_used": True,
            "matched_terms": ["llm_fallback:no_change"],
        }

    spec = INTENT_CATALOG[matched_intent]
    return {
        "intent": matched_intent,
        "domain": spec.get("domain"),
        "workflow": spec["workflow"],
        "confidence": 0.5,
        "conflict": False,
        "conflicting_intents": [],
        "llm_fallback_used": True,
        "matched_terms": [f"llm_classified:{matched_intent}"],
    }


def _route_after_classify(state: RouterState) -> str:
    confidence = state.get("confidence", 0.0)
    question = state.get("question", "")
    if confidence < _ROUTER_CONFIDENCE_THRESHOLD and len(question) > 15:
        return "llm_classify"
    return "resolve_entities"


# ---------------------------------------------------------------------------
# Node 1 – classify_intent
# ---------------------------------------------------------------------------

def classify_intent(state: RouterState) -> Dict[str, Any]:
    ql = state["question_lower"]
    scores: Dict[str, float] = {}
    all_matched: List[str] = []

    for intent_name, spec in INTENT_CATALOG.items():
        terms = spec.get("terms") or []
        score = 0.0
        matched: List[str] = []
        for term in terms:
            if term in ql:
                # longer phrases carry more weight
                weight = 1.0 + 0.5 * (len(term.split()) - 1)
                score += weight
                matched.append(term)
        scores[intent_name] = score
        all_matched.extend(matched)

    # Sort by (score DESC, priority DESC)
    ranked = sorted(
        scores.items(),
        key=lambda kv: (kv[1], INTENT_CATALOG[kv[0]]["priority"]),
        reverse=True,
    )

    top_intent, top_score = ranked[0]
    second_intent, second_score = ranked[1] if len(ranked) > 1 else ("conversational", 0.0)

    # Fall back to conversational if nothing matched
    if top_score == 0.0:
        top_intent = "conversational"
        top_score = 0.0

    confidence = min(1.0, top_score / 4.0)
    conflict = (
        top_score > 0
        and second_score > 0
        and abs(top_score - second_score) < 1.0
        and INTENT_CATALOG[top_intent]["workflow"] != INTENT_CATALOG[second_intent]["workflow"]
    )
    conflicting = [second_intent] if conflict else []

    spec = INTENT_CATALOG[top_intent]
    return {
        "intent_scores": scores,
        "intent": top_intent,
        "domain": spec.get("domain"),
        "workflow": spec["workflow"],
        "matched_terms": list(set(all_matched)),
        "confidence": round(confidence, 3),
        "conflict": conflict,
        "conflicting_intents": conflicting,
        "llm_fallback_used": False,
    }


# ---------------------------------------------------------------------------
# Node 2 – resolve_entities
# ---------------------------------------------------------------------------

def resolve_entities(state: RouterState) -> Dict[str, Any]:
    q = state["question"]
    ql = state["question_lower"]
    history = state.get("history") or []
    ctx_week = state.get("context_week_id")
    ctx_scenario = state.get("context_scenario_id")
    ctx_scope = state.get("context_scope") or {}

    entities: Dict[str, Optional[str]] = {
        "item": None,
        "site": None,
        "week_id": None,
        "scenario_id": None,
        "table_name": None,
    }
    sources: Dict[str, str] = {}

    # ITEM
    item = _extract_item(q)
    if item:
        entities["item"] = item
        sources["item"] = "question"
    else:
        # reference phrases → look in history
        ref_terms = ["for the item", "that item", "this item", "same item", "the item"]
        demand_terms = ["demand", "supply", "unmet", "root cause", "lineage", "details"]
        if any(t in ql for t in ref_terms) or any(t in ql for t in demand_terms):
            hist_item = _extract_from_history(history)
            if hist_item:
                entities["item"] = hist_item
                sources["item"] = "history"

    # SITE / PLANT
    m = _SITE_RE.search(q)
    if m:
        entities["site"] = m.group(1).strip()
        sources["site"] = "question"
    elif ctx_scope.get("site"):
        entities["site"] = ctx_scope["site"]
        sources["site"] = "context"

    # WEEK
    m = _WEEK_RE.search(q)
    if m:
        entities["week_id"] = m.group(1).strip()
        sources["week_id"] = "question"
    elif ctx_week:
        entities["week_id"] = ctx_week
        sources["week_id"] = "context"

    # SCENARIO
    m = _SCENARIO_RE.search(q)
    if m:
        entities["scenario_id"] = m.group(1).strip()
        sources["scenario_id"] = "question"
    elif ctx_scenario:
        entities["scenario_id"] = ctx_scenario
        sources["scenario_id"] = "context"

    # TABLE NAME
    if state.get("intent") == "table_explain":
        tname = _extract_table_name(q)
        if tname:
            entities["table_name"] = tname
            sources["table_name"] = "question"

    return {
        "entities": entities,
        "entity_sources": sources,
    }


# ---------------------------------------------------------------------------
# Node 3 – check_slots
# ---------------------------------------------------------------------------

def check_slots(state: RouterState) -> Dict[str, Any]:
    intent = state.get("intent", "conversational")
    entities = state.get("entities") or {}
    spec = INTENT_CATALOG.get(intent, INTENT_CATALOG["conversational"])
    required = spec.get("required_slots") or []

    missing = [slot for slot in required if not entities.get(slot)]

    if not missing:
        return {
            "missing_slots": [],
            "needs_clarification": False,
            "clarification": None,
        }

    # Build clarification payload for the first missing slot
    first_missing = missing[0]
    template = SLOT_CLARIFICATION.get(first_missing, {
        "question": f"Please provide the missing {first_missing} to continue.",
        "examples": [],
    })

    return {
        "missing_slots": missing,
        "needs_clarification": True,
        "clarification": {
            "missing_slot": first_missing,
            "intent": intent,
            "workflow": spec["workflow"],
            **template,
        },
    }


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------

def _build_router_graph() -> Any:
    builder: StateGraph = StateGraph(RouterState)
    builder.add_node("classify_intent", classify_intent)
    builder.add_node("llm_classify", llm_classify)
    builder.add_node("resolve_entities", resolve_entities)
    builder.add_node("check_slots", check_slots)
    builder.set_entry_point("classify_intent")
    builder.add_conditional_edges(
        "classify_intent",
        _route_after_classify,
        {"llm_classify": "llm_classify", "resolve_entities": "resolve_entities"},
    )
    builder.add_edge("llm_classify", "resolve_entities")
    builder.add_edge("resolve_entities", "check_slots")
    builder.add_edge("check_slots", END)
    return builder.compile()


_router_graph = _build_router_graph()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def route_question(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    week_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Classify a planner question and resolve slot entities.

    Returns the full RouterState as a dict (IntentMetadata).
    The caller (dispatcher in analyzer.py) uses meta["intent"],
    meta["entities"], meta["needs_clarification"], and meta["clarification"]
    to decide which workflow to invoke.
    """
    initial: RouterState = {
        "question": (question or "").strip(),
        "question_lower": (question or "").lower().strip(),
        "history": list(history or []),
        "context_week_id": week_id,
        "context_scenario_id": scenario_id,
        "context_scope": dict(scope or {}),
        # filled by nodes
        "intent_scores": {},
        "intent": "conversational",
        "domain": None,
        "workflow": "ConversationalCopilot",
        "matched_terms": [],
        "confidence": 0.0,
        "conflict": False,
        "conflicting_intents": [],
        "llm_fallback_used": False,
        "entities": {},
        "entity_sources": {},
        "missing_slots": [],
        "needs_clarification": False,
        "clarification": None,
    }
    return dict(_router_graph.invoke(initial))
