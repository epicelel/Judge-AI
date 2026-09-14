"""
Configuration management for JudgeAI.

Stores API keys and settings persistently in user's home directory.
"""

import os
import json
from pathlib import Path
from typing import Optional


CONFIG_DIR = Path.home() / ".judgeai"
CONFIG_FILE = CONFIG_DIR / "config.json"


def ensure_config_dir():
    """Create config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """
    Load configuration from disk.

    Returns:
        Dictionary with config values, or empty dict if no config exists
    """
    ensure_config_dir()

    if not CONFIG_FILE.exists():
        return {}

    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(config: dict):
    """
    Save configuration to disk.

    Args:
        config: Dictionary with config values
    """
    ensure_config_dir()

    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        raise IOError(f"Failed to save config: {e}")


def get_api_key(provider: str) -> Optional[str]:
    """
    Get API key for a provider.

    Checks (in order):
    1. Environment variable
    2. Saved config file

    Args:
        provider: 'anthropic', 'openai', or 'bedrock'

    Returns:
        API key string, or None if not found
    """
    env_var = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
    }.get(provider.lower())

    # Check environment first
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]

    # Check saved config
    config = load_config()
    return config.get(f"{provider.lower()}_api_key")


def set_api_key(provider: str, key: str):
    """
    Save API key for a provider.

    Saves to both environment (for current session) and config file (persistent).

    Args:
        provider: 'anthropic', 'openai', or 'bedrock'
        key: API key string
    """
    env_var = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
    }.get(provider.lower())

    # Set environment variable for current session
    if env_var:
        os.environ[env_var] = key

    # Save to config file for persistence
    config = load_config()
    config[f"{provider.lower()}_api_key"] = key
    save_config(config)


def get_provider_preference() -> Optional[str]:
    """
    Get preferred provider.

    Returns:
        Provider name ('anthropic', 'openai', 'bedrock', 'auto'), or None
    """
    # Check environment first
    if os.environ.get("LLM_PROVIDER"):
        return os.environ["LLM_PROVIDER"]

    # Check saved config
    config = load_config()
    return config.get("provider_preference")


def set_provider_preference(provider: str):
    """
    Save preferred provider.

    Args:
        provider: 'anthropic', 'openai', 'bedrock', or 'auto'
    """
    # Set environment variable for current session
    if provider and provider != "auto":
        os.environ["LLM_PROVIDER"] = provider
    else:
        os.environ.pop("LLM_PROVIDER", None)

    # Save to config file
    config = load_config()
    config["provider_preference"] = provider
    save_config(config)


def load_into_environment():
    """
    Load saved API keys into environment variables.

    Call this at app startup to restore saved keys.
    """
    config = load_config()

    # Load Anthropic key
    if config.get("anthropic_api_key"):
        os.environ["ANTHROPIC_API_KEY"] = config["anthropic_api_key"]

    # Load OpenAI key
    if config.get("openai_api_key"):
        os.environ["OPENAI_API_KEY"] = config["openai_api_key"]

    # Load provider preference
    if config.get("provider_preference"):
        pref = config["provider_preference"]
        if pref != "auto":
            os.environ["LLM_PROVIDER"] = pref


def get_available_providers() -> list[str]:
    """
    Get list of providers that have API keys configured.

    Returns:
        List of provider names that are ready to use
    """
    providers = []

    if get_api_key("anthropic"):
        providers.append("Anthropic API")

    if get_api_key("openai"):
        providers.append("OpenAI API")

    return providers
