import unittest
from pathlib import Path
from src.agents.nodes.parser import parse_logs_node
from src.core.state import GraphState
from src.utils.log_parser import LogParser
from src.utils.technology_detector import detect_technology


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "data" / "fixtures"

class TestParserNode(unittest.TestCase):
    def test_parse_logs_success(self):
        # Setup
        initial_state: GraphState = {
            "raw_cypress_logs": "ERROR: Timed out after 30000ms\nERROR: Could not find element: #password-field",
            "detected_anomalies": [],
            "evaluation_metrics": {},
            "retry_count": 0,
            "current_node": "start",
            "fix_suggestion": None
        }
        
        # Execute
        result = parse_logs_node(initial_state)
        
        # Assert
        self.assertEqual(len(result["detected_anomalies"]), 2)
        self.assertEqual(result["current_node"], "parser")
        self.assertIn("robustness_score", result["evaluation_metrics"])

    def test_fixtures_detect_supported_framework_language_pairs(self):
        expected = {
            "cypress_javascript.txt": ("Cypress", "JavaScript"),
            "selenium_java.txt": ("Selenium", "Java"),
            "selenium_javascript.txt": ("Selenium", "JavaScript"),
            "selenium_python.txt": ("Selenium", "Python"),
            "playwright_java.txt": ("Playwright", "Java"),
            "playwright_javascript.txt": ("Playwright", "JavaScript"),
            "playwright_python.txt": ("Playwright", "Python"),
        }

        for filename, expected_stack in expected.items():
            with self.subTest(filename=filename):
                path = FIXTURE_DIR / filename
                logs = path.read_text(encoding="utf-8")
                self.assertEqual(detect_technology(logs), expected_stack)
                parsed_state = parse_logs_node({
                    "raw_cypress_logs": logs,
                    "current_file_path": None,
                    "source_code": None,
                })
                self.assertEqual(
                    (parsed_state["framework"], parsed_state["language"]),
                    expected_stack,
                )
                self.assertTrue(parsed_state["detected_anomalies"])
                self.assertEqual(
                    parsed_state["detected_anomalies"][0].file_path, None
                )

    def test_playwright_ambiguity_is_detected(self):
        logs = (FIXTURE_DIR / "playwright_javascript.txt").read_text(encoding="utf-8")

        anomalies = LogParser.parse(logs)

        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0].id.split("_")[1], "AMBIGUOUS")
        self.assertEqual(anomalies[0].selector_affected, "#login-submit")

    def test_timeout_types_require_evidence_before_becoming_selector_failures(self):
        infra_anomaly = LogParser.parse("ERROR: Connection timed out during request")[0]
        http_anomaly = LogParser.parse("HTTP/1.1 503 Service Unavailable")[0]
        not_found_anomaly = LogParser.parse("HTTP 404 Not Found")[0]
        element_anomaly = LogParser.parse(
            "Timed out retrying after 4000ms: cy.get('#submit')"
        )[0]
        interaction_anomaly = LogParser.parse("ElementNotInteractableException")[0]
        unknown_anomaly = LogParser.parse("Timed out after 30000ms")[0]

        self.assertEqual(infra_anomaly.error_type, "INFRA_FAILURE")
        self.assertEqual(infra_anomaly.flakiness_score, 0.0)
        self.assertEqual(http_anomaly.error_type, "INFRA_FAILURE")
        self.assertEqual(not_found_anomaly.error_type, "INFRA_FAILURE")
        self.assertEqual(element_anomaly.error_type, "ELEMENT_TIMEOUT")
        self.assertEqual(element_anomaly.flakiness_score, 0.8)
        self.assertEqual(interaction_anomaly.error_type, "ELEMENT_NOT_INTERACTABLE")
        self.assertEqual(interaction_anomaly.flakiness_score, 0.8)
        self.assertEqual(unknown_anomaly.error_type, "UNKNOWN_TIMEOUT")
        self.assertEqual(unknown_anomaly.flakiness_score, 0.0)

if __name__ == "__main__":
    unittest.main()
