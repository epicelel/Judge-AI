"""
Phase 0 connectivity check: prove Bedrock is reachable before building features.

Makes one tiny model call and reports model ID, region, token usage, and cost.
Run it after every credential refresh:

    .venv/bin/python scripts/smoke_bedrock.py
"""

import sys
from pathlib import Path

# Allow running as a plain script without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bedrock_client import BedrockClient, BedrockError  # noqa: E402


def main() -> int:
    client = BedrockClient()
    print(f"Model:  {client.model_id}")
    print(f"Region: {client.region}")
    print("Calling Bedrock...")

    try:
        response = client.invoke(
            system="You are a terse assistant. Answer in exactly one word.",
            user="What is the capital of France?",
            max_tokens=16,
        )
    except BedrockError as exc:
        # Story 7.3: friendly message, no stack trace on stdout.
        print(f"\nFAILED\n\n{exc}", file=sys.stderr)
        return 1

    print(f"\nResponse: {response.text.strip()!r}")
    print(
        f"Tokens:   {response.input_tokens} in + {response.output_tokens} out"
        f"  (~${response.cost_usd:.6f})"
    )
    print(f"Latency:  {response.latency_seconds:.2f}s")
    print("\nOK — Bedrock is reachable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
