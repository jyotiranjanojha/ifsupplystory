from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import analyzer, router_agent
from .hybrid_router import route_hybrid_query


KNOWN_KPIS = {
    "fill_rate",
    "otif",
    "service_level",
    "capacity_utilization",
    "capacity_underload",
    "capacity_overload",
    "inventory_projection",
    "end_of_horizon_inventory",
    "lateness",
    "unmet_demand",
}

GATE_THRESHOLDS = {
    "intent_accuracy_min": 0.95,
    "file_mapping_accuracy_min": 0.95,
    "kpi_accuracy_min": 0.90,
    "hallucination_rate_max": 0.0,
}


@dataclass
class SemanticRegressionConfig:
    dataset_path: Path
    snapshot_path: Path
    json_report_path: Path
    html_report_path: Path
    snapshot_report_path: Optional[Path] = None
    coverage_report_path: Optional[Path] = None
    fail_on_snapshot_change: bool = True
    update_snapshots: bool = False


def _normalize_expected_from_scenario(scenario: Dict[str, Any]) -> Dict[str, Any]:
    legacy = scenario.get("expected") if isinstance(scenario.get("expected"), dict) else {}

    intent = str(
        scenario.get("expected_intent")
        or legacy.get("intent")
        or ""
    ).strip()

    entities = scenario.get("expected_entities") if isinstance(scenario.get("expected_entities"), dict) else None
    if entities is None:
        entities = legacy.get("entities") if isinstance(legacy.get("entities"), dict) else {}

    required_files = scenario.get("expected_files") if isinstance(scenario.get("expected_files"), list) else None
    if required_files is None:
        required_files = legacy.get("required_files") if isinstance(legacy.get("required_files"), list) else []

    required_kpis = scenario.get("expected_kpis") if isinstance(scenario.get("expected_kpis"), list) else None
    if required_kpis is None:
        required_kpis = legacy.get("required_kpis") if isinstance(legacy.get("required_kpis"), list) else []

    semantic_retrieval_files = legacy.get("semantic_retrieval_files") if isinstance(legacy.get("semantic_retrieval_files"), list) else []
    required_relationships = legacy.get("required_relationships") if isinstance(legacy.get("required_relationships"), list) else []
    semantic_route = str(legacy.get("semantic_route") or "").strip()
    no_hallucination = bool(legacy.get("no_hallucination", True))

    return {
        "intent": intent,
        "entities": entities,
        "required_files": required_files,
        "required_kpis": required_kpis,
        "semantic_retrieval_files": semantic_retrieval_files,
        "required_relationships": required_relationships,
        "semantic_route": semantic_route,
        "no_hallucination": no_hallucination,
    }


