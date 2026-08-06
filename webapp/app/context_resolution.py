from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

LOGGER = logging.getLogger(__name__)

MAX_CONTEXT_TURNS = 10
CONTEXT_TIMEOUT_MINUTES = 30

_FOLLOWUP_PATTERNS = [
    r"^why\??$",
    r"what caused (it|that|this)\??",
    r"explain more\.?$",
    r"can you elaborate\??",
    r"what is the reason\??",
    r"why did (it|that|this) happen\??",
    r"was capacity the issue\??",
    r"which constraint\??",
    r"what can i do about (it|that|this)\??",
    r"recommend actions\.?$",
    r"how can this be fixed\??",
    r"can you investigate further\??",
    r"find the root cause\.?$",
    r"can you find the exact reason for the unmet quantity\??",
]

_PRONOUN_PATTERN = re.compile(r"\b(it|that|this|those|them)\b", re.IGNORECASE)
_ITEM_PATTERN = re.compile(r"\b(?:item|dmditem)\s*[:=#-]?\s*([A-Za-z0-9_.-]{4,})\b", re.IGNORECASE)
_PARTIAL_NUMERIC_ITEM_PATTERN = re.compile(r"\b(item|dmditem)\s*[:=#-]?\s*(\d{1,5})\b", re.IGNORECASE)
_LOC_PATTERN = re.compile(r"\b(?:loc|location|site|plant)\s*[:=#-]?\s*([A-Za-z0-9_.-]{2,})\b", re.IGNORECASE)
_RES_PATTERN = re.compile(r"\b(?:res|resource)\s*[:=#-]?\s*([A-Za-z0-9_.-]{2,})\b", re.IGNORECASE)
_SUPPLIER_PATTERN = re.compile(r"\b(?:supplier|vendor)\s*[:=#-]?\s*([A-Za-z0-9_.-]{2,})\b", re.IGNORECASE)


class SessionContext(BaseModel):
    session_id: str
    current_item: Optional[str] = None
    current_location: Optional[str] = None
    current_resource: Optional[str] = None
    current_week_id: Optional[str] = None
    current_scenario_id: Optional[str] = None
    current_supplier: Optional[str] = None
    current_analysis_topic: Optional[str] = None
    current_constraint_type: Optional[str] = None
    last_intent: Optional[str] = None
    last_entities: Dict[str, Any] = Field(default_factory=dict)
    last_retrieval_plan: Dict[str, Any] = Field(default_factory=dict)
    last_files_used: List[str] = Field(default_factory=list)
    last_kpis: List[str] = Field(default_factory=list)
    last_response_summary: Optional[str] = None
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FollowUpDetectionResult(BaseModel):
    is_followup: bool
    confidence: float


class ContextResolutionResult(BaseModel):
    original_query: str
    resolved_query: str
    context_used: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    follow_up_detected: bool = False


class FollowUpDetector:
    def __init__(self) -> None:
        self._patterns = [re.compile(p, re.IGNORECASE) for p in _FOLLOWUP_PATTERNS]

    def detect(self, query: str, session_context: SessionContext) -> FollowUpDetectionResult:
        q = (query or "").strip().lower()
        if not q:
            return FollowUpDetectionResult(is_followup=False, confidence=0.0)

        for pattern in self._patterns:
            if pattern.search(q):
                return FollowUpDetectionResult(is_followup=True, confidence=0.95)

        has_pronouns = bool(_PRONOUN_PATTERN.search(q))
        followup_terms = [
            "reason",
            "cause",
            "caused",
            "elaborate",
            "explain more",
            "investigate",
            "root cause",
            "exact reason",
            "unmet quantity",
            "sku exception",
            "sku exceptions",
            "exception",
            "exceptions",
        ]
        has_followup_terms = any(term in q for term in followup_terms)
        has_recent_context = any(
            [
                session_context.current_item,
                session_context.current_location,
                session_context.current_resource,
                session_context.current_analysis_topic,
                session_context.current_constraint_type,
            ]
        )

        if has_pronouns and has_recent_context:
            return FollowUpDetectionResult(is_followup=True, confidence=0.85)

        explicit = _extract_explicit_entities(q)
        has_explicit = any(explicit.values())
        if has_followup_terms and has_recent_context and not has_explicit:
            return FollowUpDetectionResult(is_followup=True, confidence=0.9)

        return FollowUpDetectionResult(is_followup=False, confidence=0.2)


