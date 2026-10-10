from __future__ import annotations

import json
import os
import re
import secrets
import uuid
from pathlib import Path
from typing import Any

import httpx
from anthropic import AsyncAnthropic
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from evidence import bind_report_evidence
from pressure import PRESSURE_CRITERIA, PRESSURE_OPTIONS, pressure_scenario, pressure_timeline

from store import (
    CRITERIA,
    DATA_DIR,
    MEDIA_DIR,
    ROOT,
    SCENARIOS,
    candidate_by_token,
    connect,
    create_candidate,
    dashboard_data,
    initialize,
    report_for_candidate,
    turns_for_session,
    record_turn,
    utcnow,
)


app = FastAPI(title="ShiftReady")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.mount("/media", StaticFiles(directory=MEDIA_DIR, check_dir=False), name="media")
templates = Jinja2Templates(directory=ROOT / "templates")


@app.on_event("startup")
def startup() -> None:
    initialize()


def ai_client() -> AsyncAnthropic:
    api_key = os.environ.get("AI_INTEGRATIONS_ANTHROPIC_API_KEY")
    base_url = os.environ.get("AI_INTEGRATIONS_ANTHROPIC_BASE_URL")
    if not api_key or not base_url:
        raise HTTPException(503, "Managed Anthropic AI is not configured for this project.")
    return AsyncAnthropic(api_key=api_key, base_url=base_url)


def parse_json_response(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise HTTPException(502, "The AI response could not be read. Please retry.") from error
    if not isinstance(result, dict):
        raise HTTPException(502, "The AI returned an invalid response. Please retry.")
    return result


def update_candidate_status(candidate_id: str, status: str) -> None:
    with connect() as con:
        con.execute("UPDATE candidates SET status=? WHERE id=?", (status, candidate_id))


class StartRequest(BaseModel):
    token: str


class TurnRequest(BaseModel):
    session_id: str
    scenario_index: int = Field(ge=0, le=2)
    text: str = Field(min_length=1, max_length=1600)
    elapsed_seconds: float = Field(default=0, ge=0)


class CompleteRequest(BaseModel):
    session_id: str
    voice_signals: dict[str, Any] = Field(default_factory=dict)


class LiveTurnRequest(TurnRequest):
    speaker: str
    original_text: str | None = Field(default=None, max_length=1600)


class DecisionRequest(BaseModel):
    decision: str


class PressureEventRequest(BaseModel):
    session_id: str
    event_id: str
    elapsed_seconds: float = Field(ge=0, le=300)
    on_hold: bool = False
    delivery: str = "display"


@app.post("/sr-api/session/pressure-event")
def record_pressure_event(payload: PressureEventRequest) -> dict[str, Any]:
    with connect() as con:
        session = con.execute(
            "SELECT s.*,i.scenarios_json FROM sessions s JOIN invites i ON i.id=s.invite_id WHERE s.id=? AND s.completed_at IS NULL",
            (payload.session_id,),
        ).fetchone()
        if not session:
            raise HTTPException(404, "Active session not found.")
        scenarios = json.loads(session["scenarios_json"])
        if session["round"] != 2 or scenarios[0].get("mode") != "pressure":
            raise HTTPException(400, "Pressure events are only available in Pressure Mode Round 2.")
        event = next((item for item in scenarios[0]["events"] if item["id"] == payload.event_id), None)
        if not event or payload.delivery not in {"speech", "display"}:
            raise HTTPException(400, "Invalid pressure event.")
        existing = con.execute("SELECT * FROM pressure_events WHERE session_id=? AND event_id=?", (payload.session_id, payload.event_id)).fetchone()
        if existing:
            result = dict(existing)
            if payload.delivery == "speech":
                con.execute("UPDATE pressure_events SET delivery='speech' WHERE session_id=? AND event_id=?", (payload.session_id, payload.event_id))
                result["delivery"] = "speech"
            return result
        count = con.execute("SELECT COUNT(*) FROM pressure_events WHERE session_id=?", (payload.session_id,)).fetchone()[0]
        last_elapsed = con.execute("SELECT COALESCE(MAX(elapsed_seconds),0) FROM pressure_events WHERE session_id=?", (payload.session_id,)).fetchone()[0]
        if scenarios[0]["events"][count]["id"] != payload.event_id or payload.elapsed_seconds < max(event["at"], last_elapsed):
            raise HTTPException(400, "Complete the pressure events in order at their scheduled times.")
        text = event["text"] if payload.on_hold else event.get("returned_text", event["text"])
        result = {
            "session_id": payload.session_id, "event_id": event["id"], "label": event["label"],
            "speaker": event["speaker"], "text": text, "scheduled_seconds": event["at"],
            "elapsed_seconds": payload.elapsed_seconds, "delivery": payload.delivery,
        }
        con.execute(
            "INSERT INTO pressure_events(session_id,event_id,label,speaker,text,scheduled_seconds,elapsed_seconds,delivery) VALUES(:session_id,:event_id,:label,:speaker,:text,:scheduled_seconds,:elapsed_seconds,:delivery)",
            result,
        )
    return result


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    data = dashboard_data()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={**data, "page": "dashboard"},
    )


