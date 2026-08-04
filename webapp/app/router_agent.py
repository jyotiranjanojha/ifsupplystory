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

# ── Router LLM config — resolved lazily from LLM_CONFIG at call time ─────────
_ROUTER_BASE_URL_OVERRIDE = os.getenv("OLLAMA_BASE_URL")   # explicit env override only
_ROUTER_MODEL_OVERRIDE    = os.getenv("OLLAMA_MODEL")      # explicit env override only


def _get_router_llm_config() -> tuple:
    """Return (base_url, model) for intent classification using the active LLM_CONFIG."""
    try:
        from .analyzer import LLM_CONFIG  # lazy import avoids circular dep
        base_url = _ROUTER_BASE_URL_OVERRIDE or LLM_CONFIG.get("base_url") or "http://127.0.0.1:11434"
        model    = _ROUTER_MODEL_OVERRIDE    or LLM_CONFIG.get("model")    or "gemma3:latest"
    except Exception:
        base_url = _ROUTER_BASE_URL_OVERRIDE or "http://127.0.0.1:11434"
        model    = _ROUTER_MODEL_OVERRIDE    or "gemma3:latest"
    return base_url, model
# High threshold: only bypass the LLM when keyword confidence is very strong.
# This makes routing LLM-first for almost all questions.
_ROUTER_BYPASS_THRESHOLD = float(os.getenv("OLLAMA_ROUTER_CONFIDENCE_THRESHOLD", "0.75"))

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
        "description": "Demand-supply root cause and lineage analysis for an item, including late/short demand, early fulfillment, and fill rate drops",
        "terms": [
            "root cause", "why unmet", "unmet", "why demand", "why did demand",
            "demand miss", "missed demand", "explain demand", "lineage",
            "genealogy", "pegging",
            # unmet / not-met phrasing
            "not met", "demand not met", "why was demand", "why demand not",
            "demand shortage", "supply gap", "why did not demand",
            # lateness / shortness
            "demand late", "demand short", "late demand", "short demand",
            "why late", "why short", "demand got late", "demand got short",
            "demand delayed", "late fulfillment", "short fulfillment",
            # early fulfillment
            "demand early", "demand met early", "met early", "why early",
            "fulfilled early", "demand fulfilled early",
            # fill rate root cause
            "fill rate drop", "fill rate dropping", "fill rate low",
            "why fill rate", "fill rate declining", "fill rate change",
            # resource / utilization root cause
            "why res", "res low", "utilization low", "res underload",
            "why utilization", "why resource",
        ],
        "required_slots": ["item"],
        "optional_slots": ["site", "week_id", "scenario_id"],
        "priority": 9,
        "workflow": "RootCause",
        "domain": None,
    },
    "item_demand_supply": {
        "description": "Demand vs supply details, fill rate, EOH (end-of-horizon inventory), and fulfillment status for a specific item",
        "terms": [
            "demand and supply", "demand vs supply", "supply situation",
            "demand situation", "share more details about demand vs supply",
            # fulfillment / met-demand phrasing
            "was met", "met or not", "demand met", "is demand met",
            "demand fulfilled", "demand status", "fulfillment status",
            "check demand", "demand check", "was demand", "demand was",
            "demand for item", "is the demand", "was the demand",
            "demand not fulfilled", "demand not met",
            # EOH / projected inventory
            "eoh", "end of horizon", "end-of-horizon", "projected inventory",
            "inventory position", "horizon inventory", "closing inventory",
            "projected stock", "eoh for",
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
        "description": "Fulfillment domain: fill rate trends, OTIF, late/short demand, unmet demand, backorders",
        "terms": [
            "fulfillment", "why didn't we ship", "why did not we ship",
            "why not shipped", "customer order not met", "fill rate", "otif",
            "stockout", "backorder", "shortage", "lost sales",
            # fill rate trends / changes
            "fill rates dropping", "fill rates declining", "fill rate trend",
            "fill rates changing", "fill rate improving", "fill rate worsening",
            # late / short demand
            "demand got late", "demand got short", "late order", "short order",
            "demand lateness", "demand shortness", "late fulfillment",
        ],
        "required_slots": [],
        "optional_slots": ["site", "week_id", "scenario_id"],
        "priority": 7,
        "workflow": "DomainFocus",
        "domain": "Fulfillment",
    },
    "domain_generation": {
        "description": "Generation domain: resource utilization, why no planned orders, capacity, lead time, underloaded/overloaded resources",
        "terms": [
            "generation", "why didn't we build", "why did not we build",
            "why didn't we buy", "why did not we buy", "no planned orders",
            "planned order not generated", "lead time", "active forecast",
            # resource utilization
            "res utilization", "resource utilization", "res util",
            "utilization", "capacity utilization", "res load", "resource load",
            # underloaded / overloaded
            "underloaded", "overloaded", "res underloaded", "res overloaded",
            "resource underloaded", "resource overloaded",
            "underload horizon", "overload horizon",
            "why res utilization", "res utilization low", "res utilization high",
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
        "description": "Scenario comparison and delta analysis, including solve-over-solve and site mix changes",
        "terms": [
            "compare", "difference", "delta", "scenario compare", "versus", "vs",
            # solve-over-solve / run-over-run
            "solve over solve", "solve to solve", "run over run", "run to run",
            "solve run", "week over week", "period over period",
            "changing solve", "solve comparison", "plan comparison",
            # site mix
            "site mix", "site mix changing", "site mix shift", "mix change",
            "why site", "site shift", "location mix",
        ],
        "required_slots": [],
        "optional_slots": ["week_id", "base_scenario", "compare_scenario", "site"],
        "priority": 5,
        "workflow": "ScenarioCompare",
        "domain": None,
    },
    "insights": {
        "description": "Analytics insights: fill rate trends, capacity/resource utilization, EOH, demand-supply trends, underloaded horizons",
        "terms": [
            "insight", "fill rate", "capacity", "trend",
            "demand supply", "analytics",
            # resource utilization trends
            "res utilization", "resource utilization", "utilization trend",
            "capacity trend", "res load trend",
            # EOH / horizon inventory
            "eoh", "end of horizon", "end-of-horizon", "projected inventory",
            "horizon inventory",
            # underloaded/overloaded horizons
            "underloaded horizon", "overloaded horizon",
            "which horizon", "horizons underloaded", "horizons overloaded",
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

# BY ESP taxonomy overlay: keep these explicit so planner-facing intent labels are
# available while remaining backward-compatible with existing workflows.
INTENT_CATALOG.update({
    "DemandStatusLookup": {
        "description": "Independent demand status, lateness, partial and unmet checks.",
        "terms": [
            "demand status", "unmet demand", "late demand", "partial fulfillment",
            "dmd status", "customer demand status", "ship status",
        ],
        "required_slots": [],
        "optional_slots": ["item", "site", "week_id", "scenario_id"],
        "priority": 11,
        "workflow": "ItemDemandSupply",
        "domain": "Fulfillment",
    },
    "DemandSupplyPeggingExplain": {
        "description": "Demand-to-supply pegging and linkage explainability.",
        "terms": [
            "pegging", "demand supply link", "inddmd link", "order link",
            "which supply covers", "what supply serves demand",
        ],
        "required_slots": [],
        "optional_slots": ["item", "site", "week_id", "scenario_id"],
        "priority": 11,
        "workflow": "RootCause",
        "domain": "Fulfillment",
    },
    "CapacityConstraintExplain": {
        "description": "Resource overload/underload and capacity exception diagnosis.",
        "terms": [
            "capacity constraint", "resource constraint", "res exception", "utilization",
            "overutilized", "underloaded", "res load", "resprojstatic",
        ],
        "required_slots": [],
        "optional_slots": ["site", "week_id", "scenario_id"],
        "priority": 11,
        "workflow": "DomainFocus",
        "domain": "Generation",
    },
    "MaterialConstraintExplain": {
        "description": "BOM/component constraint and dependent demand propagation diagnosis.",
        "terms": [
            "material constraint", "component shortage", "dependent demand", "depdmd",
            "bom shortage", "subordinate shortage",
        ],
        "required_slots": [],
        "optional_slots": ["item", "site", "week_id", "scenario_id"],
        "priority": 11,
        "workflow": "RootCause",
        "domain": "Fulfillment",
    },
    "PlanOrderDecisionExplain": {
        "description": "Why planned production orders were/weren't generated.",
        "terms": [
            "planorder", "planned order", "production decision", "why plan generated",
            "why no planned order", "plan order decision",
        ],
        "required_slots": [],
        "optional_slots": ["item", "site", "week_id", "scenario_id"],
        "priority": 10,
        "workflow": "DomainFocus",
        "domain": "Generation",
    },
    "PlanPurchDecisionExplain": {
        "description": "Why planned purchase orders were/weren't generated.",
        "terms": [
            "planpurch", "planned purchase", "purchase decision", "purch method",
            "why no purchase plan", "why purchase generated",
        ],
        "required_slots": [],
        "optional_slots": ["item", "site", "week_id", "scenario_id"],
        "priority": 10,
        "workflow": "SqlQuery",
        "domain": "Generation",
    },
    "TransferDecisionExplain": {
        "description": "Why transfer/arrival plans were/weren't generated.",
        "terms": [
            "planarriv", "transfer decision", "arrival plan", "source dest",
            "why no transfer", "sourcing route",
        ],
        "required_slots": [],
        "optional_slots": ["item", "site", "week_id", "scenario_id"],
        "priority": 10,
        "workflow": "SqlQuery",
        "domain": "Generation",
    },
    "InventoryProjectionExplain": {
        "description": "Projected inventory, stockout and coverage explainability.",
        "terms": [
            "projected inventory", "inventory projection", "stockout", "skuprojstatic",
            "skustatstatic", "coverage duration", "constrained stock",
        ],
        "required_slots": [],
        "optional_slots": ["item", "site", "week_id", "scenario_id"],
        "priority": 10,
        "workflow": "ItemDemandSupply",
        "domain": "Fulfillment",
    },
    "AllocationPriorityExplain": {
        "description": "Allocation and priority-driven fulfillment behavior.",
        "terms": [
            "allocation", "priority", "customer tier", "demand group", "allocation horizon",
            "priority inversion",
        ],
        "required_slots": [],
        "optional_slots": ["item", "site", "week_id", "scenario_id"],
        "priority": 9,
        "workflow": "Insights",
        "domain": "Fulfillment",
    },
    "ForecastConsumptionExplain": {
        "description": "Forecast consumption and forecast-order fulfillment behavior.",
        "terms": [
            "forecast consumption", "fcstorder", "consumed forecast", "demand group forecast",
            "forecast fulfilled", "forecast unmet",
        ],
        "required_slots": [],
        "optional_slots": ["item", "site", "week_id", "scenario_id"],
        "priority": 9,
        "workflow": "Insights",
        "domain": "Fulfillment",
    },
    "ScenarioSolveComparison": {
        "description": "Simulation/solve comparison using output deltas.",
        "terms": [
            "solve version", "simulation compare", "scenario solve compare", "compare simulations",
            "across solve", "scenario delta",
        ],
        "required_slots": [],
        "optional_slots": ["week_id", "scenario_id", "site"],
        "priority": 9,
        "workflow": "ScenarioCompare",
        "domain": None,
    },
    "InputDataValidation": {
        "description": "Input and parameter quality and referential integrity validation.",
        "terms": [
            "input data validation", "ri check", "referential integrity", "master data validation",
            "parameter validation", "data readiness",
        ],
        "required_slots": [],
        "optional_slots": ["site", "week_id", "scenario_id"],
        "priority": 9,
        "workflow": "Validation",
        "domain": "DataHygiene",
    },
    "MasterDataLookup": {
        "description": "Lookup of master data definitions and entities.",
        "terms": [
            "item master", "location master", "customer master", "resource master",
            "master lookup", "describe master",
        ],
        "required_slots": [],
        "optional_slots": ["site"],
        "priority": 8,
        "workflow": "DatasetSummary",
        "domain": None,
    },
    "ParameterLookup": {
        "description": "Lookup of planning parameters and methods.",
        "terms": [
            "lead time", "lot size", "min ss", "max coverage", "production method",
            "purch method", "sourcing factor", "parameter lookup",
        ],
        "required_slots": [],
        "optional_slots": ["item", "site"],
        "priority": 8,
        "workflow": "DatasetSummary",
        "domain": None,
    },
    "Other": {
        "description": "Question outside supported BY ESP intents.",
        "terms": [],
        "required_slots": [],
        "optional_slots": [],
        "priority": 1,
        "workflow": "ConversationalCopilot",
        "domain": None,
    },
})

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

# Words that must never be treated as an item identifier
_ITEM_KEYWORD_BLOCKLIST = frozenset({
    "item", "for", "the", "a", "an", "this", "that", "all", "any",
    "some", "met", "not", "was", "check", "demand", "supply",
    "if", "is", "it", "in", "or", "of", "at", "by", "on",
    "product", "products",  # prevent 'for product' capturing the word itself
})

_ITEM_PATTERNS = [
    # Must come first — "demand for item XXXX" / "demand item XXXX"
    r"\bdemand\s+for\s+item\s*[:=]?\s*([A-Za-z0-9\-]+)",
    r"\bdemand\s+item\s*[:=]?\s*([A-Za-z0-9\-]+)",
    # "item XXXX" or "product XXXX"
    r"\bitem\s*[:=]?\s*([A-Za-z0-9\-]+)",
    r"\bproduct\s*[:=]?\s*([A-Za-z0-9\-]+)",
    # "for XXXXXXXX" (long token only)
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
            if val and val.lower() not in _ITEM_KEYWORD_BLOCKLIST:
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
    Classify the planning question intent using the active LLM (same model as main responses).

    Routes through LLM_CONFIG so the router always uses whatever model is configured,

    Strategy (version-safe):
      1. Try with JSON schema `format` (Ollama >= 0.3.9) — enum-constrained.
      2. On failure — retry without format and fall back to substring matching.
    """
    valid_intents = list(INTENT_CATALOG.keys())
    _router_base_url, _router_model = _get_router_llm_config()
    intent_lines = "\n".join(
        f"- {name}: {spec['description']}"
        for name, spec in INTENT_CATALOG.items()
    )

    few_shot_examples = (
        "Examples of natural language → intent mapping:\n"
        # Core demand / supply queries
        "- 'was the demand for item 100000000004 met?' → item_demand_supply\n"
        "- 'check if demand for item 100000000009 was fulfilled' → item_demand_supply\n"
        "- 'why is item 100000000004 unmet?' → root_cause\n"
        "- 'what is causing the supply shortage for 100000000009?' → root_cause\n"
        "- 'show me the BOM for item 100000000004' → bom_drill\n"
        "- 'compare constrained vs unconstrained scenario this week' → compare\n"
        "- 'validate master data for latest week' → validation\n"
        "- 'what does inddmdview contain?' → table_explain\n"
        "- 'run a SQL query to find all unmet demands' → sql_query\n"
        "- 'explain data quality issues' → domain_data_hygiene\n"
        "- 'why didn\\'t we ship customer order X?' → domain_fulfillment\n"
        "- 'why are there no planned orders for item Y?' → domain_generation\n"
        # BY Supply Planning natural language queries
        "- 'what is the fill rate for item 100000000004?' → insights\n"
        "- 'what is fill rate for the latest scenario?' → insights\n"
        "- 'why are fill rates dropping for product 100000000009?' → root_cause\n"
        "- 'why is fill rate declining this week?' → domain_fulfillment\n"
        "- 'why fill rates are changing solve over solve?' → compare\n"
        "- 'why did demand get late for item 100000000004?' → root_cause\n"
        "- 'why did demand get short for item 100000000009?' → root_cause\n"
        "- 'why demand got late or short?' → domain_fulfillment\n"
        "- 'what is resource utilization for RES_001?' → insights\n"
        "- 'show res utilization trend' → insights\n"
        "- 'why is res utilization low for resource RES_001?' → domain_generation\n"
        "- 'why is capacity utilization low?' → domain_generation\n"
        "- 'what are the horizons where res RES_001 is underloaded?' → insights\n"
        "- 'show periods when resource is underloaded or overloaded' → insights\n"
        "- 'why was demand met early for item 100000000004?' → root_cause\n"
        "- 'why is demand getting fulfilled ahead of schedule?' → root_cause\n"
        "- 'why is the site mix changing for product 100000000009?' → compare\n"
        "- 'why is site mix shifting between locations?' → compare\n"
        "- 'what is EOH for product 100000000004?' → item_demand_supply\n"
        "- 'show end of horizon inventory for item 100000000009' → item_demand_supply\n"
        "- 'what is the projected closing inventory?' → item_demand_supply\n"
        "- 'compare fill rate between this week and last week' → compare\n"
        "- 'is resource RES_001 overloaded in any horizon?' → domain_generation\n"
    )

    # With format: no need to say "return only" — schema enforces it
    prompt_structured = (
        f"You are a supply planning query classifier for Intel Foundry.\n"
        f"Classify this planning question into exactly one intent.\n\n"
        f"Intents:\n{intent_lines}\n\n"
        f"{few_shot_examples}\n"
        f"Question: {question}"
    )
    # Without format: explicit instruction needed
    prompt_plain = (
        f"You are a supply planning query classifier for Intel Foundry.\n"
        f"Classify this planning question into exactly one intent.\n"
        f"Return ONLY the intent name, nothing else.\n\n"
        f"Intents:\n{intent_lines}\n\n"
        f"{few_shot_examples}\n"
        f"Question: {question}\nIntent:"
    )

    # Single attempt — OpenAI /v1/chat/completions format
    payload = {
        "model": _router_model,
        "stream": False,
        "temperature": 0.0,
        "max_tokens": 20,
        "messages": [
            {"role": "system", "content": "You are a planning query classifier. Return ONLY the intent name, nothing else."},
            {"role": "user", "content": prompt_plain},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        f"{_router_base_url}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = (((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip().lower()
        if content in INTENT_CATALOG:
            return content
        return next((k for k in INTENT_CATALOG if k in content), None)
    except (error.URLError, TimeoutError, json.JSONDecodeError, OSError, KeyError):
        return None

    return None


def llm_classify(state: RouterState) -> Dict[str, Any]:
    """LLM classification node — now the primary routing path for most questions."""
    matched_intent = _call_ollama_router(state["question"])

    if matched_intent and matched_intent != "conversational":
        spec = INTENT_CATALOG[matched_intent]
        return {
            "intent": matched_intent,
            "domain": spec.get("domain"),
            "workflow": spec["workflow"],
            "confidence": 0.65,
            "conflict": False,
            "conflicting_intents": [],
            "llm_fallback_used": True,
            "matched_terms": [f"llm_classified:{matched_intent}"],
        }

    # LLM returned conversational or failed.
    # Promote the keyword result when it found something useful.
    keyword_intent = state.get("intent", "conversational")
    keyword_confidence = state.get("confidence", 0.0)
    if keyword_intent != "conversational" and keyword_confidence > 0.0:
        return {
            "llm_fallback_used": True,
            "matched_terms": [f"keyword_promoted:{keyword_intent}"],
            # Leave intent/workflow unchanged — keyword result wins
        }

    return {
        "llm_fallback_used": True,
        "matched_terms": ["llm_fallback:no_change"],
    }


def _route_after_classify(state: RouterState) -> str:
    confidence = state.get("confidence", 0.0)
    question = state.get("question", "")
    # LLM-first: skip the LLM only when keyword matching is very confident.
    # This lets natural language questions bypass rigid keyword lists.
    if confidence >= _ROUTER_BYPASS_THRESHOLD and len(question) > 0:
        return "resolve_entities"  # strong keyword match — no LLM needed
    return "llm_classify"          # everything else goes through the LLM first


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
