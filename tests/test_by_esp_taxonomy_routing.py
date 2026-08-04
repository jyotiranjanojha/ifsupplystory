import unittest
from unittest.mock import patch

from webapp.app import analyzer
from webapp.app.router_agent import route_question


class TestByEspTaxonomyRouting(unittest.TestCase):
    @patch("webapp.app.router_agent._call_ollama_router", return_value=None)
    def test_capacity_constraint_intent(self, _mock_llm):
        meta = route_question("Which resources are overutilized and have capacity constraints this week?")
        self.assertEqual(meta.get("intent"), "CapacityConstraintExplain")

    @patch("webapp.app.router_agent._call_ollama_router", return_value=None)
    def test_forecast_consumption_intent(self, _mock_llm):
        meta = route_question("Show forecast consumption from fcstorder by demand group")
        self.assertEqual(meta.get("intent"), "ForecastConsumptionExplain")

    @patch("webapp.app.router_agent._call_ollama_router", return_value=None)
    def test_inventory_projection_intent(self, _mock_llm):
        meta = route_question("What is projected inventory and stockout risk for item 100000000008?")
        self.assertEqual(meta.get("intent"), "InventoryProjectionExplain")

    def test_intent_normalization(self):
        self.assertEqual(analyzer._normalize_router_intent("CapacityConstraintExplain"), "domain_generation")
        self.assertEqual(analyzer._normalize_router_intent("PlanPurchDecisionExplain"), "sql_query")
        self.assertEqual(analyzer._normalize_router_intent("root_cause"), "root_cause")


if __name__ == "__main__":
    unittest.main()
