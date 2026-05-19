import importlib
import os
import unittest
from unittest.mock import patch


os.environ.setdefault("EXECUTION_API_KEY", "test-key")
os.environ.setdefault("PAPER_TRADING_MODE", "true")
os.environ.setdefault("POIWATCHER_DISABLE_BACKGROUND_THREADS", "1")

app_module = importlib.import_module("app")


class StopLossHardBlockTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.headers = {"X-Execution-Key": "test-key"}

    def _mt5_payload(self, **overrides):
        payload = {
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry": 1.1000,
            "sl": 1.0950,
            "tp": 1.1100,
            "risk_percent": 1.0,
            "lot_size": 0.01,
            "test_only": True,
            "account_state": {"capital": 10000},
        }
        payload.update(overrides)
        return payload

    def _bitunix_payload(self, **overrides):
        payload = {
            "symbol": "BTCUSDT",
            "direction": "BUY",
            "entry": 100000,
            "sl": 99000,
            "tp": 102000,
            "risk_percent": 1.0,
            "leverage": 1,
            "order_type": "LIMIT",
            "account_state": {"capital": 1000},
        }
        payload.update(overrides)
        return payload

    def test_mt5_approve_rejects_zero_stop_loss(self):
        resp = self.client.post(
            "/api/trade/approve",
            json=self._mt5_payload(sl=0),
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Stop loss", resp.get_json()["error"])

    def test_mt5_approve_rejects_entry_equal_stop_loss(self):
        resp = self.client.post(
            "/api/trade/approve",
            json=self._mt5_payload(entry=1.1, sl=1.1),
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("different from entry", resp.get_json()["error"])

    def test_bitunix_execute_rejects_zero_stop_loss_before_balance_or_api_calls(self):
        with patch.object(app_module, "bitunix_get_balance") as balance_mock, \
             patch.object(app_module, "bitunix_place_order") as order_mock:
            resp = self.client.post(
                "/bitunix/trade/execute",
                json=self._bitunix_payload(sl=0),
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Stop loss", resp.get_json()["error"])
        balance_mock.assert_not_called()
        order_mock.assert_not_called()

    def test_bitunix_execute_rejects_entry_equal_stop_loss_before_balance_or_api_calls(self):
        with patch.object(app_module, "bitunix_get_balance") as balance_mock, \
             patch.object(app_module, "bitunix_place_order") as order_mock:
            resp = self.client.post(
                "/bitunix/trade/execute",
                json=self._bitunix_payload(entry=100000, sl=100000),
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("different from entry", resp.get_json()["error"])
        balance_mock.assert_not_called()
        order_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
