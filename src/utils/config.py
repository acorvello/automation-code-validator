"""
Application configuration manager.

All runtime settings (Ollama connection, selected model, prompt files and
the folder containing the Cypress logs to be analyzed) are persisted in
``conf/config.json`` so the user can change them from the web UI without
touching the code.
"""

import json
import os
import shutil
import tempfile
import threading

# Project root (this file lives in <root>/src/utils/config.py)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Configuration folder and file
CONF_DIR = os.path.join(PROJECT_ROOT, "conf")
CONF_FILE = os.path.join(CONF_DIR, "config.json")

# Default values used when the file does not exist yet
DEFAULT_CONFIG = {
    "ai": {
        "preferred_model": "ollama",
    },
    "ollama": {
        "host": "http://localhost:11434",
        "model": "llama3.2",
    },
    "files": {
        "input_path": "data/fixtures",
    },
    "interface": {
        "theme": "system",
    },
    "prompts": {
        "evaluator": "src/agents/prompts/evaluator_prompt.txt",
        "fixer": "src/agents/prompts/fixer_prompt.txt",
    },
}

# Lock to avoid concurrent writes when several requests hit the API at once
_lock = threading.Lock()


class ConfigError(ValueError):
    """Base error for invalid or unreadable application configuration."""


class ConfigValidationError(ConfigError):
    """Raised when a configuration value has an unsupported shape or type."""


class ConfigLoadError(ConfigError):
    """Raised when the persisted configuration cannot be parsed or read."""


def _normalize(config: dict) -> dict:
    """Merge a partial config over the defaults and return a complete dict."""
    if not isinstance(config, dict):
        raise ConfigValidationError("Application configuration must be a JSON object.")

    result = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    for section, values in config.items():
        if section not in result:
            continue
        if not isinstance(values, dict):
            raise ConfigValidationError(
                f"Configuration section '{section}' must be an object."
            )
        result[section].update(values)

    for section, defaults in DEFAULT_CONFIG.items():
        for key in defaults:
            value = result[section][key]
            if not isinstance(value, str) or not value.strip():
                raise ConfigValidationError(
                    f"Configuration value '{section}.{key}' must be a non-empty string."
                )
    if result["interface"]["theme"] not in {"system", "light", "dark"}:
        raise ConfigValidationError(
            "Configuration value 'interface.theme' must be system, light, or dark."
        )
    return result


def _write_json_atomically(path: str, data: dict) -> None:
    """Write JSON in the destination directory, then atomically replace it."""
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=os.path.dirname(path),
            prefix=f".{os.path.basename(path)}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = temporary_file.name
            json.dump(data, temporary_file, indent=4, ensure_ascii=False)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _backup_existing_config() -> None:
    """Atomically preserve the current config before replacing it."""
    if not os.path.isfile(CONF_FILE):
        return

    backup_path = f"{CONF_FILE}.bak"
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=CONF_DIR,
            prefix=".config-backup.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = temporary_file.name
        shutil.copy2(CONF_FILE, temporary_path)
        os.replace(temporary_path, backup_path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def load_config() -> dict:
    """Load the configuration from conf/config.json (creates it if missing)."""
    with _lock:
        if not os.path.exists(CONF_FILE):
            normalized = _normalize(DEFAULT_CONFIG)
            os.makedirs(CONF_DIR, exist_ok=True)
            _write_json_atomically(CONF_FILE, normalized)
            return normalized
        try:
            with open(CONF_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return _normalize(raw)
        except (json.JSONDecodeError, OSError) as error:
            raise ConfigLoadError(
                f"Unable to read application configuration at {CONF_FILE}: {error}. "
                f"If available, restore {CONF_FILE}.bak."
            ) from error
        except ConfigValidationError as error:
            raise ConfigLoadError(
                f"Invalid application configuration at {CONF_FILE}: {error}. "
                f"If available, restore {CONF_FILE}.bak."
            ) from error


def save_config(config: dict) -> dict:
    """Persist the given configuration into conf/config.json."""
    normalized = _normalize(config)
    with _lock:
        os.makedirs(CONF_DIR, exist_ok=True)
        _backup_existing_config()
        _write_json_atomically(CONF_FILE, normalized)
    return normalized


def get_ollama_host() -> str:
    """Return the configured Ollama base URL."""
    return load_config()["ollama"]["host"]


def get_ollama_model() -> str:
    """Return the configured Ollama model name."""
    return load_config()["ollama"]["model"]


def get_input_path() -> str:
    """Return the absolute path of the folder with the Cypress logs to analyze."""
    cfg = load_config()
    raw = cfg["files"]["input_path"]
    path = raw if os.path.isabs(raw) else os.path.join(PROJECT_ROOT, raw)
    return os.path.abspath(path)


def get_prompt_path(name: str) -> str:
    """Return the absolute path of a prompt file (evaluator / fixer)."""
    cfg = load_config()
    raw = cfg["prompts"].get(name, f"src/agents/prompts/{name}_prompt.txt")
    path = raw if os.path.isabs(raw) else os.path.join(PROJECT_ROOT, raw)
    return os.path.abspath(path)
