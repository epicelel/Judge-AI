"""Fallback LLM client for Anthropic/OpenAI provider switching."""

import logging
from pathlib import Path
from typing import List

from .llm_client import CredentialsError, LLMClient, ModelInvocationError, ModelResponse

DEBUG_LOG_PATH = Path(__file__).resolve().parent.parent / "judgeai.log"
_logger = logging.getLogger("judgeai.fallback")
if not _logger.handlers:
    _handler = logging.FileHandler(DEBUG_LOG_PATH, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False


class FallbackClient(LLMClient):
    """Try the active provider first, then the remaining configured providers."""

    def __init__(self, providers: List[LLMClient], provider_names: List[str]):
        if not providers:
            raise ValueError("FallbackClient requires at least one provider")
        if len(providers) != len(provider_names):
            raise ValueError("providers and provider_names must have equal length")
        self.providers = providers
        self.provider_names = provider_names
        self.current_index = 0
        self.last_error = None

    @property
    def current_provider_name(self) -> str:
        return self.provider_names[self.current_index]

    @property
    def model_id(self) -> str:
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
        errors = []
        count = len(self.providers)
        order = [(self.current_index + offset) % count for offset in range(count)]

        for idx in order:
            provider = self.providers[idx]
            name = self.provider_names[idx]
            try:
                _logger.info("Attempting call with provider: %s", name)
                response = provider.invoke(
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    retries=retries,
                    backoff_seconds=backoff_seconds,
                )
                if self.current_index != idx:
                    _logger.info("Switched active provider to: %s", name)
                self.current_index = idx
                return response
            except Exception as exc:  # provider clients already implement retries
                _logger.error("Provider %s failed: %s", name, exc)
                errors.append(f"{name}: {exc}")

        self.last_error = "\n".join(errors)
        raise ModelInvocationError(
            f"All LLM providers failed:\n{self.last_error}\n\n"
            f"Tried: {', '.join(self.provider_names)}\n"
            f"See {DEBUG_LOG_PATH} for details"
        )


def build_fallback_client(verbose: bool = False) -> tuple[LLMClient, List[str]]:
    """Build an Anthropic -> OpenAI fallback chain from configured API keys."""
    import os

    providers: List[LLMClient] = []
    provider_names: List[str] = []

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from .anthropic_client import AnthropicAPIClient
            providers.append(AnthropicAPIClient(verbose=verbose))
            provider_names.append("Anthropic API")
        except Exception as exc:
            _logger.warning("Could not create Anthropic client: %s", exc)

    if os.environ.get("OPENAI_API_KEY"):
        try:
            from .openai_client import OpenAIClient
            providers.append(OpenAIClient(verbose=verbose))
            provider_names.append("OpenAI API")
        except Exception as exc:
            _logger.warning("Could not create OpenAI client: %s", exc)

    if not providers:
        raise CredentialsError(
            "No LLM providers configured. Add an Anthropic or OpenAI API key in Settings."
        )

    if len(providers) == 1:
        return providers[0], provider_names
    return FallbackClient(providers, provider_names), provider_names
