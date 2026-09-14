"""
Abstract base class for LLM clients.

This module defines the interface that all LLM provider clients must implement,
enabling JudgeAI to work with multiple backends (AWS Bedrock, OpenAI, Anthropic API, etc.)
without changing application code.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ModelResponse:
    """One completed model call, with usage attached."""

    text: str
    input_tokens: int
    output_tokens: int
    model_id: str
    latency_seconds: float = 0.0

    @property
    def cost_usd(self) -> float:
        """
        Estimated cost of this single call.

        Subclasses should override this if they need provider-specific pricing logic,
        or the base implementation can be extended to handle multiple providers.
        """
        # Default implementation - providers override if needed
        return 0.0


class LLMClient(ABC):
    """
    Abstract base class for LLM provider clients.

    All provider implementations (BedrockClient, OpenAIClient, AnthropicAPIClient)
    must implement the invoke() method with this signature.
    """

    @abstractmethod
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

        Args:
            system: System prompt defining the model's role and instructions
            user: User message containing the actual task/query
            max_tokens: Maximum tokens to generate in response
            temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative)
            retries: Number of retry attempts on transient failures
            backoff_seconds: Seconds to wait between retry attempts

        Returns:
            ModelResponse with text, token counts, model ID, and latency

        Raises:
            CredentialsError: When authentication fails (recoverable by user)
            ModelInvocationError: When the model call fails for other reasons
        """
        pass


class LLMError(Exception):
    """Base class for all LLM provider failures surfaced to the user."""


class CredentialsError(LLMError):
    """Credentials missing or expired — recoverable by the user."""


class ModelInvocationError(LLMError):
    """The model call failed for a reason other than credentials."""
