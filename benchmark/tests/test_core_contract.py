import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "benchmark" / "scripts" / "deck_benchmark.py"


def load_core():
    spec = importlib.util.spec_from_file_location("deck_benchmark_core", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CoreContractTest(unittest.TestCase):
    def test_version_contract(self):
        output = subprocess.check_output([sys.executable, str(SCRIPT), "version"], text=True, cwd=REPO)
        payload = json.loads(output)
        self.assertEqual(payload["benchmarkCoreVersion"], "2.1.0")
        self.assertEqual(payload["reportContractVersion"], "2")
        self.assertEqual(payload["contractId"], "deck-benchmark-core-v2")

    def test_legacy_required_maps_to_roles(self):
        core = load_core()
        self.assertEqual(core.check_role({"required": True}), "gate")
        self.assertEqual(core.check_role({"required": False}), "observation")
        self.assertEqual(core.check_role({"role": "scored", "required": True}), "scored")

    def test_quality_summary_separates_decision_and_observations(self):
        core = load_core()
        policy = {"qualityPolicy": {"version": "1", "reviewStatus": "approved", "scoring": {
            "aggregation": "macro_feature", "scale": 100, "passThreshold": 95,
            "reviewThreshold": 80,
        }}}
        results = [{"caseId": "case", "status": "failed", "assertions": [
            {"id": "gate", "status": "failed", "role": "gate"},
            {"id": "observe", "status": "review", "role": "observation", "finding": False},
        ]}]
        cases = [{"id": "case", "evaluation": {"checks": [
            {"id": "gate", "role": "gate"},
            {"id": "observe", "role": "observation"},
        ]}}]
        summary = core.summarize_quality(results, cases, policy, "specialized")
        self.assertEqual(summary["releaseDecision"], "FAIL")
        self.assertEqual(summary["gate"]["failed"], 1)
        self.assertEqual(summary["observation"]["totalChecks"], 1)

    def test_scoring_macro_averages_features_not_assertions(self):
        core = load_core()
        suite = {"qualityPolicy": {"version": "1", "reviewStatus": "approved", "scoring": {
            "aggregation": "macro_feature", "scale": 100, "passThreshold": 95,
            "reviewThreshold": 80,
        }}}
        checks = [
            {"id": "a1", "role": "scored", "featureId": "a", "weight": 1.0},
            {"id": "a2", "role": "scored", "featureId": "a", "weight": 1.0},
            {"id": "b1", "role": "scored", "featureId": "b", "weight": 1.0},
        ]
        assertions = [
            {**check, "status": "passed" if check["id"] != "b1" else "failed", "score": 1.0 if check["id"] != "b1" else 0.0}
            for check in checks
        ]
        summary = core.summarize_quality(
            [{"caseId": "case", "status": "review", "assertions": assertions}],
            [{"id": "case", "evaluation": {"checks": checks}}],
            suite,
            "specialized",
        )
        self.assertEqual(summary["scored"]["score"], 50.0)
        self.assertEqual(summary["releaseDecision"], "FAIL")

    def test_core_behavior_contract(self):
        core = load_core()
        result = core.core_conformance()
        self.assertTrue(result["ok"], result)


if __name__ == "__main__":
    unittest.main()
