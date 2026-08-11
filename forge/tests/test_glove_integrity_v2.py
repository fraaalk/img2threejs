from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from forge.stage1_intake.cs2_manifest import build_classification_record, build_manifest
from forge.stage1_intake.glove_contracts import glove_readiness_errors
from forge.stage2_spec.glove_assembly import build_glove_assembly, canonical_hash
from forge.stage3_build.glove_artifacts import build_bundle_from_assembly, verify_geometry_report, verify_model_bundle
from forge.stage3_build.glove_geometry import build_glove_geometry, validate_geometry_report
from forge.stage4_review.glove_review import build_calibrated_scene, evaluate_glove_review
from forge.stage4_review.glove_capture_evidence import derive_profile_capture_plan, finalize_glove_capture_manifest, init_glove_capture_manifest
from forge.stage4_review.render_bridge import write_manifest
from scripts.capture_threejs_playwright import capture


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "forge" / "tests" / "fixtures" / "glove_sport_v1"


def _manifest() -> dict:
    refs = [(FIXTURE / name, role) for name, role in (("dorsal.png", "dorsal"), ("palmar.png", "palmar"), ("thumb-side-profile.png", "thumb-side-profile"), ("three-quarter.png", "three-quarter"))]
    return build_manifest(refs[0][0], build_classification_record("glove", "sport-gloves", 0.99, ["fixture:glove-sport-v1"]), references=refs)


