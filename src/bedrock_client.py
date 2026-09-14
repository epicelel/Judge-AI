"""
Thin wrapper around AWS Bedrock's Converse API.

Responsibilities (Technical Spec §8):
- Cross-region inference profiles (model IDs prefixed `us.`)
- Model switching via the ANTHROPIC_MODEL env var (Story 6.1)
- Token counting + cost estimation (Story 6.2)
- Retry with backoff (Story 3.1)
- Friendly credential errors, stack traces to a debug log (Story 7.3)
"""

import os
import sys
import time
import logging
from pathlib import Path
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    NoCredentialsError,
    NoRegionError,
    EndpointConnectionError,
)

from .llm_client import (
    LLMClient,
    ModelResponse,
    CredentialsError,
    ModelInvocationError,
)

# Newer Anthropic models on Bedrock are only reachable through a cross-region
# inference profile, which is what the `us.` prefix denotes. A plain
# `anthropic.claude-sonnet-4-5-...` ID fails with "on-demand throughput isn't
# supported" (Technical Spec §3).
DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_REGION = "us-west-2"

# USD per 1M tokens. Used only for the estimated-cost line (Story 6.2);
# never treated as authoritative billing data.
PRICING_PER_MTOK = {
    "sonnet": {"input": 3.00, "output": 15.00},
    "opus": {"input": 15.00, "output": 75.00},
    "haiku": {"input": 1.00, "output": 5.00},
}

# Long transcripts (a 36KB round is ~10k tokens) plus a 5-paradigm sequential
# run means slow individual calls. The default botocore read timeout of 60s is
# far too short and was a repeated failure point in the previous build.
READ_TIMEOUT_SECONDS = 600
CONNECT_TIMEOUT_SECONDS = 15

DEBUG_LOG_PATH = Path(__file__).resolve().parent.parent / "judgeai.log"

# Story 7.3: technical detail goes to a debug log, never to stdout.
_logger = logging.getLogger("judgeai.bedrock")
if not _logger.handlers:
    _handler = logging.FileHandler(DEBUG_LOG_PATH, encoding="utf-8")
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    _logger.addHandler(_handler)
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False


CREDENTIAL_HELP = """AWS credentials are missing or expired.

Configure AWS credentials for your own account, then re-run:

  aws configure
  aws sts get-caller-identity

Technical detail written to {log_path}"""


def echo_call(
    system: str,
    user: str,
    response: Optional[str] = None,
    label: str = "model call",
) -> None:
    """
    Print a call's prompts and response for --verbose (Story 7.1).

    Always stderr: stdout carries the ballots and the diff, and must stay clean
    enough to pipe.
    """
    divider = "-" * 70
    print(f"\n{divider}\n[{label}] SYSTEM PROMPT\n{divider}", file=sys.stderr)
    print(system, file=sys.stderr)
    print(f"\n{divider}\n[{label}] USER PROMPT\n{divider}", file=sys.stderr)
    print(user, file=sys.stderr)
    if response is not None:
        print(f"\n{divider}\n[{label}] RESPONSE\n{divider}", file=sys.stderr)
        print(response, file=sys.stderr)
    print(divider, file=sys.stderr)


class BedrockModelResponse(ModelResponse):
    """
    ModelResponse subclass with Bedrock-specific pricing.

    Extends the base ModelResponse to add cost calculation based on
    AWS Bedrock's pricing for Claude models.
    """

    @property
    def cost_usd(self) -> float:
        """Estimated cost of this single call using Bedrock pricing."""
        rates = _rates_for_model(self.model_id)
        return (
            self.input_tokens / 1_000_000 * rates["input"]
            + self.output_tokens / 1_000_000 * rates["output"]
        )


def _rates_for_model(model_id: str) -> dict:
    """Pick a pricing table by model family, defaulting to Sonnet rates."""
    lowered = model_id.lower()
    for family, rates in PRICING_PER_MTOK.items():
        if family in lowered:
            return rates
    return PRICING_PER_MTOK["sonnet"]


def resolve_model_id(explicit: Optional[str] = None) -> str:
    """
    Decide which model to call (Story 6.1).

    Precedence: explicit argument > ANTHROPIC_MODEL env var > DEFAULT_MODEL.
    """
    if explicit:
        return explicit
    return os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL


def resolve_region(explicit: Optional[str] = None) -> str:
    """Region precedence: explicit > AWS_REGION > AWS_DEFAULT_REGION > default."""
    return (
        explicit
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or DEFAULT_REGION
    )


