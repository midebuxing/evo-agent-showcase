import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from experiments.failure_taxonomy import (  # noqa: E402
    FAILURE_QUERY,
    FAILURE_REFERENCE,
    classify_failure,
    summarize_failures,
)


class FailureTaxonomyTests(unittest.TestCase):
    def test_reference_inferred_from_schema_message(self) -> None:
        result = {
            "status": "failed",
            "error_code": "schema_validation_failed",
            "error_message": "DecisionTrace references unknown fact_id: x",
        }
        self.assertEqual(classify_failure(result), FAILURE_REFERENCE)

    def test_summary_counts(self) -> None:
        results = [
            {"status": "ok", "case_id": "c1"},
            {"status": "failed", "case_id": "c2", "error_code": FAILURE_QUERY, "error_message": "query failed"},
        ]
        summary = summarize_failures(results)
        self.assertEqual(summary["counts"][FAILURE_QUERY], 1)
        self.assertEqual(summary["total_failed"], 1)


if __name__ == "__main__":
    unittest.main()
