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
from forge.stage2_spec.glove_assembly import build_glove_assembly, canonical_hash, resample_ordered_spans, validate_glove_assembly
from forge.stage2_spec.glove_state import can_emit_build, can_emit_spec, intake_contract
from forge.stage2_spec.new_pre_spec_assessment import make_payload
from forge.stage2_spec.new_sculpt_spec import apply_cs2_manifest_evidence, apply_glove_template, make_spec
from forge.stage2_spec.validate_sculpt_spec import validate_spec
from forge.stage1_intake.glove_observation import apply_glove_observation
from forge.stage3_build.glove_artifacts import build_bundle_from_assembly, verify_model_bundle
from forge.stage3_build.generate_threejs_factory import generate
from forge.stage3_build.glove_geometry import build_glove_geometry, triangulate_panel_loop, validate_geometry_report
from forge.stage3_build.glove_generator_dispatch import build_glove_model_from_artifacts, unbuildable_capabilities
from forge.stage4_review.glove_review import METRIC_KINDS, REPORT_VERSION, build_uncalibrated_scene, evaluate_glove_review, validate_glove_scene
from forge.stage4_review.glove_seeded_fixtures import seeded_fixture_names, seeded_negative_metrics
from forge.stage4_review.glove_surface_gates import mutate_surface_contract, validate_glove_surface_contract


FIXTURE = Path(__file__).parent / "fixtures" / "glove_sport_v1"


def manifest() -> dict:
    refs = [(FIXTURE / "dorsal.png", "dorsal"), (FIXTURE / "palmar.png", "palmar"), (FIXTURE / "thumb-side-profile.png", "thumb-side-profile"), (FIXTURE / "three-quarter.png", "three-quarter")]
    return build_manifest(refs[0][0], build_classification_record("glove", "sport-gloves", 0.99, ["fixture:glove"]), references=refs)


