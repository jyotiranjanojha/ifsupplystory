import json
from pathlib import Path

from webapp.app import semantic_regression
from webapp.app.semantic_regression import SemanticRegressionConfig, run_semantic_regression


def _mock_semantic_debug(_base_dir, question, week_id=None, scenario_id=None, scope=None, history=None):
    return {
        "query": question,
        "intent_classification": {"normalized_intent": "item_demand_supply"},
        "entity_extraction": {"entities": {"item": "100000000001", "site": "F28"}},
        "semantic_retrieval": {"route": "SQL only", "matched_tables": ["if_snop_items"]},
        "file_selection": {"all_required_files": ["if_snop_items", "if_snop_inventory"]},
        "kpi_selection": {"required_kpis": ["inventory_projection"]},
        "relationship_discovery": {"required_relationships": []},
        "hallucinations": {"has_hallucination": False},
        "semantic_snapshot": {
            "intent": "item_demand_supply",
            "entities": {"item": "100000000001", "site": "F28"},
            "route": "SQL only",
            "files": ["if_snop_inventory", "if_snop_items"],
            "kpis": ["inventory_projection"],
            "relationships": [],
        },
    }


def _build_dataset(path: Path) -> None:
    payload = {
        "name": "snapshot-test",
        "version": "1",
        "scenario_count": 1,
        "scenarios": [
            {
                "id": "SNP-001",
                "question": "inventory for item 100000000001 at site F28",
                "context": {"scope": {"site": "F28"}},
                "expected_intent": "item_demand_supply",
                "expected_entities": {"item": "100000000001", "site": "F28"},
                "expected_files": ["if_snop_items"],
                "expected_kpis": ["inventory_projection"],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_snapshot_change_fails_when_not_allowed(tmp_path, monkeypatch):
    dataset = tmp_path / "gold.json"
    snapshots = tmp_path / "snapshots.json"
    report_json = tmp_path / "semantic_report.json"
    report_html = tmp_path / "semantic_report.html"
    snapshot_report = tmp_path / "semantic_snapshot_report.json"
    coverage_report = tmp_path / "semantic_coverage_report.json"

    _build_dataset(dataset)

    # Intentionally mismatched baseline snapshot to trigger drift.
    snapshots.write_text(
        json.dumps({"SNP-001": {"intent": "different_intent"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(semantic_regression, "evaluate_semantic_debug", _mock_semantic_debug)

    config = SemanticRegressionConfig(
        dataset_path=dataset,
        snapshot_path=snapshots,
        json_report_path=report_json,
        html_report_path=report_html,
        snapshot_report_path=snapshot_report,
        coverage_report_path=coverage_report,
        fail_on_snapshot_change=True,
        update_snapshots=False,
    )

    report = run_semantic_regression(Path("."), config)
    assert report["snapshot"]["changed"] == 1
    assert report["quality_gate"]["passed"] is False
    assert any("snapshots changed unexpectedly" in msg.lower() for msg in report["quality_gate"]["failures"])
    assert snapshot_report.exists()
    assert coverage_report.exists()


def test_snapshot_change_allowed_when_flag_disabled(tmp_path, monkeypatch):
    dataset = tmp_path / "gold.json"
    snapshots = tmp_path / "snapshots.json"

    _build_dataset(dataset)
    snapshots.write_text(json.dumps({"SNP-001": {"intent": "different_intent"}}), encoding="utf-8")

    monkeypatch.setattr(semantic_regression, "evaluate_semantic_debug", _mock_semantic_debug)

    config = SemanticRegressionConfig(
        dataset_path=dataset,
        snapshot_path=snapshots,
        json_report_path=tmp_path / "semantic_report.json",
        html_report_path=tmp_path / "semantic_report.html",
        fail_on_snapshot_change=False,
        update_snapshots=False,
    )

    report = run_semantic_regression(Path("."), config)
    assert report["snapshot"]["changed"] == 1
    assert report["quality_gate"]["passed"] is True
