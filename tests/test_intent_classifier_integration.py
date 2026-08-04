import unittest
from unittest.mock import patch

from webapp.app import analyzer


class _FakeCls:
    def __init__(self, label: str, score: float, reasoning: str = "test"):
        self._payload = {
            "classification_result": label,
            "confidence_score": score,
            "reasoning": reasoning,
        }

    def model_dump(self):
        return dict(self._payload)


class TestIntentClassifierIntegration(unittest.TestCase):
    def test_map_openvino_labels(self):
        self.assertEqual(analyzer._map_openvino_label_to_router_intent("InventoryLookup"), "InventoryProjectionExplain")
        self.assertEqual(analyzer._map_openvino_label_to_router_intent("CustomerOrderLookup"), "DemandStatusLookup")
        self.assertEqual(analyzer._map_openvino_label_to_router_intent("UnknownLabel"), "conversational")

    @patch("webapp.app.analyzer.OPENVINO_INTENT_CLASSIFIER_ENABLED", True)
    @patch("webapp.app.analyzer.OPENVINO_INTENT_OVERRIDE_THRESHOLD", 0.8)
    @patch("webapp.app.analyzer._get_openvino_intent_classifier")
    def test_applies_override_for_high_confidence_non_slot_intent(self, mock_get_classifier):
        mock_get_classifier.return_value.classify.return_value = _FakeCls("PurchaseOrderLookup", 0.91)

        meta = {
            "intent": "conversational",
            "workflow": "ConversationalCopilot",
            "entities": {},
        }
        out = analyzer._enrich_router_meta_with_openvino_intent(meta, "show open purchase orders", history=[])
        self.assertTrue(out.get("openvino_override_applied"))
        self.assertEqual(out.get("intent"), "PlanPurchDecisionExplain")

    @patch("webapp.app.analyzer.OPENVINO_INTENT_CLASSIFIER_ENABLED", True)
    @patch("webapp.app.analyzer.OPENVINO_INTENT_OVERRIDE_THRESHOLD", 0.8)
    @patch("webapp.app.analyzer._resolve_chat_item")
    @patch("webapp.app.analyzer._get_openvino_intent_classifier")
    def test_does_not_override_when_required_item_missing(self, mock_get_classifier, mock_resolve_item):
        mock_get_classifier.return_value.classify.return_value = _FakeCls("InventoryLookup", 0.95)
        mock_resolve_item.return_value = {"selected_item": None}

        meta = {
            "intent": "conversational",
            "workflow": "ConversationalCopilot",
            "entities": {},
        }
        out = analyzer._enrich_router_meta_with_openvino_intent(meta, "why unmet demand", history=[])
        self.assertFalse(out.get("openvino_override_applied"))
        self.assertEqual(out.get("intent"), "conversational")

    @patch("webapp.app.analyzer.OPENVINO_INTENT_CLASSIFIER_ENABLED", True)
    @patch("webapp.app.analyzer.OPENVINO_INTENT_OVERRIDE_THRESHOLD", 0.8)
    @patch("webapp.app.analyzer._resolve_chat_item")
    @patch("webapp.app.analyzer._get_openvino_intent_classifier")
    def test_overrides_when_required_item_resolved(self, mock_get_classifier, mock_resolve_item):
        mock_get_classifier.return_value.classify.return_value = _FakeCls("InventoryLookup", 0.95)
        mock_resolve_item.return_value = {"selected_item": "100000000008"}

        meta = {
            "intent": "conversational",
            "workflow": "ConversationalCopilot",
            "entities": {},
        }
        out = analyzer._enrich_router_meta_with_openvino_intent(meta, "why unmet demand for this item", history=[])
        self.assertTrue(out.get("openvino_override_applied"))
        self.assertEqual(out.get("intent"), "InventoryProjectionExplain")
        self.assertEqual((out.get("entities") or {}).get("item"), "100000000008")


if __name__ == "__main__":
    unittest.main()
