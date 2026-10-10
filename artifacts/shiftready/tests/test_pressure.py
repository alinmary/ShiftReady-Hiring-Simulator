"""Run with PYTHONPATH=artifacts/shiftready; never use the demo datastore."""
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

TEST_DATA = tempfile.TemporaryDirectory(prefix="shiftready-pressure-tests-")
os.environ["SHIFTREADY_DATA_DIR"] = TEST_DATA.name

from fastapi.testclient import TestClient
from app import app
from pressure import PRESSURE_CRITERIA, PRESSURE_OPTIONS
from store import CRITERIA, SCENARIOS, connect, create_candidate, dashboard_data


class PressureTests(unittest.TestCase):
    def test_round_two_and_preserved_round_one(self):
        with TestClient(app) as client:
            candidate = dashboard_data()["candidates"][0]
            with connect() as con:
                original_report = con.execute("SELECT data_json FROM reports WHERE candidate_id=?", (candidate["id"],)).fetchone()[0]
            first_html = client.get("/reports/" + candidate["id"]).text
            self.assertIn("Pressure Mode", first_html)
            self.assertEqual(first_html.count('<option value="saturday">'), 1)
            before = list(SCENARIOS)
            _new_id, token = create_candidate("Round One Regression", "", "associate")
            first = client.post("/sr-api/session/start", json={"token": token}).json()
            self.assertEqual(len(first["scenarios"]), 3)
            self.assertNotIn("events", first["scenarios"][0])
            self.assertEqual(SCENARIOS, before)
            self.assertEqual(client.post("/sr-api/session/pressure-event", json={"session_id": first["session_id"], "event_id": "operations", "elapsed_seconds": 45}).status_code, 400)

            for key, title in PRESSURE_OPTIONS:
                response = client.post("/rounds/" + candidate["id"], data={"focus": "composure / prioritisation", "mode": "pressure", "pressure_key": key}, follow_redirects=False)
                self.assertEqual(response.status_code, 303)
                self.assertTrue(response.headers["location"].startswith("/invite/"))
                token = response.headers["location"].rsplit("/", 1)[1]
                intro = client.get(response.headers["location"]).text
                self.assertIn("Pressure Mode: " + title, intro)
                started = client.post("/sr-api/session/start", json={"token": token}).json()
                self.assertEqual(started["round"], 2)
                self.assertEqual(len(started["scenarios"]), 1)
                self.assertEqual([event["at"] for event in started["scenarios"][0]["events"]], [45, 90, 150, 210])
            session_id = started["session_id"]
            self.assertEqual(client.post("/sr-api/session/live-turn", json={
                "session_id": session_id, "scenario_index": 2, "speaker": "candidate", "text": "Invalid call",
            }).status_code, 400)
            event_payload = {"session_id": session_id, "event_id": "operations", "elapsed_seconds": 45, "delivery": "display"}
            self.assertEqual(client.post("/sr-api/session/pressure-event", json={**event_payload, "elapsed_seconds": 44}).status_code, 400)
            self.assertEqual(client.post("/sr-api/session/pressure-event", json={**event_payload, "event_id": "priority", "elapsed_seconds": 90}).status_code, 400)
            self.assertEqual(client.post("/sr-api/session/pressure-event", json=event_payload).status_code, 200)
            self.assertEqual(client.post("/sr-api/session/pressure-event", json={**event_payload, "delivery": "speech"}).json()["delivery"], "speech")
            self.assertEqual(client.post("/sr-api/session/complete", json={"session_id": session_id}).status_code, 400)
            for index, event in enumerate(started["scenarios"][0]["events"]):
                self.assertEqual(client.post("/sr-api/session/pressure-event", json={
                    "session_id": session_id, "event_id": event["id"], "elapsed_seconds": event["at"],
                    "on_hold": event["id"] == "return",
                }).status_code, 200)
                self.assertEqual(client.post("/sr-api/session/live-turn", json={
                    "session_id": session_id, "scenario_index": 0, "speaker": "candidate",
                    "text": f"Response {index}: Priya, please handle that. Thank you for waiting; let us resolve your original complaint.",
                    "elapsed_seconds": event["at"] + 5,
                }).status_code, 200)
            resumed = client.post("/sr-api/session/start", json={"token": token}).json()
            self.assertEqual(len(resumed["pressure_events"]), 4)
            self.assertEqual(resumed["started_at"], started["started_at"])
            prompts = []

            async def fake_create(**kwargs):
                prompts.append(kwargs)
                report = {
                    "scores": dict.fromkeys(CRITERIA, 8),
                    "pressure_scores": dict.fromkeys(PRESSURE_CRITERIA, 7),
                    "summary": "Pressure test fixture", "confidence": "Low", "red_flags": [],
                    "highlights": [], "follow_up_questions": [],
                }
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(report))])

            fake_client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))
            with patch("app.ai_client", return_value=fake_client):
                result = client.post("/sr-api/session/complete", json={"session_id": session_id})
            self.assertEqual(result.status_code, 200, result.text)
            report = result.json()["report"]
            self.assertEqual(report["pressure_average"], 7)
            self.assertEqual(report["weighted_average"], 8)
            self.assertEqual(len(report["pressure_timeline"]), 4)
            self.assertEqual(len(report["pressure_timeline"][0]["responses"]), 1)
            self.assertEqual(report["pressure_timeline"][0]["delivery"], "speech")
            self.assertIn("Actual interruption timeline", prompts[0]["messages"][0]["content"])
            html = client.get(result.json()["report_url"]).text
            self.assertIn("Interruption &amp; response timeline", html)
            for criterion in PRESSURE_CRITERIA:
                self.assertIn(criterion, html)
            with connect() as con:
                saved_first = con.execute("SELECT data_json FROM reports WHERE candidate_id=? AND round=1", (candidate["id"],)).fetchone()[0]
            self.assertEqual(saved_first, original_report)
            self.assertNotIn("invite-notice", client.get("/?invite=anything").text)


if __name__ == "__main__":
    unittest.main()
