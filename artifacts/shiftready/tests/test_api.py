"""API tests with a fake AI client, plus one regression test per fixed bug."""
import asyncio
import json

import httpx

import app as app_module
import store
from conftest import FakeAIClient, report_json
from store import connect, create_candidate

ANSWER = "I'm sorry about that. I can arrange a prepaid return and a refund or a replacement, whichever works best for you today."


def start_round_one(client):
    _candidate_id, token = create_candidate("Test Candidate", "", "associate")
    started = client.post("/sr-api/session/start", json={"token": token}).json()
    return token, started["session_id"], started


def answer_all_calls(client, session_id, count=3):
    for index in range(count):
        response = client.post("/sr-api/session/live-turn", json={
            "session_id": session_id, "scenario_index": index, "speaker": "candidate",
            "text": ANSWER, "elapsed_seconds": 10 + index * 60,
        })
        assert response.status_code == 200, response.text


def test_full_round_one_flow(client, fake_ai):
    token, session_id, started = start_round_one(client)
    assert len(started["scenarios"]) == 3
    answer_all_calls(client, session_id)
    result = client.post("/sr-api/session/complete", json={"session_id": session_id})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["report"]["weighted_average"] == 8
    # No recording was uploaded, so the policy asks for a retest.
    assert body["report"]["verdict"] == "Retest recommended"
    page = client.get(body["report_url"])
    assert page.status_code == 200 and "Test Candidate" in page.text
    assert fake_ai.calls[0]["model"] == "claude-opus-5-5"


def test_complete_requires_a_reply_on_every_call(client, fake_ai):
    _token, session_id, _started = start_round_one(client)
    answer_all_calls(client, session_id, count=2)
    response = client.post("/sr-api/session/complete", json={"session_id": session_id})
    assert response.status_code == 400
    assert response.json()["detail"] == "Complete all 3 customer calls before generating the report."
    assert fake_ai.calls == []


def test_used_invite_cannot_start_again(client, fake_ai):
    token, session_id, _started = start_round_one(client)
    answer_all_calls(client, session_id)
    assert client.post("/sr-api/session/complete", json={"session_id": session_id}).status_code == 200
    assert client.post("/sr-api/session/start", json={"token": token}).status_code == 409


def test_invalid_decision_is_rejected(client):
    candidate = store.dashboard_data()["candidates"][0]
    response = client.post(f"/sr-api/candidates/{candidate['id']}/decision", json={"decision": "Maybe"})
    assert response.status_code == 400
    ok = client.post(f"/sr-api/candidates/{candidate['id']}/decision", json={"decision": "Strong Hire"})
    assert ok.json() == {"decision": "Strong Hire"}


# Regression tests for fixed bugs

def test_double_complete_calls_the_ai_once(client):
    _token, session_id, _started = start_round_one(client)
    answer_all_calls(client, session_id)
    fake = FakeAIClient(lambda _kwargs: report_json(), delay=0.05)

    async def complete_twice():
        transport = httpx.ASGITransport(app=app_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
            return await asyncio.gather(*[
                async_client.post("/sr-api/session/complete", json={"session_id": session_id}) for _ in range(2)
            ])

    from unittest.mock import patch
    with patch.object(app_module, "ai_client", return_value=fake):
        first, second = asyncio.run(complete_twice())
    assert first.status_code == second.status_code == 200
    assert len(fake.calls) == 1
    assert first.json()["report"] == second.json()["report"]


def test_seeded_highlights_use_timestamp_seconds():
    for candidate in store.dashboard_data()["candidates"]:
        for highlight in candidate["report"]["highlights"]:
            assert "timestamp_seconds" in highlight and "timestamp" not in highlight


def test_legacy_highlight_key_is_migrated(client):
    candidate = store.dashboard_data()["candidates"][0]
    with connect() as con:
        row = con.execute("SELECT id,data_json FROM reports WHERE candidate_id=?", (candidate["id"],)).fetchone()
        data = json.loads(row["data_json"])
        data["highlights"] = [{"kind": "strength", "timestamp": 65, "criterion": "x", "quote": "q", "note": ""}]
        con.execute("UPDATE reports SET data_json=? WHERE id=?", (json.dumps(data), row["id"]))
    store.initialize()
    report = store.report_for_candidate(candidate["id"])
    assert report["data"]["highlights"][0]["timestamp_seconds"] == 65
    assert "01:05" in client.get(f"/reports/{candidate['id']}").text


def test_round_two_for_unknown_candidate_skips_the_ai(client, fake_ai):
    response = client.post("/rounds/no-such-candidate", data={"focus": "escalation"}, follow_redirects=False)
    assert response.status_code == 404
    assert fake_ai.calls == []


def test_correction_reports_whether_a_turn_changed(client):
    _token, session_id, _started = start_round_one(client)
    base = {"session_id": session_id, "scenario_index": 0, "speaker": "customer"}
    client.post("/sr-api/session/live-turn", json={**base, "text": "Original customer line"})
    missing = client.post("/sr-api/session/live-turn", json={**base, "text": "New", "original_text": "Never said"})
    assert missing.json() == {"saved": False}
    found = client.post("/sr-api/session/live-turn", json={**base, "text": "Corrected", "original_text": "Original customer line"})
    assert found.json() == {"saved": True}


def test_customer_reply_uses_small_token_budget(client):
    _token, session_id, _started = start_round_one(client)
    fake = FakeAIClient(lambda _kwargs: "Fine, what can you do for me?")
    from unittest.mock import patch
    with patch.object(app_module, "ai_client", return_value=fake):
        response = client.post("/sr-api/session/turn", json={"session_id": session_id, "scenario_index": 0, "text": "Hello"})
    assert response.json() == {"reply": "Fine, what can you do for me?"}
    assert fake.calls[0]["max_tokens"] == 1024
    assert fake.calls[0]["model"] == "claude-sonnet-5-5"


def test_audio_upload_checks_signature_and_streams_to_disk(client):
    _token, session_id, _started = start_round_one(client)
    fake_audio = ("a.webm", b"this is not audio", "audio/webm")
    assert client.post("/sr-api/session/audio", data={"session_id": session_id}, files={"audio": fake_audio}).status_code == 400
    webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 2048
    response = client.post("/sr-api/session/audio", data={"session_id": session_id}, files={"audio": ("a.webm", webm, "audio/webm")})
    assert response.status_code == 200
    saved = store.MEDIA_DIR / f"session_{session_id}.webm"
    assert saved.read_bytes() == webm
    assert not list(store.MEDIA_DIR.glob("*.part"))


def test_audio_upload_rejects_oversized_recording(client, monkeypatch):
    import dataclasses

    _token, session_id, _started = start_round_one(client)
    monkeypatch.setattr(app_module, "settings", dataclasses.replace(app_module.settings, max_upload_bytes=1024, upload_chunk_bytes=512))
    webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 4096
    response = client.post("/sr-api/session/audio", data={"session_id": session_id}, files={"audio": ("a.webm", webm, "audio/webm")})
    assert response.status_code == 413
    assert not (store.MEDIA_DIR / f"session_{session_id}.webm").exists()
