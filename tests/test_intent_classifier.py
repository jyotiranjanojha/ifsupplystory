import unittest

from webapp.app.intent_classifier import IntentLabel, OpenVINOQwenIntentClassifier


class TestIntentClassifier(unittest.TestCase):
    def test_parse_valid_json(self):
        raw = (
            '{"classification_result":"InventoryLookup",'
            '"confidence_score":0.93,'
            '"reasoning":"Query asks for stock on hand by item."}'
        )
        result = OpenVINOQwenIntentClassifier._parse_model_output(raw)
        self.assertEqual(result.classification_result, IntentLabel.InventoryLookup)
        self.assertAlmostEqual(result.confidence_score, 0.93)
        self.assertIn("stock", result.reasoning.lower())

    def test_parse_markdown_wrapped_json(self):
        raw = """```json
        {
          "classification_result": "ForecastLookup",
          "confidence_score": "0.88",
          "reasoning": "The user asks for demand forecast values."
        }
        ```"""
        result = OpenVINOQwenIntentClassifier._parse_model_output(raw)
        self.assertEqual(result.classification_result, IntentLabel.ForecastLookup)
        self.assertAlmostEqual(result.confidence_score, 0.88)

    def test_unknown_label_maps_to_other(self):
        raw = (
            '{"classification_result":"SomethingElse",'
            '"confidence_score":0.7,'
            '"reasoning":"Unknown class."}'
        )
        result = OpenVINOQwenIntentClassifier._parse_model_output(raw)
        self.assertEqual(result.classification_result, IntentLabel.Other)

    def test_invalid_json_returns_other(self):
        result = OpenVINOQwenIntentClassifier._parse_model_output("not-json")
        self.assertEqual(result.classification_result, IntentLabel.Other)
        self.assertLessEqual(result.confidence_score, 0.2)

    def test_classify_uses_pipeline(self):
        class _FakePipeline:
            def generate(self, *_args, **_kwargs):
                return (
                    '{"classification_result":"CustomerOrderLookup",'
                    '"confidence_score":0.9,'
                    '"reasoning":"The query asks about customer order status."}'
                )

        classifier = OpenVINOQwenIntentClassifier(model_path="dummy")
        classifier._pipeline = _FakePipeline()
        result = classifier.classify("show customer order status for order 123")
        self.assertEqual(result.classification_result, IntentLabel.CustomerOrderLookup)
        self.assertAlmostEqual(result.confidence_score, 0.9)

    def test_empty_query_returns_other(self):
        classifier = OpenVINOQwenIntentClassifier(model_path="dummy")
        result = classifier.classify("   ")
        self.assertEqual(result.classification_result, IntentLabel.Other)
        self.assertEqual(result.confidence_score, 0.0)


if __name__ == "__main__":
    unittest.main()
