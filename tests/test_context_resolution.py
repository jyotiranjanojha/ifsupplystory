from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from webapp.app.context_resolution import (
    CONTEXT_TIMEOUT_MINUTES,
    ContextResolver,
    FollowUpDetector,
    SessionContext,
    get_context_store,
)
from webapp.app.analyzer import _resolve_chat_item
from webapp.app.main import app


def test_followup_detection_positive():
    detector = FollowUpDetector()
    ctx = SessionContext(session_id="s1", current_item="100000000004", current_analysis_topic="UnmetDemand")
    out = detector.detect("What caused it?", ctx)
    assert out.is_followup is True
    assert out.confidence >= 0.85


def test_item_resolution_from_context():
    resolver = ContextResolver()
    ctx = SessionContext(session_id="s2", current_item="100000000004", current_analysis_topic="UnmetDemand")
    out = resolver.resolve("Can you find the exact reason for the unmet quantity?", ctx)
    assert "item 100000000004" in out.resolved_query.lower()
    assert "current_item" in out.context_used


def test_location_resolution_from_context():
    resolver = ContextResolver()
    ctx = SessionContext(session_id="s3", current_item="100000000004", current_location="1004")
    out = resolver.resolve("What happened there?", ctx)
    assert "location 1004" in out.resolved_query.lower()
    assert "current_location" in out.context_used


def test_constraint_resolution_from_context():
    resolver = ContextResolver()
    ctx = SessionContext(
        session_id="s4",
        current_item="100000000004",
        current_constraint_type="Capacity",
        current_analysis_topic="UnmetDemand",
    )
    out = resolver.resolve("Was capacity the issue?", ctx)
    assert "item 100000000004" in out.resolved_query.lower()
    assert "current_item" in out.context_used


def test_conversation_continuation_uses_previous_item():
    store = get_context_store()
    sid = "conv-seq"
    store.reset(sid)
    store.update_after_query(
        sid,
        entities={"item": "100000000004", "analysis_topic": "UnmetDemand"},
        last_intent="item_demand_supply",
        response_summary="Demand was partially met.",
        user_query="Check if demand is met for item 100000000004",
        resolved_query="Check if demand is met for item 100000000004",
    )

    resolver = ContextResolver()
    ctx = store.get_or_create(sid)
    out = resolver.resolve("Can you find the exact reason for the unmet quantity?", ctx)

    assert out.resolved_query == "Can you find the exact reason for the unmet quantity for item 100000000004?"


def test_context_expiration_by_timeout():
    store = get_context_store()
    sid = "expire-timeout"
    ctx = store.reset(sid)
    ctx.current_item = "100000000004"
    ctx.updated_at = datetime.now(timezone.utc) - timedelta(minutes=CONTEXT_TIMEOUT_MINUTES + 1)

    fresh = store.get_or_create(sid)
    assert fresh.current_item is None
    assert fresh.conversation_history == []


def test_context_reset_clears_state():
    store = get_context_store()
    sid = "reset-case"
    store.update_after_query(
        sid,
        entities={"item": "100000000004"},
        last_intent="item_demand_supply",
        response_summary="sample",
        user_query="Q1",
        resolved_query="Q1",
    )
    reset_ctx = store.reset(sid)
    assert reset_ctx.current_item is None
    assert reset_ctx.last_intent is None
    assert reset_ctx.conversation_history == []


def test_context_api_resolve_and_reset():
    client = TestClient(app)
    sid = "api-context-1"

    # Seed context through current endpoint lifecycle.
    _ = client.get(f"/api/context/current?session_id={sid}")

    store = get_context_store()
    store.update_after_query(
        sid,
        entities={"item": "100000000004", "analysis_topic": "UnmetDemand"},
        last_intent="item_demand_supply",
        response_summary="seed",
        user_query="seed",
        resolved_query="seed",
    )

    resp = client.post("/api/context/resolve", json={"query": "What caused it?", "session_id": sid})
    assert resp.status_code == 200
    payload = resp.json()
    assert "item 100000000004" in payload["resolved_query"].lower()

    reset = client.post("/api/context/reset", json={"session_id": sid})
    assert reset.status_code == 200
    now_ctx = client.get(f"/api/context/current?session_id={sid}")
    assert now_ctx.status_code == 200
    assert now_ctx.json().get("current_item") is None


def test_followup_sku_exceptions_keeps_full_item_identifier():
    history = [
        {"role": "user", "content": "Check if demand is met for item 100000000004"},
        {"role": "assistant", "content": "Demand is partially met."},
        {"role": "user", "content": "Why unmet?"},
    ]

    out = _resolve_chat_item("Which SKU exceptions?", history)

    assert out["selected_item"] == "100000000004"
    assert out["source"] == "history"


def test_context_store_inherits_location_resource_and_scenario_for_followups():
    store = get_context_store()
    sid = "inherit-all-entities"
    store.reset(sid)

    store.update_after_query(
        sid,
        entities={
            "item": "100000000004",
            "location": "1004",
            "resource": "RES_A",
            "week_id": "202547",
            "scenario_id": "CONSTRAINED",
            "analysis_topic": "UnmetDemand",
        },
        last_intent="root_cause",
        response_summary="seed",
        user_query="Check if demand is met for item 100000000004",
        resolved_query="Check if demand is met for item 100000000004",
    )

    ctx = store.get_or_create(sid)
    assert ctx.current_item == "100000000004"
    assert ctx.current_location == "1004"
    assert ctx.current_resource == "RES_A"
    assert ctx.current_week_id == "202547"
    assert ctx.current_scenario_id == "CONSTRAINED"


def test_partial_numeric_item_does_not_override_preserved_item_context():
    resolver = ContextResolver()
    ctx = SessionContext(session_id="partial-item", current_item="100000000004", current_analysis_topic="UnmetDemand")

    out = resolver.resolve("Which SKU exceptions for item 100?", ctx)

    assert "item 100000000004" in out.resolved_query.lower()
    assert "item 100?" not in out.resolved_query.lower()
