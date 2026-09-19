"""Anthropic API client implementing JudgeAI's LLMClient interface."""

import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

try:
    from anthropic import (
        Anthropic,
        APIConnectionError,
        APIError,
        APITimeoutError,
        AuthenticationError,
        RateLimitError,
    )
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from .llm_client import CredentialsError, LLMClient, ModelInvocationError, ModelResponse

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
PRICING_PER_MTOK = {
    "sonnet": {"input": 3.00, "output": 15.00},
    "opus": {"input": 15.00, "output": 75.00},
    "haiku": {"input": 1.00, "output": 5.00},
}

DEBUG_LOG_PATH = Path(__file__).resolve().parent.parent / "judgeai.log"
_logger = logging.getLogger("judgeai.anthropic")
if not _logger.handlers:
    _handler = logging.FileHandler(DEBUG_LOG_PATH, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False

CREDENTIAL_HELP = f"""Anthropic API key is missing or invalid.
Set ANTHROPIC_API_KEY or enter the key in JudgeAI Settings.
Technical detail written to {DEBUG_LOG_PATH}"""


def echo_call(system: str, user: str, response: Optional[str] = None, label: str = "model call") -> None:
    divider = "-" * 70
    print(f"\n{divider}\n[{label}] SYSTEM PROMPT\n{divider}", file=sys.stderr)
    print(system, file=sys.stderr)
    print(f"\n{divider}\n[{label}] USER PROMPT\n{divider}", file=sys.stderr)
    print(user, file=sys.stderr)
    if response is not None:
        print(f"\n{divider}\n[{label}] RESPONSE\n{divider}", file=sys.stderr)
        print(response, file=sys.stderr)
    print(divider, file=sys.stderr)


def _rates_for_model(model_id: str) -> dict:
    lowered = model_id.lower()
    for family, rates in PRICING_PER_MTOK.items():
        if family in lowered:
            return rates
    return PRICING_PER_MTOK["sonnet"]


class AnthropicModelResponse(ModelResponse):
    @property
    def cost_usd(self) -> float:
        rates = _rates_for_model(self.model_id)
        return (
            self.input_tokens / 1_000_000 * rates["input"]
            + self.output_tokens / 1_000_000 * rates["output"]
        )


def resolve_model_id(explicit: Optional[str] = None) -> str:
    model = explicit or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
    if model.startswith("us.anthropic."):
        model = model.replace("us.anthropic.", "", 1)
    if model.endswith("-v1:0"):
        model = model[:-5]
    return model


class AnthropicAPIClient(LLMClient):
    def __init__(self, model_id: Optional[str] = None, api_key: Optional[str] = None, verbose: bool = False):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("Anthropic SDK not installed. Install with: pip install anthropic")
        self.model_id = resolve_model_id(model_id)
        self.verbose = verbose
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise CredentialsError(CREDENTIAL_HELP)
        self._client = Anthropic(api_key=api_key, timeout=600.0)

    def invoke(
        self,
        system: str,
        user: str,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        retries: int = 1,
        backoff_seconds: float = 5.0,
    ) -> ModelResponse:
        attempt = 0
        last_error: Optional[Exception] = None

        while attempt <= retries:
            attempt += 1
            started = time.monotonic()
            try:
                response = self._client.messages.create(
                    model=self.model_id,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                if not response.content:
                    raise ModelInvocationError(
                        f"Anthropic returned empty content. Stop reason: {response.stop_reason}"
                    )
                text = response.content[0].text
                usage = response.usage
                input_tokens = usage.input_tokens if usage else 0
                output_tokens = usage.output_tokens if usage else 0
                if self.verbose:
                    echo_call(system, user, text, label=self.model_id)
                return AnthropicModelResponse(
                    text=text,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    model_id=self.model_id,
                    latency_seconds=time.monotonic() - started,
                )
            except AuthenticationError as exc:
                _logger.exception("Anthropic authentication failed")
                raise CredentialsError(CREDENTIAL_HELP) from exc
            except (APIConnectionError, APITimeoutError, RateLimitError) as exc:
                _logger.exception("Anthropic transient error (attempt %d)", attempt)
                last_error = exc
            except APIError as exc:
                _logger.exception("Anthropic API error")
                status_code = getattr(exc, "status_code", None)
                if status_code is not None and 400 <= status_code < 500 and status_code != 429:
                    raise ModelInvocationError(
                        f"Anthropic API request failed: {exc}. Detail in {DEBUG_LOG_PATH}"
                    ) from exc
                last_error = exc
            except ModelInvocationError:
                raise
            except Exception as exc:  # noqa: BLE001
                _logger.exception("Unexpected Anthropic failure")
                last_error = exc

            if attempt <= retries:
                time.sleep(backoff_seconds)

        raise ModelInvocationError(
            f"Anthropic API call failed after {attempt} attempt(s): {last_error}. "
            f"Detail in {DEBUG_LOG_PATH}"
        )
