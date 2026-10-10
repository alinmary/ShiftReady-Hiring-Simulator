"""Round-two-only pressure scenarios and transcript-backed review evidence."""
from typing import Any

PRESSURE_CRITERIA = ["Prioritisation", "Delegation", "Closing the loop"]
PRESSURE_OPTIONS = [
    ("saturday", "Saturday rush"),
    ("short_staffed", "Short-staffed peak"),
    ("safety", "Safety incident mid-complaint"),
    ("boss", "Boss calls at the worst time"),
    ("shoplifting", "Suspected shoplifter during a sale"),
    ("closing", "Closing-time chaos"),
]

_SITUATIONS = {
    "saturday": (
        "An angry customer disputes an overcharge while the store is busy.",
        "I was overcharged and I'm posting a review!",
        "Card machine's down, queue's huge!",
        "Someone slipped near aisle 3!",
    ),
    "short_staffed": (
        "Two staff called in sick. A customer complains about waiting, and a delivery truck arrives early.",
        "I've been waiting for twenty minutes. Why is nobody helping me?",
        "Two people called in sick, and the delivery truck is here early. Who should unload it?",
        "The queue is growing and we only have one person at the till. What do we prioritise?",
    ),
    "safety": (
        "You are handling a customer complaint when a staff member reports a fall in aisle 3.",
        "Nobody has sorted my complaint. I need a clear answer now.",
        "Someone slipped in aisle 3! We need help and a wet-floor sign.",
        "First aid is on the way. Customers are still walking through the spill. Who can secure the area?",
    ),
    "boss": (
        "The area manager wants sales figures immediately while a VIP customer needs help at the counter.",
        "I'm at your counter and my order still isn't ready. I expected better service.",
        "The area manager is on the other line and wants today's sales figures right now.",
        "The area manager wants an update, and the counter queue is getting longer. Who can help?",
    ),
    "shoplifting": (
        "The floor is packed and you are handling a complaint when a colleague reports a possible shoplifter.",
        "I'm halfway through explaining my complaint. Are you going to help me?",
        "I think someone may be shoplifting. The floor is packed. What should I do?",
        "They are moving toward the exit. Should I confront them or contact the duty manager?",
    ),
    "closing": (
        "The till is short, an employee needs to leave for an emergency, and a customer arrives two minutes before closing.",
        "I know you're closing soon, but I need help with this purchase.",
        "The till is short, and I need to leave early for a family emergency. Can someone take over?",
        "Another customer just arrived, and the till discrepancy still needs checking. Who closes and who helps?",
    ),
}


def pressure_scenario(key: str, focus: str = "") -> dict[str, Any]:
    situation, opening, first, second = _SITUATIONS[key]
    return {
        "mode": "pressure",
        "title": dict(PRESSURE_OPTIONS)[key],
        "customer": "An impatient retail customer",
        "brief": situation + " Talk through your priorities, delegate clearly, and return to the original customer. Safety takes priority; do not physically confront a suspected shoplifter. Do not promise refunds or compensation without checking policy.",
        "opening": opening,
        "pressure": "You are the customer, never the staff member. Separate staff interruptions will be delivered by the simulation. React to contextual updates about them. If the employee explains a brief hold for safety, respect it initially. If they cope well, become more impatient but remain respectful. If they struggle, allow thinking time. Never coach or grade. Focus areas: " + (focus or "composure and prioritisation"),
        "openingSeconds": 0,
        "events": [
            {"id": "operations", "at": 45, "speaker": "staff", "label": "Staff interruption", "text": first},
            {"id": "priority", "at": 90, "speaker": "staff", "label": "Competing priority", "text": second},
            {"id": "return", "at": 150, "speaker": "customer", "label": "Customer follow-up", "text": "Hello? Are you still there?", "returned_text": "Thanks for coming back. What happens next with my original complaint?"},
            {"id": "wrap", "at": 210, "speaker": "staff", "label": "Close the loop", "text": "Thirty seconds left. Return to the original customer and explain the resolution and next steps."},
        ],
    }


def pressure_timeline(events: list[dict], turns: list[dict]) -> list[dict]:
    timeline = []
    for index, event in enumerate(events):
        end = events[index + 1]["elapsed_seconds"] if index + 1 < len(events) else float("inf")
        responses = [
            {"text": turn["text"], "timestamp_seconds": round(turn["elapsed_seconds"])}
            for turn in turns
            if turn["speaker"] == "candidate" and event["elapsed_seconds"] <= turn["elapsed_seconds"] < end
        ]
        timeline.append({
            "label": event["label"], "speaker": event["speaker"], "text": event["text"],
            "timestamp_seconds": round(event["elapsed_seconds"]),
            "scheduled_seconds": event["scheduled_seconds"], "delivery": event["delivery"],
            "responses": responses,
        })
    return timeline
