"""LLM client factory plus optional AWS Bedrock provider."""

import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError, NoRegionError

from .llm_client import CredentialsError, LLMClient, ModelInvocationError, ModelResponse

DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_REGION = "us-west-2"
READ_TIMEOUT_SECONDS = 600
CONNECT_TIMEOUT_SECONDS = 15

PRICING_PER_MTOK = {
    "sonnet": {"input": 3.00, "output": 15.00},
    "opus": {"input": 15.00, "output": 75.00},
    "haiku": {"input": 1.00, "output": 5.00},
}

DEBUG_LOG_PATH = Path(__file__).resolve().parent.parent / "judgeai.log"
_logger = logging.getLogger("judgeai.bedrock")
if not _logger.handlers:
    _handler = logging.FileHandler(DEBUG_LOG_PATH, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False

CREDENTIAL_HELP = f"""AWS credentials are missing or expired.
Configure AWS credentials and re-run.
Technical detail written to {DEBUG_LOG_PATH}"""

# Backward-compatible name for older callers. New code should use ModelInvocationError.
BedrockError = ModelInvocationError


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


class BedrockModelResponse(ModelResponse):
    @property
    def cost_usd(self) -> float:
        rates = _rates_for_model(self.model_id)
        return (
            self.input_tokens / 1_000_000 * rates["input"]
            + self.output_tokens / 1_000_000 * rates["output"]
        )


def resolve_model_id(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    return os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL


def resolve_region(explicit: Optional[str] = None) -> str:
    return explicit or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or DEFAULT_REGION


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
        if self._client is None:
            config = Config(
                read_timeout=self._read_timeout,
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                retries={"max_attempts": 1, "mode": "standard"},
            )
            try:
                self._client = boto3.client("bedrock-runtime", region_name=self.region, config=config)
            except NoRegionError as exc:
                raise ModelInvocationError("No AWS region configured. Set AWS_REGION=us-west-2.") from exc
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
        client = self._get_client()
        attempt = 0
        last_error: Optional[Exception] = None

        while attempt <= retries:
            attempt += 1
            started = time.monotonic()
            try:
                response = client.converse(
                    modelId=self.model_id,
                    messages=[{"role": "user", "content": [{"text": user}]}],
                    system=[{"text": system}],
                    inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
                )
            except NoCredentialsError as exc:
                _logger.exception("No AWS credentials available")
                raise CredentialsError(CREDENTIAL_HELP) from exc
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                _logger.exception("Bedrock ClientError (code=%s)", code)
                if code in _CREDENTIAL_ERROR_CODES:
                    raise CredentialsError(CREDENTIAL_HELP) from exc
                last_error = exc
            except EndpointConnectionError as exc:
                _logger.exception("Could not reach Bedrock endpoint")
                last_error = exc
            except Exception as exc:  # noqa: BLE001
                _logger.exception("Unexpected Bedrock failure")
                last_error = exc
            else:
                usage = response.get("usage", {})
                content = response.get("output", {}).get("message", {}).get("content", [])
                if not content:
                    stop_reason = response.get("stopReason", "unknown")
                    raise ModelInvocationError(f"Bedrock returned empty content (stopReason: {stop_reason}).")
                text = content[0].get("text", "")
                if not text:
                    raise ModelInvocationError("Bedrock returned an empty text block.")
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
            f"Bedrock model call failed after {attempt} attempt(s): {last_error}. "
            f"Detail in {DEBUG_LOG_PATH}"
        )


DRY_RUN_PLACEHOLDER = "[dry-run: no model call made]"


class DryRunClient(LLMClient):
    """Provider-neutral dry-run client."""

    def __init__(self, model_id: str = "dry-run", verbose: bool = False, echo: bool = True):
        self.model_id = model_id
        self.verbose = verbose
        self.echo = echo
        self.calls: list = []

    def invoke(self, system: str, user: str, **kwargs) -> ModelResponse:
        label = kwargs.pop("label", "would send")
        self.calls.append({"system": system, "user": user, "label": label, **kwargs})
        if self.echo:
            echo_call(system, user, response=None, label=f"DRY RUN — {label}")
        return ModelResponse(
            text=DRY_RUN_PLACEHOLDER,
            input_tokens=0,
            output_tokens=0,
            model_id=self.model_id,
        )

    @property
    def call_count(self) -> int:
        return len(self.calls)


# Preserve the old class name for tests/imports while making it provider-neutral.
DryRunBedrockClient = DryRunClient


def _normalized_provider(provider: Optional[str]) -> Optional[str]:
    value = (provider or "").strip().lower()
    return None if value in {"", "auto"} else value


def build_client(
    dry_run: bool = False,
    verbose: bool = False,
    model_id: Optional[str] = None,
    provider: Optional[str] = None,
    enable_fallback: bool = True,
):
    """Build the selected LLM client.

    Auto mode uses configured Anthropic/OpenAI keys. Bedrock remains available
    only when explicitly selected via provider="bedrock" or LLM_PROVIDER=bedrock.
    """
    requested = _normalized_provider(provider) or _normalized_provider(os.environ.get("LLM_PROVIDER"))

    if dry_run:
        return DryRunClient(model_id=model_id or "dry-run", verbose=verbose)

    if enable_fallback and requested is None:
        api_keys_count = sum(
            [bool(os.environ.get("ANTHROPIC_API_KEY")), bool(os.environ.get("OPENAI_API_KEY"))]
        )
        if api_keys_count >= 2:
            from .fallback_client import build_fallback_client
            return build_fallback_client(verbose=verbose)[0]

    selected = requested or _auto_detect_provider()

    if selected == "openai":
        try:
            from .openai_client import OpenAIClient
            return OpenAIClient(model_id=model_id, verbose=verbose)
        except ImportError as exc:
            raise ValueError("OpenAI provider selected but SDK not installed. Install with: pip install openai") from exc

    if selected == "anthropic":
        try:
            from .anthropic_client import AnthropicAPIClient
            return AnthropicAPIClient(model_id=model_id, verbose=verbose)
        except ImportError as exc:
            raise ValueError("Anthropic provider selected but SDK not installed. Install with: pip install anthropic") from exc

    if selected == "bedrock":
        return BedrockClient(model_id=model_id, verbose=verbose)

    raise ValueError(f"Unknown LLM provider: {selected}. Valid options: openai, anthropic, bedrock")


def _auto_detect_provider() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    raise CredentialsError(
        "No LLM provider configured. Add an Anthropic or OpenAI API key in Settings, "
        "or explicitly select Bedrock and configure AWS credentials."
    )
