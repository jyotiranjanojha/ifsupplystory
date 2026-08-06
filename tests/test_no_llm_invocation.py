import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webapp.app import analyzer
from webapp.app import main as app_main


def _root_cause_workflow_result() -> dict:
    return {
        "Explainability Scope": {"week_id": "202547", "scenario_id": "CONSTRAINED", "demand_item": "100000000004", "scope": {}},
        "Demand and Supply Summary": {
            "demand_qty_total": 100.0,
            "scheduled_qty_total": 70.0,
            "unmet_qty": 30.0,
            "meet_status": "Partially Met",
        },
        "Constraint and Exception Analysis": {
            "capacity_exception_rows": 2,
            "capacity_overutil_qty": 12.0,
        },
        "Lineage and Linkage Findings": {
            "pegged_demand_qty": 100.0,
            "pegged_supply_qty": 70.0,
        },
        "Confirmed Findings": ["Demand exceeds scheduled supply."],
        "Root Causes": ["Unmet demand quantity is 30.000."],
        "Cause Attribution (BY ESP Expert View)": {"policy": "ConstraintAttributionPolicy.v1"},
    }


def _meta_for_workflow(workflow_name: str, workflow_result: dict, normalized_intent: str) -> dict:
    return {
        "workflow": workflow_name,
        "workflow_result": workflow_result,
        "context": {"week_id": "202547", "scenario_id": "CONSTRAINED"},
        "rag_evidence": None,
        "clarification": None,
        "follow_ups": [],
        "history_window": [],
        "grounding": {},
        "workflow_payload": {"router_metadata": {"normalized_intent": normalized_intent}},
        "retrieval_plan": {"business_rules": ["semantic layer is source of truth"]},
        "context_resolution": {
            "original_query": "q",
            "resolved_query": "q",
            "follow_up_detected": False,
            "context_used": [],
            "confidence": 1.0,
            "reason": "",
            "duration_ms": 1.0,
        },
    }


def _sku_exception_workflow_result() -> dict:
    return {
        "SKU Exception Analysis": {
            "item": "100000000004",
            "week_id": "202547",
            "scenario_id": "CONSTRAINED",
            "site": "1004",
            "exception_count": 6,
            "exception_codes": ["5529"],
            "exception_descriptions": ["BOM has an invalid parent SKU"],
            "affected_boms": ["50"],
            "affected_parent_skus": ["100"],
            "locations": ["1004"],
            "recommended_actions": [
                "Validate parent SKU mappings in the BOM",
                "Review the exception codes and owning planning rules",
                "Check the affected parent SKUs for BOM consistency",
            ],
            "sample_rows": [
                {
                    "exception": "5529",
                    "description": "BOM has an invalid parent SKU",
                    "loc": "1004",
                    "parent_item": "100",
                    "bomnum": "50",
                    "production_method": None,
                }
            ],
        },
        "Diagnostics": {
            "resolved_item": "100000000004",
            "week": "202547",
            "scenario": "CONSTRAINED",
            "exception_rows_found": 6,
            "source_table": "by_if_snop_out_skuexception-20251120065628.csv",
            "filters_applied": ["ITEM=100000000004", "CAPTURE_WK=202547", "SIMULATION_NAME~=CONSTRAINED"],
        },
    }


@pytest.mark.parametrize(
    "intent_name,workflow_name,workflow_result",
    [
        ("DemandAnalysis", "Item Demand Supply", {"Item": "100000000004", "Demand vs Supply Stats": {"demand_qty_total": 10.0, "scheduled_qty_total": 8.0, "unmet_qty": 2.0, "meet_status": "Partially Met"}}),
        ("InventoryAnalysis", "Inventory Projection", {"EOH": {"item": "100000000004", "eoh_qty": 25.0}}),
        ("ConstraintAnalysis", "Domain Generation", {"Constraint Signals": {"capacity_exception_rows": 1}}),
        ("RootCauseAnalysis", "Root Cause", _root_cause_workflow_result()),
        ("RecommendationRequest", "Recommendation", {"Recommendations": ["Increase planned order in week 202547"]}),
    ],
)
def test_no_llm_mode_skips_llm_for_all_core_intents(monkeypatch, intent_name, workflow_name, workflow_result):
    monkeypatch.setattr(analyzer, "NO_LLM_RESPONSE_MODE", True)

    llm_calls = {"count": 0}

    def _fake_llm(*_args, **_kwargs):
        llm_calls["count"] += 1
        return "unexpected"

    monkeypatch.setattr(analyzer, "_ollama_chat_with_model", _fake_llm)
    monkeypatch.setattr(
        analyzer,
        "build_grounded_chat_prompt",
        lambda *_args, **_kwargs: ("system", "prompt", _meta_for_workflow(workflow_name, workflow_result, intent_name)),
    )

    response = analyzer.run_chat_assistant(
        Path("."),
        "test question",
        "sid-no-llm",
        None,
        None,
        {},
        llm_enabled=True,
        llm_model=None,
        history=[],
    )

    assert llm_calls["count"] == 0
    assert response.get("LLM Invoked") is False
    assert response.get("NO_LLM_RESPONSE_MODE") is True


