import json
from pathlib import Path


def _load_dataset() -> dict:
    dataset_path = Path(__file__).resolve().parent / "gold_semantic_dataset.json"
    return json.loads(dataset_path.read_text(encoding="utf-8"))


def test_dataset_contains_intent_expectations():
    data = _load_dataset()
    scenarios = data.get("scenarios") or []

    assert isinstance(scenarios, list)
    assert len(scenarios) >= 200

    for scenario in scenarios:
        intent = scenario.get("expected_intent")
        assert isinstance(intent, str)
        assert intent.strip() != ""


def test_intent_coverage_spans_multiple_workflows():
    data = _load_dataset()
    scenarios = data.get("scenarios") or []

    intents = {
        str(s.get("expected_intent") or "").strip()
        for s in scenarios
    }
    intents.discard("")

    # Expect broad coverage from semantic-routing behavior.
    assert len(intents) >= 4
