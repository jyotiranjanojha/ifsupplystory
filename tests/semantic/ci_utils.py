from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict


def parse_junit_xml(xml_path: Path) -> Dict[str, int]:
    if not xml_path.exists():
        raise FileNotFoundError(f"JUnit XML report not found: {xml_path}")

    root = ET.parse(xml_path).getroot()

    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = list(root.findall("testsuite"))
    else:
        raise ValueError(f"Unsupported JUnit XML root tag: {root.tag}")

    tests = failures = errors = skipped = 0

    for suite in suites:
        tests += int(suite.attrib.get("tests", 0))
        failures += int(suite.attrib.get("failures", 0))
        errors += int(suite.attrib.get("errors", 0))
        skipped += int(suite.attrib.get("skipped", suite.attrib.get("disabled", 0)))

    passed = max(0, tests - failures - errors - skipped)
    return {
        "tests": tests,
        "passed": passed,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
    }


def format_console_summary(stats: Dict[str, int]) -> str:
    lines = [
        "Semantic Regression Test Summary",
        f"Total: {stats['tests']}",
        f"Passed: {stats['passed']}",
        f"Failures: {stats['failures']}",
        f"Errors: {stats['errors']}",
        f"Skipped: {stats['skipped']}",
    ]
    return "\n".join(lines)


def write_summary_file(summary_text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(summary_text + "\n", encoding="utf-8")


def parse_semantic_report(report_path: Path) -> Dict[str, float]:
    if not report_path.exists():
        raise FileNotFoundError(f"Semantic report not found: {report_path}")

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    summary = payload.get("summary") if isinstance(payload, dict) else {}
    if not isinstance(summary, dict):
        raise ValueError("Semantic report is invalid: missing summary object.")

    return {
        "intent_accuracy_pct": float(summary.get("intent_accuracy_pct", 0.0)),
        "entity_accuracy_pct": float(summary.get("entity_accuracy_pct", 0.0)),
        "file_mapping_accuracy_pct": float(summary.get("file_mapping_accuracy_pct", 0.0)),
        "kpi_accuracy_pct": float(summary.get("kpi_accuracy_pct", 0.0)),
        "hallucination_rate_pct": float(summary.get("hallucination_rate_pct", 0.0)),
    }


def build_github_step_summary(stats: Dict[str, int], metrics: Dict[str, float]) -> str:
    failed = stats["failures"] + stats["errors"]
    lines = [
        "Semantic Regression Report",
        "",
        f"Tests Run: {stats['tests']}",
        f"Passed: {stats['passed']}",
        f"Failed: {failed}",
        "",
        f"Intent Accuracy: {metrics['intent_accuracy_pct']:.2f}%",
        f"Entity Accuracy: {metrics['entity_accuracy_pct']:.2f}%",
        f"File Mapping Accuracy: {metrics['file_mapping_accuracy_pct']:.2f}%",
        f"KPI Accuracy: {metrics['kpi_accuracy_pct']:.2f}%",
        f"Hallucination Rate: {metrics['hallucination_rate_pct']:.2f}%",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize semantic pytest JUnit XML")
    parser.add_argument("--junit", required=True, help="Path to JUnit XML file")
    parser.add_argument("--summary-out", required=True, help="Path to write summary text")
    parser.add_argument("--semantic-report", required=False, help="Path to semantic_report.json")
    parser.add_argument("--gha-summary-out", required=False, help="Path to GitHub step summary output file")
    args = parser.parse_args()

    junit_path = Path(args.junit)
    summary_out = Path(args.summary_out)

    stats = parse_junit_xml(junit_path)
    summary = format_console_summary(stats)

    print(summary)
    write_summary_file(summary, summary_out)

    if args.semantic_report and args.gha_summary_out:
        metrics = parse_semantic_report(Path(args.semantic_report))
        gha_summary = build_github_step_summary(stats, metrics)
        print("\n" + gha_summary)
        write_summary_file(gha_summary, Path(args.gha_summary_out))

    # Return non-zero if tests had failures/errors so CI can fail clearly.
    if stats["failures"] > 0 or stats["errors"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
