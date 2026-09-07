import importlib.util
import unittest
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "evaluators" / "document-probe-contract" / "1" / "evaluate.py"
SPEC = importlib.util.spec_from_file_location("document_probe_evaluator", MODULE)
EVALUATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(EVALUATOR)


def valid_report():
    return {
        "schema_version": 2,
        "tool_version": "test",
        "status": "ok",
        "input": {},
        "driver": {"id": "powerpoint", "profile": "pptx"},
        "results": {
            "powerpoint.slide_count": {
                "target": "powerpoint.slide_count",
                "status": "resolved",
                "value": 16,
                "confidence": "exact",
                "confidence_score": 1.0,
                "path": "powerpoint.presentation_xml",
                "source": "ppt/presentation.xml",
            }
        },
        "execution": {
            "actual_cost": {"physical_bytes_read": 100, "expanded_bytes": 200, "random_reads": 2},
            "unresolved_targets": [],
        },
        "diagnostics": [],
    }


class EvaluatorTests(unittest.TestCase):
    def test_positive_contract_and_fact(self):
        report = valid_report()
        contract = EVALUATOR.run_check({"id": "contract", "type": "probe_contract"}, report, {"exitCode": 0})
        fact = EVALUATOR.run_check({"id": "slides", "type": "target_equals", "target": "powerpoint.slide_count", "expected": 16}, report, {"exitCode": 0})
        self.assertEqual(contract["status"], "passed", contract)
        self.assertEqual(fact["status"], "passed", fact)

    def test_rejects_evidence_and_status_inconsistency(self):
        report = valid_report()
        report["results"]["powerpoint.slide_count"].pop("source")
        report["status"] = "partial"
        result = EVALUATOR.run_check({"id": "contract", "type": "probe_contract"}, report, {"exitCode": 0})
        self.assertEqual(result["status"], "failed")
        self.assertGreaterEqual(len(result["actual"]["issues"]), 2)

    def test_error_contract_requires_exit_code_agreement(self):
        report = {"schema_version": 2, "tool_version": "test", "status": "error", "error": {"code": "BUDGET_EXCEEDED", "exit_code": 4}}
        passed = EVALUATOR.run_check({"id": "contract", "type": "probe_contract"}, report, {"exitCode": 4})
        failed = EVALUATOR.run_check({"id": "contract", "type": "probe_contract"}, report, {"exitCode": 0})
        self.assertEqual(passed["status"], "passed")
        self.assertEqual(failed["status"], "failed")

    def test_cost_boundary_is_inclusive(self):
        report = valid_report()
        check = {"id": "cost", "type": "cost_ceiling", "expected": {"physical_bytes_read": 100}}
        self.assertEqual(EVALUATOR.run_check(check, report, {"exitCode": 0})["status"], "passed")
        report["execution"]["actual_cost"]["physical_bytes_read"] = 101
        self.assertEqual(EVALUATOR.run_check(check, report, {"exitCode": 0})["status"], "failed")

    def test_probe_observation_never_becomes_a_gate(self):
        report = valid_report()
        result = EVALUATOR.run_check(
            {"id": "observe", "type": "probe_observation", "target": "powerpoint.slide_count"},
            report,
            {"exitCode": 0},
        )
        self.assertEqual(result["status"], "review")
        self.assertFalse(result["required"])
        self.assertFalse(result["finding"])
        self.assertEqual(result["actual"]["targetResult"]["value"], 16)

    def test_target_status_can_define_an_honest_capability_boundary(self):
        report = valid_report()
        report["results"]["powerpoint.slide_count"] = {
            "target": "powerpoint.slide_count",
            "status": "unknown",
            "confidence": "none",
            "confidence_score": 0.0,
            "path": "legacy.powerpoint_document",
            "source": "PowerPoint Document",
        }
        check = {"id": "boundary", "type": "target_status_equals", "target": "powerpoint.slide_count", "expected": "unknown"}
        self.assertEqual(EVALUATOR.run_check(check, report, {"exitCode": 0})["status"], "passed")


if __name__ == "__main__":
    unittest.main()
