from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from forge._shared.pipeline_routing import classification_from_cs2_manifest, resolve_pipeline_routing, validate_pipeline_routing
from forge.stage1_intake.cs2_manifest import build_classification_record, build_manifest, validate_manifest
from forge.stage2_spec.cs2_adapters import STAGED_ADAPTERS, get_family_adapter, resolve_family_adapter
from forge.stage2_spec.glove_assembly import build_glove_assembly, validate_glove_assembly
from forge.stage2_spec.new_pre_spec_assessment import make_payload
from forge.stage2_spec.new_sculpt_spec import apply_glove_template, make_spec
from forge.stage3_build.glove_artifacts import build_bundle_from_assembly, verify_model_bundle
from forge.stage3_build.glove_geometry import build_glove_geometry, validate_geometry_report
from forge.stage4_review.glove_review import METRIC_KINDS, REPORT_VERSION, build_uncalibrated_scene, evaluate_glove_review, validate_glove_scene


ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixtures" / "glove_sport_v1"


class GlovePipelineTest(unittest.TestCase):
    def manifest(self) -> dict:
        refs = [(FIXTURE / "dorsal.png", "dorsal"), (FIXTURE / "palmar.png", "palmar"), (FIXTURE / "thumb-side-profile.png", "thumb-side-profile"), (FIXTURE / "three-quarter.png", "three-quarter")]
        return build_manifest(FIXTURE / "dorsal.png", build_classification_record("glove", "sport-gloves", 0.99, ["fixture:glove"]), references=refs)

    def test_four_view_manifest_is_admitted_and_legacy_alias_is_dorsal(self) -> None:
        manifest = self.manifest()
        self.assertEqual(manifest["state"], "proceed")
        self.assertTrue(validate_manifest(manifest))
        self.assertEqual({view["role"] for view in manifest["sourceViews"]}, {"dorsal", "palmar", "thumb-side-profile", "three-quarter"})
        self.assertEqual(manifest["sourceImage"], next(view["path"] for view in manifest["sourceViews"] if view["role"] == "dorsal"))
        self.assertEqual(manifest["extensions"]["glove"]["version"], 1)

    def test_missing_required_view_is_request_input_and_intake_only(self) -> None:
        refs = [(FIXTURE / "dorsal.png", "dorsal"), (FIXTURE / "palmar.png", "palmar")]
        manifest = build_manifest(FIXTURE / "dorsal.png", build_classification_record("glove", "sport-gloves", 0.99, ["fixture:glove"]), references=refs)
        self.assertEqual(manifest["state"], "request-input")
        self.assertTrue(validate_manifest(manifest))
        payload = make_payload("CS2 Sport Gloves", manifest["sourceImage"], "ultra-complex", True, manifest, source_images=[view["path"] for view in manifest["sourceViews"]])
        self.assertTrue(payload["intakeOnly"])
        self.assertEqual(len(payload["sourceViews"]), 2)

    def test_wearable_routing_is_not_weapon_routing(self) -> None:
        manifest = self.manifest()
        classification = classification_from_cs2_manifest(manifest)
        self.assertEqual(classification["kind"], "wearable")
        routing = resolve_pipeline_routing(classification=classification)
        self.assertEqual(routing["track"], "wearable-v1.0")
        self.assertEqual(routing["status"], "resolved")
        self.assertEqual(validate_pipeline_routing(routing), [])

    def test_glove_adapter_is_staged_until_activation(self) -> None:
        with self.assertRaises(ValueError):
            get_family_adapter("glove", "sport-gloves")
        self.assertEqual(resolve_family_adapter("glove", "sport-gloves", staged=True).family, "glove")
        self.assertIn("glove", STAGED_ADAPTERS)

    def test_assembly_and_geometry_cover_seams_and_hands(self) -> None:
        assembly = build_glove_assembly()
        self.assertEqual(validate_glove_assembly(assembly), [])
        geometry = build_glove_geometry(assembly)
        self.assertEqual(validate_geometry_report(geometry, require_production=False), [])
        self.assertTrue(validate_geometry_report(geometry))
        self.assertEqual({mesh["hand"] for mesh in geometry["meshes"]}, {"left", "right"})
        self.assertTrue(all(not seam["welded"] for seam in geometry["seams"]))

    def test_glove_template_has_sewn_route_and_no_blade_tree(self) -> None:
        spec = apply_glove_template(make_spec("CS2 Sport Gloves", None))
        self.assertEqual(spec["wearable"]["track"], "wearable-v1.0")
        self.assertEqual(spec["wearable"]["template"], "glove-shell-v1")
        self.assertFalse(any(node.get("role") == "blade" for node in spec["componentTree"]))
        self.assertGreaterEqual(len(spec["preSpecAssessment"]["detailInventory"]["details"]), 16)

    def test_model_bundle_is_content_addressed_and_geometry_binds_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle, report = build_bundle_from_assembly(build_glove_assembly(), Path(directory))
            descriptor = verify_model_bundle(bundle)
            geometry_report = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(geometry_report["modelBundleDigest"], descriptor["rootDigest"])
            self.assertEqual(descriptor["version"], "glove-model-bundle.v2")
            self.assertTrue(descriptor["payloads"])

    def test_uncalibrated_scene_is_not_ready_scene(self) -> None:
        scene = build_uncalibrated_scene()
        self.assertEqual(validate_glove_scene(scene), [])
        self.assertEqual(scene["thresholdStatus"], "uncalibrated")

    def test_review_names_a_missing_artifact_locator_and_measures_nothing(self) -> None:
        # Supplying scalar metrics used to look like a passing chain; they are ignored, so this
        # asserts what the evaluator actually does with an absent locator: name it, and report
        # every metric as inconclusive rather than omitting or passing them.
        manifest = self.manifest()
        review = evaluate_glove_review(manifest, {"captures": [{"role": "dorsal", "modelBundleDigest": "wrong"}]}, build_uncalibrated_scene())
        self.assertEqual((review["verdict"], review["version"]), ("reject", REPORT_VERSION))
        self.assertTrue([gate for gate in review["failedGates"] if gate.startswith("artifact-chain:")])
        self.assertEqual(
            {gate.split(":", 1)[1] for gate in review["failedGates"] if gate.startswith("metric-inconclusive:")},
            set(METRIC_KINDS),
        )
        self.assertEqual(review["metrics"], {})


if __name__ == "__main__":
    unittest.main()
