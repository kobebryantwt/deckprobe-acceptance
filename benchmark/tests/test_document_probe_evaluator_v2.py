import importlib.util
import unittest
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "evaluators" / "document-probe-contract" / "2" / "evaluate.py"
SPEC = importlib.util.spec_from_file_location("document_probe_evaluator_v2", MODULE)
EVALUATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(EVALUATOR)


def report(value=16):
    return {
        "schema_version": 2, "tool_version": "test", "status": "ok",
        "input": {}, "driver": {"id": "powerpoint", "profile": "pptx"},
        "results": {"powerpoint.slide_count": {
            "target": "powerpoint.slide_count", "status": "resolved", "value": value,
            "confidence": "exact", "confidence_score": 1.0,
            "path": "powerpoint.presentation_xml", "source": "ppt/presentation.xml",
        }},
        "execution": {"actual_cost": {"physical_bytes_read": 1, "expanded_bytes": 2, "random_reads": 1}, "unresolved_targets": []},
        "diagnostics": [],
    }


class EvaluatorV2Tests(unittest.TestCase):
    def test_scored_binary_check_emits_role_feature_weight_and_score(self):
        check = {
            "id": "slides", "type": "target_equals", "target": "powerpoint.slide_count", "expected": 16,
            "role": "scored", "featureId": "powerpoint.structure", "severity": "minor",
            "weight": 1.0, "scoreMode": "binary",
        }
        passed = EVALUATOR.run_check(check, report(), {"exitCode": 0})
        failed = EVALUATOR.run_check(check, report(15), {"exitCode": 0})
        self.assertEqual(passed["score"], 1.0)
        self.assertEqual(failed["score"], 0.0)
        self.assertEqual(passed["featureId"], "powerpoint.structure")
        self.assertEqual(passed["role"], "scored")

    def test_observation_never_emits_score_or_finding(self):
        check = {
            "id": "observe", "type": "probe_observation", "target": "powerpoint.slide_count",
            "role": "observation", "featureId": "planner.observation", "severity": "minor",
        }
        value = EVALUATOR.run_check(check, report(), {"exitCode": 0})
        self.assertEqual(value["role"], "observation")
        self.assertFalse(value["finding"])
        self.assertNotIn("score", value)


if __name__ == "__main__":
    unittest.main()