class GloveIntegrityV2Tests(unittest.TestCase):
    def test_unknown_or_uncovered_form_profile_is_not_ready(self):
        profile = {
            "kind": "unknown", "classificationState": "unknown",
            "digitTopology": [{"id": "digits", "opening": "cuff", "path": "unknown", "evidenceRefs": ["dorsal"]}],
            "openingPolicy": {"allowedBoundaryKinds": ["cuff"]},
        }
        self.assertTrue(glove_readiness_errors({"formProfile": profile, "coverageMatrix": [], "surfaceRegionEvidence": []}))
        profile.update({"kind": "fingerless", "classificationState": "observed"})
        profile["digitTopology"] = [{"id": "index-cut", "opening": "open-cut", "path": "curved", "evidenceRefs": ["thumb"]}]
        coverage = [{"ownerId": "index-cut", "sourceViewId": "thumb", "sourceHash": "a" * 64, "cropDigest": "b" * 64, "visibility": "visible", "state": "covered", "renderCameras": ["finger-detail"]}]
        surface = [{"id": "palmar-grip", "sourceCropDigest": "c" * 64, "comparisonMaskDigest": "d" * 64, "orientation": "palmar", "projectionTransform": {"kind": "uv"}, "channels": {"baseColor": "e" * 64, "normal": "f" * 64, "roughness": "g" * 64}}]
        self.assertEqual(glove_readiness_errors({"formProfile": profile, "coverageMatrix": coverage, "surfaceRegionEvidence": surface}), [])
        self.assertTrue(glove_readiness_errors({"formProfile": profile, "coverageMatrix": coverage, "surfaceRegionEvidence": [{**surface[0], "orientation": "mirrored"}]}))

    def test_profile_capture_plan_grows_from_critical_coverage(self):
        coverage = [
            {"ownerId": "curved-index", "sourceViewId": "side", "sourceHash": "a" * 64, "cropDigest": "b" * 64, "visibility": "visible", "state": "covered", "renderCameras": ["finger-detail-left"]},
            {"ownerId": "dorsal-pattern", "sourceViewId": "dorsal", "sourceHash": "c" * 64, "cropDigest": "d" * 64, "visibility": "visible", "state": "covered", "renderCameras": ["dorsal", "back-pattern-detail"]},
        ]
        plan = derive_profile_capture_plan(coverage)
        by_role = {item["role"]: item for item in plan}
        self.assertIn("finger-detail-left", by_role)
        self.assertIn("back-pattern-detail", by_role)
        self.assertEqual(by_role["finger-detail-left"]["owners"], ["curved-index"])
        with self.assertRaises(ValueError):
            derive_profile_capture_plan([{**coverage[0], "state": "missing"}])

    def test_canonical_panel_extrusion_is_non_degenerate_but_diagnostic(self):
        geometry = build_glove_geometry(build_glove_assembly())
        self.assertEqual(validate_geometry_report(geometry, require_production=False), [])
        self.assertTrue(validate_geometry_report(geometry))
        for mesh in geometry["meshes"]:
            self.assertIn("indices", mesh)
            self.assertNotIn("faces", mesh)
            self.assertGreaterEqual(mesh["measurements"]["minimumThickness"], 0.01)
            self.assertEqual(mesh["measurements"]["zeroAreaTriangleCount"], 0)

    def test_v2_bundle_and_report_are_portable_and_reject_traversal(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bundle_path, report_path = build_bundle_from_assembly(build_glove_assembly(), root / "bundle")
            bundle = verify_model_bundle(bundle_path)
            report = verify_geometry_report(report_path, bundle_path)
            self.assertEqual(report["modelBundlePath"], bundle_path.name)
            forged = json.loads(bundle_path.read_text(encoding="utf-8"))
            forged["factoryModule"]["path"] = "../factory/glove_factory.mjs"
            forged["rootDigest"] = canonical_hash({key: value for key, value in forged.items() if key != "rootDigest"})
            bundle_path.write_text(json.dumps(forged), encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_model_bundle(bundle_path)

    def test_report_claims_are_bound_to_the_verified_bundle(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bundle_path, report_path = build_bundle_from_assembly(build_glove_assembly(), root / "bundle")
            forged = json.loads(report_path.read_text(encoding="utf-8"))
            forged["evidenceTier"] = "evidence-backed"
            forged["reportDigest"] = canonical_hash({key: value for key, value in forged.items() if key != "reportDigest"})
            report_path.write_text(json.dumps(forged), encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_geometry_report(report_path, bundle_path)

    def test_runtime_loads_factory_but_emits_pending_plan_not_fake_pixels(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bundle_path, _report_path = build_bundle_from_assembly(build_glove_assembly(), root / "bundle")
            capture_path = root / "capture-plan.json"
            subprocess.run(["node", str(ROOT / "runtime" / "glove-review" / "src" / "index.mjs"), str(bundle_path), str(capture_path)], check=True, cwd=ROOT)
            capture = json.loads(capture_path.read_text(encoding="utf-8"))
            self.assertEqual(capture["version"], "capture-manifest.v2")
            self.assertFalse(capture["finalized"])
            self.assertTrue(all(item["status"] == "pending-render" for item in capture["captures"]))

    def test_scalar_metrics_and_valid_flag_cannot_make_diagnostic_artifact_ready(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bundle_path, report_path = build_bundle_from_assembly(build_glove_assembly(), root / "bundle")
            capture_path = root / "capture-plan.json"
            subprocess.run(["node", str(ROOT / "runtime" / "glove-review" / "src" / "index.mjs"), str(bundle_path), str(capture_path)], check=True, cwd=ROOT)
            artifacts = {"artifactRoot": str(root), "modelBundlePath": "bundle/glove-model-bundle.v2.json", "geometryReport": "bundle/geometry-report.v2.json", "captureManifest": "capture-plan.json", "artifactChain": {"valid": True}, **{key: 1.0 for key in build_calibrated_scene()["thresholds"]}}
            report = evaluate_glove_review(_manifest(), artifacts, build_calibrated_scene())
            self.assertEqual(report["verdict"], "reject")
            self.assertEqual(report["action"], "request-input")
            self.assertIn("evidence-tier:diagnostic", report["failedGates"])
            self.assertIn("runtime:capture-manifest-not-finalized", report["failedGates"])

    def test_verified_threejs_pixels_finalize_evidence_but_do_not_upgrade_diagnostic_geometry(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bundle_path, geometry_path = build_bundle_from_assembly(build_glove_assembly(), root / "bundle")
            scene = build_calibrated_scene()
            scene_path = root / "scene.json"
            scene_path.write_text(json.dumps(scene), encoding="utf-8")
            viewer = root / "viewer.html"
            subprocess.run(["node", str(ROOT / "runtime" / "glove-review" / "src" / "index.mjs"), "--viewer", str(bundle_path), str(viewer)], check=True, cwd=ROOT)
            server = subprocess.Popen(["node", str(ROOT / "runtime" / "glove-review" / "serve.mjs"), str(root)], stdout=subprocess.PIPE, text=True)
            try:
                runtime_url = server.stdout.readline().strip()
                self.assertTrue(runtime_url.startswith("http://127.0.0.1:"))
                bridge_path = root / "bridge.json"
                write_manifest(bridge_path, init_glove_capture_manifest(bundle_path, FIXTURE / "dorsal.png", f"{runtime_url}/viewer.html", bridge_path, scene))
                result = capture(bridge_path, [], False, 30000, "procedural")
                self.assertEqual(result["consoleErrors"], [])
                repeat_bridge_path = root / "bridge-repeat.json"
                write_manifest(repeat_bridge_path, init_glove_capture_manifest(bundle_path, FIXTURE / "dorsal.png", f"{runtime_url}/viewer.html", repeat_bridge_path, scene, capture_dir="captures-repeat"))
                self.assertEqual(capture(repeat_bridge_path, [], False, 30000, "procedural")["consoleErrors"], [])
                evidence_path = root / "capture-manifest.v2.json"
                evidence = finalize_glove_capture_manifest(bridge_path, repeat_bridge_path, bundle_path, scene, evidence_path)
                self.assertTrue(evidence["finalized"])
                self.assertEqual(len(evidence["captures"]), 7)
                self.assertTrue(all(item["browserSnapshot"]["nonBackgroundPixels"] > 0 for item in evidence["captures"]))
                review = evaluate_glove_review(_manifest(), {"artifactRoot": str(root), "modelBundlePath": "bundle/glove-model-bundle.v2.json", "geometryReport": "bundle/geometry-report.v2.json", "captureManifest": "capture-manifest.v2.json"}, scene)
                self.assertEqual(review["verdict"], "reject")
                self.assertEqual(review["metrics"]["runtimeDeterministic"]["value"], 1.0)
                self.assertEqual(review["action"], "request-input")
                repeated = json.loads(repeat_bridge_path.read_text(encoding="utf-8"))
                repeated["captures"][0]["screenshotSha256"] = "0" * 64
                repeat_bridge_path.write_text(json.dumps(repeated), encoding="utf-8")
                with self.assertRaises(ValueError):
                    finalize_glove_capture_manifest(bridge_path, repeat_bridge_path, bundle_path, scene, root / "forged-capture-manifest.v2.json")
            finally:
                server.terminate()
                server.wait(timeout=10)
                assert server.stdout is not None
                server.stdout.close()


if __name__ == "__main__":
    unittest.main()