@app.post("/invites/create")
def create_invite(
    name: str = Form(...),
    email: str = Form(""),
    role_id: str = Form(...),
) -> RedirectResponse:
    if not name.strip():
        raise HTTPException(400, "Candidate name is required.")
    try:
        _candidate_id, token = create_candidate(name, email, role_id)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return RedirectResponse(f"/?invite={token}", status_code=303)


@app.get("/invite/{token}", response_class=HTMLResponse)
def invite_page(request: Request, token: str) -> HTMLResponse:
    candidate = candidate_by_token(token)
    if not candidate:
        raise HTTPException(404, "This interview invitation is invalid or has expired.")
    if candidate["used_at"]:
        return RedirectResponse(f"/candidate/{token}", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="candidate.html",
        context={
            "candidate": candidate,
            "token": token,
            "scenarios": json.loads(candidate["scenarios_json"]),
            "page": "candidate",
        },
    )


@app.get("/candidate/{token}", response_class=HTMLResponse)
def candidate_page(request: Request, token: str) -> HTMLResponse:
    candidate = candidate_by_token(token)
    if not candidate:
        raise HTTPException(404, "This interview invitation is invalid or has expired.")
    return templates.TemplateResponse(
        request=request,
        name="candidate.html",
        context={
            "candidate": candidate,
            "token": token,
            "scenarios": json.loads(candidate["scenarios_json"]),
            "page": "candidate",
        },
    )


@app.get("/reports/{candidate_id}", response_class=HTMLResponse)
def report_page(request: Request, candidate_id: str) -> HTMLResponse:
    report = report_for_candidate(candidate_id)
    if not report:
        raise HTTPException(404, "No completed interview report is available yet.")
    return templates.TemplateResponse(
        request=request,
        name="report.html",
        context={"report": report, "page": "report", "pressure_options": PRESSURE_OPTIONS},
    )


@app.post("/sr-api/session/start")
def start_session(payload: StartRequest) -> dict[str, Any]:
    candidate = candidate_by_token(payload.token)
    if not candidate:
        raise HTTPException(404, "This interview link is not valid.")
    if candidate["status"] == "Completed" and candidate["used_at"]:
        raise HTTPException(409, "This invitation has already been completed.")

    with connect() as con:
        completed = con.execute(
            "SELECT id FROM sessions WHERE invite_id=? AND completed_at IS NOT NULL LIMIT 1",
            (candidate["invite_id"],),
        ).fetchone()
        if completed:
            raise HTTPException(409, "This invitation has already been completed.")
        active = con.execute(
            "SELECT id FROM sessions WHERE invite_id=? AND completed_at IS NULL ORDER BY started_at DESC LIMIT 1",
            (candidate["invite_id"],),
        ).fetchone()
        if active:
            session_id = active["id"]
        else:
            session_id = uuid.uuid4().hex
            con.execute(
                "INSERT INTO sessions(id,candidate_id,invite_id,round,started_at) VALUES(?,?,?,?,?)",
                (session_id, candidate["id"], candidate["invite_id"], candidate["round"], utcnow()),
            )
            con.execute("UPDATE invites SET used_at=? WHERE id=?", (utcnow(), candidate["invite_id"]))
            con.execute("UPDATE candidates SET status='In progress' WHERE id=?", (candidate["id"],))

    scenarios = json.loads(candidate["scenarios_json"])
    result = {
        "session_id": session_id,
        "scenarios": [
            {key: scenario[key] for key in ("title", "customer", "brief", "opening", "pressure", "mode", "events") if key in scenario}
            for scenario in scenarios
        ],
        "round": candidate["round"],
    }
    if scenarios[0].get("mode") == "pressure":
        with connect() as con:
            result["started_at"] = con.execute("SELECT started_at FROM sessions WHERE id=?", (session_id,)).fetchone()[0]
            result["pressure_events"] = [dict(row) for row in con.execute("SELECT * FROM pressure_events WHERE session_id=? ORDER BY elapsed_seconds", (session_id,))]
    return result


