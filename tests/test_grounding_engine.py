import unittest

from webapp.app.grounding_engine import build_grounded_answer


class TestGroundingEngine(unittest.TestCase):
    def test_insufficient_evidence_returns_guardrail_message(self):
        result = build_grounded_answer(
            answer_text="Some answer",
            workflow_result=None,
            rag_evidence=None,
            confidence={"level": "Low"},
        )
        self.assertEqual(result["Answer"], "I do not have enough data to answer.")
        self.assertEqual(result["Evidence"]["Data Source"], [])
        self.assertEqual(result["Evidence"]["Confidence Score"], 0.0)

    def test_sql_result_grounding_schema(self):
        sql_workflow = {
            "Selected Tables": ["by_if_snop_out_inddmdview"],
            "Result Rows": [{"ITEM": "A", "QTY": 10}],
        }
        result = build_grounded_answer(
            answer_text="Inventory is 10.",
            workflow_result=sql_workflow,
            rag_evidence=None,
            confidence={"level": "High"},
        )
        self.assertEqual(result["Answer"], "Inventory is 10.")
        self.assertIn("Structured Data (SQL)", result["Evidence"]["Data Source"])
        self.assertEqual(result["Evidence"]["SQL Result"], [{"ITEM": "A", "QTY": 10}])
        self.assertIn("by_if_snop_out_inddmdview", result["Source Tables"])
        self.assertAlmostEqual(result["Evidence"]["Confidence Score"], 0.9)

    def test_rag_grounding_with_documents(self):
        rag = {
            "hits": [
                {
                    "file": "policy.md",
                    "table": "policy_table",
                    "row_number": 5,
                    "citation": "policy.md#row5",
                    "score": 0.88,
                    "text": "Safety stock policy definition",
                }
            ]
        }
        result = build_grounded_answer(
            answer_text="Safety stock is policy buffer.",
            workflow_result=None,
            rag_evidence=rag,
            confidence={"level": "Medium"},
        )
        self.assertIn("Retrieved Documents", result["Evidence"]["Data Source"])
        self.assertEqual(result["Documents Referenced"], ["policy.md#row5"])
        self.assertEqual(result["Source Tables"], ["policy_table"])
        self.assertAlmostEqual(result["Evidence"]["Confidence Score"], 0.6)


if __name__ == "__main__":
    unittest.main()
