from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

# Standalone execution path: keep semantic mode startup validation satisfied.
os.environ.setdefault("SEMANTIC_MODE", "legacy")

from webapp.app.semantic_regression import SemanticRegressionConfig, run_semantic_regression


def main() -> int:
    parser = argparse.ArgumentParser(description="Run semantic regression suite")
    parser.add_argument("--dataset", default="tests/semantic/gold_semantic_dataset.json")
    parser.add_argument("--snapshots", default="tests/semantic/snapshots/semantic_snapshots.json")
    parser.add_argument("--json-report", default="reports/semantic_report.json")
    parser.add_argument("--html-report", default="reports/semantic_report.html")
    parser.add_argument("--snapshot-report", default="reports/semantic_snapshot_report.json")
    parser.add_argument("--coverage-report", default="reports/semantic_coverage_report.json")
    parser.add_argument("--allow-snapshot-change", action="store_true")
    parser.add_argument("--update-snapshots", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    config = SemanticRegressionConfig(
        dataset_path=repo_root / args.dataset,
        snapshot_path=repo_root / args.snapshots,
        json_report_path=repo_root / args.json_report,
        html_report_path=repo_root / args.html_report,
        snapshot_report_path=repo_root / args.snapshot_report,
        coverage_report_path=repo_root / args.coverage_report,
        fail_on_snapshot_change=not args.allow_snapshot_change,
        update_snapshots=args.update_snapshots,
    )

    report = run_semantic_regression(repo_root, config)
    summary = report.get("summary") or {}
    gate = report.get("quality_gate") or {}

    print(json.dumps({"summary": summary, "quality_gate": gate}, indent=2, ensure_ascii=True))

    return 0 if gate.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
