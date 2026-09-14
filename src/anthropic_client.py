"""
Anthropic API client implementing the LLMClient interface.

Supports Claude models via the direct Anthropic API (not AWS Bedrock).
Requires ANTHROPIC_API_KEY environment variable.
"""

import os
import sys
import time
import logging
from pathlib import Path
from typing import Optional

try:
    import anthropic
    from anthropic import Anthropic, APIError, APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from .llm_client import (
    LLMClient,
    ModelResponse,
    CredentialsError,
    ModelInvocationError,
)

# Default to Claude Sonnet 4.5 for high-quality judging
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

# Anthropic API pricing per 1M tokens
PRICING_PER_MTOK = {
    "sonnet": {"input": 3.00, "output": 15.00},
    "opus": {"input": 15.00, "output": 75.00},
    "haiku": {"input": 1.00, "output": 5.00},
}

DEBUG_LOG_PATH = Path(__file__).resolve().parent.parent / "judgeai.log"

_logger = logging.getLogger("judgeai.anthropic")
if not _logger.handlers:
    _handler = logging.FileHandler(DEBUG_LOG_PATH, encoding="utf-8")
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    _logger.addHandler(_handler)
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False


CREDENTIAL_HELP = """Anthropic API key is missing or invalid.

Set your API key:

  export ANTHROPIC_API_KEY='sk-ant-...'

Get an API key at: https://console.anthropic.com/

Technical detail written to {log_path}"""


def echo_call(
    system: str,
    user: str,
    response: Optional[str] = None,
    label: str = "model call",
) -> None:
    """Print a call's prompts and response for --verbose."""
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
    """Pick a pricing table by model family."""
    lowered = model_id.lower()
    for family, rates in PRICING_PER_MTOK.items():
        if family in lowered:
            return rates
    # Default to sonnet pricing if unknown
    return PRICING_PER_MTOK["sonnet"]


class AnthropicModelResponse(ModelResponse):
    """ModelResponse subclass with Anthropic-specific pricing."""

    @property
    def cost_usd(self) -> float:
        """Estimated cost of this single call using Anthropic API pricing."""
        rates = _rates_for_model(self.model_id)
        return (
            self.input_tokens / 1_000_000 * rates["input"]
            + self.output_tokens / 1_000_000 * rates["output"]
        )


def resolve_model_id(explicit: Optional[str] = None) -> str:
    """
    Decide which Claude model to call.

    Precedence: explicit argument > ANTHROPIC_MODEL env var > DEFAULT_MODEL.

    Note: If ANTHROPIC_MODEL contains a Bedrock-style model ID (with "us." prefix),
    we strip the prefix since Anthropic API uses simpler model names.
    """
    if explicit:
        model = explicit
    else:
        model = os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL

    # Strip Bedrock-style "us." prefix if present
    if model.startswith("us.anthropic."):
        model = model.replace("us.anthropic.", "")

    return model


class AnthropicAPIClient(LLMClient):
    """
    Anthropic API client implementing the LLMClient interface.

    Uses the official anthropic SDK to call Claude models directly
    (not through AWS Bedrock).
    """

    def __init__(
        self,
        model_id: Optional[str] = None,
        api_key: Optional[str] = None,
        verbose: bool = False,
    ):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "Anthropic SDK not installed. Install with: pip install anthropic"
            )

        self.model_id = resolve_model_id(model_id)
        self.verbose = verbose

        # Get API key from parameter or environment
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise CredentialsError(
                CREDENTIAL_HELP.format(log_path=DEBUG_LOG_PATH)
            )

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
        """
        Call Anthropic's API and return the response.

        Retries on transient failures. Credential failures are never retried.
        """
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
                    messages=[
                        {"role": "user", "content": user}
                    ],
                )

                # Extract response text
                if not response.content:
                    raise ModelInvocationError(
                        f"Anthropic returned empty content. "
                        f"Stop reason: {response.stop_reason}"
                    )

                text = response.content[0].text

                # Get token usage
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
                raise CredentialsError(
                    CREDENTIAL_HELP.format(log_path=DEBUG_LOG_PATH)
                ) from exc

            except (APIConnectionError, APITimeoutError, RateLimitError) as exc:
                # Transient errors - retry
                _logger.exception("Anthropic transient error (attempt %d)", attempt)
                last_error = exc

            except APIError as exc:
                _logger.exception("Anthropic API error")
                last_error = exc

            except Exception as exc:  # noqa: BLE001
                _logger.exception("Unexpected Anthropic failure")
                last_error = exc

            if attempt <= retries:
                time.sleep(backoff_seconds)

        raise ModelInvocationError(
            f"Anthropic API call failed after {attempt} attempt(s): {last_error}. "
            f"Detail in {DEBUG_LOG_PATH}"
        )
