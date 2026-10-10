"""The one definition of criteria, weights, verdicts and retest rules."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from domain.enums import Verdict

EMPATHY = "Empathy & active listening"
PROBLEM_RESOLUTION = "Problem resolution"
ESCALATION = "Escalation judgment"
POLICY = "Policy & integrity"
CLARITY = "Communication clarity"
VOCAL_TONE = "Vocal tone & warmth"
COMPOSURE = "Composure under pressure"

CRITERIA = [EMPATHY, PROBLEM_RESOLUTION, ESCALATION, POLICY, CLARITY, VOCAL_TONE, COMPOSURE]


def clamp_scores(raw: Any, criteria: list[str]) -> dict[str, int]:
    """Return integer 1-10 scores for exactly `criteria`.

    Raises ValueError when a criterion is missing or not a number.
    """
    try:
        return {criterion: max(1, min(10, int(raw[criterion]))) for criterion in criteria}
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("A criterion score is missing or invalid.") from error


@dataclass(frozen=True)
class ScoringPolicy:
    """Weighted average, verdict and retest rules for the seven-criterion score.

    Weights are looked up by criterion name, so reordering CRITERIA is safe.
    """

    weights: Mapping[str, float] = field(default_factory=lambda: {EMPATHY: 1.5, COMPOSURE: 1.5})
    strong_hire_average: float = 8.0
    strong_hire_min_score: int = 6
    decent_hire_average: float = 6.0
    min_candidate_words: int = 90
    min_spoken_words: int = 30

    def weight(self, criterion: str) -> float:
        return self.weights.get(criterion, 1.0)

    def weighted_average(self, scores: Mapping[str, int]) -> float:
        """Unrounded weighted average; callers round for display."""
        total_weight = sum(self.weight(criterion) for criterion in scores)
        return sum(score * self.weight(criterion) for criterion, score in scores.items()) / total_weight

    def verdict(self, scores: Mapping[str, int], red_flags: list[Any] | None = None) -> Verdict:
        average = self.weighted_average(scores)
        if red_flags or average < self.decent_hire_average:
            return Verdict.DO_NOT_HIRE
        if average >= self.strong_hire_average and min(scores.values()) >= self.strong_hire_min_score:
            return Verdict.STRONG_HIRE
        return Verdict.DECENT_HIRE

    def needs_retest(self, *, has_audio: bool, candidate_words: int, spoken_words: float, model_confidence: Any) -> bool:
        """True when there is too little recorded evidence to trust the scores."""
        return (
            not has_audio
            or candidate_words < self.min_candidate_words
            or spoken_words < self.min_spoken_words
            or "low" in str(model_confidence).lower()
        )


def pressure_average(pressure_scores: Mapping[str, int]) -> float:
    return round(sum(pressure_scores.values()) / len(pressure_scores), 1)


scoring_policy = ScoringPolicy()
