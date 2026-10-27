"""
Application configuration manager.

All runtime settings (Ollama connection, selected model, prompt files and
the folder containing the Cypress logs to be analyzed) are persisted in
``conf/config.json`` so the user can change them from the web UI without
touching the code.
"""

import json
import os
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
    "prompts": {
        "evaluator": "src/agents/prompts/evaluator_prompt.txt",
        "fixer": "src/agents/prompts/fixer_prompt.txt",
    },
}

# Lock to avoid concurrent writes when several requests hit the API at once
_lock = threading.Lock()


def _normalize(config: dict) -> dict:
    """Merge a partial config over the defaults and return a complete dict."""
    result = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    for section, values in (config or {}).items():
        if isinstance(values, dict) and isinstance(result.get(section), dict):
            result[section].update(values)
    return result


def load_config() -> dict:
    """Load the configuration from conf/config.json (creates it if missing)."""
    with _lock:
        if not os.path.exists(CONF_FILE):
            save_config(DEFAULT_CONFIG)
            return json.loads(json.dumps(DEFAULT_CONFIG))
        try:
            with open(CONF_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return _normalize(raw)
        except (json.JSONDecodeError, OSError):
            # Corrupted or unreadable file: fall back to defaults
            return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(config: dict) -> dict:
    """Persist the given configuration into conf/config.json."""
    normalized = _normalize(config)
    with _lock:
        os.makedirs(CONF_DIR, exist_ok=True)
        with open(CONF_FILE, "w", encoding="utf-8") as f:
            json.dump(normalized, f, indent=4, ensure_ascii=False)
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