@app.post("/sr-api/session/live-turn")
def live_turn(payload: LiveTurnRequest) -> dict[str, bool]:
    if payload.speaker not in {"candidate", "customer"}:
        raise HTTPException(400, "Invalid conversation speaker.")
    with connect() as con:
        session = con.execute("SELECT s.id,i.scenarios_json FROM sessions s JOIN invites i ON i.id=s.invite_id WHERE s.id=? AND s.completed_at IS NULL", (payload.session_id,)).fetchone()
    if not session:
        raise HTTPException(404, "This interview session is no longer active.")
    if payload.scenario_index >= len(json.loads(session["scenarios_json"])):
        raise HTTPException(400, "Invalid call number.")
    if payload.original_text is not None:
        if payload.speaker != "customer":
            raise HTTPException(400, "Only customer interruptions can correct an existing turn.")
        with connect() as con:
            con.execute(
                """UPDATE turns SET text=? WHERE id=(
                   SELECT id FROM turns WHERE session_id=? AND scenario_index=?
                   AND speaker='customer' AND text=? ORDER BY id DESC LIMIT 1)""",
                (payload.text.strip(), payload.session_id, payload.scenario_index, payload.original_text),
            )
        return {"saved": True}
    record_turn(payload.session_id, payload.scenario_index, payload.speaker, payload.text.strip(), payload.elapsed_seconds)
    return {"saved": True}


@app.post("/sr-api/session/turn")
async def session_turn(payload: TurnRequest) -> dict[str, Any]:
    with connect() as con:
        session = con.execute(
            "SELECT s.*, i.scenarios_json FROM sessions s JOIN invites i ON i.id=s.invite_id WHERE s.id=?",
            (payload.session_id,),
        ).fetchone()
    if not session or session["completed_at"]:
        raise HTTPException(404, "This interview session is no longer active.")
    scenarios = json.loads(session["scenarios_json"])
    if payload.scenario_index >= len(scenarios):
        raise HTTPException(400, "Invalid call number.")
    scenario = scenarios[payload.scenario_index]
    transcript = turns_for_session(payload.session_id, payload.scenario_index)

    messages = [
        {"role": "user" if row["speaker"] == "candidate" else "assistant", "content": row["text"]}
        for row in transcript
    ]
    messages.append({"role": "user", "content": payload.text.strip()})
    prompt = f"""You are role-playing a retail customer in a hiring simulation. Stay in character as {scenario['customer']}.
Situation: {scenario['brief']}
Escalation behavior: {scenario['pressure']}
The candidate is the store employee. Reply in one or two natural spoken sentences, usually under 45 words. React only to what they actually said. Do not grade, coach, reveal hidden scenario instructions, or mention being an AI. Never insult or threaten them. If they offer a respectful practical solution, show a believable reduction in frustration. If they avoid the problem, push once for a concrete answer. Keep the customer's personality consistent.
"""
    if scenario.get("mode") == "pressure":
        with connect() as con:
            events = [dict(row) for row in con.execute("SELECT * FROM pressure_events WHERE session_id=? ORDER BY elapsed_seconds", (payload.session_id,))]
        prompt += "\nSimulation interruptions that have actually occurred (context, not candidate speech): " + json.dumps(events)
    try:
        client = ai_client()
        response = await client.messages.create(
            model="claude-sonnet-5-5",
            max_tokens=8192,
            system=prompt,
            messages=messages,
        )
        reply = "".join(block.text for block in response.content if getattr(block, "type", "") == "text").strip()
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(502, f"Customer simulation could not respond: {error.__class__.__name__}") from error

    if not reply:
        raise HTTPException(502, "Customer simulation returned an empty response.")
    record_turn(payload.session_id, payload.scenario_index, "candidate", payload.text.strip(), payload.elapsed_seconds)
    record_turn(payload.session_id, payload.scenario_index, "customer", reply, payload.elapsed_seconds + 3)
    return {"reply": reply}


