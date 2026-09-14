"""
Shared test fixtures.

Every story's acceptance criteria run against FakeBedrockClient, so the suite
is free, fast, offline, and needs no AWS credentials. Real Bedrock calls happen
only in the manual smoke runs at each phase boundary.
"""

import json
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bedrock_client import ModelResponse  # noqa: E402
from src.storage import LocalDiskBallotStore  # noqa: E402


class FakeBedrockClient:
    """
    Drop-in stand-in for BedrockClient.

    - `responses`: returned in order; the last one repeats once exhausted.
    - `fail_times`: raise on the first N calls, to exercise retry paths.
    - `calls`: every (system, user, kwargs) triple, for asserting prompt content.
    """

    def __init__(
        self,
        responses: Optional[Sequence[str]] = None,
        fail_times: int = 0,
        exception: Optional[Exception] = None,
        model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        region: str = "us-west-2",
    ):
        self._responses: List[str] = list(responses or ["fake response"])
        self._index = 0
        self._fail_times = fail_times
        self._exception = exception or RuntimeError("simulated model failure")
        self.model_id = model_id
        self.region = region
        self.calls: List[Dict[str, Any]] = []
        # Paradigms now judge concurrently (BALLOT_CONCURRENCY); the fake is
        # stateful (_index, _responses), so guard invoke. Reentrant so subclasses
        # that set _responses then call super().invoke() don't self-deadlock.
        self._lock = threading.RLock()

    def invoke(self, system: str, user: str, **kwargs: Any) -> ModelResponse:
        with self._lock:
            self.calls.append({"system": system, "user": user, **kwargs})

            if self._fail_times > 0:
                self._fail_times -= 1
                raise self._exception

            text = self._responses[min(self._index, len(self._responses) - 1)]
            self._index += 1
            return ModelResponse(
                text=text,
                input_tokens=1000,
                output_tokens=200,
                model_id=self.model_id,
                latency_seconds=0.01,
            )

    @property
    def call_count(self) -> int:
        return len(self.calls)


@pytest.fixture
def fake_bedrock() -> FakeBedrockClient:
    """A client that always succeeds, returning a single canned response."""
    return FakeBedrockClient()


@pytest.fixture
def make_fake_bedrock():
    """Factory for tests that need scripted responses or induced failures."""
    return FakeBedrockClient


@pytest.fixture
def store(tmp_path: Path) -> LocalDiskBallotStore:
    """A ballot store rooted in a temp dir, so tests never touch ~/Desktop."""
    return LocalDiskBallotStore(base_path=tmp_path / "Ballots")


DETECTION_JSON = json.dumps(
    {
        "speeches": [
            {"label": "1AC", "speaker": "Aff", "start_marker": "PLACEHOLDER"}
        ],
        "resolution": {"text": None, "quote": None, "confidence": "low"},
        "notes": "",
    }
)

FLOW_STUB = "A. FRAMEWORKS\nAff: morality / preventing death. Neg: none offered."

BALLOT_STUB = (
    "WINNER: AFF\n"
    "LEAN: clear\n"
    "RFD: The affirmative won on a conceded argument.\n"
    "SPEAKER POINTS: Aff 28 / Neg 27\n"
    "KEY VOTING ISSUES:\n"
    "1. A specific dropped warrant.\n"
)


DIFF_STUB = (
    "=== JudgeAI — Cross-Paradigm Diff ===\n"
    "—— PARADIGM DECISIONS ——\n"
    "Lay Parent: clear AFF (1/1) — the dropped accident impact.\n"
    "—— PRIMARY FLIP POINT ——\n"
    "No meaningful flip point — all paradigms agree that AFF wins.\n"
    "—— HOW EACH SIDE WINS / LOSES ——\n"
    "AFF wins by: the dropped accident impact; loses by: nothing this round.\n"
    "NEG wins by: nothing this round; loses by: dropping the accident impact.\n"
)


class PromptAwareFakeClient(FakeBedrockClient):
    """
    Returns a plausible response for whichever pass is calling.

    A single canned response cannot serve all the passes: detection needs JSON,
    ballots need a parseable WINNER or every paradigm registers as failed, and the
    cross-paradigm diff needs the §4.6 shape. Dispatching on the system prompt
    keeps CLI tests working as passes are added.
    """

    def invoke(self, system: str, user: str, **kwargs):
        with self._lock:
            if "Speech Boundaries" in system or "start_marker" in system:
                self._responses = [DETECTION_JSON]
            elif "Extract the flow" in system:
                self._responses = [FLOW_STUB]
            elif "CROSS-PARADIGM DIFF" in system:
                self._responses = [DIFF_STUB]
            else:
                self._responses = [BALLOT_STUB]
            self._index = 0
            return super().invoke(system, user, **kwargs)


@pytest.fixture(autouse=True)
def no_real_model_calls(monkeypatch, request, tmp_path):
    """
    Safety net: no test may reach Bedrock or the real filesystem.

    Wiring detection into the CLI made several Story 1.x tests start issuing
    real, billable calls (suite time went 0.4s -> 8.2s). Tests that want to
    exercise the client directly opt out with @pytest.mark.allow_real_client.
    """
    if "allow_real_client" in request.keywords:
        return

    def fake_build_client(dry_run: bool = False, verbose: bool = False, **_kwargs):
        from src.bedrock_client import DryRunBedrockClient

        if dry_run:
            return DryRunBedrockClient(verbose=verbose)
        return PromptAwareFakeClient()

    monkeypatch.setattr("src.cli.build_client", fake_build_client)

    # Redirect every real filesystem root into tmp_path. Without the archive
    # root here, wiring archiving to a successful run (Increment 12) made CLI
    # tests move their fixtures into the user's real ~/Desktop archive.
    sandbox = tmp_path / "judgeai-sandbox"
    monkeypatch.setattr("src.ingest.INBOX_ROOT", sandbox / "New_Rounds")
    monkeypatch.setattr("src.ingest.ARCHIVE_ROOT", sandbox / "Past_Rounds")
    monkeypatch.setattr("src.archive.ARCHIVE_ROOT", sandbox / "Past_Rounds")
    monkeypatch.setattr("src.storage.DEFAULT_BALLOTS_ROOT", sandbox / "Ballots")

    def explode(*_args, **_kwargs):
        raise AssertionError(
            "A test attempted a real boto3 client. Mock it, or mark the test "
            "with @pytest.mark.allow_real_client."
        )

    monkeypatch.setattr("src.bedrock_client.boto3.client", explode)
