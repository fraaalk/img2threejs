from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from forge._shared.pipeline_routing import classification_from_cs2_manifest, resolve_pipeline_routing
from forge.stage1_intake.cs2_manifest import build_classification_record, build_manifest
from forge.stage1_intake.glove_contracts import build_glove_extension, validate_glove_extension
from forge.stage2_spec.cs2_adapters import activate_staged_adapter_after_review, disable_staged_adapter, get_family_adapter, resolve_family_adapter
from forge.stage2_spec.glove_assembly import build_glove_assembly, resample_ordered_spans, validate_glove_assembly
from forge.stage2_spec.glove_state import can_emit_build, can_emit_spec, intake_contract
from forge.stage2_spec.new_pre_spec_assessment import make_payload
from forge.stage2_spec.new_sculpt_spec import apply_cs2_manifest_evidence, apply_glove_template, make_spec
from forge.stage2_spec.validate_sculpt_spec import validate_spec
from forge.stage1_intake.glove_observation import apply_glove_observation
from forge.stage3_build.glove_artifacts import build_bundle_from_assembly, verify_model_bundle
from forge.stage3_build.generate_threejs_factory import generate
from forge.stage3_build.glove_geometry import build_glove_geometry, triangulate_panel_loop, validate_geometry_report
from forge.stage3_build.glove_generator_dispatch import build_glove_model_from_artifacts
from forge.stage4_review.glove_review import build_calibrated_scene, build_uncalibrated_scene, evaluate_glove_review, validate_glove_scene
from forge.stage4_review.glove_seeded_fixtures import seeded_fixture_names, seeded_negative_metrics
from forge.stage4_review.glove_surface_gates import mutate_surface_contract, validate_glove_surface_contract


FIXTURE = Path(__file__).parent / "fixtures" / "glove_sport_v1"


def manifest() -> dict:
    refs = [(FIXTURE / "dorsal.png", "dorsal"), (FIXTURE / "palmar.png", "palmar"), (FIXTURE / "thumb-side-profile.png", "thumb-side-profile"), (FIXTURE / "three-quarter.png", "three-quarter")]
    return build_manifest(refs[0][0], build_classification_record("glove", "sport-gloves", 0.99, ["fixture:glove"]), references=refs)


