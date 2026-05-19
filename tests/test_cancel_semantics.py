import importlib
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("EXECUTION_API_KEY", "test-key")
os.environ.setdefault("PAPER_TRADING_MODE", "true")
os.environ.setdefault("POIWATCHER_DISABLE_BACKGROUND_THREADS", "1")

app_module = importlib.import_module("app")


class CancelSemanticsTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.headers = {"X-Execution-Key": "test-key"}
        app_module._pending_limit_orders.clear()
        app_module._execution_queue.clear()
        if hasattr(app_module, "_mt5_cancel_requests"):
            app_module._mt5_cancel_requests.clear()

    def test_bitunix_cancel_does_not_mark_local_cancelled_when_exchange_rejects(self):
        app_module.BITUNIX_API_KEY = "test-bitunix-key"
        app_module._pending_limit_orders.append({
            "id": "journal-1",
            "venue": "bitunix",
            "symbol": "BTCUSDT",
            "direction": "BUY",
            "entry": 100000,
            "order_ticket": "exchange-order-1",
            "client_id": "journal-1",
            "status": "bitunix_limit_placed",
        })
        with patch.object(app_module, "bitunix_cancel_order", return_value={"code": 1001, "msg": "not found"}), \
             patch.object(app_module, "_log_execution_event") as log_mock, \
             patch.object(app_module, "send_telegram"):
            resp = self.client.post(
                "/bitunix/trade/cancel",
                json={"symbol": "BTCUSDT", "order_id": "exchange-order-1", "client_id": "journal-1"},
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 502)
        self.assertFalse(resp.get_json()["verified"])
        self.assertEqual(app_module._pending_limit_orders[0]["status"], "bitunix_limit_placed")
        log_mock.assert_not_called()

    def test_bitunix_cancel_marks_local_cancelled_only_when_exchange_confirms(self):
        app_module.BITUNIX_API_KEY = "test-bitunix-key"
        app_module._pending_limit_orders.append({
            "id": "journal-1",
            "venue": "bitunix",
            "symbol": "BTCUSDT",
            "direction": "BUY",
            "entry": 100000,
            "order_ticket": "exchange-order-1",
            "client_id": "journal-1",
            "status": "bitunix_limit_placed",
        })
        with patch.object(app_module, "bitunix_cancel_order", return_value={"code": 0, "data": {"successList": [{"orderId": "exchange-order-1"}]}}), \
             patch.object(app_module, "_log_execution_event") as log_mock, \
             patch.object(app_module, "send_telegram"):
            resp = self.client.post(
                "/bitunix/trade/cancel",
                json={"symbol": "BTCUSDT", "order_id": "exchange-order-1", "client_id": "journal-1"},
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["verified"])
        self.assertEqual(app_module._pending_limit_orders[0]["status"], "bitunix_limit_cancelled_verified")
        log_mock.assert_called_once()

    def test_mt5_limit_cancel_request_queues_command_not_fake_confirmed_cancel(self):
        app_module._pending_limit_orders.append({
            "id": "trade-1",
            "venue": "mt5",
            "symbol": "EURUSD",
            "direction": "BUY",
            "entry": 1.1,
            "order_ticket": 123456,
            "status": "limit_order_placed",
        })
        with patch.object(app_module, "_log_execution_event") as log_mock, \
             patch.object(app_module, "send_telegram"):
            resp = self.client.post(
                "/api/mt5/limit-order/cancel-request",
                json={"id": "trade-1", "order_ticket": 123456, "reason": "user_cancel"},
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(app_module._pending_limit_orders[0]["status"], "limit_order_cancel_requested")
        self.assertEqual(len(app_module._mt5_cancel_requests), 1)
        log_mock.assert_called_once()

    def test_mt5_cancel_requests_endpoint_returns_pending_then_marks_delivered(self):
        app_module._mt5_cancel_requests.append({"id": "trade-1", "order_ticket": 123456, "status": "pending"})
        resp = self.client.get("/api/mt5/cancel-requests", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data["requests"]), 1)
        self.assertEqual(app_module._mt5_cancel_requests[0]["status"], "delivered")
    def test_pending_orders_endpoint_exposes_venue_and_bitunix_orders(self):
        app_module._pending_limit_orders.extend([
            {
                "id": "mt5-1",
                "venue": "mt5",
                "symbol": "EURUSD",
                "direction": "BUY",
                "entry": 1.1,
                "sl": 1.09,
                "tp": 1.12,
                "order_ticket": 111,
                "placed_at": "2026-01-01T00:00:00+00:00",
                "expires_at": "2026-01-02T00:00:00+00:00",
                "status": "limit_placed",
            },
            {
                "id": "bitunix-1",
                "venue": "bitunix",
                "client_id": "bitunix-1",
                "symbol": "BTCUSDT",
                "direction": "SELL",
                "entry": 100000,
                "sl": 101000,
                "tp": 99000,
                "order_ticket": "bx-123",
                "placed_at": "2026-01-01T00:00:00+00:00",
                "expires_at": "2026-01-02T00:00:00+00:00",
                "status": "bitunix_limit_placed",
            },
        ])
        resp = self.client.get("/api/pending-orders", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        orders = resp.get_json()["orders"]
        venues = {o["id"]: o["venue"] for o in orders}
        self.assertEqual(venues["mt5-1"], "mt5")
        self.assertEqual(venues["bitunix-1"], "bitunix")
        self.assertEqual([o for o in orders if o["id"] == "bitunix-1"][0]["client_id"], "bitunix-1")


if __name__ == "__main__":
    unittest.main()
