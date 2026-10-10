"""Unit tests for scoring, AI parsing, evidence binding and the pressure timeline."""
import pytest

from ai_responses import AIResponseError, parse_json, parse_json_object
from domain.enums import Verdict
from domain.scoring import COMPOSURE, CRITERIA, EMPATHY, ScoringPolicy, clamp_scores, pressure_average
from evidence import bind_report_evidence
from pressure import pressure_timeline

policy = ScoringPolicy()


def scores(default: int = 8, **overrides: int) -> dict[str, int]:
    result = dict.fromkeys(CRITERIA, default)
    for criterion in CRITERIA:
        key = criterion.split()[0].lower()
        if key in overrides:
            result[criterion] = overrides[key]
    return result


# ScoringPolicy

def test_empathy_and_composure_weigh_one_and_a_half():
    values = scores(6, empathy=10, composure=10)
    assert policy.weighted_average(values) == pytest.approx((6 * 5 + 10 * 1.5 * 2) / 8)


def test_weights_follow_names_not_positions():
    values = scores(6, empathy=10)
    reordered = dict(reversed(list(values.items())))
    assert policy.weighted_average(reordered) == policy.weighted_average(values)


def test_strong_hire_boundary():
    assert policy.verdict(scores(8)) == Verdict.STRONG_HIRE


def test_a_score_of_five_blocks_strong_hire():
    values = scores(9, problem=5)
    assert policy.weighted_average(values) >= 8
    assert policy.verdict(values) == Verdict.DECENT_HIRE


def test_decent_hire_range():
    assert policy.verdict(scores(6)) == Verdict.DECENT_HIRE
    assert policy.verdict(scores(7)) == Verdict.DECENT_HIRE


def test_below_six_is_do_not_hire():
    assert policy.verdict(scores(5)) == Verdict.DO_NOT_HIRE


def test_red_flag_forces_do_not_hire():
    assert policy.verdict(scores(10), ["Rudeness: “quote”"]) == Verdict.DO_NOT_HIRE


@pytest.mark.parametrize("has_audio,words,spoken,confidence,expected", [
    (True, 90, 30, "High", False),
    (False, 200, 100, "High", True),
    (True, 89, 100, "High", True),
    (True, 200, 29, "High", True),
    (True, 200, 100, "Low", True),
])
def test_retest_rules(has_audio, words, spoken, confidence, expected):
    assert policy.needs_retest(has_audio=has_audio, candidate_words=words, spoken_words=spoken, model_confidence=confidence) is expected


def test_pressure_average_uses_criterion_count():
    assert pressure_average({"a": 6, "b": 7, "c": 8}) == 7
    assert pressure_average({"a": 6, "b": 7}) == 6.5


# Score clamping

def test_clamp_scores():
    raw = dict.fromkeys(CRITERIA, 5) | {EMPATHY: 0, COMPOSURE: 11, CRITERIA[1]: "7"}
    clamped = clamp_scores(raw, CRITERIA)
    assert clamped[EMPATHY] == 1 and clamped[COMPOSURE] == 10 and clamped[CRITERIA[1]] == 7


def test_clamp_scores_rejects_missing_criterion():
    with pytest.raises(ValueError):
        clamp_scores({EMPATHY: 7}, CRITERIA)
    with pytest.raises(ValueError):
        clamp_scores(None, CRITERIA)


# AI JSON parsing

def test_parse_plain_and_fenced_json():
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json("```\n[1, 2]\n```") == [1, 2]


def test_parse_invalid_json():
    with pytest.raises(AIResponseError, match="could not be read"):
        parse_json_object("not json")


def test_parse_list_when_object_expected():
    with pytest.raises(AIResponseError, match="invalid response"):
        parse_json_object("[1, 2]")


# Evidence binding

TRANSCRIPT = [
    {"speaker": "customer", "text": "You are useless and I want a refund now.", "timestamp_seconds": 5},
    {"speaker": "candidate", "text": "I understand, let me check the receipt for you.", "timestamp_seconds": 12},
    {"speaker": "candidate", "text": "I understand, let me check the receipt for you.", "timestamp_seconds": 70},
]


def test_red_flag_needs_candidate_quote():
    report = {"red_flags": [
        {"label": "Rudeness", "quote": "You are useless and I want a refund"},
        {"label": "Rudeness", "quote": "this was never said by anyone"},
        {"label": "Rudeness", "quote": "let me check the receipt"},
    ]}
    bind_report_evidence(report, TRANSCRIPT)
    assert report["red_flags"] == ["Rudeness: “let me check the receipt”"]


def test_highlights_are_capped_and_snapped():
    item = {"kind": "strength", "quote": "let me check the receipt", "criterion": EMPATHY, "note": "", "timestamp_seconds": 60}
    report = {"highlights": [dict(item) for _ in range(7)] + [{"quote": "missing quote entirely"}]}
    bind_report_evidence(report, TRANSCRIPT)
    assert len(report["highlights"]) == 5
    assert report["highlights"][0]["timestamp_seconds"] == 70


# Pressure timeline

def test_pressure_timeline_assigns_replies_to_event_windows():
    events = [
        {"label": "A", "speaker": "staff", "text": "a", "elapsed_seconds": 45, "scheduled_seconds": 45, "delivery": "display"},
        {"label": "B", "speaker": "staff", "text": "b", "elapsed_seconds": 90, "scheduled_seconds": 90, "delivery": "speech"},
    ]
    turns = [
        {"speaker": "candidate", "text": "before", "elapsed_seconds": 10},
        {"speaker": "candidate", "text": "first", "elapsed_seconds": 50},
        {"speaker": "customer", "text": "ignored", "elapsed_seconds": 60},
        {"speaker": "candidate", "text": "second", "elapsed_seconds": 95},
    ]
    timeline = pressure_timeline(events, turns)
    assert [r["text"] for r in timeline[0]["responses"]] == ["first"]
    assert [r["text"] for r in timeline[1]["responses"]] == ["second"]