def test_root_cause_deterministic_payload_in_no_llm_chat(monkeypatch):
    monkeypatch.setattr(analyzer, "NO_LLM_RESPONSE_MODE", True)
    monkeypatch.setattr(
        analyzer,
        "build_grounded_chat_prompt",
        lambda *_args, **_kwargs: (
            "system",
            "prompt",
            _meta_for_workflow("Root Cause", _root_cause_workflow_result(), "RootCauseAnalysis"),
        ),
    )
    monkeypatch.setattr(analyzer, "_ollama_chat_with_model", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")))

    response = analyzer.run_chat_assistant(Path("."), "why unmet?", "sid-root", None, None, {}, llm_enabled=True, history=[])

    deterministic = response.get("Deterministic Result")
    assert isinstance(deterministic, dict)
    assert sorted(deterministic.keys()) == ["business_rules", "evidence", "kpis", "root_cause"]

    reply = response.get("Assistant Reply")
    assert "Root Cause Analysis" in reply
    assert "Item: 100000000004" in reply
    assert "Unmet Quantity: 30" in reply
    assert "lineage" not in reply.lower()
    assert 120 <= len(reply) <= 900


def test_root_cause_deterministic_payload_returns_full_json_when_detailed_requested(monkeypatch):
    monkeypatch.setattr(analyzer, "NO_LLM_RESPONSE_MODE", True)
    monkeypatch.setattr(
        analyzer,
        "build_grounded_chat_prompt",
        lambda *_args, **_kwargs: (
            "system",
            "prompt",
            _meta_for_workflow("Root Cause", _root_cause_workflow_result(), "RootCauseAnalysis"),
        ),
    )
    monkeypatch.setattr(analyzer, "_ollama_chat_with_model", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")))

    response = analyzer.run_chat_assistant(Path("."), "why unmet?", "sid-root", None, None, {}, llm_enabled=True, history=[], show_detailed_analysis=True)

    payload = json.loads(response.get("Assistant Reply"))
    assert payload["kpis"]["unmet_qty"] == 30.0
    assert "lineage" in payload["evidence"]


def test_sku_exception_deterministic_reply_is_planner_friendly(monkeypatch):
    monkeypatch.setattr(analyzer, "NO_LLM_RESPONSE_MODE", True)
    monkeypatch.setattr(
        analyzer,
        "build_grounded_chat_prompt",
        lambda *_args, **_kwargs: (
            "system",
            "prompt",
            _meta_for_workflow("SKU Exception Analysis", _sku_exception_workflow_result(), "sku_exception_analysis"),
        ),
    )
    monkeypatch.setattr(analyzer, "_ollama_chat_with_model", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")))

    response = analyzer.run_chat_assistant(Path("."), "Which SKU exceptions?", "sid-sku", None, None, {}, llm_enabled=True, history=[])

    reply = response.get("Assistant Reply")
    assert "SKU Exception Analysis" in reply
    assert "Exception Count: 6" in reply
    assert "Exception Codes: 5529" in reply
    assert "Affected BOMs: 50" in reply
    assert "Affected Parent SKUs: 100" in reply


def test_run_root_cause_explained_no_llm_skips_narrative_model(monkeypatch):
    monkeypatch.setattr(analyzer, "NO_LLM_RESPONSE_MODE", True)
    monkeypatch.setattr(analyzer, "run_root_cause", lambda *_args, **_kwargs: _root_cause_workflow_result())

    def _fail_llm(*_args, **_kwargs):
        raise AssertionError("LLM must not be invoked when NO_LLM_RESPONSE_MODE=true")

    monkeypatch.setattr(analyzer, "_ollama_chat_with_model", _fail_llm)

    result = analyzer.run_root_cause_explained(Path("."), None, None, None, {}, question_type="full_diagnosis")

    assert result.get("llm_invoked") is False
    assert result.get("mode") == "NO_LLM_RESPONSE_MODE"
    assert "root_cause" in result
    assert "evidence" in result
    assert "kpis" in result
    assert "business_rules" in result


@pytest.mark.parametrize(
    "intent_name,workflow_name,workflow_result,question,expected_contains",
    [
        (
            "DemandAnalysis",
            "Item Demand Supply",
            {"Item": "100000000004", "Demand vs Supply Stats": {"demand_qty_total": 10.0, "scheduled_qty_total": 8.0, "unmet_qty": 2.0, "meet_status": "Partially Met"}},
            "check if demand is met",
            "demand",
        ),
        (
            "InventoryAnalysis",
            "Inventory Projection",
            {"EOH": {"item": "100000000004", "eoh_qty": 25.0}},
            "inventory status",
            "eoh",
        ),
        (
            "ConstraintAnalysis",
            "Domain Generation",
            {"Constraint Signals": {"capacity_exception_rows": 1}},
            "constraints",
            "constraint",
        ),
        (
            "RootCauseAnalysis",
            "Root Cause",
            _root_cause_workflow_result(),
            "why unmet?",
            "root_cause",
        ),
        (
            "SkuExceptionAnalysis",
            "SKU Exception Analysis",
            _sku_exception_workflow_result(),
            "which SKU exceptions?",
            "sku exception analysis",
        ),
        (
            "RecommendationRequest",
            "Recommendation",
            {"Recommendations": ["Increase planned order in week 202547"]},
            "recommendation",
            "recommendation",
        ),
    ],
)
def test_stream_no_llm_returns_deterministic_response_and_no_fallback(
    monkeypatch,
    intent_name,
    workflow_name,
    workflow_result,
    question,
    expected_contains,
):
    monkeypatch.setattr(app_main, "NO_LLM_RESPONSE_MODE", True)

    llm_calls = {"count": 0}

    def _fake_stream_llm(*_args, **_kwargs):
        llm_calls["count"] += 1
        yield "should-not-happen"

    monkeypatch.setattr(app_main, "stream_llm", _fake_stream_llm)
    monkeypatch.setattr(
        app_main,
        "build_grounded_chat_prompt",
        lambda *_args, **_kwargs: (
            "system",
            "prompt",
            _meta_for_workflow(workflow_name, workflow_result, intent_name),
        ),
    )

    client = TestClient(app_main.app)
    resp = client.post(
        "/api/chat/stream",
        json={
            "question": question,
            "llm_enabled": True,
            "history": [],
            "scope": {},
        },
    )

    assert resp.status_code == 200
    assert llm_calls["count"] == 0
    lower = resp.text.lower()
    assert "model response timed out" not in lower
    assert (
        expected_contains in lower
        or "returned deterministic results without llm generation" in lower
        or "root cause analysis" in lower
    )

    dbg = client.get("/api/debug/last-response")
    assert dbg.status_code == 200
    payload = dbg.json()
    assert payload["formatted_response_exists"] is True
    assert payload["response_exists"] is True
    assert payload["response_length"] > 0
    assert payload["stream_required"] is False
    assert payload["returned_response_type"] == "deterministic"
    assert payload["fallback_triggered"] is False
    assert payload["fallback_source"] == ""


@pytest.mark.parametrize(
    "workflow_name,workflow_result,normalized_intent,question",
    [
        (
            "Item Demand Supply",
            {
                "Item": "100000000004",
                "Demand vs Supply Stats": {
                    "item": "100000000004",
                    "demand_qty_total": 10.0,
                    "scheduled_qty_total": 8.0,
                    "unmet_qty": 2.0,
                    "meet_status": "Partially Met",
                },
            },
            "item_demand_supply",
            "check if demand is met for item 100000000004",
        ),
        (
            "Root Cause",
            _root_cause_workflow_result(),
            "root_cause_analysis",
            "why unmet?",
        ),
        (
            "Root Cause",
            _root_cause_workflow_result(),
            "root_cause_analysis",
            "which SKU exceptions?",
        ),
        (
            "SKU Exception Analysis",
            _sku_exception_workflow_result(),
            "sku_exception_analysis",
            "which SKU exceptions?",
        ),
        (
            "Validation Gate",
            {"Issues Found": ["BOM row X is invalid"]},
            "constraint_analysis",
            "which BOM is invalid?",
        ),
    ],
)
def test_stream_deterministic_first_skips_llm_for_fact_based_queries(
    monkeypatch,
    workflow_name,
    workflow_result,
    normalized_intent,
    question,
):
    monkeypatch.setattr(app_main, "NO_LLM_RESPONSE_MODE", False)

    llm_calls = {"count": 0}

    def _fake_stream_llm(*_args, **_kwargs):
        llm_calls["count"] += 1
        yield "should-not-happen"

    monkeypatch.setattr(app_main, "stream_llm", _fake_stream_llm)
    monkeypatch.setattr(
        app_main,
        "build_grounded_chat_prompt",
        lambda *_args, **_kwargs: (
            "system",
            "prompt",
            _meta_for_workflow(
                workflow_name,
                workflow_result,
                normalized_intent,
            ),
        ),
    )

    client = TestClient(app_main.app)
    resp = client.post(
        "/api/chat/stream",
        json={
            "question": question,
            "llm_enabled": True,
            "history": [],
            "scope": {},
        },
    )

    assert resp.status_code == 200
    assert llm_calls["count"] == 0

    dbg = client.get("/api/debug/last-response")
    assert dbg.status_code == 200
    payload = dbg.json()
    assert payload["returned_response_type"] == "deterministic"
    assert payload["fallback_triggered"] is False
    assert payload["deterministic_response_available"] is True
    assert payload["deterministic_response_used"] is True
    assert payload["llm_skipped"] is True
    assert payload["reason"] == "deterministic-first"
    assert payload["workflow_duration_ms"] >= 0
    assert payload["llm_duration_ms"] == 0
    assert payload["total_duration_ms"] >= 0
    lower = resp.text.lower()
    assert "llm_timeout_no_visible_token" not in lower
    assert '"lineage"' not in lower


def test_debug_last_request_endpoint_shape():
    app_main._update_last_request_debug(
        intent="Root Cause",
        analysis_completed=True,
        llm_invoked=False,
        llm_model="qwen2@GPU",
        prompt_characters=1234,
        estimated_tokens=309,
        llm_duration_ms=0,
        timeout_duration_ms=60000,
        response_generation_stage="FINAL_RESPONSE_END",
    )

    client = TestClient(app_main.app)
    resp = client.get("/api/debug/last-request")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["intent"] == "Root Cause"
    assert payload["analysis_completed"] is True
    assert payload["llm_invoked"] is False
    assert payload["prompt_characters"] == 1234
    assert payload["estimated_tokens"] == 309
    assert payload["response_generation_stage"] == "FINAL_RESPONSE_END"


def test_debug_last_response_endpoint_shape():
    app_main._record_last_response(
        "deterministic result",
        False,
        "",
        fallback_source="",
        analysis_completed=True,
        api_response_created=True,
        api_response_sent=True,
        returned_response_type="deterministic",
    )
    client = TestClient(app_main.app)
    resp = client.get("/api/debug/last-response")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["analysis_completed"] is True
    assert payload["formatted_response"] == "deterministic result"
    assert payload["formatted_response_exists"] is True
    assert payload["response_length"] == len("deterministic result")
    assert payload["response_exists"] is True
    assert payload["deterministic_response_available"] is False
    assert payload["deterministic_response_used"] is False
    assert payload["llm_skipped"] is False
    assert payload["reason"] == ""
    assert payload["workflow_duration_ms"] == 0
    assert payload["llm_duration_ms"] == 0
    assert payload["total_duration_ms"] == 0
    assert payload["stream_required"] is False
    assert payload["api_response_created"] is True
    assert payload["api_response_sent"] is True
    assert payload["returned_response_type"] == "deterministic"
    assert payload["fallback_triggered"] is False
    assert payload["fallback_reason"] == ""
    assert payload["fallback_source"] == ""