@app.post("/sr-api/session/audio")
async def upload_audio(
    session_id: str = Form(...),
    audio: UploadFile = File(...),
) -> dict[str, str]:
    if not audio.content_type or not audio.content_type.startswith("audio/"):
        raise HTTPException(400, "Upload an audio recording.")
    if not audio.filename or not audio.filename.lower().endswith((".webm", ".wav", ".mp4", ".ogg")):
        raise HTTPException(400, "Unsupported audio format.")
    with connect() as con:
        session = con.execute("SELECT id FROM sessions WHERE id=? AND completed_at IS NULL", (session_id,)).fetchone()
    if not session:
        raise HTTPException(404, "Active session not found.")
    content = await audio.read(80 * 1024 * 1024 + 1)
    if len(content) > 80 * 1024 * 1024:
        raise HTTPException(413, "The recording is too large.")
    suffix = Path(audio.filename).suffix.lower()
    filename = f"session_{session_id}{suffix}"
    (MEDIA_DIR / filename).write_bytes(content)
    with connect() as con:
        con.execute("UPDATE sessions SET audio_path=? WHERE id=?", (f"/media/{filename}", session_id))
    return {"audio_url": f"/media/{filename}"}


@app.post("/sr-api/session/complete")
async def complete_session(payload: CompleteRequest) -> dict[str, Any]:
    with connect() as con:
        session = con.execute(
            """SELECT s.*, c.name AS candidate_name, c.role_id, r.name AS role_name,
                      i.scenarios_json FROM sessions s
               JOIN candidates c ON c.id=s.candidate_id JOIN roles r ON r.id=c.role_id
               JOIN invites i ON i.id=s.invite_id WHERE s.id=?""",
            (payload.session_id,),
        ).fetchone()
    if not session:
        raise HTTPException(404, "Interview session not found.")
    if session["completed_at"]:
        report = report_for_candidate(session["candidate_id"])
        return {"candidate_id": session["candidate_id"], "report_url": f"/reports/{session['candidate_id']}", "report": report["data"] if report else {}}
    turns = turns_for_session(payload.session_id)
    scenarios = json.loads(session["scenarios_json"])
    is_pressure = session["round"] == 2 and scenarios[0].get("mode") == "pressure"
    if any(not any(turn["speaker"] == "candidate" and turn["scenario_index"] == index for turn in turns) for index in range(len(scenarios))):
        raise HTTPException(400, "Respond to the Pressure Mode customer before generating the report." if is_pressure else "Complete all three customer calls before generating the report.")
    timeline = []
    if is_pressure:
        with connect() as con:
            events = [dict(row) for row in con.execute("SELECT * FROM pressure_events WHERE session_id=? ORDER BY elapsed_seconds", (payload.session_id,))]
        if len(events) != len(scenarios[0]["events"]):
            raise HTTPException(400, "Complete all timed Pressure Mode interruptions before generating the report.")
        timeline = pressure_timeline(events, turns)
    transcript = [
        {
            "scenario": scenarios[turn["scenario_index"]]["title"],
            "speaker": turn["speaker"],
            "text": turn["text"],
            "timestamp_seconds": round(turn["elapsed_seconds"]),
        }
        for turn in turns
    ]
    scoring_prompt = f"""Score a retail job interview simulation based only on the transcript and the provided recording-derived signals.
Return one JSON object with keys: scores, weighted_average, verdict, red_flags, confidence, summary, highlights, follow_up_questions.
scores must contain these exact seven keys with integer scores 1 through 10: {json.dumps(CRITERIA)}.
Score fairly and consistently. Empathy and Composure have 1.5x weight; all other criteria have 1x. Compute the weighted average over total weight 8, rounded to one decimal. Strong Hire requires average >= 8 and no criterion below 6. Decent Hire is 6.0 to 7.9. Do Not Hire is below 6 or any substantiated red flag.
Only report a red flag when the transcript provides direct evidence of rudeness, a knowingly false promise, or discriminatory remarks. Quote the exact evidence. Do not infer intent or penalize a candidate for accent, dialect, fluency, grammar, disability, speech impediment, or language style. Vocal Tone & Warmth means calmness, warmth, and respect only; never accent or fluency. Use the recording-derived signals only for pace, pauses, filler words, and relative loudness. If evidence is insufficient for audio criteria, state low confidence and recommend a retest instead of pretending to know tone.
red_flags must be an array of objects with label (exactly "Rudeness", "Knowingly false promise", or "Discriminatory remarks") and quote (an exact excerpt of the candidate's words, not the customer's).
highlights must be 2-5 items with kind ("strength" or "coaching"), timestamp_seconds (copied from a relevant transcript entry), criterion, quote (exact transcript excerpt), and note. follow_up_questions must be 2-4 concise questions for a human interviewer.
Do not make an employment decision. This is advisory support only. Return valid JSON only.

Role: {session['role_name']}
Candidate: {session['candidate_name']}
Scenario briefs: {json.dumps([{k: v for k, v in s.items() if k in ('title','brief')} for s in scenarios])}
Transcript: {json.dumps(transcript, ensure_ascii=False)}
Recording-derived signals: {json.dumps(payload.voice_signals, ensure_ascii=False)}
"""
    if is_pressure:
        scoring_prompt += f"""
This is Round 2 Pressure Mode. Additionally return pressure_scores with exactly these keys and integer scores 1-10: {json.dumps(PRESSURE_CRITERIA)}.
Prioritisation: safety first, then money/operations, then complaints, while acknowledging competing needs.
Delegation: clear named or role-based assignment, specific action, and appropriate escalation; do not reward doing everything personally.
Closing the loop: return to and resolve the ORIGINAL customer issue after interruptions; do not mistake a promise to return for actually returning.
Review communication under interruption and composure using the existing seven criteria. Do not penalise lack of audio or accent; lower confidence where evidence is insufficient.
Base the three additional scores only on actual candidate words and the event timeline. Missing responses are missing evidence, not proof of misconduct.
The seven-criterion average stays separate from these additional pressure scores.
Actual interruption timeline and candidate responses: {json.dumps(timeline, ensure_ascii=False)}
"""
    try:
        response = await ai_client().messages.create(
            model="claude-opus-5-5",
            max_tokens=8192,
            messages=[{"role": "user", "content": scoring_prompt}],
        )
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        report = parse_json_response(text)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(502, f"Report generation failed: {error.__class__.__name__}") from error

    report["transcript"] = transcript
    report["signals"] = payload.voice_signals
    report["red_flags"] = report.get("red_flags") if isinstance(report.get("red_flags"), list) else []
    report["highlights"] = report.get("highlights") if isinstance(report.get("highlights"), list) else []
    report["follow_up_questions"] = report.get("follow_up_questions") if isinstance(report.get("follow_up_questions"), list) else []
    bind_report_evidence(report, transcript)
    try:
        report["scores"] = {
            criterion: max(1, min(10, int(report["scores"][criterion])))
            for criterion in CRITERIA
        }
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(502, "The AI report omitted a valid score. Please retry.") from error
    scores = report["scores"]
    if is_pressure:
        try:
            report["pressure_scores"] = {
                criterion: max(1, min(10, int(report["pressure_scores"][criterion])))
                for criterion in PRESSURE_CRITERIA
            }
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(502, "The Pressure Mode report omitted a valid score. Please retry.") from error
        report["pressure_timeline"] = timeline
        report["pressure_average"] = round(sum(report["pressure_scores"].values()) / 3, 1)
        report["mode"] = "pressure"
    average = (sum(scores.values()) + scores[CRITERIA[0]] * 0.5 + scores[CRITERIA[6]] * 0.5) / 8
    report["weighted_average"] = round(average, 1)
    if report["red_flags"] or average < 6:
        report["verdict"] = "Do Not Hire"
    elif average >= 8 and min(scores.values()) >= 6:
        report["verdict"] = "Strong Hire"
    else:
        report["verdict"] = "Decent Hire"
    candidate_words = sum(len(turn["text"].split()) for turn in turns if turn["speaker"] == "candidate")
    low_confidence = (
        not session["audio_path"]
        or candidate_words < 90
        or float(payload.voice_signals.get("spoken_word_count", 0) or 0) < 30
        or "low" in str(report.get("confidence", "")).lower()
    )
    report["retest_recommended"] = low_confidence
    if low_confidence:
        report["confidence"] = "Low — more voice evidence is needed; scores are provisional"
        if not report["red_flags"]:
            report["verdict"] = "Retest recommended"
    with connect() as con:
        con.execute(
            "UPDATE sessions SET completed_at=?,voice_signals_json=? WHERE id=?",
            (utcnow(), json.dumps(payload.voice_signals), payload.session_id),
        )
        con.execute(
            "INSERT OR REPLACE INTO reports(id,session_id,candidate_id,round,data_json,created_at) VALUES(?,?,?,?,?,?)",
            (uuid.uuid4().hex, payload.session_id, session["candidate_id"], session["round"], json.dumps(report), utcnow()),
        )
        con.execute("UPDATE candidates SET status='Completed' WHERE id=?", (session["candidate_id"],))
    return {
        "candidate_id": session["candidate_id"],
        "report_url": f"/reports/{session['candidate_id']}",
        "report": report,
    }


