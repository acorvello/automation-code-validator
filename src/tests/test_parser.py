import unittest
from src.agents.nodes.parser import parse_logs_node
from src.core.state import GraphState

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

if __name__ == "__main__":
    unittest.main()
