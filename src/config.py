"""Configuration management for JudgeAI."""

import json
import logging
import os
import stat
from pathlib import Path
from typing import Iterable, Optional

CONFIG_DIR = Path.home() / ".judgeai"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEBUG_LOG_PATH = Path(__file__).resolve().parent.parent / "judgeai.log"

_logger = logging.getLogger("judgeai.config")
if not _logger.handlers:
    _handler = logging.FileHandler(DEBUG_LOG_PATH, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False

_PROVIDER_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

_DEFAULT_GUI_SETTINGS = {
    "default_runs": 3,
    "default_paradigms": ["lay", "educated_lay", "traditional", "circuit"],
}


_DEFAULT_UI_STATE = {
    "theme": "system",
    "recent_search": "",
    "recent_format": "all",
    "recent_winner": "all",
    "recent_sort": "newest",
    "window_geometry": None,
    "window_maximized": False,
    "onboarding_complete": False,
}

_MODEL_ENV = {
    "anthropic": "ANTHROPIC_MODEL",
    "openai": "OPENAI_MODEL",
}


def _harden_permissions(path: Path, mode: int) -> None:
    """Best-effort private permissions on POSIX; harmless on Windows."""
    try:
        path.chmod(mode)
    except OSError:
        pass


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        _harden_permissions(CONFIG_DIR, stat.S_IRWXU)


def load_config() -> dict:
    """Load config, preserving corrupt files instead of silently discarding them."""
    ensure_config_dir()
    if not CONFIG_FILE.exists():
        return {}

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        backup = CONFIG_FILE.with_suffix(".corrupt.json")
        try:
            CONFIG_FILE.replace(backup)
            _logger.error("Invalid config JSON moved to %s: %s", backup, exc)
        except OSError:
            _logger.exception("Invalid config JSON at %s", CONFIG_FILE)
        return {}
    except OSError as exc:
        _logger.error("Could not read config %s: %s", CONFIG_FILE, exc)
        return {}

    return data if isinstance(data, dict) else {}


def save_config(config: dict) -> None:
    ensure_config_dir()
    temp_file = CONFIG_FILE.with_suffix(".tmp")
    try:
        with temp_file.open("w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)
            handle.write("\n")
        if os.name != "nt":
            _harden_permissions(temp_file, stat.S_IRUSR | stat.S_IWUSR)
        temp_file.replace(CONFIG_FILE)
        if os.name != "nt":
            _harden_permissions(CONFIG_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        try:
            temp_file.unlink(missing_ok=True)
        except OSError:
            pass
        raise IOError(f"Failed to save config: {exc}") from exc


def get_api_key(provider: str) -> Optional[str]:
    provider = provider.lower()
    env_var = _PROVIDER_ENV.get(provider)
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    return load_config().get(f"{provider}_api_key")


def set_api_key(provider: str, key: str) -> None:
    provider = provider.lower()
    if provider not in _PROVIDER_ENV:
        raise ValueError(f"Unsupported API-key provider: {provider}")
    key = (key or "").strip()
    if not key:
        clear_api_key(provider)
        return

    os.environ[_PROVIDER_ENV[provider]] = key
    config = load_config()
    config[f"{provider}_api_key"] = key
    save_config(config)


def clear_api_key(provider: str) -> None:
    """Remove a saved provider key from both this process and persistent config."""
    provider = provider.lower()
    env_var = _PROVIDER_ENV.get(provider)
    if env_var is None:
        raise ValueError(f"Unsupported API-key provider: {provider}")

    os.environ.pop(env_var, None)
    config = load_config()
    config.pop(f"{provider}_api_key", None)
    save_config(config)


def get_provider_preference() -> Optional[str]:
    env_value = os.environ.get("LLM_PROVIDER")
    if env_value:
        return env_value
    return load_config().get("provider_preference")


def set_provider_preference(provider: str) -> None:
    provider = (provider or "auto").strip().lower()
    if provider not in {"auto", "anthropic", "openai", "bedrock"}:
        raise ValueError(f"Unsupported provider preference: {provider}")

    if provider == "auto":
        os.environ.pop("LLM_PROVIDER", None)
    else:
        os.environ["LLM_PROVIDER"] = provider

    config = load_config()
    config["provider_preference"] = provider
    save_config(config)


def get_model_preference(provider: str) -> Optional[str]:
    """Return the configured model override for a provider, if any."""
    provider = provider.lower()
    env_var = _MODEL_ENV.get(provider)
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    return load_config().get(f"{provider}_model")


def set_model_preference(provider: str, model_id: Optional[str]) -> None:
    """Persist or clear a provider-specific model override."""
    provider = provider.lower()
    env_var = _MODEL_ENV.get(provider)
    if env_var is None:
        raise ValueError(f"Unsupported model provider: {provider}")

    model = (model_id or "").strip()
    config = load_config()
    if model:
        config[f"{provider}_model"] = model
        os.environ[env_var] = model
    else:
        config.pop(f"{provider}_model", None)
        os.environ.pop(env_var, None)
    save_config(config)


def get_gui_defaults() -> dict:
    """Return validated GUI defaults without mutating persisted config."""
    config = load_config()
    try:
        runs = int(config.get("default_runs", _DEFAULT_GUI_SETTINGS["default_runs"]))
    except (TypeError, ValueError):
        runs = _DEFAULT_GUI_SETTINGS["default_runs"]
    if runs not in {1, 3, 5}:
        runs = _DEFAULT_GUI_SETTINGS["default_runs"]

    raw = config.get("default_paradigms", _DEFAULT_GUI_SETTINGS["default_paradigms"])
    if not isinstance(raw, list):
        raw = list(_DEFAULT_GUI_SETTINGS["default_paradigms"])
    paradigms = [str(value) for value in raw if str(value).strip()]
    if not paradigms:
        paradigms = list(_DEFAULT_GUI_SETTINGS["default_paradigms"])
    return {"default_runs": runs, "default_paradigms": paradigms}


def set_gui_defaults(runs: int, paradigms: Iterable[str]) -> None:
    """Persist the user's default run count and selected paradigms."""
    runs = int(runs)
    if runs not in {1, 3, 5}:
        raise ValueError("Default runs must be 1, 3, or 5.")
    cleaned = []
    for paradigm in paradigms:
        key = str(paradigm).strip()
        if key and key not in cleaned:
            cleaned.append(key)
    if not cleaned:
        raise ValueError("Choose at least one default paradigm.")

    config = load_config()
    config["default_runs"] = runs
    config["default_paradigms"] = cleaned
    save_config(config)


def get_theme_preference() -> str:
    value = str(load_config().get("theme", _DEFAULT_UI_STATE["theme"])).strip().lower()
    return value if value in {"system", "light", "dark"} else "system"


def set_theme_preference(theme: str) -> None:
    value = (theme or "system").strip().lower()
    if value not in {"system", "light", "dark"}:
        raise ValueError("Theme must be system, light, or dark.")
    config = load_config()
    config["theme"] = value
    save_config(config)


def get_ui_state() -> dict:
    """Return validated persistent desktop UI state."""
    config = load_config()

    search = str(config.get("recent_search", "") or "")
    recent_format = str(config.get("recent_format", "all") or "all")
    recent_winner = str(config.get("recent_winner", "all") or "all")
    recent_sort = str(config.get("recent_sort", "newest") or "newest")

    if recent_format not in {"all", "LD", "PF", "Worlds", "Congress", "Parli"}:
        recent_format = "all"
    if recent_winner not in {"all", "AFF", "NEG", "split"}:
        recent_winner = "all"
    if recent_sort not in {"newest", "oldest", "aff", "neg", "resolution", "result"}:
        recent_sort = "newest"

    geometry = config.get("window_geometry")
    if (
        not isinstance(geometry, list)
        or len(geometry) != 4
        or not all(isinstance(value, int) for value in geometry)
    ):
        geometry = None

    return {
        "recent_search": search,
        "recent_format": recent_format,
        "recent_winner": recent_winner,
        "recent_sort": recent_sort,
        "window_geometry": geometry,
        "window_maximized": bool(config.get("window_maximized", False)),
    }


def set_ui_state(
    *,
    recent_search: str,
    recent_format: str,
    recent_winner: str,
    recent_sort: str,
    window_geometry: Optional[list[int]],
    window_maximized: bool,
) -> None:
    """Persist window/history state without touching API credentials."""
    config = load_config()
    config["recent_search"] = str(recent_search or "")
    config["recent_format"] = (
        recent_format
        if recent_format in {"all", "LD", "PF", "Worlds", "Congress", "Parli"}
        else "all"
    )
    config["recent_winner"] = (
        recent_winner if recent_winner in {"all", "AFF", "NEG", "split"} else "all"
    )
    config["recent_sort"] = (
        recent_sort
        if recent_sort in {"newest", "oldest", "aff", "neg", "resolution", "result"}
        else "newest"
    )
    if (
        isinstance(window_geometry, list)
        and len(window_geometry) == 4
        and all(isinstance(value, int) for value in window_geometry)
    ):
        config["window_geometry"] = window_geometry
    else:
        config.pop("window_geometry", None)
    config["window_maximized"] = bool(window_maximized)
    save_config(config)


def is_onboarding_complete() -> bool:
    return bool(load_config().get("onboarding_complete", False))


def set_onboarding_complete(complete: bool = True) -> None:
    config = load_config()
    config["onboarding_complete"] = bool(complete)
    save_config(config)


def load_into_environment() -> None:
    """Restore saved keys/preferences/models without overriding explicit env values."""
    config = load_config()
    for provider, env_var in _PROVIDER_ENV.items():
        saved = config.get(f"{provider}_api_key")
        if saved and not os.environ.get(env_var):
            os.environ[env_var] = saved

    for provider, env_var in _MODEL_ENV.items():
        saved = config.get(f"{provider}_model")
        if saved and not os.environ.get(env_var):
            os.environ[env_var] = saved

    if not os.environ.get("LLM_PROVIDER"):
        pref = (config.get("provider_preference") or "auto").lower()
        if pref != "auto":
            os.environ["LLM_PROVIDER"] = pref


def get_available_providers() -> list[str]:
    providers = []
    if get_api_key("anthropic"):
        providers.append("Anthropic API")
    if get_api_key("openai"):
        providers.append("OpenAI API")
    return providers
