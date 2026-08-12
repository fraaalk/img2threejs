"""Function-level gate isolation for the wearable-v1.0 review.

Every rule the review enforces is proven here by calling the function that implements it with a
constructed payload and asserting the EXACT resulting set. Exact-set assertions are the point: a
membership assertion passes while unrelated rules also fail, which is how the previous suite
managed to assert nothing while every verdict was already `reject`.

No artifact chain, no digests, no browser. Proving that a mutated *artifact* reaches the intended
gate rather than tripping a digest first needs the cascade re-signer and belongs to the
glove-artifact-negative-suite follow-up.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from forge.stage2_spec.glove_assembly import build_glove_assembly
from forge.stage3_build.glove_geometry import build_glove_geometry
from forge.stage4_review.glove_review import (
    METRIC_KINDS,
    UNMEASURED_CONCERNS,
    _derived_metrics,
    _spec_failures,
    _threshold_failures,
    build_uncalibrated_scene,
    validate_glove_scene,
)
from forge.stage4_review.glove_surface_gates import (
    measure_hand_separation,
    mutate_surface_contract,
    validate_glove_surface_contract,
)

FIXTURE_SPEC = {"materials": [{"id": material, "qualityTier": "reference"} for material in ("glove-leather", "glove-textile", "glove-guard", "glove-closure")]}
# The measured baseline: which gates this fixture actually satisfies, with handedness derived from
# the real surface contract rather than assumed. Recorded as an assertion so a change in what the
# instrument reports is detectable instead of silent.
BASELINE_PASSING = {"finiteGeometry", "minimumThicknessMeasured", "provenanceVerified", "runtimeDeterministic", "selfIntersectionFree", "uvMaterialOwnership"}
BASELINE_FAILING = {"handednessCorrect", "penetrationFree", "topologyReady"}
# With handedness and provenance forced true, only the genuinely structural gates still fail.
STRUCTURAL_FAILING = {"penetrationFree", "topologyReady"}


def geometry() -> dict:
    return build_glove_geometry(build_glove_assembly())


def fixture_metrics() -> dict:
    report = geometry()
    errors = validate_glove_surface_contract(report, FIXTURE_SPEC)
    handedness_ok = not any(error.startswith(("handedness:", "asymmetry:", "blank-form:")) for error in errors)
    return metrics_for(report, handedness_ok=handedness_ok)


def metrics_for(report: dict, **overrides) -> dict:
    kwargs = {"provenance_verified": True, "production_valid": True, "handedness_ok": True}
    kwargs.update(overrides)
    return _derived_metrics(
        {"reportDigest": "report"}, {"rootDigest": "bundle"},
        {"manifestDigest": "capture", "finalized": True, "repeatVerified": True},
        report["meshes"], **kwargs,
    )


def thresholds_for(**overrides) -> dict:
    records = {key: {"kind": kind, "threshold": 1.0 if kind == "boolean" else 0.5} for key, kind in METRIC_KINDS.items()}
    records.update(overrides)
    return records


class MetricIdentityTests(unittest.TestCase):
    def test_metric_set_is_exact_and_carries_no_topology_aliases(self):
        published = set(metrics_for(geometry()))
        self.assertEqual(published, set(METRIC_KINDS))
        self.assertEqual(published & {"evidenceCoverage", "graphCompleteness", "seamBoundaryCorrespondence", "attachmentContinuity", "productionManifold", "asymmetryPreserved"}, set())

    def test_minimum_thickness_is_named_for_what_it_measures(self):
        published = set(metrics_for(geometry()))
        self.assertIn("minimumThicknessMeasured", published)
        self.assertNotIn("crossSectionVariation", published)

    def test_unmeasurable_concerns_are_recorded_not_derived(self):
        published = set(metrics_for(geometry()))
        self.assertEqual(published & set(UNMEASURED_CONCERNS), set())
        for concern in ("seamBoundaryCorrespondence", "productionManifold", "referenceResemblance"):
            self.assertTrue(UNMEASURED_CONCERNS[concern].strip())

    def test_measured_baseline_is_asserted(self):
        values = {key: item["value"] for key, item in fixture_metrics().items()}
        self.assertEqual({key for key, value in values.items() if value == 1.0}, BASELINE_PASSING)
        self.assertEqual({key for key, value in values.items() if value == 0.0}, BASELINE_FAILING)

    def test_provenance_and_handedness_are_independent_of_topology(self):
        report = geometry()
        without_provenance = metrics_for(report, provenance_verified=False)
        without_handedness = metrics_for(report, handedness_ok=False)
        self.assertEqual(without_provenance["provenanceVerified"]["value"], 0.0)
        self.assertEqual(without_handedness["handednessCorrect"]["value"], 0.0)
        self.assertEqual(metrics_for(report)["provenanceVerified"]["value"], 1.0)


class HandSeparationTests(unittest.TestCase):
    def test_declaration_does_not_substitute_for_a_measurement(self):
        report = geometry()
        self.assertTrue(report["diagnosticOverlapSeparate"])
        separation = measure_hand_separation(report)
        self.assertEqual(separation["status"], "measured")
        self.assertFalse(separation["separated"])
        self.assertLess(separation["minimumSeparation"], 0.02)

    def test_flipping_the_declaration_changes_nothing(self):
        report = geometry()
        report["diagnosticOverlapSeparate"] = False
        errors = [error for error in validate_glove_surface_contract(report, {}) if error.startswith("blank-form:")]
        report["diagnosticOverlapSeparate"] = True
        still = [error for error in validate_glove_surface_contract(report, {}) if error.startswith("blank-form:")]
        self.assertEqual(errors, still)

    def test_separated_hands_pass(self):
        report = geometry()
        for mesh in report["meshes"]:
            if mesh["hand"] == "right":
                mesh["vertices"] = [[vertex[0] + 5.0, vertex[1], vertex[2]] for vertex in mesh["vertices"]]
        self.assertTrue(measure_hand_separation(report)["separated"])


class SurfaceContractTests(unittest.TestCase):
    def test_an_empty_spec_does_not_pass(self):
        self.assertTrue(validate_glove_surface_contract(geometry(), {}))

    def test_named_mutations_each_add_a_failure(self):
        report = geometry()
        spec = {"materials": [{"id": material, "qualityTier": "reference"} for material in ("glove-leather", "glove-textile", "glove-guard", "glove-closure")]}
        baseline = set(validate_glove_surface_contract(report, spec))
        for mutation in ("rotation-only", "flipped-orientation", "missing-overrides", "blind-finish-mirroring", "coincident-hands", "no-inspectable-material", "mesh-material-not-in-spec"):
            with self.subTest(mutation=mutation):
                mutated_report, mutated_spec = mutate_surface_contract(report, spec, mutation)
                self.assertTrue(set(validate_glove_surface_contract(mutated_report, mutated_spec)) - baseline)

    def test_all_utility_materials_do_not_pass(self):
        report = geometry()
        errors = validate_glove_surface_contract(report, {"materials": [{"id": "x", "qualityTier": "utility"}]})
        self.assertIn("surface:spec-declares-no-inspectable-material", errors)

    def test_unknown_mutation_is_refused(self):
        with self.assertRaises(ValueError):
            mutate_surface_contract(geometry(), {}, "not-a-mutation")


class SpecRecoveryTests(unittest.TestCase):
    def test_absent_spec_is_a_named_failure_not_a_skip(self):
        self.assertEqual(_spec_failures(None), ["surface-contract:spec-unavailable"])

    def test_wrongly_routed_spec_is_refused(self):
        failures = _spec_failures({"pipelineRouting": {"track": "weapon-v1.4"}})
        self.assertIn("surface-contract:spec-track-mismatch", failures)

    def test_spec_without_routing_is_refused(self):
        self.assertIn("surface-contract:spec-track-mismatch", _spec_failures({}))


class ThresholdTests(unittest.TestCase):
    def setUp(self):
        self.metrics = metrics_for(geometry())

    def test_absent_thresholds_do_not_fall_back_to_constants(self):
        self.assertEqual(_threshold_failures(self.metrics, {"thresholds": {}}), ["calibration:thresholds-absent"])
        self.assertEqual(_threshold_failures(self.metrics, {}), ["calibration:thresholds-absent"])

    def test_a_boolean_gate_at_zero_fails_by_key(self):
        failures = _threshold_failures(self.metrics, {"thresholds": thresholds_for()})
        self.assertEqual(set(failures), STRUCTURAL_FAILING)

    def test_a_boolean_threshold_below_one_is_refused(self):
        scene = {"thresholds": thresholds_for(topologyReady={"kind": "boolean", "threshold": 0.5})}
        self.assertIn("calibration:threshold-invalid:topologyReady", _threshold_failures(self.metrics, scene))

    def test_malformed_thresholds_are_named_not_raised(self):
        for bad in (None, "0.9", float("nan"), float("inf"), -1.0, 1.5, {"kind": "continuous", "threshold": 1.0}):
            with self.subTest(bad=repr(bad)):
                record = bad if isinstance(bad, dict) else {"kind": "boolean", "threshold": bad}
                failures = _threshold_failures(self.metrics, {"thresholds": thresholds_for(topologyReady=record)})
                self.assertIn("calibration:threshold-invalid:topologyReady", failures)

    def test_threshold_set_must_equal_the_metric_set_in_both_directions(self):
        short = thresholds_for()
        short.pop("topologyReady")
        self.assertIn("calibration:threshold-set-mismatch", _threshold_failures(self.metrics, {"thresholds": short}))
        extra = thresholds_for(unknownGate={"kind": "boolean", "threshold": 1.0})
        self.assertIn("calibration:threshold-set-mismatch", _threshold_failures(self.metrics, {"thresholds": extra}))

    def test_a_fractional_value_cannot_satisfy_a_boolean_gate(self):
        metrics = dict(self.metrics)
        metrics["topologyReady"] = {**metrics["topologyReady"], "value": 0.5}
        self.assertIn("topologyReady", _threshold_failures(metrics, {"thresholds": thresholds_for()}))


class SceneStatusTests(unittest.TestCase):
    def test_only_two_statuses_are_accepted(self):
        scene = build_uncalibrated_scene()
        self.assertEqual(validate_glove_scene(scene), [])
        for retired in ("diagnostic-frozen-v1", "frozen-from-golden-and-seeded-negative-measurements", "verified"):
            with self.subTest(status=retired):
                self.assertTrue(validate_glove_scene({**scene, "thresholdStatus": retired}))

    def test_only_verified_calibration_may_authorize_readiness(self):
        scene = build_uncalibrated_scene()
        self.assertTrue(validate_glove_scene(scene, calibrated=True))
        calibrated = {**scene, "thresholdStatus": "verified-artifact-calibration-v2", "thresholds": thresholds_for()}
        self.assertEqual(validate_glove_scene(calibrated, calibrated=True), [])

    def test_a_calibrated_scene_with_a_wrong_threshold_set_is_refused(self):
        scene = build_uncalibrated_scene()
        short = thresholds_for()
        short.pop("penetrationFree")
        calibrated = {**scene, "thresholdStatus": "verified-artifact-calibration-v2", "thresholds": short}
        self.assertTrue(validate_glove_scene(calibrated, calibrated=True))


if __name__ == "__main__":
    unittest.main()