class ContextStore:
    def __init__(self) -> None:
        self._store: Dict[str, SessionContext] = {}
        self._lock = threading.Lock()

    def get_or_create(self, session_id: Optional[str]) -> SessionContext:
        sid = (session_id or "").strip() or str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        with self._lock:
            return self._get_or_create_unlocked(sid, now)

    def _get_or_create_unlocked(self, sid: str, now: datetime) -> SessionContext:
        ctx = self._store.get(sid)
        if ctx is None:
            ctx = SessionContext(session_id=sid)
            self._store[sid] = ctx
            return ctx

        if self._is_expired(ctx, now):
            ctx = SessionContext(session_id=sid)
            self._store[sid] = ctx
            return ctx
        return ctx

    def reset(self, session_id: str) -> SessionContext:
        sid = (session_id or "").strip() or str(uuid.uuid4())
        with self._lock:
            ctx = SessionContext(session_id=sid)
            self._store[sid] = ctx
            return ctx

    def update_after_query(
        self,
        session_id: str,
        *,
        entities: Optional[Dict[str, Any]] = None,
        last_intent: Optional[str] = None,
        last_retrieval_plan: Optional[Dict[str, Any]] = None,
        last_files_used: Optional[List[str]] = None,
        last_kpis: Optional[List[str]] = None,
        response_summary: Optional[str] = None,
        user_query: Optional[str] = None,
        resolved_query: Optional[str] = None,
    ) -> SessionContext:
        now = datetime.now(timezone.utc)
        sid = (session_id or "").strip() or str(uuid.uuid4())
        with self._lock:
            ctx = self._get_or_create_unlocked(sid, now)

            if entities:
                current_item = _coalesce_entity(entities, ["item", "ITEM", "demand_item", "demand_id"])
                current_location = _coalesce_entity(entities, ["location", "loc", "site", "plant"])
                current_resource = _coalesce_entity(entities, ["resource", "res"])
                current_week_id = _coalesce_entity(entities, ["week_id", "capture_wk"])
                current_scenario_id = _coalesce_entity(entities, ["scenario_id", "simulation_name"])
                current_supplier = _coalesce_entity(entities, ["supplier", "vendor"])
                current_constraint_type = _coalesce_entity(entities, ["constraint", "constraint_type"])
                topic = _coalesce_entity(entities, ["analysis_topic", "topic"])

                if current_item:
                    ctx.current_item = str(current_item)
                if current_location:
                    ctx.current_location = str(current_location)
                if current_resource:
                    ctx.current_resource = str(current_resource)
                if current_week_id:
                    ctx.current_week_id = str(current_week_id)
                if current_scenario_id:
                    ctx.current_scenario_id = str(current_scenario_id)
                if current_supplier:
                    ctx.current_supplier = str(current_supplier)
                if current_constraint_type:
                    ctx.current_constraint_type = str(current_constraint_type)
                if topic:
                    ctx.current_analysis_topic = str(topic)
                ctx.last_entities = dict(entities)

            if last_intent:
                ctx.last_intent = str(last_intent)

            if last_retrieval_plan:
                ctx.last_retrieval_plan = dict(last_retrieval_plan)

            if last_files_used is not None:
                ctx.last_files_used = [str(f) for f in last_files_used if str(f).strip()]

            if last_kpis is not None:
                ctx.last_kpis = [str(k) for k in last_kpis if str(k).strip()]

            if response_summary:
                ctx.last_response_summary = str(response_summary)[:500]

            if user_query:
                ctx.conversation_history.append({"role": "user", "content": str(user_query)})
            if resolved_query and resolved_query != user_query:
                ctx.conversation_history.append({"role": "system", "content": f"Resolved query: {resolved_query}"})
            if response_summary:
                ctx.conversation_history.append({"role": "assistant", "content": str(response_summary)[:500]})

            if len(ctx.conversation_history) > (MAX_CONTEXT_TURNS * 3):
                ctx.conversation_history = ctx.conversation_history[-(MAX_CONTEXT_TURNS * 3):]

            if _turn_count(ctx.conversation_history) > MAX_CONTEXT_TURNS:
                ctx = SessionContext(session_id=sid)
                self._store[sid] = ctx
                return ctx

            ctx.updated_at = now
            self._store[sid] = ctx
            return ctx

    @staticmethod
    def _is_expired(ctx: SessionContext, now: datetime) -> bool:
        timeout = timedelta(minutes=CONTEXT_TIMEOUT_MINUTES)
        if (now - ctx.updated_at) > timeout:
            return True
        if _turn_count(ctx.conversation_history) > MAX_CONTEXT_TURNS:
            return True
        return False


