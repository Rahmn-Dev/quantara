from django.test import SimpleTestCase

from trading.engine import Snapshot, create_decision, quant_score


class QuantEngineTests(SimpleTestCase):
    def setUp(self):
        self.good = Snapshot("TEST", 1000, 0.1, 2.0, 0.01, 0.03, 90, 80, 0.01)

    def test_score_is_bounded(self):
        self.assertGreaterEqual(quant_score(self.good), 0)
        self.assertLessEqual(quant_score(self.good), 100)

    def test_good_setup_can_be_ready(self):
        result = create_decision(self.good, equity=100_000_000, daily_pnl_pct=0, regime="BULLISH")
        self.assertEqual(result.status, "READY")
        self.assertGreater(result.position_size, 0)

    def test_risk_engine_vetoes_large_gap(self):
        bad = Snapshot("TEST", 1000, 0.1, 2, 0.01, 0.03, 90, 80, 0.04)
        result = create_decision(bad, equity=100_000_000, daily_pnl_pct=0, regime="BULLISH")
        self.assertEqual(result.status, "WAIT")
        self.assertIn("Gap", result.veto_reasons)

    def test_daily_loss_is_hard_veto(self):
        result = create_decision(
            self.good, equity=100_000_000, daily_pnl_pct=-0.03, regime="BULLISH"
        )
        self.assertEqual(result.status, "WAIT")
        self.assertFalse(result.checks["daily_loss"])
