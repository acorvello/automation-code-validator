import unittest
from unittest.mock import Mock, patch

import requests

from src.utils.llm_client import (
    OllamaClient,
    OllamaConnectionError,
    OllamaOutputError,
)


class TestOllamaClientErrors(unittest.TestCase):
    def setUp(self):
        self.client = OllamaClient(
            model="test-model",
            base_url="http://localhost:11434",
        )

    def test_generation_connection_failure_is_reported(self):
        with patch(
            "src.utils.llm_client.requests.post",
            side_effect=requests.ConnectionError("connection refused"),
        ):
            with self.assertRaisesRegex(OllamaConnectionError, "connection refused"):
                self.client.generate_response("test prompt")

    def test_generation_rejects_malformed_api_response(self):
        response = Mock()
        response.json.side_effect = ValueError("invalid JSON")
        with patch("src.utils.llm_client.requests.post", return_value=response):
            with self.assertRaisesRegex(OllamaConnectionError, "non-JSON"):
                self.client.generate_response("test prompt")

    def test_json_generation_rejects_invalid_model_output(self):
        with patch.object(self.client, "generate_response", return_value="not json"):
            with self.assertRaises(OllamaOutputError):
                self.client.generate_json_response("test prompt")

    def test_json_generation_requires_an_object(self):
        with patch.object(self.client, "generate_response", return_value="[1, 2]"):
            with self.assertRaisesRegex(OllamaOutputError, "JSON object"):
                self.client.generate_json_response("test prompt")

    def test_json_generation_accepts_json_fenced_output(self):
        with patch.object(
            self.client,
            "generate_response",
            return_value='```json\n{"result": "ok"}\n```',
        ):
            self.assertEqual(
                self.client.generate_json_response("test prompt"),
                {"result": "ok"},
            )

    def test_model_listing_connection_failure_is_reported(self):
        with patch(
            "src.utils.llm_client.requests.get",
            side_effect=requests.ConnectionError("Ollama is offline"),
        ):
            with self.assertRaisesRegex(OllamaConnectionError, "Ollama is offline"):
                self.client.list_models()

    def test_model_listing_rejects_invalid_payload(self):
        response = Mock()
        response.json.return_value = {"models": "not-a-list"}
        with patch("src.utils.llm_client.requests.get", return_value=response):
            with self.assertRaisesRegex(OllamaConnectionError, "invalid response"):
                self.client.list_models()


if __name__ == "__main__":
    unittest.main()
