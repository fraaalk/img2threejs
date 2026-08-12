"""Keep the documented glove e2e harness under test.

The harness owns the seeded-negative suite, and it silently stopped running: both commands in
`docs/CS2_GLOVE_WORKFLOW.md` tracebacked because spec-quality warnings were promoted to fatal at
spec-build time — the same warnings the review reports as `coverage:` gates. Nothing imported the
file, so nothing noticed. This test exists so that cannot recur.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from forge.stage4_review.glove_review import METRIC_KINDS, REPORT_VERSION
from forge.tests.run_glove_e2e import run_golden


GLOVE_RUNTIME = ROOT / "runtime" / "glove-review" / "src" / "index.mjs"


@unittest.skipUnless(
    GLOVE_RUNTIME.is_file(),
    # .gitignore excludes runtime/* and re-includes only runtime/scripts/, so runtime/glove-review/
    # is absent from a fresh clone even though it is source rather than capture output. Without this
    # guard the harness fails here with a bare file-not-found, which reads as a broken harness
    # instead of a missing runtime.
    f"{GLOVE_RUNTIME.relative_to(ROOT)} is absent: runtime/glove-review is not tracked by git",
)
class GloveE2EHarnessTests(unittest.TestCase):
    def test_documented_golden_invocation_runs_and_writes_a_report(self):
        with tempfile.TemporaryDirectory(prefix="img2-glove-harness-") as raw:
            result = run_golden(Path(raw))
            self.assertEqual((result["verdict"], result["action"]), ("reject", "request-input"))
            report = json.loads(Path(result["report"]).read_text(encoding="utf-8"))
            self.assertEqual(report["version"], REPORT_VERSION)
            self.assertEqual(set(report["metrics"]), set(METRIC_KINDS))
            # The readiness deficiencies the harness used to abort on are reported here instead.
            self.assertTrue([gate for gate in report["failedGates"] if gate.startswith("coverage:")])
            self.assertIn("evidence-tier:diagnostic", report["failedGates"])
            self.assertIn("calibration:thresholds-absent", report["failedGates"])
            # The diagnostic payload survives: refusing to authorize readiness is not refusing to
            # report measurements.
            self.assertTrue(any(item["status"] == "measured" for item in report["metrics"].values()))


if __name__ == "__main__":
    unittest.main()
