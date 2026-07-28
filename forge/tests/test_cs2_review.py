from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

from forge.stage4_review.cs2_review import evaluate_family_review, evaluate_glove_review, evaluate_knife_review, load_review_scene
from forge.stage4_review.append_review import main as append_review_main


class Cs2ReviewGateTest(unittest.TestCase):
    scene: dict[str, Any] = {}
    manifest: dict[str, Any] = {}

    def glove_manifest(self) -> dict[str, Any]:
        return json.loads((ROOT / "tests" / "fixtures" / "glove_multiview_valid.json").read_text(encoding="utf-8"))

    def glove_captures(self) -> dict[str, Any]:
        fixed = {
            "left-dorsal": ("left", "dorsal", [0, 0, 1]),
            "left-palmar": ("left", "palmar", [0, 0, -1]),
            "right-dorsal": ("right", "dorsal", [0, 0, 1]),
            "right-palmar": ("right", "palmar", [0, 0, -1]),
        }
        captures: dict[str, Any] = {
            capture_id: {
                "hand": hand,
                "role": role,
                "cameraPosition": position,
                "regionCoverage": {"shell": 0.97},
                "requiredOccupancy": {"thumb": 0.99, "cuff": 0.99},
                "textureOwnership": 1,
                "reversedFacePixels": 0,
            }
            for capture_id, (hand, role, position) in fixed.items()
        }
        captures["left-orbit-35"] = {"silhouetteXor": 0.08, "normalDirectionChange": 0.12}
        captures["right-orbit-35"] = {"silhouetteXor": 0.08, "normalDirectionChange": 0.12}
        return captures

    def setUp(self) -> None:
        self.scene = load_review_scene(ROOT / "tests" / "fixtures" / "knife_review_scene.json")
        self.manifest = {
            "schemaVersion": 1,
            "state": "proceed",
            "itemFamily": "knife",
            "subtype": "karambit",
            "componentAdapter": "cs2-knife-v1",
            "route": "reference-projection",
            "exactnessTier": "image-only",
            "confidence": {"overall": 0.86, "hiddenRegions": 0.25},
            "assumptions": {"hiddenRegions": "inferred"},
        }

    def passing_inputs(self) -> dict[str, Any]:
        return {
            "silhouetteIoU": 0.91,
            "aspectRatioDelta": 0.02,
            "scaleDelta": 0.04,
            "finishMaterialResponse": 0.88,
            "identityDetail": 0.9,
            "paintedRegions": [{"id": "blade_finish", "score": 0.9, "confidence": 0.8}],
            "projection": {"coverage": 0.94, "required": True},
            "multiAngle": {"degenerate": False, "collapseRatio": 0.08, "angles": [{"id": "orbit-a"}, {"id": "orbit-b"}]},
            "criticalFeatures": [{"id": "karambit_ring", "score": 0.9, "threshold": 0.8}],
            "approximationNotes": ["hidden blade side inferred from single view"],
        }

    def test_passing_knife_review_returns_machine_readable_report(self) -> None:
        report = evaluate_knife_review(self.manifest, self.passing_inputs(), self.scene)

        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["action"], "continue")
        self.assertEqual(report["family"], "knife")
        self.assertEqual(report["exactnessTier"], "image-only")
        self.assertEqual(report["reviewScene"]["version"], 1)
        self.assertEqual(report["failedGates"], [])
        self.assertEqual(report["approximationNotes"], ["hidden blade side inferred from single view"])

    def test_wrong_family_is_blocking_even_when_visual_metrics_pass(self) -> None:
        manifest = {**self.manifest, "itemFamily": "rifle"}

        report = evaluate_knife_review(manifest, self.passing_inputs(), self.scene)

        self.assertEqual(report["verdict"], "reject")
        self.assertEqual(report["action"], "request-input")
        self.assertIn("unsupported-family:rifle", report["failedGates"])

    def test_supported_family_review_uses_fixture_identity_and_adapter(self) -> None:
        for family, subtype in (("pistol", "glock-18"), ("rifle", "awp")):
            manifest = {
                **self.manifest,
                "itemFamily": family,
                "subtype": subtype,
                "componentAdapter": f"cs2-{family}-v1",
            }
            scene = {
                **self.scene,
                "fixtureId": f"cs2-{family}-front-v1",
                "identity": {"family": family, "subtype": subtype, "adapterId": f"cs2-{family}-v1"},
            }
            report = evaluate_family_review(manifest, self.passing_inputs(), scene, expected_family=family)
            self.assertEqual(report["verdict"], "pass")
            self.assertEqual(report["family"], family)
            self.assertEqual(report["subtype"], subtype)

    def test_activated_fixture_scenes_are_calibrated_and_family_qualified(self) -> None:
        for family, subtype in (("knife", "karambit"), ("pistol", "glock-18"), ("rifle", "awp")):
            scene = load_review_scene(ROOT / "tests" / "fixtures" / f"{family}_review_scene.json")
            self.assertEqual(scene["identity"]["family"], family)
            self.assertEqual(scene["identity"]["subtype"], subtype)
            self.assertEqual(scene["calibration"]["status"], "calibrated")
            self.assertTrue(scene["calibration"]["positiveFixtures"])
            self.assertTrue(scene["calibration"]["negativeFixtures"])

    def test_family_review_rejects_adapter_mismatch(self) -> None:
        scene = {
            **self.scene,
            "identity": {"family": "pistol", "subtype": "glock-18", "adapterId": "cs2-rifle-v1"},
        }
        manifest = {**self.manifest, "itemFamily": "pistol", "subtype": "glock-18", "componentAdapter": "cs2-pistol-v1"}
        report = evaluate_family_review(manifest, self.passing_inputs(), scene, expected_family="pistol")
        self.assertEqual(report["verdict"], "reject")
        self.assertIn("fixture-adapter-mismatch", report["failedGates"])

    def test_projection_coverage_and_identity_detail_are_blocking(self) -> None:
        inputs = self.passing_inputs()
        inputs["projection"] = {"coverage": 0.42, "required": True}
        inputs["criticalFeatures"] = [{"id": "karambit_ring", "score": 0.4, "threshold": 0.8}]

        report = evaluate_knife_review(self.manifest, inputs, self.scene)

        self.assertEqual(report["verdict"], "reject")
        self.assertEqual(report["action"], "refine-code")
        self.assertIn("projection-coverage", report["failedGates"])
        self.assertIn("critical-feature:karambit_ring", report["failedGates"])

    def test_glove_review_uses_fixed_anatomical_captures_and_rejects_mutations(self) -> None:
        manifest = self.glove_manifest()
        scene = json.loads((ROOT / "tests" / "fixtures" / "glove_review_scene.json").read_text(encoding="utf-8"))

        report = evaluate_glove_review(manifest, scene, self.glove_captures())
        self.assertEqual(report["verdict"], "pass")

        swapped = self.glove_captures()
        swapped["left-palmar"]["role"] = "dorsal"
        self.assertIn("GLOVE_SURFACE_SWAP", evaluate_glove_review(manifest, scene, swapped)["failedGates"])

        missing_thumb = self.glove_captures()
        missing_thumb["left-dorsal"]["requiredOccupancy"]["thumb"] = 0.5
        self.assertIn("GLOVE_REQUIRED_DIGIT_NOT_OBSERVED", evaluate_glove_review(manifest, scene, missing_thumb)["failedGates"])

    def test_degenerate_orbit_is_blocking_and_missing_scene_metadata_is_error(self) -> None:
        inputs = self.passing_inputs()
        inputs["multiAngle"] = {"degenerate": True, "angles": [{"id": "orbit-a", "degenerate": True}]}
        report = evaluate_knife_review(self.manifest, inputs, self.scene)
        self.assertEqual(report["verdict"], "reject")
        self.assertIn("degenerate-orbit", report["failedGates"])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps({"version": 1}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_review_scene(path)

    def test_append_review_persists_cs2_report_and_rejects_failed_report(self) -> None:
        report = evaluate_knife_review(self.manifest, self.passing_inputs(), self.scene)
        failed = evaluate_knife_review(
            self.manifest,
            {**self.passing_inputs(), "identityDetail": 0.2},
            self.scene,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "spec.json"
            report_path = root / "report.json"
            failed_path = root / "failed.json"
            spec_path.write_text(json.dumps({"sourceImage": "ref.png"}), encoding="utf-8")
            report_path.write_text(json.dumps(report), encoding="utf-8")
            failed_path.write_text(json.dumps(failed), encoding="utf-8")
            append_review_main([
                str(spec_path), "--pass-id", "optimization-pass", "--fidelity", "0.9",
                "--action", "continue", "--summary", "ok", "--cs2-review-json", str(report_path),
                "--review-scene-json", str(ROOT / "tests" / "fixtures" / "knife_review_scene.json"),
                "--force-out-of-order",
                "--in-place",
            ])
            persisted = json.loads(spec_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["reviewHistory"][0]["cs2Review"]["verdict"], "pass")
            with self.assertRaises(ValueError):
                append_review_main([
                    str(spec_path), "--pass-id", "optimization-pass", "--fidelity", "0.9",
                    "--action", "continue", "--summary", "blocked", "--cs2-review-json", str(failed_path),
                ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
