import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.main import (
    _make_client,
    _normalize_evaluation_response,
    check_ollama_ready,
    fixer_node,
    stream_validation_graph,
)
from src.utils.llm_client import CancellationToken, GenerationCancelledError, OllamaClient
from src.utils.prompt_loader import PromptLoader
from web_ui.app import app


class TestRunInspectionRoute(unittest.TestCase):
    def setUp(self):
        self.input_dir = tempfile.TemporaryDirectory()
        self.logs_dir = tempfile.TemporaryDirectory()
        self.client = app.test_client()
        self.input_path_patch = patch(
            "web_ui.app.get_input_path", return_value=self.input_dir.name
        )
        self.logs_path_patch = patch("web_ui.app.LOGS_DIR", self.logs_dir.name)
        self.run_graph_patch = patch("web_ui.app.run_validation_graph")
        self.input_path_patch.start()
        self.logs_path_patch.start()
        self.run_graph = self.run_graph_patch.start()

    def tearDown(self):
        self.run_graph_patch.stop()
        self.logs_path_patch.stop()
        self.input_path_patch.stop()
        self.input_dir.cleanup()
        self.logs_dir.cleanup()

    def test_empty_input_folder_returns_empty_status(self):
        response = self.client.post("/api/run")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "empty")
        self.run_graph.assert_not_called()
        self.assertEqual(list(Path(self.logs_dir.name).iterdir()), [])

    def test_txt_files_are_processed_and_summary_is_saved(self):
        input_file = Path(self.input_dir.name) / "mock_logs.txt"
        input_file.write_text("ERROR: Could not find element: #submit", encoding="utf-8")
        self.run_graph.return_value = {
            "success": True,
            "data": {
                "detected_anomalies": [{
                    "id": "ERR_ELEMENT_NOT_FOUND_1",
                    "description": "Missing submit button",
                    "file_path": str(input_file),
                }],
                "evaluation_metrics": {
                    "evaluations": [{
                        "anomaly_id": "ERR_ELEMENT_NOT_FOUND_1",
                        "classification": "FLAKY_SELECTOR",
                        "reasoning": "The selector is unstable.",
                        "needs_fix": True,
                        "recommendation": "Use a stable data attribute.",
                    }]
                },
                "needs_fix": True,
                "fix_suggestion": "[data-testid='submit-button']",
            },
        }

        response = self.client.post("/api/run")
        result = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["files_processed"], 1)
        self.run_graph.assert_called_once_with(
            "ERROR: Could not find element: #submit", file_path=str(input_file)
        )

        self.assertRegex(
            result["filename"], r"^verification_summary_\d{8}_\d{6}\.json$"
        )
        saved_summary = json.loads(
            (Path(self.logs_dir.name) / result["filename"]).read_text(encoding="utf-8")
        )
        file_block = saved_summary[0]
        self.assertEqual(file_block["file_name"], "mock_logs.txt")
        self.assertEqual(file_block["framework"], "Unknown")
        self.assertEqual(file_block["framework_type"], "Unknown")
        self.assertEqual(file_block["anomaly_count"], 1)
        anomaly = file_block["anomalies"][0]
        self.assertEqual(anomaly["id"], "ERR_ELEMENT_NOT_FOUND_1")
        self.assertEqual(anomaly["status"], "fix_suggested")
        self.assertFalse(anomaly["corrected"])
        self.assertTrue(anomaly["needs_fix"])
        self.assertEqual(
            anomaly["evaluation"]["classification"], "FLAKY_SELECTOR"
        )
        self.assertEqual(
            anomaly["fix_suggestion"], "[data-testid='submit-button']"
        )

    def test_multiple_log_files_are_validated_independently(self):
        first_path = Path(self.input_dir.name) / "cypress_javascript.txt"
        second_path = Path(self.input_dir.name) / "playwright_python.txt"
        first_path.write_text("Framework: Cypress\nLanguage: JavaScript", encoding="utf-8")
        second_path.write_text("Framework: Playwright\nLanguage: Python", encoding="utf-8")
        self.run_graph.side_effect = [
            {"success": True, "data": {
                "detected_anomalies": [], "framework": "Cypress", "language": "JavaScript"
            }},
            {"success": True, "data": {"detected_anomalies": []}},
        ]

        response = self.client.post("/api/run")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["files_processed"], 2)
        self.assertEqual(self.run_graph.call_count, 2)
        self.assertEqual(
            [call.kwargs["file_path"] for call in self.run_graph.call_args_list],
            [str(first_path), str(second_path)],
        )
        result_filename = response.get_json()["filename"]
        file_blocks = json.loads(
            (Path(self.logs_dir.name) / result_filename).read_text(encoding="utf-8")
        )
        self.assertEqual(
            [
                (block["file_name"], block["framework"], block["framework_type"])
                for block in file_blocks
            ],
            [
                (first_path.name, "Cypress", "Cypress"),
                (second_path.name, "Playwright", "Playwright"),
            ],
        )
        self.assertTrue(all(block["anomalies"] == [] for block in file_blocks))