class GloveAcceptanceTests(unittest.TestCase):
    def test_target_and_scope_are_narrow(self):
        target = json.loads((FIXTURE.parent / "glove_target_v1.json").read_text())
        self.assertEqual((target["subtype"], target["output"], target["scale"]), ("sport-gloves", "static-pair", "normalized"))
        with self.assertRaises(ValueError):
            resolve_family_adapter("glove", "fingerless", staged=True)
        unsupported = build_manifest(FIXTURE / "dorsal.png", build_classification_record("glove", "fingerless", 0.99, ["fixture:glove"]), references=[(FIXTURE / "dorsal.png", "dorsal")])
        self.assertEqual(unsupported["state"], "unsupported-subtype")

    def test_intake_schema_and_source_precedence(self):
        current = manifest()
        self.assertEqual(validate_glove_extension(current["extensions"]["glove"]), [])
        self.assertEqual(current["sourceImage"], next(view["path"] for view in current["sourceViews"] if view["role"] == "dorsal"))
        assessment = make_payload(
            "Sport Gloves",
            current["sourceImage"],
            "ultra-complex",
            True,
            current,
            source_images=[view["path"] for view in current["sourceViews"]],
        )
        synthesis = assessment["multiViewSynthesis"]
        self.assertEqual(synthesis["mode"], "evidence-only")
        self.assertEqual(synthesis["sourceViewCount"], 4)
        self.assertEqual(synthesis["calibration"]["status"], "not-supplied")
        broken = json.loads(json.dumps(current["extensions"]["glove"]))
        broken["sourceViews"][0].pop("id")
        self.assertTrue(validate_glove_extension(broken))

    def test_duplicate_and_conflicting_hand_inputs_remain_request_input(self):
        refs = [(FIXTURE / "dorsal.png", "dorsal"), (FIXTURE / "palmar.png", "palmar"), (FIXTURE / "thumb-side-profile.png", "thumb-side-profile"), (FIXTURE / "three-quarter.png", "three-quarter"), (FIXTURE / "dorsal.png", "orbit")]
        duplicate = build_manifest(refs[0][0], build_classification_record("glove", "sport-gloves", 0.99, ["fixture:glove"]), references=refs)
        self.assertEqual(duplicate["state"], "proceed")
        self.assertEqual(duplicate["sourceViews"][-1]["duplicateOf"], duplicate["sourceViews"][0]["id"])
        conflict = build_manifest(refs[0][0], build_classification_record("glove", "sport-gloves", 0.99, ["fixture:glove"]), explicit_identity={"hand": "right"}, references=refs[:4])
        self.assertEqual(conflict["state"], "request-input")
        self.assertIn("conflicting-hand-identity", conflict["warnings"])

    def test_pair_layout_admission_is_a_glove_only_evidence_override(self):
        refs = [(FIXTURE / "dorsal.png", "dorsal"), (FIXTURE / "palmar.png", "palmar")]
        raw_admission = {
            "admitted": False,
            "reasons": ["mask coherence: largest connected blob is 0.50 of foreground < 0.6 (fragmented/scattered subject — ambiguous)"],
            "provenance": {"pHash": 777, "width": 2560, "height": 1440, "foregroundCoverage": 0.45, "largestComponentFraction": 0.5, "duplicateOfHash": None},
        }
        with patch("forge.stage1_intake.cs2_manifest.check_admission", return_value=raw_admission):
            current = build_manifest(refs[0][0], build_classification_record("glove", "sport-gloves", 0.99, ["fixture:pair"]), references=refs)
        self.assertEqual([view["admission"] for view in current["sourceViews"]], ["admitted", "admitted"])
        self.assertTrue(all(view["admissionOverride"]["id"] == "paired-glove-plate-v1" for view in current["sourceViews"]))
        self.assertEqual(current["state"], "request-input")  # profile and three-quarter evidence remain required

    def test_unreadable_required_view_is_request_input_not_buildable(self):
        refs = [(FIXTURE / "dorsal.png", "dorsal"), (FIXTURE / "missing.png", "palmar"), (FIXTURE / "thumb-side-profile.png", "thumb-side-profile"), (FIXTURE / "three-quarter.png", "three-quarter")]
        current = build_manifest(refs[0][0], build_classification_record("glove", "sport-gloves", 0.99, ["fixture:glove"]), references=refs)
        self.assertEqual(current["state"], "request-input")
        self.assertFalse(can_emit_spec(current))

    def test_assembly_routes_and_mutations(self):
        assembly = build_glove_assembly("sport-gloves")
        self.assertEqual(validate_glove_assembly(assembly), [])
        self.assertGreaterEqual(len(assembly["panelGraph"]["nodes"]), 12)
        invalid = json.loads(json.dumps(assembly))
        invalid["seamGraph"]["nodes"][0]["orderedBoundarySpansB"] = [0, 1]
        self.assertTrue(validate_glove_assembly(invalid))
        self.assertEqual(resample_ordered_spans([0, 2, 4], 5), [0, 0, 2, 4, 4])

    def test_routing_template_and_state(self):
        current = manifest()
        classification = classification_from_cs2_manifest(current)
        self.assertEqual(classification["kind"], "wearable")
        self.assertEqual(resolve_pipeline_routing(classification=classification)["track"], "wearable-v1.0")
        spec = apply_glove_template(make_spec("Sport Gloves", None), manifest=current)
        self.assertEqual(spec["wearable"]["template"], "glove-shell-v1")
        self.assertFalse(any(node.get("role") == "blade" for node in spec["componentTree"]))
        self.assertEqual(intake_contract(current)["action"], "build")
        self.assertTrue(can_emit_spec(current) and can_emit_build(current))

    def test_panel_blank_form_handedness_and_integrity(self):
        assembly = build_glove_assembly()
        geometry = build_glove_geometry(assembly)
        self.assertEqual(validate_geometry_report(geometry, require_production=False), [])
        self.assertTrue(validate_geometry_report(geometry))
        self.assertEqual(geometry["evidenceTier"], "diagnostic")
        self.assertGreaterEqual(min(mesh["measurements"]["minimumThickness"] for mesh in geometry["meshes"]), 0.01)
        self.assertEqual({mesh["hand"] for mesh in geometry["meshes"]}, {"left", "right"})
        self.assertTrue(geometry["handedness"]["windingCorrected"])
        self.assertTrue(geometry["diagnosticOverlapSeparate"])
        self.assertEqual(len(triangulate_panel_loop([[0, 0], [1, 0], [1, 1], [0, 1]])), 2)
        with self.assertRaises(ValueError):
            triangulate_panel_loop([[0, 0], [1, 1], [0, 1], [1, 0]])

    def test_surface_contract_and_named_mutations(self):
        current = manifest()
        spec = apply_glove_template(make_spec("Sport Gloves", current["sourceImage"]), manifest=current)
        apply_cs2_manifest_evidence(spec, current)
        geometry = build_glove_geometry(build_glove_assembly())
        self.assertEqual(validate_glove_surface_contract(geometry, spec), [])
        for mutation in ("rotation-only", "flipped-orientation", "missing-overrides", "blind-finish-mirroring", "pbr-channel-alias"):
            mutated_geometry, mutated_spec = mutate_surface_contract(geometry, spec, mutation)
            self.assertTrue(validate_glove_surface_contract(mutated_geometry, mutated_spec), mutation)

    def test_bundle_dispatch_and_digests(self):
        current = manifest()
        spec = apply_glove_template(make_spec("Sport Gloves", current["sourceImage"]), manifest=current)
        spec["pipelineRouting"] = resolve_pipeline_routing(classification=classification_from_cs2_manifest(current))
        assessment = {"intakeOnly": False, "sourceViews": current["sourceViews"]}
        with tempfile.TemporaryDirectory() as directory:
            bundle, report, upstream = build_glove_model_from_artifacts(current, assessment, spec, Path(directory))
            descriptor = verify_model_bundle(bundle)
            self.assertEqual(json.loads(report.read_text())["modelBundleDigest"], descriptor["rootDigest"])
            self.assertEqual(descriptor["upstream"], upstream)

    def test_glove_unknown_form_and_coverage_are_strict_quality_blockers(self):
        current = manifest()
        spec = apply_glove_template(make_spec("Sport Gloves", current["sourceImage"]), manifest=current)
        apply_cs2_manifest_evidence(spec, current)
        errors, warnings = validate_spec(spec)
        self.assertEqual(errors, [])
        self.assertTrue(any("glove evidence readiness: form profile" in warning for warning in warnings))
        self.assertTrue(any("glove evidence readiness: coverage matrix" in warning for warning in warnings))

    def test_observation_merges_only_known_view_hashes(self):
        current = manifest()
        dorsal = current["extensions"]["glove"]["sourceViews"][0]
        observation = {
            "formProfile": {"kind": "full-finger", "classificationState": "observed", "digitTopology": [{"id": "index", "opening": "closed-tip", "path": "curved", "evidenceRefs": [dorsal["id"]]}], "openingPolicy": {"allowedBoundaryKinds": ["closed-tip", "cuff"]}},
            "coverageMatrix": [{"ownerId": "dorsal", "sourceViewId": dorsal["id"], "sourceHash": dorsal["hash"], "cropDigest": "crop", "visibility": "visible", "state": "covered", "renderCameras": ["dorsal"]}],
            "surfaceRegionEvidence": [{"id": "dorsal", "sourceCropDigest": "crop", "comparisonMaskDigest": "mask", "orientation": "dorsal", "projectionTransform": {"kind": "uv"}, "channels": {"baseColor": {"source": "reference"}}}],
            "evidence": [{"id": "observed-topology", "sourceRefs": [dorsal["id"]], "region": "topology", "visibility": "visible", "epistemicState": "observed", "confidence": 0.9, "contradictions": []}],
            "sourceUse": {dorsal["id"]: "target-geometry-and-surface"},
        }
        merged = apply_glove_observation(current, observation)
        self.assertEqual(merged["extensions"]["glove"]["formProfile"]["kind"], "full-finger")
        bad = json.loads(json.dumps(observation))
        bad["coverageMatrix"][0]["sourceHash"] = "wrong"
        with self.assertRaises(ValueError):
            apply_glove_observation(current, bad)

    def test_glove_factory_preserves_cs2_identity_and_runtime_hooks(self):
        current = manifest()
        spec = apply_glove_template(make_spec("Sport Gloves", current["sourceImage"]), manifest=current)
        apply_cs2_manifest_evidence(spec, current)
        generated = generate(spec, "blockout")
        self.assertIn('"itemFamily": "glove"', generated)
        self.assertIn('root.userData.pivots = pivots', generated)
        self.assertIn('root.userData.tick =', generated)
        self.assertIn("url.startsWith('fixture://') ? null : url", generated)
        self.assertIn('disableMaterialMaps?: boolean;', generated)
        self.assertIn('options.disableMaterialMaps ? null', generated)

    def test_review_scenes_and_seeded_fixtures(self):
        self.assertEqual(validate_glove_scene(build_uncalibrated_scene()), [])
        calibrated = build_calibrated_scene()
        self.assertTrue(validate_glove_scene(calibrated, calibrated=True))
        self.assertEqual(len(seeded_fixture_names()), 8)
        for case in seeded_fixture_names():
            self.assertTrue(seeded_negative_metrics(case))

    def test_activation_and_rollback_are_explicit(self):
        with self.assertRaises(ValueError):
            get_family_adapter("glove", "sport-gloves")
        activate_staged_adapter_after_review("glove", {"verdict": "ready", "modelBundleDigest": "digest"})
        self.assertEqual(get_family_adapter("glove", "sport-gloves").family, "glove")
        disable_staged_adapter("glove")
        with self.assertRaises(ValueError):
            get_family_adapter("glove", "sport-gloves")


if __name__ == "__main__":
    unittest.main()