class GloveAcceptanceTests(unittest.TestCase):
    def test_any_glove_subtype_is_admitted_and_a_nameless_one_is_not(self):
        """Subtype is no longer an admission decision.

        This test used to assert the opposite -- that `fingerless` raised and reached
        `unsupported-subtype` -- because `sport-gloves` was the staged pilot
        (`cs2_adapters.register_staged_adapter`: "Activate only after the end-to-end glove gates have
        passed"). The gates passed and the allowlist is gone. What may still refuse is capability, checked
        where the geometry is built, and a glove that declares no subtype at all.
        """
        target = json.loads((FIXTURE.parent / "glove_target_v1.json").read_text())
        self.assertEqual((target["output"], target["scale"]), ("static-pair", "normalized"))
        adapter = resolve_family_adapter("glove", "hydra-gloves", staged=True)
        self.assertEqual((adapter.family, adapter.subtype), ("glove", "hydra-gloves"))
        admitted = build_manifest(FIXTURE / "dorsal.png", build_classification_record("glove", "hydra-gloves", 0.99, ["fixture:glove"]), references=[(FIXTURE / "dorsal.png", "dorsal")])
        self.assertNotEqual(admitted["state"], "unsupported-subtype")
        nameless = build_manifest(FIXTURE / "dorsal.png", build_classification_record("glove", None, 0.99, ["fixture:glove"]), references=[(FIXTURE / "dorsal.png", "dorsal")])
        self.assertEqual(nameless["state"], "unsupported-subtype")

    def test_the_worked_observation_example_loads_from_disk(self):
        """The example the docs point at must exist in the repo AND merge.

        Neither was true. `docs/CS2_GLOVE_WORKFLOW.md` cited a path under `.img2threejs/`, which
        `.gitignore:22` excludes, so a fresh checkout had no example for the only step that can set
        `evidenceUse`. The copy that did exist raised `surfaceRegionEvidence[0] names unknown source view
        None`, because it nested `sourceViewId` under `projectionTransform` and carried no `sourceHash`,
        against the top-level pair `glove_contracts.py:134` requires. No test loaded a file, so the suite
        stayed green over it. This one loads a file.
        """
        example = FIXTURE / "observation.json"
        self.assertTrue(example.is_file(), "the worked observation example must be committed, not written by a run")
        merged = apply_glove_observation(manifest(), json.loads(example.read_text(encoding="utf-8")))
        classified = {view["role"]: view.get("evidenceUse") for view in merged["sourceViews"]}
        self.assertEqual(classified["dorsal"], "target-geometry-and-surface")
        self.assertEqual(classified["palmar"], "target-geometry-and-surface")
        self.assertEqual(merged["extensions"]["glove"]["formProfile"]["kind"], "full-finger")

    def test_capability_refuses_what_the_name_no_longer_does(self):
        """Removing the subtype allowlist without this turns a refusal into a silently wrong model.

        `glove_contracts.VALID_OPENING_KINDS` has admitted `grouped-chamber` since before any builder
        existed, and there still is not one: a mitten's digits share a chamber, which is a different solid,
        not a different tip. It must fail closed and say so, not come out as separate fingers.
        """
        def profile(state, digits):
            return {"extensions": {"glove": {"formProfile": {"kind": "fingerless", "classificationState": state, "digitTopology": digits}}}}

        # The seeded default is not a demand: `build_glove_extension` gives every manifest one placeholder
        # digit `unclassified-digits` with `opening: "cuff"` under `classificationState: "unknown"`.
        seeded = build_glove_extension([{"id": "glove-view-1-dorsal", "role": "dorsal"}], "sport-gloves")["formProfile"]
        self.assertEqual((seeded["kind"], seeded["classificationState"]), ("unknown", "unknown"))
        self.assertEqual(unbuildable_capabilities({"extensions": {"glove": {"formProfile": seeded}}}), [])

        observed = unbuildable_capabilities(profile("observed", [{"id": "index", "opening": "grouped-chamber"}, {"id": "thumb", "opening": "closed-tip"}]))
        self.assertEqual(len(observed), 1)
        self.assertIn("grouped-chamber", observed[0])
        self.assertIn("index", observed[0])
        # Both endings the armature can build pass: a capsule's own cap, and that cap subtracted away.
        for opening in ("closed-tip", "open-cut"):
            self.assertEqual(unbuildable_capabilities(profile("observed", [{"id": "index", "opening": opening}])), [])

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
        # The fixture's two hands are coincident: the right hand is the left with x negated, so
        # the panels symmetric about x=0 occupy the same volume. The contract measures that
        # instead of reading the report's diagnosticOverlapSeparate declaration, which is True.
        self.assertTrue(geometry["diagnosticOverlapSeparate"])
        baseline = validate_glove_surface_contract(geometry, spec)
        self.assertEqual([error.split(":")[0:2] for error in baseline], [["blank-form", "hands-coincident"]])
        for mutation in ("rotation-only", "flipped-orientation", "missing-overrides", "blind-finish-mirroring", "pbr-channel-alias", "coincident-hands", "no-inspectable-material", "mesh-material-not-in-spec"):
            mutated_geometry, mutated_spec = mutate_surface_contract(geometry, spec, mutation)
            mutated = set(validate_glove_surface_contract(mutated_geometry, mutated_spec))
            self.assertTrue(mutated - set(baseline), mutation)

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
            "surfaceRegionEvidence": [{"id": "dorsal", "sourceViewId": dorsal["id"], "sourceHash": dorsal["hash"], "sourceCropDigest": "crop", "comparisonMaskDigest": "mask", "orientation": "dorsal", "projectionTransform": {"kind": "uv"}, "channels": {"baseColor": {"source": "reference"}}}],
            "evidence": [{"id": "observed-topology", "sourceRefs": [dorsal["id"]], "region": "topology", "visibility": "visible", "epistemicState": "observed", "confidence": 0.9, "contradictions": []}],
            "sourceUse": {dorsal["id"]: "target-geometry-and-surface"},
        }
        merged = apply_glove_observation(current, observation)
        self.assertEqual(merged["extensions"]["glove"]["formProfile"]["kind"], "full-finger")
        bad = json.loads(json.dumps(observation))
        bad["coverageMatrix"][0]["sourceHash"] = "wrong"
        with self.assertRaises(ValueError):
            apply_glove_observation(current, bad)

    def test_surface_evidence_may_only_come_from_the_target_item(self):
        """A real CS2 item ships two plates; the other required roles are borrowed technical views
        of the same glove at another wear tier. Those are sound for geometry and would paint the
        wrong finish, so surface evidence must be refused from them."""
        current = manifest()
        views = current["extensions"]["glove"]["sourceViews"]
        dorsal, palmar, technical = views[0], views[1], views[2]
        use = {
            dorsal["id"]: "target-geometry-and-surface",
            palmar["id"]: "target-geometry-and-surface",
            technical["id"]: "technical-geometry-only",
        }

        def observation(region_view, source_use=use, source_hash=None):
            return {
                "formProfile": {"kind": "full-finger", "classificationState": "observed", "digitTopology": [{"id": "index", "opening": "closed-tip", "path": "curved", "evidenceRefs": [dorsal["id"]]}], "openingPolicy": {"allowedBoundaryKinds": ["closed-tip", "cuff"]}},
                "coverageMatrix": [{"ownerId": "dorsal", "sourceViewId": dorsal["id"], "sourceHash": dorsal["hash"], "cropDigest": "crop", "visibility": "visible", "state": "covered", "renderCameras": ["dorsal"]}],
                "surfaceRegionEvidence": [{"id": "region", "sourceViewId": region_view["id"], "sourceHash": source_hash or region_view["hash"], "sourceCropDigest": "crop", "comparisonMaskDigest": "mask", "orientation": "dorsal", "projectionTransform": {"kind": "uv"}, "channels": {"baseColor": {"source": "plate"}}}],
                "evidence": [{"id": "observed", "sourceRefs": [dorsal["id"]], "region": "shell", "visibility": "visible", "epistemicState": "observed", "confidence": 0.9, "contradictions": []}],
                "sourceUse": source_use,
            }

        merged = apply_glove_observation(current, observation(dorsal))
        self.assertEqual(merged["extensions"]["glove"]["sourceViews"][0]["evidenceUse"], "target-geometry-and-surface")

        with self.assertRaises(ValueError):  # colour borrowed from another wear tier
            apply_glove_observation(current, observation(technical))
        with self.assertRaises(ValueError):  # surface evidence not bound to its view's bytes
            apply_glove_observation(current, observation(dorsal, source_hash="wrong"))
        with self.assertRaises(ValueError):  # unclassified provenance
            apply_glove_observation(current, observation(dorsal, source_use={dorsal["id"]: "whatever"}))

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
        scene = build_uncalibrated_scene()
        self.assertEqual(validate_glove_scene(scene), [])
        # The diagnostic scene carries no thresholds, so it can never authorize readiness.
        self.assertTrue(validate_glove_scene(scene, calibrated=True))
        for retired in ("diagnostic-frozen-v1", "frozen-from-golden-and-seeded-negative-measurements"):
            self.assertTrue(validate_glove_scene({**scene, "thresholdStatus": retired}))
        self.assertEqual(len(seeded_fixture_names()), 8)
        for case in seeded_fixture_names():
            self.assertTrue(seeded_negative_metrics(case))

    def test_activation_requires_a_self_consistent_report(self):
        forged = [
            {"verdict": "ready", "modelBundleDigest": "digest"},
            {"version": REPORT_VERSION, "verdict": "ready", "modelBundleDigest": "digest", "failedGates": [], "reportDigest": "0" * 64},
            {"version": REPORT_VERSION, "verdict": "ready", "modelBundleDigest": "digest", "failedGates": ["topologyReady"]},
        ]
        for payload in forged:
            with self.subTest(payload=sorted(payload)):
                with self.assertRaises(ValueError):
                    activate_staged_adapter_after_review("glove", payload)
        with self.assertRaises(ValueError):
            get_family_adapter("glove", "sport-gloves")

    def test_activation_and_rollback_are_explicit(self):
        with self.assertRaises(ValueError):
            get_family_adapter("glove", "sport-gloves")
        report = {"version": REPORT_VERSION, "verdict": "ready", "modelBundleDigest": "digest", "failedGates": []}
        report["reportDigest"] = canonical_hash(report)
        activate_staged_adapter_after_review("glove", report)
        self.assertEqual(get_family_adapter("glove", "sport-gloves").family, "glove")
        disable_staged_adapter("glove")
        with self.assertRaises(ValueError):
            get_family_adapter("glove", "sport-gloves")


if __name__ == "__main__":
    unittest.main()