def _build_coverage_report(scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(scenarios)
    if total == 0:
        return {
            "total_test_cases": 0,
            "coverage": {},
            "categories": {},
            "unique_expected_intents": [],
        }

    with_intent = 0
    with_entities = 0
    with_files = 0
    with_kpis = 0
    categories: Dict[str, int] = {}
    unique_intents: set[str] = set()

    for scenario in scenarios:
        expected = _normalize_expected_from_scenario(scenario)
        cat = str(scenario.get("category") or "UNKNOWN").strip() or "UNKNOWN"
        categories[cat] = categories.get(cat, 0) + 1

        if expected["intent"]:
            with_intent += 1
            unique_intents.add(expected["intent"])
        if expected["entities"]:
            with_entities += 1
        if expected["required_files"]:
            with_files += 1
        if expected["required_kpis"]:
            with_kpis += 1

    def pct(v: int) -> float:
        return round((v / total) * 100, 2)

    return {
        "total_test_cases": total,
        "coverage": {
            "expected_intent": {"count": with_intent, "pct": pct(with_intent)},
            "expected_entities": {"count": with_entities, "pct": pct(with_entities)},
            "expected_files": {"count": with_files, "pct": pct(with_files)},
            "expected_kpis": {"count": with_kpis, "pct": pct(with_kpis)},
        },
        "categories": categories,
        "unique_expected_intents": sorted(unique_intents),
    }


def _to_set(values: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for v in values:
        text = str(v or "").strip()
        if text:
            out.add(text.lower())
    return out


def _normalize_relationship(rel: str) -> str:
    text = str(rel or "").strip().lower()
    if " on " in text:
        text = text.split(" on ", 1)[0]
    return text


def _build_router_meta(question: str, week_id: Optional[str], scenario_id: Optional[str], scope: Optional[Dict[str, Any]], history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    base_state: Dict[str, Any] = {
        "question": (question or "").strip(),
        "question_lower": (question or "").lower().strip(),
        "history": list(history or []),
        "context_week_id": week_id,
        "context_scenario_id": scenario_id,
        "context_scope": dict(scope or {}),
    }
    state = dict(base_state)
    state.update(router_agent.classify_intent(state))
    state.update(router_agent.resolve_entities(state))
    state.update(router_agent.check_slots(state))
    return state


def evaluate_semantic_debug(
    base_dir: Path,
    question: str,
    week_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    scope: Optional[Dict[str, Any]] = None,
    history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    scope_data = dict(scope or {})
    router_meta = _build_router_meta(question, week_id, scenario_id, scope_data, history)
    context = analyzer._resolve_context(base_dir, week_id, scenario_id)
    grounding = analyzer._build_chat_grounding(base_dir, question, context, scope_data)

    workflow_name = str(router_meta.get("workflow") or "ConversationalCopilot")
    retrieval_plan = analyzer._build_semantic_retrieval_plan(
        base_dir,
        question,
        {
            "intent": router_meta.get("intent"),
            "workflow": workflow_name,
            "entities": router_meta.get("entities") or {},
        },
        context,
        grounding,
        workflow_name,
        None,
    )

    relationships = analyzer._relationship_strings_from_plan(retrieval_plan)
    table_catalog = analyzer._chat_table_catalog(base_dir)
    known_tables = {str(row.get("table") or "").strip() for row in table_catalog if str(row.get("table") or "").strip()}
    known_relationship_pairs = {
        f"{str(rel.get('from') or '').strip().lower()}->{str(rel.get('to') or '').strip().lower()}"
        for rel in (analyzer.BY_ESP_DOMAIN_KNOWLEDGE.get("linkages") or [])
        if isinstance(rel, dict)
    }

    predicted_files = [str(v).strip() for v in (retrieval_plan.get("files") or []) if str(v).strip()]
    predicted_kpis = [str(v).strip() for v in (retrieval_plan.get("kpis") or []) if str(v).strip()]

    hallucinated_files = [
        f for f in predicted_files
        if f != "UNKNOWN" and f not in known_tables
    ]
    hallucinated_kpis = [
        k for k in predicted_kpis
        if k != "UNKNOWN" and k.lower() not in KNOWN_KPIS
    ]
    hallucinated_relationships = []
    for rel in relationships:
        if rel == "UNKNOWN":
            continue
        pair = _normalize_relationship(rel)
        if pair and pair not in known_relationship_pairs:
            hallucinated_relationships.append(rel)

    hybrid = route_hybrid_query(question)
    normalized_intent = analyzer._normalize_router_intent(str(router_meta.get("intent") or "conversational"))

    snapshot_payload = {
        "intent": normalized_intent,
        "entities": router_meta.get("entities") or {},
        "route": hybrid.get("route"),
        "files": sorted(predicted_files),
        "kpis": sorted(predicted_kpis),
        "relationships": sorted(relationships),
    }

    return {
        "query": question,
        "context": {
            "requested_week_id": week_id,
            "requested_scenario_id": scenario_id,
            "scope": scope_data,
            "resolved": context,
        },
        "intent_classification": {
            "raw_intent": router_meta.get("intent"),
            "normalized_intent": normalized_intent,
            "workflow": router_meta.get("workflow"),
            "confidence": router_meta.get("confidence"),
            "matched_terms": router_meta.get("matched_terms") or [],
            "needs_clarification": bool(router_meta.get("needs_clarification")),
        },
        "entity_extraction": {
            "entities": router_meta.get("entities") or {},
            "entity_sources": router_meta.get("entity_sources") or {},
            "missing_slots": router_meta.get("missing_slots") or [],
        },
        "semantic_retrieval": {
            "route": hybrid.get("route"),
            "route_reason": hybrid.get("reason"),
            "matched_tables": [t.get("table") for t in (grounding.get("matched_tables") or []) if isinstance(t, dict)],
            "relationship_count": len(relationships),
        },
        "file_selection": {
            "required_input_files": retrieval_plan.get("required_input_files") or [],
            "required_output_files": retrieval_plan.get("required_output_files") or [],
            "all_required_files": predicted_files,
        },
        "kpi_selection": {
            "required_kpis": predicted_kpis,
        },
        "relationship_discovery": {
            "required_relationships": relationships,
        },
        "retrieval_plan": retrieval_plan,
        "hallucinations": {
            "files": sorted(hallucinated_files),
            "kpis": sorted(hallucinated_kpis),
            "relationships": sorted(hallucinated_relationships),
            "has_hallucination": bool(hallucinated_files or hallucinated_kpis or hallucinated_relationships),
        },
        "semantic_snapshot": snapshot_payload,
    }


def _score_case(result: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
    intent_actual = str((result.get("intent_classification") or {}).get("normalized_intent") or "")
    intent_expected = str(expected.get("intent") or "")
    intent_pass = bool(intent_expected and intent_actual == intent_expected)

    expected_entities = expected.get("entities") if isinstance(expected.get("entities"), dict) else {}
    actual_entities = ((result.get("entity_extraction") or {}).get("entities") or {})

    entity_total = 0
    entity_hits = 0
    for key, val in expected_entities.items():
        if val is None:
            continue
        entity_total += 1
        if str(actual_entities.get(key) or "").strip().lower() == str(val).strip().lower():
            entity_hits += 1
    entity_accuracy = (entity_hits / entity_total) if entity_total else 1.0
    entity_pass = entity_accuracy >= 1.0

    expected_files = _to_set(expected.get("required_files") or [])
    actual_files = _to_set(((result.get("file_selection") or {}).get("all_required_files") or []))
    file_mapping_pass = expected_files.issubset(actual_files) if expected_files else True

    expected_semantic_tables = _to_set(expected.get("semantic_retrieval_files") or [])
    actual_semantic_tables = _to_set(((result.get("semantic_retrieval") or {}).get("matched_tables") or []))
    semantic_retrieval_pass = expected_semantic_tables.issubset(actual_semantic_tables) if expected_semantic_tables else True

    expected_kpis = _to_set(expected.get("required_kpis") or [])
    actual_kpis = _to_set(((result.get("kpi_selection") or {}).get("required_kpis") or []))
    kpi_pass = expected_kpis.issubset(actual_kpis) if expected_kpis else True

    expected_relationships = {_normalize_relationship(v) for v in (expected.get("required_relationships") or []) if str(v).strip()}
    actual_relationships = {_normalize_relationship(v) for v in (((result.get("relationship_discovery") or {}).get("required_relationships") or [])) if str(v).strip()}
    relationship_pass = expected_relationships.issubset(actual_relationships) if expected_relationships else True

    expected_route = str(expected.get("semantic_route") or "").strip()
    actual_route = str((result.get("semantic_retrieval") or {}).get("route") or "").strip()
    route_pass = (actual_route == expected_route) if expected_route else True

    no_hallucination_expected = bool(expected.get("no_hallucination", True))
    has_hallucination = bool((result.get("hallucinations") or {}).get("has_hallucination"))
    hallucination_pass = (not has_hallucination) if no_hallucination_expected else True

    case_pass = all(
        [
            intent_pass,
            entity_pass,
            semantic_retrieval_pass,
            file_mapping_pass,
            kpi_pass,
            relationship_pass,
            route_pass,
            hallucination_pass,
        ]
    )

    return {
        "intent_pass": intent_pass,
        "entity_accuracy": entity_accuracy,
        "entity_pass": entity_pass,
        "semantic_retrieval_pass": semantic_retrieval_pass,
        "file_mapping_pass": file_mapping_pass,
        "kpi_pass": kpi_pass,
        "relationship_pass": relationship_pass,
        "semantic_route_pass": route_pass,
        "hallucination_pass": hallucination_pass,
        "has_hallucination": has_hallucination,
        "case_pass": case_pass,
        "actual": {
            "intent": intent_actual,
            "entities": actual_entities,
            "files": sorted(actual_files),
            "kpis": sorted(actual_kpis),
            "relationships": sorted(actual_relationships),
            "semantic_route": actual_route,
        },
    }


def _evaluate_snapshots(
    snapshots_expected: Dict[str, Any],
    snapshots_actual: Dict[str, Any],
) -> Dict[str, Any]:
    total = len(snapshots_actual)
    matched = 0
    changed_ids: List[str] = []

    for scenario_id, actual in snapshots_actual.items():
        expected = snapshots_expected.get(scenario_id)
        if expected == actual:
            matched += 1
        else:
            changed_ids.append(scenario_id)

    pass_rate = (matched / total) if total else 1.0
    return {
        "total": total,
        "matched": matched,
        "changed": len(changed_ids),
        "changed_ids": changed_ids,
        "pass_rate": pass_rate,
    }


def _build_html_report(report: Dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    gate = report.get("quality_gate") or {}
    failed = report.get("failed_cases") or []

    rows = []
    for case in failed[:80]:
        rows.append(
            "<tr>"
            f"<td>{case.get('id')}</td>"
            f"<td>{case.get('category')}</td>"
            f"<td>{case.get('intent_expected')}</td>"
            f"<td>{case.get('intent_actual')}</td>"
            f"<td>{case.get('query')}</td>"
            "</tr>"
        )

    gate_color = "#1f7a1f" if gate.get("passed") else "#9b1c1c"
    generated = report.get("generated_at_utc") or ""

    return f"""<!doctype html>
<html>
<head>
<meta charset=\"utf-8\" />
<title>Semantic Regression Report</title>
<style>
body {{ font-family: Segoe UI, Arial, sans-serif; background: #f7f9fc; color: #1f2a44; margin: 0; padding: 24px; }}
.container {{ max-width: 1200px; margin: 0 auto; }}
.card {{ background: #fff; border: 1px solid #d8e0ef; border-radius: 10px; padding: 16px; margin-bottom: 16px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }}
.kpi {{ background: #f2f6ff; border: 1px solid #d9e5ff; border-radius: 8px; padding: 10px; }}
.label {{ font-size: 12px; color: #4f5e7a; }}
.value {{ font-size: 24px; font-weight: 700; }}
.badge {{ display: inline-block; padding: 4px 10px; border-radius: 12px; color: #fff; background: {gate_color}; font-weight: 600; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ border-bottom: 1px solid #e5eaf5; text-align: left; padding: 8px; vertical-align: top; font-size: 13px; }}
th {{ background: #f3f7ff; }}
</style>
</head>
<body>
  <div class=\"container\">
    <div class=\"card\">
      <h1>Semantic Regression Report</h1>
      <div>Generated: {generated}</div>
      <div style=\"margin-top:8px\">Quality Gate: <span class=\"badge\">{'PASS' if gate.get('passed') else 'FAIL'}</span></div>
    </div>

    <div class=\"card\">
      <div class=\"grid\">
        <div class=\"kpi\"><div class=\"label\">Scenario Count</div><div class=\"value\">{summary.get('scenario_count', 0)}</div></div>
        <div class=\"kpi\"><div class=\"label\">Pass Rate</div><div class=\"value\">{summary.get('pass_rate_pct', 0.0)}%</div></div>
        <div class=\"kpi\"><div class=\"label\">Intent Accuracy</div><div class=\"value\">{summary.get('intent_accuracy_pct', 0.0)}%</div></div>
        <div class=\"kpi\"><div class=\"label\">Entity Accuracy</div><div class=\"value\">{summary.get('entity_accuracy_pct', 0.0)}%</div></div>
        <div class=\"kpi\"><div class=\"label\">Semantic Retrieval Accuracy</div><div class=\"value\">{summary.get('semantic_retrieval_accuracy_pct', 0.0)}%</div></div>
        <div class=\"kpi\"><div class=\"label\">File Mapping Accuracy</div><div class=\"value\">{summary.get('file_mapping_accuracy_pct', 0.0)}%</div></div>
        <div class=\"kpi\"><div class=\"label\">KPI Accuracy</div><div class=\"value\">{summary.get('kpi_accuracy_pct', 0.0)}%</div></div>
        <div class=\"kpi\"><div class=\"label\">Relationship Accuracy</div><div class=\"value\">{summary.get('relationship_accuracy_pct', 0.0)}%</div></div>
        <div class=\"kpi\"><div class=\"label\">Hallucination Rate</div><div class=\"value\">{summary.get('hallucination_rate_pct', 0.0)}%</div></div>
        <div class=\"kpi\"><div class=\"label\">Snapshot Pass Rate</div><div class=\"value\">{summary.get('snapshot_pass_rate_pct', 0.0)}%</div></div>
      </div>
    </div>

    <div class=\"card\">
      <h2>Failed Cases ({len(failed)})</h2>
      <table>
        <thead><tr><th>ID</th><th>Category</th><th>Intent Expected</th><th>Intent Actual</th><th>Query</th></tr></thead>
        <tbody>{''.join(rows) if rows else '<tr><td colspan="5">No failed cases.</td></tr>'}</tbody>
      </table>
    </div>
  </div>
</body>
</html>"""


def run_semantic_regression(base_dir: Path, config: SemanticRegressionConfig) -> Dict[str, Any]:
    dataset = json.loads(config.dataset_path.read_text(encoding="utf-8"))
    scenarios = dataset.get("scenarios") if isinstance(dataset, dict) else None
    if not isinstance(scenarios, list):
        raise ValueError("Dataset is invalid: expected top-level 'scenarios' list.")

    snapshots_expected: Dict[str, Any] = {}
    if config.snapshot_path.exists() and not config.update_snapshots:
        loaded = json.loads(config.snapshot_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            snapshots_expected = loaded

    snapshots_actual: Dict[str, Any] = {}
    snapshot_validation_rows: List[Dict[str, Any]] = []
    case_results: List[Dict[str, Any]] = []

    intent_hits = 0
    file_hits = 0
    kpi_hits = 0
    semantic_retrieval_hits = 0
    relationship_hits = 0
    pass_hits = 0
    hallucination_hits = 0

    entity_total = 0
    entity_hits = 0

    for scenario in scenarios:
        scenario_id = str(scenario.get("id") or "").strip()
        category = str(scenario.get("category") or "").strip()
        query = str(scenario.get("question") or scenario.get("query") or "").strip()
        context = scenario.get("context") if isinstance(scenario.get("context"), dict) else {}
        expected = _normalize_expected_from_scenario(scenario)

        result = evaluate_semantic_debug(
            base_dir,
            question=query,
            week_id=context.get("week_id"),
            scenario_id=context.get("scenario_id"),
            scope=context.get("scope") if isinstance(context.get("scope"), dict) else {},
            history=[],
        )

        score = _score_case(result, expected)
        actual_snapshot = result.get("semantic_snapshot")
        snapshots_actual[scenario_id] = actual_snapshot

        expected_entities = expected.get("entities") if isinstance(expected.get("entities"), dict) else {}
        entity_total += len([k for k, v in expected_entities.items() if v is not None])
        entity_hits += int(round(score.get("entity_accuracy", 0.0) * len([k for k, v in expected_entities.items() if v is not None])))

        if score["intent_pass"]:
            intent_hits += 1
        if score["file_mapping_pass"]:
            file_hits += 1
        if score["kpi_pass"]:
            kpi_hits += 1
        if score["semantic_retrieval_pass"]:
            semantic_retrieval_hits += 1
        if score["relationship_pass"]:
            relationship_hits += 1
        if score["case_pass"]:
            pass_hits += 1
        if score["has_hallucination"]:
            hallucination_hits += 1

        case_results.append(
            {
                "id": scenario_id,
                "category": category,
                "query": query,
                "score": score,
                "intent_expected": expected.get("intent"),
                "intent_actual": (result.get("intent_classification") or {}).get("normalized_intent"),
            }
        )

        snapshot_validation_rows.append(
            {
                "id": scenario_id,
                "question": query,
                "expected": {
                    "intent": expected.get("intent"),
                    "entities": expected.get("entities") or {},
                    "files": expected.get("required_files") or [],
                    "kpis": expected.get("required_kpis") or [],
                },
                "actual": {
                    "intent": (result.get("intent_classification") or {}).get("normalized_intent"),
                    "entities": ((result.get("entity_extraction") or {}).get("entities") or {}),
                    "files": ((result.get("file_selection") or {}).get("all_required_files") or []),
                    "kpis": ((result.get("kpi_selection") or {}).get("required_kpis") or []),
                },
                "pass": bool(score.get("intent_pass") and score.get("entity_pass") and score.get("file_mapping_pass") and score.get("kpi_pass")),
            }
        )

    total = len(case_results)

    if config.update_snapshots or not config.snapshot_path.exists():
        config.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        config.snapshot_path.write_text(json.dumps(snapshots_actual, indent=2, ensure_ascii=True), encoding="utf-8")
        snapshot_summary = {
            "total": total,
            "matched": total,
            "changed": 0,
            "changed_ids": [],
            "pass_rate": 1.0,
            "updated": True,
        }
    else:
        snapshot_summary = _evaluate_snapshots(snapshots_expected, snapshots_actual)
        snapshot_summary["updated"] = False

    pass_rate = (pass_hits / total) if total else 1.0
    intent_accuracy = (intent_hits / total) if total else 1.0
    entity_accuracy = (entity_hits / entity_total) if entity_total else 1.0
    semantic_retrieval_accuracy = (semantic_retrieval_hits / total) if total else 1.0
    file_mapping_accuracy = (file_hits / total) if total else 1.0
    kpi_accuracy = (kpi_hits / total) if total else 1.0
    relationship_accuracy = (relationship_hits / total) if total else 1.0
    hallucination_rate = (hallucination_hits / total) if total else 0.0

    summary = {
        "scenario_count": total,
        "pass_rate_pct": round(pass_rate * 100, 2),
        "intent_accuracy_pct": round(intent_accuracy * 100, 2),
        "entity_accuracy_pct": round(entity_accuracy * 100, 2),
        "semantic_retrieval_accuracy_pct": round(semantic_retrieval_accuracy * 100, 2),
        "file_mapping_accuracy_pct": round(file_mapping_accuracy * 100, 2),
        "kpi_accuracy_pct": round(kpi_accuracy * 100, 2),
        "relationship_accuracy_pct": round(relationship_accuracy * 100, 2),
        "hallucination_rate_pct": round(hallucination_rate * 100, 2),
        "snapshot_pass_rate_pct": round(snapshot_summary["pass_rate"] * 100, 2),
    }

    gate_failures: List[str] = []
    if intent_accuracy < GATE_THRESHOLDS["intent_accuracy_min"]:
        gate_failures.append(
            f"Intent accuracy {intent_accuracy:.4f} is below {GATE_THRESHOLDS['intent_accuracy_min']:.2f}."
        )
    if file_mapping_accuracy < GATE_THRESHOLDS["file_mapping_accuracy_min"]:
        gate_failures.append(
            f"File mapping accuracy {file_mapping_accuracy:.4f} is below {GATE_THRESHOLDS['file_mapping_accuracy_min']:.2f}."
        )
    if kpi_accuracy < GATE_THRESHOLDS["kpi_accuracy_min"]:
        gate_failures.append(
            f"KPI accuracy {kpi_accuracy:.4f} is below {GATE_THRESHOLDS['kpi_accuracy_min']:.2f}."
        )
    if hallucination_rate > GATE_THRESHOLDS["hallucination_rate_max"]:
        gate_failures.append(
            f"Hallucination rate {hallucination_rate:.4f} exceeds {GATE_THRESHOLDS['hallucination_rate_max']:.2f}."
        )
    if config.fail_on_snapshot_change and (not config.update_snapshots) and snapshot_summary.get("changed", 0) > 0:
        gate_failures.append(
            f"Semantic snapshots changed unexpectedly ({snapshot_summary.get('changed', 0)} case(s))."
        )

    coverage_report = _build_coverage_report(scenarios)

    snapshot_report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_summary": snapshot_summary,
        "rows": snapshot_validation_rows,
    }

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "thresholds": GATE_THRESHOLDS,
        "quality_gate": {
            "passed": len(gate_failures) == 0,
            "failures": gate_failures,
        },
        "snapshot": snapshot_summary,
        "coverage": coverage_report,
        "failed_cases": [c for c in case_results if not c["score"]["case_pass"]],
        "cases": case_results,
    }

    config.json_report_path.parent.mkdir(parents=True, exist_ok=True)
    config.html_report_path.parent.mkdir(parents=True, exist_ok=True)
    config.json_report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    config.html_report_path.write_text(_build_html_report(report), encoding="utf-8")

    snapshot_report_path = config.snapshot_report_path or (config.json_report_path.parent / "semantic_snapshot_report.json")
    coverage_report_path = config.coverage_report_path or (config.json_report_path.parent / "semantic_coverage_report.json")
    snapshot_report_path.parent.mkdir(parents=True, exist_ok=True)
    coverage_report_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_report_path.write_text(json.dumps(snapshot_report, indent=2, ensure_ascii=True), encoding="utf-8")
    coverage_report_path.write_text(json.dumps(coverage_report, indent=2, ensure_ascii=True), encoding="utf-8")

    return report
