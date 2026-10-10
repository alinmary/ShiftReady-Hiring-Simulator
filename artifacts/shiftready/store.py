from __future__ import annotations

import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("SHIFTREADY_DATA_DIR", ROOT / "data"))
MEDIA_DIR = DATA_DIR / "media"
DB_PATH = DATA_DIR / "shiftready.sqlite3"

CRITERIA = [
    "Empathy & active listening",
    "Problem resolution",
    "Escalation judgment",
    "Policy & integrity",
    "Communication clarity",
    "Vocal tone & warmth",
    "Composure under pressure",
]

SCENARIOS = [
    {
        "title": "A damaged delivery",
        "customer": "Maya, who ordered a countertop espresso machine",
        "brief": "A customer calls after receiving an espresso machine with a cracked water tank and a dented side panel. They want a full refund and an extra $100 for the inconvenience. Store policy allows a prepaid return and refund or replacement, but no extra compensation.",
        "opening": "Hi, I just opened the espresso machine I ordered and the water tank is cracked. The box was a mess. I want a full refund and another hundred dollars for wasting my time.",
        "pressure": "If they refuse to offer a clear solution, mention that the machine was a gift needed this weekend. If they stay respectful and explain the return options, become more cooperative.",
        "openingSeconds": 0,
    },
    {
        "title": "An unexpected charge",
        "customer": "Jordan, a frustrated customer disputing a charge",
        "brief": "A customer sees a $79 accessory charge they did not expect and threatens to post a one-star review. They demand the manager immediately. Store policy allows you to review the receipt, explain the charge, and escalate a disputed transaction.",
        "opening": "I was charged seventy-nine dollars for an accessory I never agreed to buy. This is ridiculous. Get me your manager right now or I'm posting this everywhere.",
        "pressure": "If the candidate dismisses the concern, raise the stakes by saying this is the second unexplained charge. If they listen and explain a concrete next step, reduce the urgency.",
        "openingSeconds": 245,
    },
    {
        "title": "A promise we cannot keep",
        "customer": "Priya, a regular customer who was promised an unavailable item",
        "brief": "A regular customer was told a limited-edition wireless speaker would be held for pickup today. Inventory records show it was oversold and will not arrive for two weeks. They are disappointed, not angry. The candidate must be honest and offer realistic alternatives.",
        "opening": "I came in to pick up the speaker your team promised to hold for me. I planned a birthday surprise around it. Can you tell me it's still there?",
        "pressure": "If the candidate is honest, respond with disappointment and ask about practical alternatives. If they make an unsupported promise, ask for a specific delivery date.",
        "openingSeconds": 490,
    },
]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS roles (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS candidates (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL DEFAULT '',
                role_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Invited',
                owner_decision TEXT NOT NULL DEFAULT 'Pending', created_at TEXT NOT NULL,
                FOREIGN KEY(role_id) REFERENCES roles(id)
            );
            CREATE TABLE IF NOT EXISTS invites (
                id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, token TEXT NOT NULL UNIQUE,
                round INTEGER NOT NULL DEFAULT 1, scenarios_json TEXT NOT NULL,
                used_at TEXT, created_at TEXT NOT NULL,
                FOREIGN KEY(candidate_id) REFERENCES candidates(id)
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, invite_id TEXT NOT NULL,
                round INTEGER NOT NULL, started_at TEXT NOT NULL, completed_at TEXT,
                audio_path TEXT, voice_signals_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(candidate_id) REFERENCES candidates(id),
                FOREIGN KEY(invite_id) REFERENCES invites(id)
            );
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                scenario_index INTEGER NOT NULL, speaker TEXT NOT NULL, text TEXT NOT NULL,
                elapsed_seconds REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL UNIQUE,
                candidate_id TEXT NOT NULL, round INTEGER NOT NULL,
                data_json TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id),
                FOREIGN KEY(candidate_id) REFERENCES candidates(id)
            );
            """
        )
        if con.execute("SELECT COUNT(*) FROM roles").fetchone()[0] == 0:
            con.executemany(
                "INSERT INTO roles(id,name,description) VALUES(?,?,?)",
                [
                    ("associate", "Store Associate", "Customer conversations, service recovery, and store policy."),
                    ("category", "Category Manager", "Customer judgment, ownership, and cross-team escalation."),
                ],
            )
        if con.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 0:
            seed_demo_data(con)


def seed_demo_data(con: sqlite3.Connection) -> None:
    examples = [
        ("Aarav Patel", "Store Associate", [9, 8, 8, 9, 8, 8, 9], "Strong Hire", "Strong listening; offered a prepaid return without promising extra compensation."),
        ("Sofia Bennett", "Store Associate", [8, 7, 6, 8, 8, 8, 7], "Decent Hire", "Warm opening; could have clarified the escalation path earlier."),
        ("Noah Williams", "Category Manager", [7, 8, 8, 9, 8, 7, 8], "Strong Hire", "Clear next steps and sound policy judgment under pressure."),
        ("Amara Okafor", "Store Associate", [9, 9, 8, 8, 9, 9, 8], "Strong Hire", "Acknowledged the inconvenience and presented two realistic options."),
        ("Ethan Chen", "Category Manager", [6, 7, 5, 8, 7, 6, 6], "Decent Hire", "Stayed respectful; escalated before confirming the receipt details."),
    ]
    now = utcnow()
    for name, role_name, scores, verdict, summary in examples:
        role_id = "category" if role_name == "Category Manager" else "associate"
        candidate_id = secrets.token_hex(12)
        session_id = secrets.token_hex(12)
        invite_id = secrets.token_hex(12)
        report_id = secrets.token_hex(12)
        con.execute(
            "INSERT INTO candidates(id,name,email,role_id,status,owner_decision,created_at) VALUES(?,?,?,?,?,?,?)",
            (candidate_id, name, "", role_id, "Completed", "Pending", now),
        )
        con.execute(
            "INSERT INTO invites(id,candidate_id,token,round,scenarios_json,used_at,created_at) VALUES(?,?,?,?,?,?,?)",
            (invite_id, candidate_id, secrets.token_urlsafe(18), 1, json.dumps(SCENARIOS), now, now),
        )
        con.execute(
            "INSERT INTO sessions(id,candidate_id,invite_id,round,started_at,completed_at,voice_signals_json) VALUES(?,?,?,?,?,?,?)",
            (session_id, candidate_id, invite_id, 1, now, now, json.dumps({"label": "Demo sample — no audio recorded"})),
        )
        score_map = dict(zip(CRITERIA, scores))
        weighted = (
            sum(score_map.values()) + score_map[CRITERIA[0]] * 0.5 + score_map[CRITERIA[6]] * 0.5
        ) / 8
        report = {
            "scores": score_map,
            "weighted_average": round(weighted, 1),
            "verdict": verdict,
            "red_flags": [],
            "confidence": "Demo sample",
            "summary": summary,
            "highlights": [
                {"kind": "strength", "timestamp": 38, "criterion": CRITERIA[0], "quote": "I can see why that would be frustrating.", "note": "Acknowledged the customer's concern before moving to options."},
                {"kind": "coaching", "timestamp": 105, "criterion": CRITERIA[2], "quote": "Let me check the receipt and bring in a manager if the charge is still unclear.", "note": "A specific next step keeps the escalation proportionate."},
            ],
            "follow_up_questions": [
                "How would you respond if the customer rejected both options?",
                "What information would you confirm before escalating this situation?",
            ],
            "transcript": [
                {"scenario": "A damaged delivery", "speaker": "customer", "text": "The espresso machine arrived damaged and I want this fixed."},
                {"scenario": "A damaged delivery", "speaker": "candidate", "text": "I'm sorry it arrived that way. I can arrange a prepaid return and a refund or replacement."},
            ],
            "signals": {"label": "Demo sample — no audio recorded"},
        }
        con.execute(
            "INSERT INTO reports(id,session_id,candidate_id,round,data_json,created_at) VALUES(?,?,?,?,?,?)",
            (report_id, session_id, candidate_id, 1, json.dumps(report), now),
        )


def create_candidate(name: str, email: str, role_id: str, round_number: int = 1, scenarios: list[dict[str, Any]] | None = None) -> tuple[str, str]:
    candidate_id = secrets.token_hex(12)
    invite_id = secrets.token_hex(12)
    token = secrets.token_urlsafe(24)
    with connect() as con:
        role = con.execute("SELECT id FROM roles WHERE id = ?", (role_id,)).fetchone()
        if not role:
            raise ValueError("Select a valid role.")
        con.execute(
            "INSERT INTO candidates(id,name,email,role_id,status,created_at) VALUES(?,?,?,?,?,?)",
            (candidate_id, name.strip(), email.strip(), role_id, "Invited", utcnow()),
        )
        con.execute(
            "INSERT INTO invites(id,candidate_id,token,round,scenarios_json,created_at) VALUES(?,?,?,?,?,?)",
            (invite_id, candidate_id, token, round_number, json.dumps(scenarios or SCENARIOS), utcnow()),
        )
    return candidate_id, token


def candidate_by_token(token: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute(
            """SELECT c.*, r.name AS role_name, i.id AS invite_id, i.round, i.scenarios_json, i.used_at
               FROM invites i JOIN candidates c ON c.id=i.candidate_id
               JOIN roles r ON r.id=c.role_id WHERE i.token=?""",
            (token,),
        ).fetchone()
    return dict(row) if row else None


def dashboard_data() -> dict[str, Any]:
    with connect() as con:
        roles = [dict(row) for row in con.execute("SELECT * FROM roles ORDER BY name")]
        candidates = [
            dict(row)
            for row in con.execute(
                """SELECT c.*, r.name AS role_name,
                          (SELECT id FROM reports rp WHERE rp.candidate_id=c.id ORDER BY rp.round DESC LIMIT 1) AS report_id,
                          (SELECT data_json FROM reports rp WHERE rp.candidate_id=c.id ORDER BY rp.round DESC LIMIT 1) AS report_json,
                          (SELECT round FROM reports rp WHERE rp.candidate_id=c.id ORDER BY rp.round DESC LIMIT 1) AS report_round
                   FROM candidates c JOIN roles r ON r.id=c.role_id
                   ORDER BY CASE c.status WHEN 'Invited' THEN 0 WHEN 'In progress' THEN 1 ELSE 2 END, c.created_at DESC"""
            )
        ]
    for candidate in candidates:
        candidate["report"] = json.loads(candidate.pop("report_json")) if candidate["report_json"] else None
    return {"roles": roles, "candidates": candidates}


def report_for_candidate(candidate_id: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute(
            """SELECT rp.*, c.name AS candidate_name, c.email, c.owner_decision,
                      r.name AS role_name, s.audio_path, s.voice_signals_json
               FROM reports rp JOIN candidates c ON c.id=rp.candidate_id
               JOIN roles r ON r.id=c.role_id JOIN sessions s ON s.id=rp.session_id
               WHERE c.id=? ORDER BY rp.round DESC LIMIT 1""",
            (candidate_id,),
        ).fetchone()
        prior = con.execute(
            "SELECT round,data_json,created_at FROM reports WHERE candidate_id=? ORDER BY round",
            (candidate_id,),
        ).fetchall()
    if not row:
        return None
    result = dict(row)
    result["data"] = json.loads(result.pop("data_json"))
    result["signals"] = json.loads(result.pop("voice_signals_json") or "{}")
    result["rounds"] = [{"round": r["round"], "data": json.loads(r["data_json"]), "created_at": r["created_at"]} for r in prior]
    return result


def turns_for_session(session_id: str, scenario_index: int | None = None) -> list[dict[str, Any]]:
    with connect() as con:
        if scenario_index is None:
            rows = con.execute(
                "SELECT * FROM turns WHERE session_id=? ORDER BY id", (session_id,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM turns WHERE session_id=? AND scenario_index=? ORDER BY id",
                (session_id, scenario_index),
            ).fetchall()
    return [dict(row) for row in rows]


def record_turn(session_id: str, scenario_index: int, speaker: str, text: str, elapsed_seconds: float) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO turns(session_id,scenario_index,speaker,text,elapsed_seconds,created_at) VALUES(?,?,?,?,?,?)",
            (session_id, scenario_index, speaker, text, max(0, elapsed_seconds), utcnow()),
        )