# Error codes Bedrock/STS return when the caller's session is no longer valid.
_CREDENTIAL_ERROR_CODES = {
    "ExpiredToken",
    "ExpiredTokenException",
    "InvalidClientTokenId",
    "InvalidSignatureException",
    "UnrecognizedClientException",
    "AccessDeniedException",
    "AuthFailure",
}


class BedrockClient(LLMClient):
    """
    Synchronous Bedrock caller implementing the LLMClient interface.

    The boto3 client is created lazily so that constructing a BedrockClient
    never touches the network — important for --dry-run (Story 7.2) and for
    tests, which must not require credentials.
    """

    def __init__(
        self,
        model_id: Optional[str] = None,
        region: Optional[str] = None,
        read_timeout: int = READ_TIMEOUT_SECONDS,
        verbose: bool = False,
    ):
        self.model_id = resolve_model_id(model_id)
        self.region = resolve_region(region)
        self._read_timeout = read_timeout
        self.verbose = verbose
        self._client = None

    def _get_client(self):
        """Create the bedrock-runtime client on first use."""
        if self._client is None:
            config = Config(
                read_timeout=self._read_timeout,
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                # We own retry policy at the invoke() level so backoff matches
                # Story 3.1 (one retry, 5s). Disable botocore's own retrying.
                retries={"max_attempts": 1, "mode": "standard"},
            )
            try:
                self._client = boto3.client(
                    "bedrock-runtime", region_name=self.region, config=config
                )
            except NoRegionError as exc:
                raise ModelInvocationError(
                    "No AWS region configured. Set AWS_REGION=us-west-2."
                ) from exc
        return self._client

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
        Call the model once and return its text plus token usage.

        Retries `retries` times on transient failures with a fixed backoff
        (Story 3.1: "retries once with 5s backoff"). Credential failures are
        never retried — a refresh is required, so retrying only wastes time.
        """
        client = self._get_client()
        attempt = 0
        last_error: Optional[Exception] = None

        while attempt <= retries:
            attempt += 1
            started = time.monotonic()
            try:
                # The Converse API normalizes message shape across model
                # families, so we don't hand-build Anthropic-specific JSON.
                response = client.converse(
                    modelId=self.model_id,
                    messages=[{"role": "user", "content": [{"text": user}]}],
                    system=[{"text": system}],
                    inferenceConfig={
                        "maxTokens": max_tokens,
                        "temperature": temperature,
                    },
                )
            except NoCredentialsError as exc:
                _logger.exception("No credentials available")
                raise CredentialsError(
                    CREDENTIAL_HELP.format(log_path=DEBUG_LOG_PATH)
                ) from exc
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                _logger.exception("ClientError from Bedrock (code=%s)", code)
                if code in _CREDENTIAL_ERROR_CODES:
                    raise CredentialsError(
                        CREDENTIAL_HELP.format(log_path=DEBUG_LOG_PATH)
                    ) from exc
                last_error = exc
            except EndpointConnectionError as exc:
                _logger.exception("Could not reach the Bedrock endpoint")
                last_error = exc
            except Exception as exc:  # noqa: BLE001 - surface as BedrockError
                _logger.exception("Unexpected Bedrock failure")
                last_error = exc
            else:
                usage = response.get("usage", {})
                content = response.get("output", {}).get("message", {}).get("content", [])
                if not content:
                    stop_reason = response.get("stopReason", "unknown")
                    _logger.error(
                        f"Empty content in Bedrock response. "
                        f"StopReason: {stop_reason}, Response keys: {list(response.keys())}"
                    )
                    if stop_reason == "content_filtered":
                        raise ModelInvocationError(
                            "AWS Bedrock content filter blocked this request. "
                            "Debate topics involving weapons, violence, or sensitive content may "
                            "trigger guardrails. Check your Bedrock guardrails configuration."
                        )
                    raise ModelInvocationError(
                        f"Bedrock returned empty content (stopReason: {stop_reason}). "
                        f"Possible causes: request too large or model error."
                    )
                text = content[0]["text"]
                if self.verbose:
                    echo_call(system, user, text, label=self.model_id)
                return BedrockModelResponse(
                    text=text,
                    input_tokens=usage.get("inputTokens", 0),
                    output_tokens=usage.get("outputTokens", 0),
                    model_id=self.model_id,
                    latency_seconds=time.monotonic() - started,
                )

            if attempt <= retries:
                time.sleep(backoff_seconds)

        raise ModelInvocationError(
            f"Model call failed after {attempt} attempt(s): {last_error}. "
            f"Detail in {DEBUG_LOG_PATH}"
        )


DRY_RUN_PLACEHOLDER = "[dry-run: no model call made]"


class DryRunBedrockClient:
    """
    Interface-compatible stand-in that never calls the model (Story 7.2).

    Records every prompt it was handed so the CLI can show exactly what would
    have been sent, and reports zero tokens so cost totals stay honest at $0.
    Deliberately not a subclass of BedrockClient: inheriting would risk quietly
    falling through to a real call if invoke() were ever refactored.
    """

    def __init__(
        self,
        model_id: Optional[str] = None,
        region: Optional[str] = None,
        verbose: bool = False,
        echo: bool = True,
    ):
        self.model_id = resolve_model_id(model_id)
        self.region = resolve_region(region)
        self.verbose = verbose
        self.echo = echo
        self.calls: list = []

    def invoke(self, system: str, user: str, **kwargs) -> ModelResponse:
        label = kwargs.pop("label", "would send")
        self.calls.append({"system": system, "user": user, "label": label, **kwargs})
        if self.echo:
            echo_call(system, user, response=None, label=f"DRY RUN — {label}")
        return BedrockModelResponse(
            text=DRY_RUN_PLACEHOLDER,
            input_tokens=0,
            output_tokens=0,
            model_id=self.model_id,
        )

    @property
    def call_count(self) -> int:
        return len(self.calls)


def build_client(
    dry_run: bool = False,
    verbose: bool = False,
    model_id: Optional[str] = None,
    provider: Optional[str] = None,
    enable_fallback: bool = True,
):
    """
    Build an LLM client for the specified provider.

    Provider selection (in order of precedence):
    1. Explicit provider parameter
    2. LLM_PROVIDER environment variable
    3. Auto-detect based on available credentials:
       - ANTHROPIC_API_KEY → anthropic
       - OPENAI_API_KEY → openai
       - AWS credentials → bedrock (default fallback)

    With enable_fallback=True and multiple API keys configured:
    - Creates a FallbackClient that automatically switches providers on rate limits
    - Fallback chain: Anthropic → OpenAI → Bedrock

    Args:
        dry_run: If True, return a dry-run client that never calls the model
        verbose: If True, print prompts and responses to stderr
        model_id: Optional model ID override
        provider: Optional provider override ('bedrock', 'openai', 'anthropic')
        enable_fallback: If True, use FallbackClient when multiple providers available

    Returns:
        LLMClient instance (BedrockClient, OpenAIClient, AnthropicAPIClient, or FallbackClient)

    Raises:
        ValueError: If provider is specified but not available
    """
    if dry_run:
        return DryRunBedrockClient(model_id=model_id, verbose=verbose)

    # If enable_fallback and no specific provider requested, try to build fallback chain
    if enable_fallback and not provider and not os.environ.get("LLM_PROVIDER"):
        # Check if multiple API keys are available
        api_keys_count = sum([
            bool(os.environ.get("ANTHROPIC_API_KEY")),
            bool(os.environ.get("OPENAI_API_KEY")),
        ])

        if api_keys_count >= 2:
            # Multiple providers available - use fallback
            from .fallback_client import build_fallback_client
            return build_fallback_client(verbose=verbose)[0]

    # Single provider mode (original behavior)
    provider = (
        provider
        or os.environ.get("LLM_PROVIDER", "").lower()
        or _auto_detect_provider()
    )

    if provider == "openai":
        try:
            from .openai_client import OpenAIClient
            return OpenAIClient(model_id=model_id, verbose=verbose)
        except ImportError as exc:
            raise ValueError(
                "OpenAI provider selected but SDK not installed. "
                "Install with: pip install openai"
            ) from exc

    elif provider == "anthropic":
        try:
            from .anthropic_client import AnthropicAPIClient
            return AnthropicAPIClient(model_id=model_id, verbose=verbose)
        except ImportError as exc:
            raise ValueError(
                "Anthropic provider selected but SDK not installed. "
                "Install with: pip install anthropic"
            ) from exc

    elif provider == "bedrock":
        return BedrockClient(model_id=model_id, verbose=verbose)

    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. "
            f"Valid options: bedrock, openai, anthropic"
        )


def _auto_detect_provider() -> str:
    """
    Auto-detect which LLM provider to use based on available credentials.

    Returns:
        Provider name ('anthropic', 'openai', or 'bedrock')
    """
    # Check for Anthropic API key
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"

    # Check for OpenAI API key
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"

    # Default to Bedrock (assumes AWS credentials are configured)
    return "bedrock"