class TestConfigurationRoutes(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.config = {
            "ai": {"preferred_model": "ollama"},
            "ollama": {"host": "http://localhost:11434", "model": "qwen3.5:9b"},
            "files": {"input_path": "data/fixtures"},
            "prompts": {},
        }

    def test_ollama_settings_are_loaded_from_config(self):
        with patch("web_ui.app.load_config", return_value=self.config):
            response = self.client.get("/api/config/ollama")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["preferred_model"], "ollama")
        self.assertEqual(response.get_json()["model"], "qwen3.5:9b")

    def test_selected_preferred_model_is_saved_to_config(self):
        with patch("web_ui.app.load_config", return_value=self.config), patch(
            "web_ui.app.save_config"
        ) as save_config:
            response = self.client.post(
                "/api/config/ollama",
                json={
                    "preferred_model": "ollama",
                    "host": "http://localhost:11434",
                    "model": "qwen3.5:9b",
                },
            )

        self.assertEqual(response.status_code, 200)
        saved = save_config.call_args.args[0]
        self.assertEqual(saved["ai"]["preferred_model"], "ollama")
        self.assertEqual(saved["ollama"]["model"], "qwen3.5:9b")

    def test_unintegrated_provider_cannot_be_saved(self):
        with patch("web_ui.app.load_config", return_value=self.config), patch(
            "web_ui.app.save_config"
        ) as save_config:
            response = self.client.post(
                "/api/config/ollama", json={"preferred_model": "gpt-4o"}
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Ollama", response.get_json()["error"])
        save_config.assert_not_called()

    def test_prompt_routes_use_configured_prompt_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "custom_evaluator.txt"
            prompt_path.write_text("configured prompt", encoding="utf-8")
            with patch(
                "web_ui.app.get_prompt_path", return_value=str(prompt_path)
            ):
                response = self.client.get("/api/prompts")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["evaluator"], "configured prompt")


class TestLogsPaginationRoute(unittest.TestCase):
    def test_logs_are_returned_in_pages_of_five(self):
        with tempfile.TemporaryDirectory() as logs_dir:
            for index in range(12):
                log_path = Path(logs_dir) / f"log-{index:02}.json"
                log_path.write_text("[]", encoding="utf-8")
                os.utime(log_path, (index, index))

            client = app.test_client()
            with patch("web_ui.app.LOGS_DIR", logs_dir):
                first_page = client.get("/api/logs?page=1").get_json()
                second_page = client.get("/api/logs?page=2").get_json()
                third_page = client.get("/api/logs?page=3").get_json()

        self.assertEqual(first_page["total"], 12)
        self.assertEqual(first_page["page_size"], 5)
        self.assertTrue(first_page["has_more"])
        self.assertEqual(len(first_page["logs"]), 5)
        self.assertEqual(len(second_page["logs"]), 5)
        self.assertEqual(len(third_page["logs"]), 2)
        self.assertFalse(third_page["has_more"])
        self.assertEqual(
            [log["filename"] for log in first_page["logs"]],
            [f"log-{index:02}.json" for index in range(11, 6, -1)],
        )