@app.post("/sr-api/candidates/{candidate_id}/decision")
def set_decision(candidate_id: str, payload: DecisionRequest) -> dict[str, str]:
    if payload.decision not in {"Pending", "Strong Hire", "Decent Hire", "Do Not Hire"}:
        raise HTTPException(400, "Select a valid hiring decision.")
    with connect() as con:
        result = con.execute(
            "UPDATE candidates SET owner_decision=? WHERE id=?",
            (payload.decision, candidate_id),
        )
        if result.rowcount == 0:
            raise HTTPException(404, "Candidate not found.")
    return {"decision": payload.decision}


@app.post("/rounds/{candidate_id}")
async def create_round(
    candidate_id: str,
    focus: str = Form(...),
    mode: str = Form("standard"),
    pressure_key: str = Form("saturday"),
) -> RedirectResponse:
    old_report = report_for_candidate(candidate_id)
    if not old_report:
        raise HTTPException(404, "Complete a first-round interview before creating a follow-up round.")
    if mode not in {"standard", "pressure"}:
        raise HTTPException(400, "Select a valid Round 2 mode.")
    if mode == "pressure":
        if old_report["round"] != 1 or pressure_key not in dict(PRESSURE_OPTIONS):
            raise HTTPException(400, "Pressure Mode follows Round 1. Select one of the six pressure situations.")
        generated = [pressure_scenario(pressure_key, focus.strip())]
        token = secrets.token_urlsafe(24)
        with connect() as con:
            con.execute(
                "INSERT INTO invites(id,candidate_id,token,round,scenarios_json,created_at) VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex, candidate_id, token, 2, json.dumps(generated), utcnow()),
            )
            con.execute("UPDATE candidates SET status='Invited' WHERE id=?", (candidate_id,))
        return RedirectResponse(f"/invite/{token}", status_code=303)
    if not focus.strip():
        focus = ", ".join(old_report["data"].get("scores", {}).keys())
    try:
        response = await ai_client().messages.create(
            model="claude-opus-5-5",
            max_tokens=8192,
            messages=[
                {
                    "role": "user",
                    "content": f"""Create exactly 3 realistic, harder retail phone-call scenarios for a second interview round.
Target these specific development areas: {focus.strip()}
Role: {old_report['role_name']}
Use different situations from the first-round scenarios. Include for each: title, customer, brief, opening, pressure, openingSeconds. openingSeconds should be 0 for all scenarios; app timing is round-relative.
Keep policy ethical and never include discriminatory scenarios. Return valid JSON only as an array. First round report: {json.dumps(old_report['data'].get('scores', {}))}""",
                }
            ],
        )
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        generated = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I))
        if not isinstance(generated, list) or len(generated) != 3:
            raise ValueError("Expected three scenarios.")
        required = {"title", "customer", "brief", "opening", "pressure"}
        if any(not isinstance(item, dict) or not required.issubset(item) for item in generated):
            raise ValueError("Scenario fields were incomplete.")
        for item in generated:
            item["openingSeconds"] = 0
    except Exception as error:
        raise HTTPException(502, f"Second-round scenario generation failed: {error.__class__.__name__}") from error

    with connect() as con:
        candidate = con.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not candidate:
        raise HTTPException(404, "Candidate not found.")
    token = secrets.token_urlsafe(24)
    with connect() as con:
        con.execute(
            "INSERT INTO invites(id,candidate_id,token,round,scenarios_json,created_at) VALUES(?,?,?,?,?,?)",
            (uuid.uuid4().hex, candidate_id, token, old_report["round"] + 1, json.dumps(generated), utcnow()),
        )
        con.execute("UPDATE candidates SET status='Invited' WHERE id=?", (candidate_id,))
    return RedirectResponse(f"/?invite={token}", status_code=303)


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "app": "ShiftReady"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), app_dir=str(ROOT))
