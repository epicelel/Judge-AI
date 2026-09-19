"""
OpenAI API client implementing the LLMClient interface.

Supports GPT-4 and other OpenAI models via the official openai SDK.
Requires OPENAI_API_KEY environment variable.
"""

import os
import sys
import time
import logging
from pathlib import Path
from typing import Optional

try:
    from openai import OpenAI
    from openai import (
        APIError,
        APIConnectionError,
        APITimeoutError,
        AuthenticationError,
        RateLimitError,
    )
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from .llm_client import (
    LLMClient,
    ModelResponse,
    CredentialsError,
    ModelInvocationError,
)

# Default to GPT-5.6 Luna
DEFAULT_MODEL = "gpt-5.6-luna"

# OpenAI pricing per 1M tokens
PRICING_PER_MTOK = {
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
}

DEBUG_LOG_PATH = Path(__file__).resolve().parent.parent / "judgeai.log"

_logger = logging.getLogger("judgeai.openai")
if not _logger.handlers:
    _handler = logging.FileHandler(DEBUG_LOG_PATH, encoding="utf-8")
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    _logger.addHandler(_handler)
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False


CREDENTIAL_HELP = """OpenAI API key is missing or invalid.

Set your API key:

  export OPENAI_API_KEY='sk-...'

Get an API key at: https://platform.openai.com/api-keys

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
    # Default to gpt-4-turbo pricing if unknown
    return PRICING_PER_MTOK["gpt-4-turbo"]


class OpenAIModelResponse(ModelResponse):
    """ModelResponse subclass with OpenAI-specific pricing."""

    @property
    def cost_usd(self) -> float:
        """Estimated cost of this single call using OpenAI pricing."""
        rates = _rates_for_model(self.model_id)
        return (
            self.input_tokens / 1_000_000 * rates["input"]
            + self.output_tokens / 1_000_000 * rates["output"]
        )


def resolve_model_id(explicit: Optional[str] = None) -> str:
    """
    Decide which OpenAI model to call.

    Precedence: explicit argument > OPENAI_MODEL env var > DEFAULT_MODEL.
    """
    if explicit:
        return explicit
    return os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL


class OpenAIClient(LLMClient):
    """
    OpenAI API client implementing the LLMClient interface.

    Uses the official openai SDK to call GPT-4 and other models.
    """

    def __init__(
        self,
        model_id: Optional[str] = None,
        api_key: Optional[str] = None,
        verbose: bool = False,
    ):
        if not OPENAI_AVAILABLE:
            raise ImportError(
                "OpenAI SDK not installed. Install with: pip install openai"
            )

        self.model_id = resolve_model_id(model_id)
        self.verbose = verbose

        # Get API key from parameter or environment
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise CredentialsError(
                CREDENTIAL_HELP.format(log_path=DEBUG_LOG_PATH)
            )

        self._client = OpenAI(api_key=api_key, timeout=600.0)

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
        Call OpenAI's API and return the response.

        Retries on transient failures. Credential failures are never retried.
        """
        attempt = 0
        last_error: Optional[Exception] = None

        while attempt <= retries:
            attempt += 1
            started = time.monotonic()

            try:
                response = self._client.chat.completions.create(
                    model=self.model_id,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

                # Extract response
                text = response.choices[0].message.content
                if not text:
                    raise ModelInvocationError(
                        f"OpenAI returned empty content. "
                        f"Finish reason: {response.choices[0].finish_reason}"
                    )

                # Get token usage
                usage = response.usage
                input_tokens = usage.prompt_tokens if usage else 0
                output_tokens = usage.completion_tokens if usage else 0

                if self.verbose:
                    echo_call(system, user, text, label=self.model_id)

                return OpenAIModelResponse(
                    text=text,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    model_id=self.model_id,
                    latency_seconds=time.monotonic() - started,
                )

            except AuthenticationError as exc:
                _logger.exception("OpenAI authentication failed")
                raise CredentialsError(
                    CREDENTIAL_HELP.format(log_path=DEBUG_LOG_PATH)
                ) from exc

            except (APIConnectionError, APITimeoutError, RateLimitError) as exc:
                # Transient errors - retry
                _logger.exception("OpenAI transient error (attempt %d)", attempt)
                last_error = exc

            except APIError as exc:
                _logger.exception("OpenAI API error")
                last_error = exc

            except Exception as exc:  # noqa: BLE001
                _logger.exception("Unexpected OpenAI failure")
                last_error = exc

            if attempt <= retries:
                time.sleep(backoff_seconds)

        raise ModelInvocationError(
            f"OpenAI API call failed after {attempt} attempt(s): {last_error}. "
            f"Detail in {DEBUG_LOG_PATH}"
        )
