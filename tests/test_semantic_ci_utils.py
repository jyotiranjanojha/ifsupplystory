from pathlib import Path
import json

from tests.semantic.ci_utils import (
    build_github_step_summary,
    format_console_summary,
    parse_junit_xml,
    parse_semantic_report,
    write_summary_file,
)


def test_parse_junit_xml_testsuite(tmp_path):
    xml_path = tmp_path / "junit.xml"
    xml_path.write_text(
        '<testsuite name="semantic" tests="6" failures="1" errors="0" skipped="2"></testsuite>',
        encoding="utf-8",
    )

    stats = parse_junit_xml(xml_path)
    assert stats == {
        "tests": 6,
        "passed": 3,
        "failures": 1,
        "errors": 0,
        "skipped": 2,
    }


def test_parse_junit_xml_testsuites(tmp_path):
    xml_path = tmp_path / "junit.xml"
    xml_path.write_text(
        """
<testsuites>
  <testsuite name="a" tests="4" failures="0" errors="0" skipped="1"/>
  <testsuite name="b" tests="3" failures="1" errors="1" skipped="0"/>
</testsuites>
""".strip(),
        encoding="utf-8",
    )

    stats = parse_junit_xml(xml_path)
    assert stats == {
        "tests": 7,
        "passed": 4,
        "failures": 1,
        "errors": 1,
        "skipped": 1,
    }


def test_summary_format_and_write(tmp_path):
    stats = {"tests": 5, "passed": 5, "failures": 0, "errors": 0, "skipped": 0}
    summary = format_console_summary(stats)

    out_path = tmp_path / "summary.txt"
    write_summary_file(summary, out_path)

    text = out_path.read_text(encoding="utf-8")
    assert "Semantic Regression Test Summary" in text
    assert "Total: 5" in text
    assert "Passed: 5" in text


def test_parse_semantic_report(tmp_path):
    report_path = tmp_path / "semantic_report.json"
    payload = {
        "summary": {
            "intent_accuracy_pct": 97.5,
            "entity_accuracy_pct": 96.0,
            "file_mapping_accuracy_pct": 95.5,
            "kpi_accuracy_pct": 91.25,
            "hallucination_rate_pct": 0.0,
        }
    }
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    metrics = parse_semantic_report(report_path)
    assert metrics["intent_accuracy_pct"] == 97.5
    assert metrics["kpi_accuracy_pct"] == 91.25


def test_build_github_step_summary_contains_required_lines():
    stats = {"tests": 10, "passed": 9, "failures": 1, "errors": 0, "skipped": 0}
    metrics = {
        "intent_accuracy_pct": 96.0,
        "entity_accuracy_pct": 95.0,
        "file_mapping_accuracy_pct": 97.0,
        "kpi_accuracy_pct": 92.0,
        "hallucination_rate_pct": 0.0,
    }

    summary = build_github_step_summary(stats, metrics)
    assert "Semantic Regression Report" in summary
    assert "Tests Run: 10" in summary
    assert "Failed: 1" in summary
    assert "Intent Accuracy: 96.00%" in summary
    assert "KPI Accuracy: 92.00%" in summary
