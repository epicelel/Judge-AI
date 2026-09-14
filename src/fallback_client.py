"""
Fallback LLM client with automatic provider switching on rate limits.

When one provider hits rate limits, automatically switches to backup provider.
Supports Anthropic → OpenAI → Bedrock fallback chain.
"""

import logging
from typing import List, Optional
from pathlib import Path

from .llm_client import LLMClient, ModelResponse, CredentialsError, ModelInvocationError

DEBUG_LOG_PATH = Path(__file__).resolve().parent.parent / "judgeai.log"

_logger = logging.getLogger("judgeai.fallback")
if not _logger.handlers:
    _handler = logging.FileHandler(DEBUG_LOG_PATH, encoding="utf-8")
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    _logger.addHandler(_handler)
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False


class FallbackClient(LLMClient):
    """
    LLM client that automatically falls back to alternate providers on rate limits.

    Tries providers in order until one succeeds. Rate limit errors trigger
    immediate fallback to the next provider.
    """

    def __init__(self, providers: List[LLMClient], provider_names: List[str]):
        """
        Initialize fallback client.

        Args:
            providers: List of LLMClient instances to try in order
            provider_names: Human-readable names for each provider (for logging)
        """
        if not providers:
            raise ValueError("FallbackClient requires at least one provider")

        self.providers = providers
        self.provider_names = provider_names
        self.current_index = 0
        self.last_error = None

    @property
    def current_provider_name(self) -> str:
        """Get the name of the currently active provider."""
        return self.provider_names[self.current_index]

    @property
    def model_id(self) -> str:
        """Get the model ID of the current provider."""
        return self.providers[self.current_index].model_id

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
        Call LLM with automatic fallback on rate limits.

        Tries each provider in order. Rate limit errors trigger immediate
        fallback to next provider. Other errors retry with the same provider
        before falling back.

        Args:
            system: System prompt
            user: User message
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            retries: Retries per provider before falling back
            backoff_seconds: Seconds between retries

        Returns:
            ModelResponse from whichever provider succeeded

        Raises:
            ModelInvocationError: If all providers fail
        """
        errors = []

        # Try each provider in order
        for idx, (provider, name) in enumerate(zip(self.providers, self.provider_names)):
            try:
                _logger.info(f"Attempting call with provider: {name}")

                response = provider.invoke(
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    retries=retries,
                    backoff_seconds=backoff_seconds,
                )

                # Success! Update current provider index
                if self.current_index != idx:
                    _logger.info(f"Switched to provider: {name}")
                    self.current_index = idx

                return response

            except Exception as e:
                error_msg = str(e).lower()

                # Check if it's a rate limit error
                is_rate_limit = any(
                    term in error_msg
                    for term in [
                        "rate limit",
                        "rate_limit",
                        "ratelimit",
                        "too many requests",
                        "429",
                        "quota exceeded",
                        "overloaded",
                    ]
                )

                if is_rate_limit:
                    _logger.warning(f"Rate limit hit on {name}, trying next provider")
                    errors.append(f"{name}: Rate limit exceeded")
                    # Don't retry, immediately try next provider
                    continue
                else:
                    _logger.error(f"Error from {name}: {e}")
                    errors.append(f"{name}: {str(e)}")
                    # For non-rate-limit errors, this provider already retried
                    # Try next provider
                    continue

        # All providers failed
        self.last_error = "\n".join(errors)
        raise ModelInvocationError(
            f"All LLM providers failed:\n{self.last_error}\n\n"
            f"Tried: {', '.join(self.provider_names)}\n"
            f"See {DEBUG_LOG_PATH} for details"
        )


def build_fallback_client(verbose: bool = False) -> tuple[LLMClient, List[str]]:
    """
    Build a fallback client chain from available API keys.

    Tries to create clients for each provider that has credentials configured.
    Returns the client and a list of available provider names.

    Supports: Anthropic API and OpenAI API only.
    AWS Bedrock removed for simplicity.

    Returns:
        Tuple of (client, available_providers)
        - If multiple providers: returns FallbackClient
        - If one provider: returns that provider directly
        - If no providers: raises CredentialsError

    Raises:
        CredentialsError: If no valid providers could be created
    """
    import os

    providers = []
    provider_names = []

    # Try Anthropic API
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from .anthropic_client import AnthropicAPIClient

            client = AnthropicAPIClient(verbose=verbose)
            providers.append(client)
            provider_names.append("Anthropic API")
            _logger.info("Added Anthropic API to fallback chain")
        except Exception as e:
            _logger.warning(f"Could not create Anthropic client: {e}")

    # Try OpenAI API
    if os.environ.get("OPENAI_API_KEY"):
        try:
            from .openai_client import OpenAIClient

            client = OpenAIClient(verbose=verbose)
            providers.append(client)
            provider_names.append("OpenAI API")
            _logger.info("Added OpenAI API to fallback chain")
        except Exception as e:
            _logger.warning(f"Could not create OpenAI client: {e}")

    if not providers:
        raise CredentialsError(
            "No LLM providers configured. Set at least one:\n"
            "  • ANTHROPIC_API_KEY (recommended - $3/$15 per 1M tokens)\n"
            "  • OPENAI_API_KEY ($10/$30 per 1M tokens)\n\n"
            "Configure in Settings or set environment variables."
        )

    if len(providers) == 1:
        _logger.info(f"Single provider: {provider_names[0]}")
        return providers[0], provider_names
    else:
        _logger.info(f"Fallback chain: {' → '.join(provider_names)}")
        return FallbackClient(providers, provider_names), provider_names
