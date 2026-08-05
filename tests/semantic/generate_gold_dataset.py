from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List

# Standalone execution path: keep semantic mode startup validation satisfied.
os.environ.setdefault("SEMANTIC_MODE", "legacy")

from webapp.app.semantic_regression import evaluate_semantic_debug


def _build_query_templates() -> Dict[str, List[str]]:
    return {
        "Inventory": [
            "Show demand and supply status for item {item} at site {site}",
            "What is projected inventory and stockout risk for item {item} in plant {site}?",
            "Is demand for item {item} met this week at location {site}?",
            "Give EOH and fill rate context for item {item} at site {site}",
        ],
        "Forecast": [
            "Show forecast consumption from fcstorder for item {item} at site {site}",
            "How is forecast vs actual trending for item {item} in site {site}?",
            "Explain forecast demand behavior and service trend for item {item}",
            "Provide forecast accuracy drivers for item {item} at location {site}",
        ],
        "Capacity Constraints": [
            "Which resources are overutilized and constrained in site {site} for item {item}?",
            "Why is capacity utilization low for item {item} in site {site}?",
            "Show resource load and capacity exception risk for site {site}",
            "Find underloaded or overloaded horizons affecting item {item} at {site}",
        ],
        "Solver Decisions": [
            "Run SQL query to list planned orders for item {item} at site {site}",
            "Show planorder and planpurch rows for item {item} in location {site}",
            "Find records explaining plan order decision for item {item}",
            "List all rows for item {item} in by_if_snop_out_planorder at {site}",
        ],
        "Root Cause Analysis": [
            "Root cause why demand was not met for item {item} at site {site}",
            "Explain late and short demand for item {item} with pegging evidence",
            "Why did fill rate drop for item {item} in plant {site}?",
            "Show linkage and lineage causing unmet demand for item {item}",
        ],
        "Recommendations": [
            "What should we do to improve fill rate for item {item} at site {site}?",
            "Recommend actions for reducing stockout risk on item {item} in {site}",
            "Suggest best next checks for planning performance of item {item}",
            "Give recommendation strategy for capacity and service on item {item} at {site}",
        ],
    }


def _build_scenarios(per_topic: int) -> List[Dict[str, Any]]:
    templates = _build_query_templates()
    items = [
        "100000000001",
        "100000000002",
        "100000000003",
        "100000000004",
        "100000000005",
        "100000000006",
        "100000000007",
        "100000000008",
        "100000000009",
        "100000000010",
    ]
    sites = ["F28", "F32", "AZ01", "OR01", "IRL1", "VN02", "MY03", "US01", "IL07", "SG10"]

    scenarios: List[Dict[str, Any]] = []
    for category, category_templates in templates.items():
        for idx in range(per_topic):
            item = items[idx % len(items)]
            site = sites[idx % len(sites)]
            template = category_templates[idx % len(category_templates)]
            query = template.format(item=item, site=site)

            scenarios.append(
                {
                    "id": f"{category[:3].upper()}-{idx + 1:03d}",
                    "category": category,
                    "query": query,
                    "context": {
                        "week_id": None,
                        "scenario_id": None,
                        "scope": {"site": site},
                    },
                }
            )
    return scenarios


def _materialize_expected(base_dir: Path, scenarios: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for scenario in scenarios:
        result = evaluate_semantic_debug(
            base_dir=base_dir,
            question=scenario["query"],
            week_id=None,
            scenario_id=None,
            scope=(scenario.get("context") or {}).get("scope") or {},
            history=[],
        )

        entities = ((result.get("entity_extraction") or {}).get("entities") or {})
        files = ((result.get("file_selection") or {}).get("all_required_files") or [])
        kpis = ((result.get("kpi_selection") or {}).get("required_kpis") or [])
        rels = ((result.get("relationship_discovery") or {}).get("required_relationships") or [])
        matched_tables = ((result.get("semantic_retrieval") or {}).get("matched_tables") or [])

        expected = {
            "intent": ((result.get("intent_classification") or {}).get("normalized_intent") or "conversational"),
            "entities": {
                "item": entities.get("item"),
                "site": entities.get("site"),
            },
            "required_files": files[:4],
            "semantic_retrieval_files": matched_tables[:3],
            "required_kpis": kpis[:4],
            "required_relationships": rels[:3],
            "semantic_route": (result.get("semantic_retrieval") or {}).get("route"),
            "no_hallucination": True,
        }

        shaped = dict(scenario)
        shaped["expected"] = expected
        out.append(shaped)

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate gold semantic regression dataset")
    parser.add_argument("--per-topic", type=int, default=40, help="Scenarios per topic (default: 40)")
    parser.add_argument(
        "--output",
        default="tests/semantic/gold_semantic_dataset.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    output_path = repo_root / args.output

    scenarios = _build_scenarios(per_topic=args.per_topic)
    materialized = _materialize_expected(repo_root, scenarios)

    payload = {
        "name": "IFSP Gold Semantic Dataset",
        "version": "1.0.0",
        "scenario_count": len(materialized),
        "categories": sorted({s["category"] for s in materialized}),
        "generated_by": "tests/semantic/generate_gold_dataset.py",
        "scenarios": materialized,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Wrote {len(materialized)} scenarios to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
