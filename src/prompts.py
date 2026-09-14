"""
Loading prompt files from `prompts/`.

Prompts live on disk as Markdown rather than in string literals so they can be
edited and diffed without touching code — persona iteration (v0.15) is expected
to be the main activity after v0.1 ships.
"""

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class PromptNotFound(FileNotFoundError):
    """A prompt file is missing — a packaging error, not user error."""


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """
    Read a prompt by path relative to prompts/, e.g. "shared/structure_detection".

    Cached: a 5-persona run would otherwise re-read the shared standards file
    five times.
    """
    path = PROMPTS_DIR / (name if name.endswith(".md") else f"{name}.md")
    if not path.exists():
        raise PromptNotFound(
            f"Prompt not found: {path}. Expected under {PROMPTS_DIR}."
        )
    return path.read_text(encoding="utf-8")


def prompt_path(name: str) -> Path:
    return PROMPTS_DIR / (name if name.endswith(".md") else f"{name}.md")
