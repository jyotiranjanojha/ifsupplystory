import json
from pathlib import Path


def _load_dataset() -> dict:
    dataset_path = Path(__file__).resolve().parent / "gold_semantic_dataset.json"
    return json.loads(dataset_path.read_text(encoding="utf-8"))


def test_dataset_contains_entity_expectations():
    data = _load_dataset()
    scenarios = data.get("scenarios") or []

    for scenario in scenarios:
        entities = scenario.get("expected_entities") or {}

        assert isinstance(entities, dict)
        assert "item" in entities
        assert "site" in entities


def test_entity_values_are_not_empty_when_present():
    data = _load_dataset()
    scenarios = data.get("scenarios") or []

    non_empty_items = 0
    non_empty_sites = 0

    for scenario in scenarios:
        entities = (scenario.get("expected_entities") or {})
        item = entities.get("item")
        site = entities.get("site")

        if isinstance(item, str) and item.strip():
            non_empty_items += 1
        if isinstance(site, str) and site.strip():
            non_empty_sites += 1

    assert non_empty_items > 0
    assert non_empty_sites > 0
