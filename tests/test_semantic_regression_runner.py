from pathlib import Path

from webapp.app.semantic_regression import SemanticRegressionConfig, run_semantic_regression


def test_semantic_regression_runner_gate_passes(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]

    config = SemanticRegressionConfig(
        dataset_path=repo_root / "tests/semantic/gold_semantic_dataset.json",
        snapshot_path=repo_root / "tests/semantic/snapshots/semantic_snapshots.json",
        json_report_path=tmp_path / "semantic_regression_report.json",
        html_report_path=tmp_path / "semantic_regression_report.html",
        update_snapshots=False,
    )

    report = run_semantic_regression(repo_root, config)

    summary = report["summary"]
    assert summary["scenario_count"] >= 200
    assert report["quality_gate"]["passed"] is True
    assert summary["intent_accuracy_pct"] >= 95.0
    assert summary["file_mapping_accuracy_pct"] >= 95.0
    assert summary["hallucination_rate_pct"] == 0.0
    assert config.json_report_path.exists()
    assert config.html_report_path.exists()
