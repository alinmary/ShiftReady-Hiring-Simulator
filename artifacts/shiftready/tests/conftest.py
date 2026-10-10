"""Shared pytest setup: a throwaway data directory, a fresh database per test,
and a fake AI client so tests never call the network."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import patch

import pytest

TEST_DATA = tempfile.TemporaryDirectory(prefix="shiftready-tests-")
os.environ["SHIFTREADY_DATA_DIR"] = TEST_DATA.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module  # noqa: E402
import store  # noqa: E402
from domain.scoring import CRITERIA  # noqa: E402


class FakeAIClient:
    """Stands in for AsyncAnthropic. `reply` builds the text for each call."""

    def __init__(self, reply: Callable[[dict[str, Any]], str], delay: float = 0) -> None:
        self.reply = reply
        self.delay = delay
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.reply(kwargs))])


def report_json(score: int = 8, **extra: Any) -> str:
    report = {
        "scores": dict.fromkeys(CRITERIA, score), "summary": "Fixture", "confidence": "High",
        "red_flags": [], "highlights": [], "follow_up_questions": [], **extra,
    }
    return json.dumps(report)


@pytest.fixture(autouse=True)
def fresh_db():
    store.DB_PATH.unlink(missing_ok=True)
    store.initialize()
    yield


@pytest.fixture
def fake_ai():
    fake = FakeAIClient(lambda _kwargs: report_json())
    with patch.object(app_module, "ai_client", return_value=fake):
        yield fake


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with TestClient(app_module.app) as test_client:
        yield test_client
