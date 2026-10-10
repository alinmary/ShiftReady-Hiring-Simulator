"""Bind generated report claims to actual conversation evidence."""
from typing import Any


def bind_report_evidence(report: dict[str, Any], transcript: list[dict[str, Any]]) -> None:
    flags = []
    for flag in report.get("red_flags", []):
        if not isinstance(flag, dict):
            continue
        label, quote = str(flag.get("label", "")), str(flag.get("quote", ""))
        allowed = label.lower() in {"rudeness", "knowingly false promise", "discriminatory remarks"}
        supported = len(quote) >= 12 and any(
            quote in entry["text"] for entry in transcript if entry["speaker"] == "candidate"
        )
        if allowed and supported:
            flags.append(f"{label}: “{quote}”")
    report["red_flags"] = flags

    highlights = []
    for item in report.get("highlights", []):
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote", ""))
        matches = [entry for entry in transcript if len(quote) >= 5 and quote in entry["text"]]
        if not matches:
            continue
        try:
            target = float(item.get("timestamp_seconds", 0))
        except (TypeError, ValueError):
            target = 0
        source = min(matches, key=lambda entry: abs(entry["timestamp_seconds"] - target))
        highlights.append({
            "kind": "strength" if item.get("kind") == "strength" else "coaching",
            "quote": quote,
            "criterion": str(item.get("criterion", "Conversation evidence")),
            "note": str(item.get("note", "")),
            "timestamp_seconds": source["timestamp_seconds"],
        })
    report["highlights"] = highlights[:5]
