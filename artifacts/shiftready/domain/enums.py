"""Named values that were previously repeated as string literals."""
from __future__ import annotations

from enum import StrEnum


class CandidateStatus(StrEnum):
    INVITED = "Invited"
    IN_PROGRESS = "In progress"
    COMPLETED = "Completed"


class Verdict(StrEnum):
    STRONG_HIRE = "Strong Hire"
    DECENT_HIRE = "Decent Hire"
    DO_NOT_HIRE = "Do Not Hire"
    RETEST = "Retest recommended"


class Speaker(StrEnum):
    CANDIDATE = "candidate"
    CUSTOMER = "customer"


class RoundMode(StrEnum):
    STANDARD = "standard"
    PRESSURE = "pressure"


PENDING_DECISION = "Pending"
OWNER_DECISIONS = (PENDING_DECISION, Verdict.STRONG_HIRE.value, Verdict.DECENT_HIRE.value, Verdict.DO_NOT_HIRE.value)
