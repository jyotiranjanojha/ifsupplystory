import unittest

from webapp.app.kpi_engine import DeterministicKPIEngine, KPIInputBundle


class TestDeterministicKPIEngine(unittest.TestCase):
    def setUp(self):
        self.engine = DeterministicKPIEngine()

    def _assert_common_fields(self, result):
        self.assertTrue(result.formula)
        self.assertTrue(result.business_description)
        self.assertIn("is_valid", result.output_validation)
        self.assertIn("checks", result.output_validation)
        self.assertIn("warnings", result.output_validation)

    def test_inventory_coverage_formula(self):
        result = self.engine.inventory_coverage(on_hand_inventory=300, demand_qty=150, period_days=15)
        self.assertAlmostEqual(result.value, 30.0)
        self._assert_common_fields(result)

    def test_inventory_coverage_invalid_period(self):
        result = self.engine.inventory_coverage(on_hand_inventory=300, demand_qty=150, period_days=0)
        self.assertEqual(result.value, 0.0)
        self.assertFalse(result.output_validation["is_valid"])

    def test_inventory_turns_formula(self):
        result = self.engine.inventory_turns(cogs=1200, average_inventory=300)
        self.assertAlmostEqual(result.value, 4.0)
        self._assert_common_fields(result)

    def test_inventory_turns_invalid_denominator(self):
        result = self.engine.inventory_turns(cogs=1200, average_inventory=0)
        self.assertEqual(result.value, 0.0)
        self.assertFalse(result.output_validation["is_valid"])

    def test_forecast_accuracy_perfect(self):
        result = self.engine.forecast_accuracy([10, 20, 30], [10, 20, 30])
        self.assertAlmostEqual(result.value, 1.0)
        self.assertTrue(result.output_validation["is_valid"])

    def test_forecast_accuracy_non_perfect(self):
        result = self.engine.forecast_accuracy([100, 90], [80, 100])
        # wmape = (20 + 10) / (80 + 100) = 30/180 = 0.166666...
        self.assertAlmostEqual(result.value, 0.8333333333, places=6)

    def test_forecast_accuracy_mismatched_lengths(self):
        result = self.engine.forecast_accuracy([10, 20], [10])
        self.assertEqual(result.value, 0.0)
        self.assertFalse(result.output_validation["is_valid"])

    def test_fill_rate_formula(self):
        result = self.engine.fill_rate(fulfilled_qty=90, total_demand_qty=100)
        self.assertAlmostEqual(result.value, 0.9)
        self.assertTrue(result.output_validation["is_valid"])

    def test_fill_rate_clamped(self):
        result = self.engine.fill_rate(fulfilled_qty=120, total_demand_qty=100)
        self.assertEqual(result.value, 1.0)

    def test_fill_rate_invalid_denominator(self):
        result = self.engine.fill_rate(fulfilled_qty=10, total_demand_qty=0)
        self.assertFalse(result.output_validation["is_valid"])

    def test_service_level_formula(self):
        result = self.engine.service_level(on_time_orders=45, total_orders=50)
        self.assertAlmostEqual(result.value, 0.9)
        self.assertTrue(result.output_validation["is_valid"])

    def test_service_level_invalid_when_on_time_exceeds_total(self):
        result = self.engine.service_level(on_time_orders=55, total_orders=50)
        self.assertEqual(result.value, 1.0)
        self.assertFalse(result.output_validation["is_valid"])

    def test_safety_stock_gap_formula(self):
        result = self.engine.safety_stock_gap(current_safety_stock=70, target_safety_stock=100)
        self.assertEqual(result.value, 30.0)
        self.assertTrue(result.output_validation["is_valid"])

    def test_safety_stock_gap_negative_current_invalid(self):
        result = self.engine.safety_stock_gap(current_safety_stock=-1, target_safety_stock=100)
        self.assertFalse(result.output_validation["is_valid"])

    def test_stockout_risk_formula(self):
        result = self.engine.stockout_risk(projected_stockout_periods=2, total_periods=10)
        self.assertAlmostEqual(result.value, 0.2)

    def test_stockout_risk_invalid_when_periods_exceed_total(self):
        result = self.engine.stockout_risk(projected_stockout_periods=11, total_periods=10)
        self.assertEqual(result.value, 1.0)
        self.assertFalse(result.output_validation["is_valid"])

    def test_customer_order_fulfilment_formula(self):
        result = self.engine.customer_order_fulfilment(fulfilled_customer_order_qty=400, total_customer_order_qty=500)
        self.assertAlmostEqual(result.value, 0.8)

    def test_demand_supply_analysis_formula(self):
        result = self.engine.demand_supply_analysis(total_supply_qty=90, total_demand_analysis_qty=120)
        self.assertAlmostEqual(result.value, 0.75)
        self.assertAlmostEqual(result.components["demand_supply_gap_qty"], -30.0)

    def test_capacity_constraint_no_overload(self):
        result = self.engine.capacity_constraint(required_capacity=80, available_capacity=100)
        self.assertEqual(result.value, 0.0)
        self.assertAlmostEqual(result.components["utilization_ratio"], 0.8)

    def test_capacity_constraint_with_overload(self):
        result = self.engine.capacity_constraint(required_capacity=125, available_capacity=100)
        self.assertAlmostEqual(result.value, 0.25)
        self.assertAlmostEqual(result.components["overload_qty"], 25.0)

    def test_capacity_constraint_invalid_denominator(self):
        result = self.engine.capacity_constraint(required_capacity=100, available_capacity=0)
        self.assertFalse(result.output_validation["is_valid"])

    def test_compute_all_returns_all_kpis(self):
        bundle = KPIInputBundle(
            on_hand_inventory=500,
            demand_qty=250,
            period_days=10,
            cogs=3000,
            average_inventory=600,
            forecast_qty=[90, 110, 100],
            actual_qty=[100, 100, 100],
            fulfilled_qty=230,
            total_demand_qty=250,
            on_time_orders=45,
            total_orders=50,
            current_safety_stock=120,
            target_safety_stock=150,
            projected_stockout_periods=1,
            total_periods=8,
            fulfilled_customer_order_qty=460,
            total_customer_order_qty=500,
            total_supply_qty=240,
            total_demand_analysis_qty=250,
            required_capacity=105,
            available_capacity=100,
        )
        result = self.engine.compute_all(bundle)
        self.assertEqual(len(result), 10)
        self.assertIn("Fill Rate", result)
        self.assertIn("Capacity Constraint", result)
        for kpi in result.values():
            self._assert_common_fields(kpi)

    def test_all_results_have_validation_flags(self):
        bundle = KPIInputBundle(
            on_hand_inventory=0,
            demand_qty=0,
            period_days=0,
            cogs=0,
            average_inventory=0,
            forecast_qty=[],
            actual_qty=[],
            fulfilled_qty=0,
            total_demand_qty=0,
            on_time_orders=0,
            total_orders=0,
            current_safety_stock=0,
            target_safety_stock=0,
            projected_stockout_periods=0,
            total_periods=0,
            fulfilled_customer_order_qty=0,
            total_customer_order_qty=0,
            total_supply_qty=0,
            total_demand_analysis_qty=0,
            required_capacity=0,
            available_capacity=0,
        )
        result = self.engine.compute_all(bundle)
        invalid_count = 0
        for kpi in result.values():
            if not kpi.output_validation["is_valid"]:
                invalid_count += 1
        self.assertGreaterEqual(invalid_count, 6)


if __name__ == "__main__":
    unittest.main()