class TestRuntimeConfiguration(unittest.TestCase):
    def test_ollama_client_uses_configured_host_and_model(self):
        config = {
            "ai": {"preferred_model": "ollama"},
            "ollama": {"host": "http://localhost:11434", "model": "configured:7b"},
        }
        with patch("src.main.load_config", return_value=config), patch(
            "src.main.OllamaClient"
        ) as client_factory:
            client_factory.return_value.list_models.return_value = ["configured:7b"]

            client = _make_client()

        client_factory.assert_called_once_with(
            model="configured:7b", base_url="http://localhost:11434"
        )
        self.assertEqual(client.model, "configured:7b")

    def test_prompt_loader_uses_configured_file_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "custom_prompt.txt"
            prompt_path.write_text("configured prompt content", encoding="utf-8")
            with patch(
                "src.utils.prompt_loader.get_prompt_path", return_value=str(prompt_path)
            ):
                prompt = PromptLoader.get_prompt("evaluator")

        self.assertTrue(prompt.startswith("configured prompt content"))
        self.assertIn("Framework: Unknown", prompt)
        self.assertIn("Language: Unknown", prompt)

    def test_prompt_loader_appends_detected_technology(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = Path(temp_dir) / "custom_prompt.txt"
            prompt_path.write_text("English base prompt", encoding="utf-8")
            with patch(
                "src.utils.prompt_loader.get_prompt_path", return_value=str(prompt_path)
            ):
                prompt = PromptLoader.get_prompt("fixer", "Playwright", "Python")

        self.assertIn("Framework: Playwright", prompt)
        self.assertIn("Language: Python", prompt)
        self.assertIn("English base prompt", prompt)

    def test_unintegrated_preferred_provider_fails_explicitly(self):
        config = {
            "ai": {"preferred_model": "gpt-4o"},
            "ollama": {"host": "http://localhost:11434", "model": "configured:7b"},
        }
        with patch("src.main.load_config", return_value=config):
            with self.assertRaisesRegex(ValueError, "not integrated"):
                _make_client()


class TestPromptSafety(unittest.TestCase):
    def test_evaluator_classification_determines_needs_fix(self):
        response, consistent = _normalize_evaluation_response({
            "anomaly_id": "wrong-model-id",
            "classification": "LOGIC_OR_STATE_ERROR",
            "reasoning": "Business state mismatch.",
            "needs_fix": True,
            "recommendation": "Review the expected state.",
        }, "anomaly-1")

        self.assertEqual(response["anomaly_id"], "anomaly-1")
        self.assertFalse(response["needs_fix"])
        self.assertFalse(consistent)

    def test_invalid_evaluator_response_fails_closed(self):
        response, consistent = _normalize_evaluation_response(
            {"classification": "UNKNOWN", "needs_fix": True}, "anomaly-2"
        )

        self.assertEqual(response["classification"], "UNCLASSIFIED")
        self.assertFalse(response["needs_fix"])
        self.assertFalse(consistent)

    def test_evaluator_response_requires_json_boolean(self):
        response, consistent = _normalize_evaluation_response({
            "anomaly_id": "anomaly-3",
            "classification": "FLAKY_SELECTOR",
            "reasoning": "The locator is unstable.",
            "needs_fix": "true",
            "recommendation": "Use a stable locator.",
        }, "anomaly-3")

        self.assertEqual(response["classification"], "UNCLASSIFIED")
        self.assertFalse(response["needs_fix"])
        self.assertFalse(consistent)

    def test_parser_evidence_overrides_contradictory_evaluator_classification(self):
        infra_response, infra_consistent = _normalize_evaluation_response({
            "anomaly_id": "timeout-1",
            "classification": "FLAKY_SELECTOR",
            "reasoning": "The model guessed a selector issue.",
            "needs_fix": True,
            "recommendation": "Change the locator.",
        }, "timeout-1", error_type="INFRA_FAILURE", flakiness_score=0.8)
        ambiguous_response, ambiguous_consistent = _normalize_evaluation_response({
            "anomaly_id": "ambiguous-1",
            "classification": "LOGIC_OR_STATE_ERROR",
            "reasoning": "The model ignored explicit ambiguity.",
            "needs_fix": False,
            "recommendation": "Review application state.",
        }, "ambiguous-1", error_type="AMBIGUOUS_SELECTOR", flakiness_score=0.1)
        unknown_timeout, timeout_consistent = _normalize_evaluation_response({
            "anomaly_id": "unknown-timeout-1",
            "classification": "FLAKY_SELECTOR",
            "reasoning": "The model guessed a timeout cause.",
            "needs_fix": True,
            "recommendation": "Add a wait.",
        }, "unknown-timeout-1", error_type="UNKNOWN_TIMEOUT", flakiness_score=0.8)
        low_flakiness, low_flakiness_consistent = _normalize_evaluation_response({
            "anomaly_id": "element-1",
            "classification": "FLAKY_SELECTOR",
            "reasoning": "The model ignored the low score.",
            "needs_fix": True,
            "recommendation": "Change the locator.",
        }, "element-1", error_type="ELEMENT_NOT_FOUND", flakiness_score=0.4)

        self.assertEqual(infra_response["classification"], "INFRA_FAILURE")
        self.assertFalse(infra_response["needs_fix"])
        self.assertFalse(infra_consistent)
        self.assertEqual(ambiguous_response["classification"], "ERR_AMBIGUOUS_SELECTOR")
        self.assertTrue(ambiguous_response["needs_fix"])
        self.assertFalse(ambiguous_consistent)
        self.assertEqual(unknown_timeout["classification"], "UNCLASSIFIED")
        self.assertFalse(unknown_timeout["needs_fix"])
        self.assertFalse(timeout_consistent)
        self.assertEqual(low_flakiness["classification"], "LOGIC_OR_STATE_ERROR")
        self.assertFalse(low_flakiness["needs_fix"])
        self.assertFalse(low_flakiness_consistent)

    def test_fixer_receives_only_validated_fixable_anomalies(self):
        client = Mock()
        client.generate_response.return_value = "NO_SAFE_FIX"
        state = {
            "detected_anomalies": [
                {
                    "id": "fixable-1",
                    "description": "Element not found",
                    "error_type": "ELEMENT_NOT_FOUND",
                    "selector_affected": "#submit",
                },
                {
                    "id": "infra-1",
                    "description": "HTTP 503 Service Unavailable",
                    "error_type": "INFRA_FAILURE",
                    "selector_affected": None,
                },
            ],
            "evaluation_metrics": {"evaluations": [
                {
                    "anomaly_id": "fixable-1",
                    "classification": "FLAKY_SELECTOR",
                    "reasoning": "The locator failed intermittently.",
                    "needs_fix": True,
                    "recommendation": "Use a stable test id.",
                },
                {
                    "anomaly_id": "infra-1",
                    "classification": "INFRA_FAILURE",
                    "reasoning": "The server returned 503.",
                    "needs_fix": False,
                    "recommendation": "Check service availability.",
                },
            ]},
            "execution_history": [],
            "source_code": None,
            "current_file_path": None,
            "framework": "Selenium",
            "language": "Python",
        }

        with patch("src.main._make_client", return_value=client):
            result = fixer_node(state)

        prompt = client.generate_response.call_args.args[0]
        self.assertIn("Anomaly ID: fixable-1", prompt)
        self.assertIn("Use a stable test id.", prompt)
        self.assertNotIn("Anomaly ID: infra-1", prompt)
        self.assertEqual(result["fix_suggestion"], "")


class TestOllamaCancellation(unittest.TestCase):
    def test_cancellation_token_closes_active_response(self):
        token = CancellationToken()
        response = Mock()
        token.attach_response(response)

        token.cancel()

        self.assertTrue(token.cancelled)
        response.close.assert_called()
        with self.assertRaises(GenerationCancelledError):
            token.raise_if_cancelled()

    def test_cancelled_generation_raises_instead_of_returning_partial_text(self):
        token = CancellationToken()
        response = Mock()

        def response_lines():
            yield b'{"response":"partial","done":false}'
            token.cancel()
            yield b'{"response":"ignored","done":true}'

        response.iter_lines.side_effect = response_lines
        client = OllamaClient(
            model="test-model",
            base_url="http://localhost:11434",
            cancellation_token=token,
        )
        with patch("src.utils.llm_client.requests.post", return_value=response):
            with self.assertRaises(GenerationCancelledError):
                client.generate_response("test prompt")

        response.close.assert_called()


class TestRunCancellationRoutes(unittest.TestCase):
    def test_cancel_endpoint_marks_active_run(self):
        token = CancellationToken()
        with patch.dict("web_ui.app.active_runs", {"active-test-run": token}):
            response = app.test_client().post("/api/run-cancel/active-test-run")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(token.cancelled)

    def test_cancelled_stream_does_not_save_a_result_log(self):
        with tempfile.TemporaryDirectory() as input_dir, tempfile.TemporaryDirectory() as logs_dir:
            (Path(input_dir) / "mock_logs.txt").write_text("ERROR: test", encoding="utf-8")
            with patch("web_ui.app.get_input_path", return_value=input_dir), patch(
                "web_ui.app.LOGS_DIR", logs_dir
            ), patch("web_ui.app.check_ollama_ready", return_value={
                "host": "http://localhost:11434",
                "model": "test-model",
                "used_fallback": False,
            }), patch(
                "web_ui.app.stream_validation_graph",
                return_value=iter([{"type": "cancelled", "message": "Inspection stopped."}]),
            ):
                response = app.test_client().post("/api/run-stream")
                body = response.get_data(as_text=True)

            self.assertIn('"type": "cancelled"', body)
            self.assertEqual(list(Path(logs_dir).glob("*.json")), [])

    def test_ollama_readiness_resolves_configured_model(self):
        config = {
            "ai": {"preferred_model": "ollama"},
            "ollama": {"host": "http://localhost:11434", "model": "model-b"},
        }
        with patch("src.main.load_config", return_value=config), patch(
            "src.main.OllamaClient"
        ) as client_factory:
            client_factory.return_value.list_models.return_value = ["model-a", "model-b"]

            readiness = check_ollama_ready()

        self.assertEqual(readiness, {
            "host": "http://localhost:11434",
            "model": "model-b",
            "used_fallback": False,
        })

    def test_ollama_readiness_fails_when_no_models_respond(self):
        config = {
            "ai": {"preferred_model": "ollama"},
            "ollama": {"host": "http://localhost:11434", "model": "missing"},
        }
        with patch("src.main.load_config", return_value=config), patch(
            "src.main.OllamaClient"
        ) as client_factory:
            client_factory.return_value.list_models.return_value = []

            with self.assertRaisesRegex(RuntimeError, "did not respond"):
                check_ollama_ready()

    def test_graph_stream_reports_parser_evaluator_and_fixer(self):
        graph_states = [
            {
                "current_node": "parser",
                "detected_anomalies": [],
            },
            {
                "current_node": "parser",
                "detected_anomalies": [{"id": "anomaly-1"}],
            },
            {
                "current_node": "evaluator",
                "detected_anomalies": [{"id": "anomaly-1"}],
                "evaluation_metrics": {"evaluations": [{"needs_fix": True}]},
                "needs_fix": True,
            },
            {
                "current_node": "fixer",
                "detected_anomalies": [{"id": "anomaly-1"}],
                "execution_history": [],
                "needs_fix": True,
                "fix_suggestion": "Use a stable selector.",
            },
        ]
        with patch("src.main.GRAPH") as graph:
            graph.stream.return_value = iter(graph_states)

            events = list(stream_validation_graph("ERROR: selector not found"))

        messages = [event["message"] for event in events if event["type"] == "progress"]
        self.assertIn("[PARSER] Found 1 anomalie(s).", messages)
        self.assertIn("[EVALUATOR] Evaluating 1 anomalie(s) with Ollama...", messages)
        self.assertIn("[FIXER] Generating a correction suggestion with Ollama...", messages)
        self.assertTrue(events[-1]["success"])
        self.assertEqual(events[-1]["data"]["fix_suggestion"], "Use a stable selector.")

    def test_compiled_graph_streams_parser_and_evaluator_progress(self):
        client = unittest.mock.Mock()
        client.generate_json_response.return_value = {
            "anomaly_id": "ERR_ELEMENT_NOT_FOUND_1",
            "needs_fix": False,
            "classification": "LOGIC_OR_STATE_ERROR",
            "reasoning": "The failure is consistent.",
            "recommendation": "Review the expected application state.",
        }
        client.generate_response.return_value = "NO_SAFE_FIX"

        with patch("src.main._make_client", return_value=client):
            events = list(stream_validation_graph(
                "ERROR: Could not find element: #password-field"
            ))

        messages = [event["message"] for event in events if event["type"] == "progress"]
        self.assertTrue(any(message.startswith("[PARSER]") for message in messages))
        self.assertTrue(any(message.startswith("[EVALUATOR]") for message in messages))
        self.assertFalse(any("Found 0 anomalie(s)" in message for message in messages))
        self.assertTrue(events[-1]["success"])


class TestRunInspectionStreamRoute(unittest.TestCase):
    def test_streams_progress_and_saves_result_log(self):
        with tempfile.TemporaryDirectory() as input_dir, tempfile.TemporaryDirectory() as logs_dir:
            input_file = Path(input_dir) / "mock_logs.txt"
            input_file.write_text("ERROR: selector not found", encoding="utf-8")
            graph_events = [
                {"type": "progress", "message": "[PARSER] Found 1 anomalie(s)."},
                {"type": "progress", "message": "[EVALUATOR] Evaluating 1 anomalie(s)."},
                {
                    "type": "result",
                    "success": True,
                    "data": {
                        "detected_anomalies": [{
                            "id": "anomaly-1",
                            "description": "Selector not found",
                            "file_path": str(input_file),
                        }]
                    },
                },
            ]
            with patch("web_ui.app.get_input_path", return_value=input_dir), patch(
                "web_ui.app.LOGS_DIR", logs_dir
            ), patch("web_ui.app.check_ollama_ready", return_value={
                "host": "http://localhost:11434",
                "model": "configured:7b",
                "used_fallback": False,
            }), patch("web_ui.app.stream_validation_graph", return_value=iter(graph_events)):
                response = app.test_client().post("/api/run-stream")
                body = response.get_data(as_text=True)
                events = [
                    json.loads(line[6:])
                    for line in body.splitlines()
                    if line.startswith("data: ")
                ]
                complete = next(event for event in events if event["type"] == "complete")
                saved_exists = (Path(logs_dir) / complete["filename"]).is_file()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/event-stream")
        self.assertTrue(any("[READ] Loading file 1/1" in event.get("message", "") for event in events))
        ready_index = next(
            index for index, event in enumerate(events)
            if "Ollama Ready" in event.get("message", "")
        )
        parser_index = next(
            index for index, event in enumerate(events)
            if "[PARSER]" in event.get("message", "")
        )
        self.assertLess(ready_index, parser_index)
        self.assertTrue(any("[PARSER] Found 1" in event.get("message", "") for event in events))
        self.assertEqual(complete["files_processed"], 1)
        self.assertTrue(saved_exists)

    def test_stream_processes_each_framework_fixture_separately(self):
        with tempfile.TemporaryDirectory() as input_dir, tempfile.TemporaryDirectory() as logs_dir:
            first_path = Path(input_dir) / "cypress_javascript.txt"
            second_path = Path(input_dir) / "selenium_java.txt"
            first_path.write_text("Framework: Cypress", encoding="utf-8")
            second_path.write_text("Framework: Selenium", encoding="utf-8")
            result_event = {"type": "result", "success": True}
            first_result = {
                **result_event,
                "data": {
                    "detected_anomalies": [],
                    "framework": "Cypress",
                    "language": "JavaScript",
                },
            }
            second_result = {
                **result_event,
                "data": {
                    "detected_anomalies": [],
                    "framework": "Selenium",
                    "language": "Java",
                },
            }
            with patch("web_ui.app.get_input_path", return_value=input_dir), patch(
                "web_ui.app.LOGS_DIR", logs_dir
            ), patch("web_ui.app.check_ollama_ready", return_value={
                "host": "http://localhost:11434",
                "model": "test-model",
                "used_fallback": False,
            }), patch(
                "web_ui.app.stream_validation_graph",
                side_effect=[iter([first_result]), iter([second_result])],
            ) as graph_stream:
                response = app.test_client().post("/api/run-stream")
                events = [
                    json.loads(line[6:])
                    for line in response.get_data(as_text=True).splitlines()
                    if line.startswith("data: ")
                ]
                completion = next(
                    event for event in events if event["type"] == "complete"
                )
                saved_blocks = json.loads(
                    (Path(logs_dir) / completion["filename"]).read_text(encoding="utf-8")
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(graph_stream.call_count, 2)
        processing_messages = [
            event["message"] for event in events
            if event.get("message", "").startswith("[PARSER] Processing")
        ]
        self.assertIn(
            "[PARSER] Processing 1/2: cypress_javascript.txt | Framework detected: Cypress.",
            processing_messages,
        )
        self.assertIn(
            "[PARSER] Processing 2/2: selenium_java.txt | Framework detected: Selenium.",
            processing_messages,
        )
        self.assertEqual(
            [call.kwargs["file_path"] for call in graph_stream.call_args_list],
            [str(first_path), str(second_path)],
        )
        self.assertEqual(
            next(event for event in events if event["type"] == "complete")["files_processed"],
            2,
        )
        self.assertEqual(
            [(block["file_name"], block["framework"]) for block in saved_blocks],
            [(first_path.name, "Cypress"), (second_path.name, "Selenium")],
        )

    def test_unready_ollama_prevents_sending_input_to_graph(self):
        with tempfile.TemporaryDirectory() as input_dir, tempfile.TemporaryDirectory() as logs_dir:
            (Path(input_dir) / "mock_logs.txt").write_text("ERROR: test", encoding="utf-8")
            with patch("web_ui.app.get_input_path", return_value=input_dir), patch(
                "web_ui.app.LOGS_DIR", logs_dir
            ), patch(
                "web_ui.app.check_ollama_ready", side_effect=RuntimeError("Ollama offline")
            ), patch("web_ui.app.stream_validation_graph") as graph_stream:
                response = app.test_client().post("/api/run-stream")
                events = [
                    json.loads(line[6:])
                    for line in response.get_data(as_text=True).splitlines()
                    if line.startswith("data: ")
                ]

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("Checking if Ollama is responding" in event.get("message", "") for event in events))
        self.assertTrue(any("Not ready. Input was not sent" in event.get("message", "") for event in events))
        graph_stream.assert_not_called()


if __name__ == "__main__":
    unittest.main()