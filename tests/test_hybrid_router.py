import unittest

from webapp.app.hybrid_router import HybridRoute, route_hybrid_query


class TestHybridRouter(unittest.TestCase):
    def test_sql_only_inventory_level(self):
        result = route_hybrid_query("What is inventory level?")
        self.assertEqual(result["route"], HybridRoute.SQL_ONLY.value)

    def test_rag_only_safety_stock_definition(self):
        result = route_hybrid_query("What is safety stock?")
        self.assertEqual(result["route"], HybridRoute.RAG_ONLY.value)

    def test_sql_and_rag_inventory_under_safety_stock(self):
        result = route_hybrid_query("Why is inventory under safety stock?")
        self.assertEqual(result["route"], HybridRoute.SQL_AND_RAG.value)

    def test_rag_only_policy_question(self):
        result = route_hybrid_query("Define service level policy for customer commitments")
        self.assertEqual(result["route"], HybridRoute.RAG_ONLY.value)

    def test_sql_only_operational_count(self):
        result = route_hybrid_query("How many orders are unmet this week by location?")
        self.assertEqual(result["route"], HybridRoute.SQL_ONLY.value)

    def test_sql_and_rag_policy_violation(self):
        result = route_hybrid_query("Show inventory by item and explain policy violation against safety stock")
        self.assertEqual(result["route"], HybridRoute.SQL_AND_RAG.value)

    def test_response_contains_scores_and_reason(self):
        result = route_hybrid_query("What is safety stock?")
        self.assertIn("scores", result)
        self.assertIn("reason", result)
        self.assertIn("matched_signals", result)
        self.assertIsInstance(result["scores"], dict)


if __name__ == "__main__":
    unittest.main()
