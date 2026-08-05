import json
from pathlib import Path


def _load_dataset() -> dict:
    dataset_path = Path(__file__).resolve().parent / "gold_semantic_dataset.json"
    return json.loads(dataset_path.read_text(encoding="utf-8"))


def test_dataset_contains_retrieval_plan_expectations():
    data = _load_dataset()
    scenarios = data.get("scenarios") or []

    for scenario in scenarios:
        required_files = scenario.get("expected_files") or []
        required_kpis = scenario.get("expected_kpis") or []
        relationships = ((scenario.get("expected") or {}).get("required_relationships") or [])
        semantic_route = ((scenario.get("expected") or {}).get("semantic_route") or "")

        assert isinstance(required_files, list)
        assert isinstance(required_kpis, list)
        assert isinstance(relationships, list)
        assert isinstance(semantic_route, str)
        assert semantic_route.strip() != ""


def test_retrieval_plan_expectations_have_meaningful_content():
    data = _load_dataset()
    scenarios = data.get("scenarios") or []

    with_files = 0
    with_kpis = 0
    with_relationships = 0

    for scenario in scenarios:
        if len(scenario.get("expected_files") or []) > 0:
            with_files += 1
        if len(scenario.get("expected_kpis") or []) > 0:
            with_kpis += 1
        expected = scenario.get("expected") or {}
        if len(expected.get("required_relationships") or []) > 0:
            with_relationships += 1

    assert with_files > 0
    assert with_kpis > 0
    assert with_relationships > 0