class ContextResolver:
    def __init__(self, detector: Optional[FollowUpDetector] = None) -> None:
        self._detector = detector or FollowUpDetector()

    def resolve(self, query: str, session_context: SessionContext) -> ContextResolutionResult:
        start = time.perf_counter()
        original_query = (query or "").strip()
        resolved_query = original_query
        context_used: List[str] = []

        followup = self._detector.detect(original_query, session_context)

        if followup.is_followup and session_context.current_item:
            # Keep canonical item ID on follow-ups like "item 100".
            if _PARTIAL_NUMERIC_ITEM_PATTERN.search(resolved_query):
                resolved_query = _PARTIAL_NUMERIC_ITEM_PATTERN.sub(
                    f"item {session_context.current_item}",
                    resolved_query,
                    count=1,
                )
                context_used.append("current_item")

        explicit = _extract_explicit_entities(resolved_query)
        inferred_topic = _infer_topic(original_query)

        if not explicit.get("item") and session_context.current_item and (
            followup.is_followup or _mentions_demand_or_reason(original_query)
        ):
            resolved_query = _append_phrase_if_missing(resolved_query, f"for item {session_context.current_item}")
            context_used.append("current_item")

        if not explicit.get("location") and session_context.current_location and _mentions_location_need(original_query):
            resolved_query = _append_phrase_if_missing(resolved_query, f"at location {session_context.current_location}")
            context_used.append("current_location")

        if not explicit.get("resource") and session_context.current_resource and _mentions_resource_need(original_query):
            resolved_query = _append_phrase_if_missing(resolved_query, f"for resource {session_context.current_resource}")
            context_used.append("current_resource")

        if not inferred_topic and session_context.current_analysis_topic and _mentions_topic_need(original_query):
            resolved_query = _append_phrase_if_missing(
                resolved_query,
                f"for {session_context.current_analysis_topic.lower().replace('_', ' ')}",
            )
            context_used.append("current_analysis_topic")

        if _PRONOUN_PATTERN.search(resolved_query):
            replacement_parts = []
            if session_context.current_analysis_topic:
                replacement_parts.append(session_context.current_analysis_topic.lower().replace("_", " "))
            if session_context.current_item:
                replacement_parts.append(f"item {session_context.current_item}")
            pronoun_replacement = " ".join(replacement_parts).strip()
            if pronoun_replacement:
                resolved_query = _PRONOUN_PATTERN.sub(pronoun_replacement, resolved_query)
                context_used.append("pronoun_resolution")

        if _is_action_query(original_query) and session_context.current_item and "current_item" not in context_used:
            resolved_query = _append_phrase_if_missing(resolved_query, f"for item {session_context.current_item}")
            context_used.append("current_item")

        confidence = followup.confidence if context_used else 0.25
        duration_ms = (time.perf_counter() - start) * 1000.0

        LOGGER.info(
            "[ContextResolver] original=%r resolved=%r follow_up=%s context_used=%s resolution_ms=%.2f",
            original_query,
            resolved_query,
            followup.is_followup,
            context_used,
            duration_ms,
        )

        return ContextResolutionResult(
            original_query=original_query,
            resolved_query=resolved_query,
            context_used=context_used,
            confidence=confidence,
            follow_up_detected=followup.is_followup,
        )


def _coalesce_entity(entities: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    for key in keys:
        value = entities.get(key)
        if value not in {None, ""}:
            return value
    return None


def _extract_explicit_entities(query: str) -> Dict[str, Optional[str]]:
    q = query or ""
    item = _ITEM_PATTERN.search(q)
    item_val = item.group(1) if item else None
    # Prevent partial numeric IDs like "item 100" from overriding preserved context.
    if item_val and item_val.isdigit() and len(item_val) < 6:
        item_val = None
    location = _LOC_PATTERN.search(q)
    resource = _RES_PATTERN.search(q)
    supplier = _SUPPLIER_PATTERN.search(q)
    return {
        "item": item_val,
        "location": location.group(1) if location else None,
        "resource": resource.group(1) if resource else None,
        "supplier": supplier.group(1) if supplier else None,
    }


def _append_phrase_if_missing(query: str, phrase: str) -> str:
    q = (query or "").strip()
    p = (phrase or "").strip()
    if not p:
        return q
    if p.lower() in q.lower():
        return q
    if q.endswith("?"):
        return f"{q[:-1]} {p}?"
    return f"{q} {p}".strip()


def _infer_topic(query: str) -> Optional[str]:
    q = (query or "").lower()
    if "unmet" in q or "demand met" in q or "demand" in q:
        return "UnmetDemand"
    if "capacity" in q:
        return "CapacityConstraint"
    if "root cause" in q or "reason" in q:
        return "RootCause"
    return None


def _mentions_demand_or_reason(query: str) -> bool:
    q = (query or "").lower()
    keywords = ["demand", "unmet", "reason", "caused", "cause", "root cause", "why", "issue", "sku", "exception"]
    return any(k in q for k in keywords)


def _mentions_location_need(query: str) -> bool:
    q = (query or "").lower()
    return any(k in q for k in ["location", "site", "plant", "there"])


def _mentions_resource_need(query: str) -> bool:
    q = (query or "").lower()
    return any(k in q for k in ["resource", "capacity", "constraint"])


def _mentions_topic_need(query: str) -> bool:
    q = (query or "").lower()
    return any(k in q for k in ["why", "reason", "elaborate", "explain", "more", "issue"])


def _is_action_query(query: str) -> bool:
    q = (query or "").lower()
    return any(k in q for k in ["what can i do", "recommend", "how can", "fix", "actions"]) and "item" not in q


def _turn_count(history: List[Dict[str, str]]) -> int:
    return len([h for h in history if (h or {}).get("role") == "user"])


_CONTEXT_STORE = ContextStore()
_CONTEXT_RESOLVER = ContextResolver()


def get_context_store() -> ContextStore:
    return _CONTEXT_STORE


def get_context_resolver() -> ContextResolver:
    return _CONTEXT_RESOLVER
