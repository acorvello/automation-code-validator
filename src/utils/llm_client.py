import json
import os
import threading
from typing import Optional

import requests

from src.utils.config import get_ollama_host, get_ollama_model


class GenerationCancelledError(Exception):
    """Raised when an active Ollama generation is cancelled by the user."""


class OllamaConnectionError(RuntimeError):
    """Raised when Ollama cannot complete or return a valid API response."""


class OllamaOutputError(ValueError):
    """Raised when generated content does not match the requested format."""


class CancellationToken:
    """Thread-safe cancellation state that can close the active HTTP response."""

    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._response = None

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise GenerationCancelledError("Generation cancelled by user.")

    def attach_response(self, response) -> None:
        with self._lock:
            self._response = response
            should_close = self.cancelled
        if should_close:
            response.close()

    def detach_response(self, response) -> None:
        with self._lock:
            if self._response is response:
                self._response = None

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            response = self._response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass


class OllamaClient:
    """
    Client for communicating with a local Ollama server.

    The base URL and the model are read from the application configuration
    (``conf/config.json``). The environment variables ``OLLAMA_HOST`` and
    ``OLLAMA_MODEL`` still take precedence so the user can override the
    settings without editing the file.
    """

    def __init__(
        self,
        model: str = None,
        base_url: str = None,
        cancellation_token: Optional[CancellationToken] = None,
    ):
        base_url = base_url or self._env_host() or get_ollama_host()
        self.base_url = base_url.rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL") or get_ollama_model()
        self.cancellation_token = cancellation_token
        print(f"--- Using model: {self.model} at {self.base_url} ---")

    @staticmethod
    def _env_host() -> Optional[str]:
        """Return the ``OLLAMA_HOST`` env var only when it looks like a URL.

        A bare value (e.g. ``0.0.0.0``) usually means the variable was set
        for the Ollama *server* (listen address) and must not be used as the
        client base URL, so it is ignored in that case.
        """
        env_host = os.getenv("OLLAMA_HOST")
        if env_host and "://" in env_host:
            return env_host
        return None

    def generate_response(self, prompt: str) -> str:
        """
        Sends a prompt to Ollama and returns the response as text.
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",  # Force JSON output when the model supports it
        }

        # Timeout generoso: modelos de ~9B rodando em CPU (llamacpp) são lentos.
        # A chamada de "ok" simples levou ~40s, então 600s cobre prompts longos
        # de avaliação/correção sem estourar o read timeout.
        timeout = int(os.getenv("OLLAMA_TIMEOUT", "600"))

        if self.cancellation_token is not None:
            return self._generate_cancellable(payload, timeout)

        try:
            response = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=timeout)
            response.raise_for_status()
            try:
                result = response.json()
            except ValueError as error:
                raise OllamaConnectionError(
                    "Ollama returned a non-JSON response from /api/generate."
                ) from error
            if not isinstance(result, dict):
                raise OllamaConnectionError(
                    "Ollama returned an invalid response from /api/generate."
                )
            response_text = result.get("response")
            if not isinstance(response_text, str) or not response_text.strip():
                raise OllamaConnectionError(
                    "Ollama returned an empty generation response."
                )
            return response_text
        except requests.RequestException as error:
            raise OllamaConnectionError(
                f"Unable to generate a response with Ollama at {self.base_url}: {error}"
            ) from error

    def _generate_cancellable(self, payload: dict, timeout: int) -> str:
        response = None
        try:
            self.cancellation_token.raise_if_cancelled()
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={**payload, "stream": True},
                timeout=timeout,
                stream=True,
            )
            self.cancellation_token.attach_response(response)
            response.raise_for_status()

            response_parts = []
            for line in response.iter_lines():
                self.cancellation_token.raise_if_cancelled()
                if not line:
                    continue
                chunk = json.loads(line)
                text = chunk.get("response", "")
                if isinstance(text, str):
                    response_parts.append(text)
                if chunk.get("done"):
                    break

            self.cancellation_token.raise_if_cancelled()
            response_text = "".join(response_parts)
            if not response_text.strip():
                raise OllamaConnectionError(
                    "Ollama returned an empty generation response."
                )
            return response_text
        except GenerationCancelledError:
            raise
        except (requests.RequestException, ValueError) as error:
            if self.cancellation_token.cancelled:
                raise GenerationCancelledError("Generation cancelled by user.") from error
            raise OllamaConnectionError(
                f"Unable to generate a response with Ollama at {self.base_url}: {error}"
            ) from error
        finally:
            if response is not None:
                self.cancellation_token.detach_response(response)
                response.close()

    def generate_json_response(self, prompt: str) -> dict:
        """
        Sends a prompt and tries to return a parsed dictionary.
        """
        response_text = self.generate_response(prompt)
        try:
            result = json.loads(response_text)
        except json.JSONDecodeError:
            if "```json" in response_text:
                try:
                    cleaned_json = response_text.split("```json")[1].split("```")[0].strip()
                    result = json.loads(cleaned_json)
                except json.JSONDecodeError:
                    raise OllamaOutputError(
                        "Ollama returned invalid JSON for the requested structured output."
                    ) from None
            else:
                raise OllamaOutputError(
                    "Ollama returned invalid JSON for the requested structured output."
                ) from None
        if not isinstance(result, dict):
            raise OllamaOutputError(
                "Ollama structured output must be a JSON object."
            )
        return result

    def list_models(self) -> list[str]:
        """Return the names of the models installed on the Ollama server.

        Uses the ``/api/tags`` endpoint and raises a connection error if the
        server is unreachable or returns an invalid response.
        """
        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=10,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise OllamaConnectionError(
                f"Unable to list Ollama models at {self.base_url}: {error}"
            ) from error

        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            raise OllamaConnectionError(
                "Ollama returned an invalid response from /api/tags."
            )
        return [
            model["name"]
            for model in payload["models"]
            if isinstance(model, dict)
            and isinstance(model.get("name"), str)
            and model["name"]
        ]
