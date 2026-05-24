import importlib
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("EXECUTION_API_KEY", "test-key")
os.environ.setdefault("PAPER_TRADING_MODE", "true")
os.environ.setdefault("POIWATCHER_DISABLE_BACKGROUND_THREADS", "1")

app_module = importlib.import_module("app")


class NclexExternalReviewTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def test_public_post_accepts_single_review_and_returns_receipt(self):
        payload = {
            "schemaVersion": "external-review-submission.v1",
            "questionId": "assistive_devices_first20_q008_variant_c",
            "reviewer": {"key": "emeka", "name": "Emeka", "role": "Founder"},
            "decision": "FIX",
            "response": {"notes": "Rationale is too generic."},
            "itemSnapshot": {"stem": "Which action is safest?"},
        }
        with patch.object(app_module, "nclex_external_reviews_append") as append_mock:
            append_mock.return_value = [{
                "id": "saved-1",
                "questionId": payload["questionId"],
                "reviewer": {"key": "emeka"},
                "receivedAt": "2026-05-24T00:00:00+00:00",
            }]
            resp = self.client.post("/api/nclex/external-reviews", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["savedCount"], 1)
        self.assertEqual(data["saved"][0]["questionId"], payload["questionId"])

    def test_public_post_rejects_invalid_payload(self):
        resp = self.client.post("/api/nclex/external-reviews", json={"schemaVersion": "unknown"})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json()["ok"])

    def test_append_stores_batch_in_separate_private_gist_file(self):
        existing = {"schemaVersion": "nclex-external-reviews-log.v1", "submissions": []}
        batch = {
            "schemaVersion": "external-review-batch.v1",
            "submissions": [
                {
                    "schemaVersion": "external-review-submission.v1",
                    "questionId": "q1",
                    "reviewer": {"key": "alexis", "name": "Alexis"},
                    "response": {"decision": "PASS"},
                },
                {
                    "schemaVersion": "external-review-submission.v1",
                    "questionId": "q2",
                    "reviewer": {"key": "ihechi", "name": "Ihechi"},
                    "response": {"decision": "FIX"},
                },
            ],
        }
        written = {}
        def fake_write(file_name, data):
            written["file_name"] = file_name
            written["data"] = data
            return True

        with patch.object(app_module, "gist_file_read_json", return_value=existing), \
             patch.object(app_module, "gist_file_write_json", side_effect=fake_write):
            saved = app_module.nclex_external_reviews_append(batch)

        self.assertEqual(len(saved), 2)
        self.assertEqual(written["file_name"], app_module.NCLEX_EXTERNAL_REVIEWS_GIST_FILE)
        self.assertEqual(written["data"]["schemaVersion"], "nclex-external-reviews-log.v1")
        self.assertEqual([s["questionId"] for s in written["data"]["submissions"]], ["q1", "q2"])

    def test_admin_get_requires_execution_key(self):
        no_key = self.client.get("/api/nclex/external-reviews")
        self.assertEqual(no_key.status_code, 401)
        with patch.object(app_module, "nclex_external_reviews_read", return_value={"schemaVersion": "nclex-external-reviews-log.v1", "submissions": [], "updatedAt": None}):
            ok = self.client.get("/api/nclex/external-reviews", headers={"X-Execution-Key": "test-key"})
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
