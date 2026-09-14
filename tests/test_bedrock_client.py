"""
Phase 0 tests for the Bedrock wrapper.

Covers Story 6.1 (model switching), 6.2 (token/cost accounting), 3.1 (retry
with backoff), and 7.3 (credential errors are friendly, not stack traces).
No network access: boto3 is stubbed at the client boundary.
"""

import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError, NoCredentialsError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bedrock_client import (  # noqa: E402
    DEFAULT_MODEL,
    BedrockClient,
    CredentialsError,
    ModelInvocationError,
    ModelResponse,
    resolve_model_id,
    resolve_region,
)


def converse_payload(text: str = "ballot", tokens_in: int = 100, tokens_out: int = 50):
    """Minimal shape of a real Bedrock Converse API response."""
    return {
        "output": {"message": {"content": [{"text": text}]}},
        "usage": {"inputTokens": tokens_in, "outputTokens": tokens_out},
    }


class StubBotoClient:
    """Stands in for boto3's bedrock-runtime client."""

    def __init__(self, payload=None, raises=None, fail_times=0):
        self.payload = payload or converse_payload()
        self.raises = raises
        self.fail_times = fail_times
        self.call_count = 0
        self.last_kwargs = None

    def converse(self, **kwargs):
        self.call_count += 1
        self.last_kwargs = kwargs
        if self.raises is not None and self.call_count <= (self.fail_times or 10**9):
            raise self.raises
        return self.payload


def client_with(stub: StubBotoClient, **init) -> BedrockClient:
    client = BedrockClient(**init)
    client._client = stub  # bypass lazy boto3 construction
    return client


# --- Story 6.1: model switching via config -----------------------------


def test_model_defaults_when_env_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    assert resolve_model_id() == DEFAULT_MODEL


def test_env_var_overrides_default_model(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert resolve_model_id() == "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def test_explicit_argument_beats_env_var(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert resolve_model_id("us.anthropic.claude-opus-4-5-20251101-v1:0").endswith("opus-4-5-20251101-v1:0")


def test_region_falls_back_to_us_west_2(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    assert resolve_region() == "us-west-2"


def test_configured_model_is_the_one_called(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    stub = StubBotoClient()
    client_with(stub).invoke(system="s", user="u")
    assert stub.last_kwargs["modelId"] == "us.anthropic.claude-haiku-4-5-20251001-v1:0"


# --- Story 6.2: token usage and cost ----------------------------------


def test_invoke_reports_token_usage():
    stub = StubBotoClient(converse_payload("text", tokens_in=1234, tokens_out=567))
    response = client_with(stub).invoke(system="s", user="u")
    assert (response.input_tokens, response.output_tokens) == (1234, 567)


def test_cost_uses_sonnet_rates():
    response = ModelResponse(
        text="x", input_tokens=1_000_000, output_tokens=1_000_000, model_id=DEFAULT_MODEL
    )
    assert response.cost_usd == pytest.approx(18.00)  # $3 in + $15 out


def test_haiku_costs_less_than_sonnet_for_identical_usage():
    usage = dict(text="x", input_tokens=40_000, output_tokens=10_000)
    sonnet = ModelResponse(model_id=DEFAULT_MODEL, **usage)
    haiku = ModelResponse(model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0", **usage)
    assert haiku.cost_usd < sonnet.cost_usd


def test_full_run_cost_is_in_the_expected_ballpark():
    """Technical Spec §9 budgets ~40k in + ~10k out at roughly $0.27."""
    response = ModelResponse(
        text="x", input_tokens=40_000, output_tokens=10_000, model_id=DEFAULT_MODEL
    )
    assert 0.20 < response.cost_usd < 0.35


# --- Story 3.1: retry with backoff ------------------------------------


def test_transient_failure_is_retried_once_then_succeeds(monkeypatch):
    monkeypatch.setattr("src.bedrock_client.time.sleep", lambda _: None)
    stub = StubBotoClient(raises=RuntimeError("boom"), fail_times=1)
    response = client_with(stub).invoke(system="s", user="u", retries=1)
    assert stub.call_count == 2 and response.text == "ballot"


def test_persistent_failure_raises_after_retries(monkeypatch):
    monkeypatch.setattr("src.bedrock_client.time.sleep", lambda _: None)
    stub = StubBotoClient(raises=RuntimeError("boom"))
    with pytest.raises(ModelInvocationError):
        client_with(stub).invoke(system="s", user="u", retries=1)
    assert stub.call_count == 2


def test_backoff_waits_five_seconds_between_attempts(monkeypatch):
    slept = []
    monkeypatch.setattr("src.bedrock_client.time.sleep", slept.append)
    stub = StubBotoClient(raises=RuntimeError("boom"), fail_times=1)
    client_with(stub).invoke(system="s", user="u", retries=1, backoff_seconds=5.0)
    assert slept == [5.0]


# --- Story 7.3: credential errors are actionable ----------------------


def expired_token_error() -> ClientError:
    return ClientError(
        {"Error": {"Code": "ExpiredTokenException", "Message": "token expired"}},
        "Converse",
    )


def test_expired_credentials_raise_credentials_error(monkeypatch):
    monkeypatch.setattr("src.bedrock_client.time.sleep", lambda _: None)
    stub = StubBotoClient(raises=expired_token_error())
    with pytest.raises(CredentialsError):
        client_with(stub).invoke(system="s", user="u")


def test_missing_credentials_raise_credentials_error():
    stub = StubBotoClient(raises=NoCredentialsError())
    with pytest.raises(CredentialsError):
        client_with(stub).invoke(system="s", user="u")


def test_credential_error_names_the_refresh_commands():
    stub = StubBotoClient(raises=NoCredentialsError())
    with pytest.raises(CredentialsError) as caught:
        client_with(stub).invoke(system="s", user="u")
    message = str(caught.value)
    assert "aws configure" in message
    assert "aws sts get-caller-identity" in message


def test_credential_error_is_not_retried():
    """Retrying an expired token only wastes the user's time."""
    stub = StubBotoClient(raises=expired_token_error())
    with pytest.raises(CredentialsError):
        client_with(stub).invoke(system="s", user="u", retries=3)
    assert stub.call_count == 1


def test_credential_message_carries_no_stack_trace():
    stub = StubBotoClient(raises=NoCredentialsError())
    with pytest.raises(CredentialsError) as caught:
        client_with(stub).invoke(system="s", user="u")
    assert "Traceback" not in str(caught.value)


# --- request shape ----------------------------------------------------


def test_system_and_user_prompts_are_sent_separately():
    stub = StubBotoClient()
    client_with(stub).invoke(system="you are a judge", user="the transcript")
    kwargs = stub.last_kwargs
    assert kwargs["system"] == [{"text": "you are a judge"}]
    assert kwargs["messages"][0]["content"][0]["text"] == "the transcript"


@pytest.mark.allow_real_client
def test_constructing_the_client_makes_no_network_call(monkeypatch):
    """--dry-run and tests must never require credentials."""
    def explode(*_args, **_kwargs):
        raise AssertionError("boto3.client() must not be called eagerly")

    monkeypatch.setattr("src.bedrock_client.boto3.client", explode)
    BedrockClient()  # must not raise
