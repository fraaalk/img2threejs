"""Fail-closed v3 evaluator for evidence-backed glove artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from forge.stage1_intake.glove_contracts import glove_manifest_errors, glove_readiness_errors
from forge.stage2_spec.glove_assembly import canonical_hash
from forge.stage2_spec.validate_sculpt_spec import validate_spec
from forge.stage3_build.glove_artifacts import load_verified_meshes, verify_geometry_report
from forge.stage3_build.glove_geometry import validate_geometry_report
from forge.stage4_review.capture_sanity import check as capture_sanity_check
from forge.stage4_review.capture_sanity import measure as capture_sanity_measure
from forge.stage4_review.geometry_integrity import measure_geometry_integrity
from forge.stage4_review.glove_surface_gates import validate_glove_surface_contract
from forge.stage4_review.pairwise_penetration import analyze_meshes

REPORT_VERSION: Final[str] = "glove-review-report.v3"

# Each entry is one independent measurement. Concerns that cannot be measured yet are listed in
# UNMEASURED_CONCERNS instead of being published as a derived value that would read as a result.
METRIC_KINDS: Final[dict[str, str]] = {
    "provenanceVerified": "boolean",
    "topologyReady": "boolean",
    "handednessCorrect": "boolean",
    "finiteGeometry": "boolean",
    "selfIntersectionFree": "boolean",
    "penetrationFree": "boolean",
    "minimumThicknessMeasured": "boolean",
    "uvMaterialOwnership": "boolean",
    "runtimeDeterministic": "boolean",
}
UNMEASURED_CONCERNS: Final[dict[str, str]] = {
    "seamBoundaryCorrespondence": "seam topology has not been emitted; a production weld stage must supply shared vertices",
    "productionManifold": "production seam welding has not been emitted, so manifoldness cannot be measured",
    "referenceResemblance": "the wearable track makes no claim about resemblance to the reference image; see the glove-reference-conformance follow-up",
}
# The azimuth-90 capture renders the flat panel slabs edge-on, collapsing the foreground mask to
# whole-frame coverage. That is a stage-3 geometry defect, recorded rather than scored.
QUARANTINED_CAPTURE_ROLES: Final[dict[str, str]] = {
    "thumb-side-profile": "azimuth-90 render collapses to near-zero-width slivers and the foreground mask falls back to whole-frame; stage-3 geometry defect",
}
REQUIRED_CAPTURE_ROLES = {"dorsal", "palmar", "thumb-side-profile", "left-three-quarter", "right-three-quarter"}
REQUIRED_RENDER_ENVIRONMENT = {
    "viewport": [1024, 1024], "devicePixelRatio": 1, "settleFrames": 2,
    "renderer": "WebGLRenderer", "threeRevision": "185", "antialias": False,
    "preserveDrawingBuffer": True, "clearColor": "#ffffff",
}
VALID_THRESHOLD_STATUSES = frozenset({"uncalibrated", "verified-artifact-calibration-v2"})


def build_uncalibrated_scene() -> dict[str, Any]:
    return {
        "version": "glove-review-scene-v2", "thresholdStatus": "uncalibrated",
        "fixtureId": "sport-gloves-diagnostic-v1", "requiredViewRoles": sorted(REQUIRED_CAPTURE_ROLES),
        "cameras": [{"id": role, "role": role, "azimuth": angle, "elevation": 8.0, "viewport": [1024, 1024]} for role, angle in (("dorsal", 0), ("palmar", 180), ("thumb-side-profile", 90), ("three-quarter", 35), ("left-three-quarter", 35), ("right-three-quarter", -35), ("orbit-a", 120), ("orbit-b", -120))],
        "environment": {"hash": "glove-qa-neutral-v2", "toneMapping": "ACESFilmic", "exposure": 0.0},
        "rendererVersion": "browser-render-bridge-required-v2", "resolution": {"width": 1024, "height": 1024},
        "background": "neutral-white", "thresholds": {},
    }


def validate_glove_scene(scene: Any, *, calibrated: bool | None = None) -> list[str]:
    if not isinstance(scene, dict):
        return ["glove review scene must be an object"]
    required = {"version", "thresholdStatus", "fixtureId", "requiredViewRoles", "cameras", "environment", "rendererVersion", "resolution", "background", "thresholds"}
    errors = [f"missing scene field: {field}" for field in sorted(required - set(scene))]
    if scene.get("version") != "glove-review-scene-v2":
        errors.append("v2 glove review scene is required")
    if scene.get("thresholdStatus") not in VALID_THRESHOLD_STATUSES:
        errors.append("scene thresholdStatus must be uncalibrated or verified-artifact-calibration-v2")
    if not REQUIRED_CAPTURE_ROLES.issubset(set(scene.get("requiredViewRoles", []))):
        errors.append("scene requiredViewRoles is incomplete")
    if not isinstance(scene.get("cameras"), list) or len(scene["cameras"]) < 8:
        errors.append("scene must define required and orbit cameras")
    if calibrated is True:
        if scene.get("thresholdStatus") != "verified-artifact-calibration-v2":
            errors.append("only verified artifact calibration may authorize readiness")
        if set(scene.get("thresholds", {}) if isinstance(scene.get("thresholds"), dict) else {}) != set(METRIC_KINDS):
            errors.append("calibrated scene thresholds must match the evaluator metric set exactly")
    return errors


def _load_json(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _metric(value: float, source: dict[str, Any]) -> dict[str, Any]:
    return {"value": float(value), "status": "measured", "unit": "ratio", "source": source, "computation": "glove-review-v3-artifact-derived"}


def _derived_metrics(report: dict[str, Any], bundle: dict[str, Any], capture: dict[str, Any], meshes: list[dict[str, Any]], provenance_verified: bool, production_valid: bool, handedness_ok: bool) -> dict[str, dict[str, Any]]:
    structural = measure_geometry_integrity({"meshes": meshes})
    collision = analyze_meshes(meshes)
    meshes_by_hand: dict[str, list[dict[str, Any]]] = {"left": [], "right": []}
    for mesh in meshes:
        hand = mesh.get("hand")
        if hand in meshes_by_hand:
            meshes_by_hand[hand].append(mesh)
    # A production glove must emit a single, topology-joined shell per hand. This
    # intentionally refuses any report declaration to stand in for an actual weld.
    joined_shells = all(len(meshes_by_hand[hand]) == 1 for hand in meshes_by_hand)
    mesh_integrity = {item.get("id"): item for item in structural.get("meshes", []) if isinstance(item, dict)}
    normals_valid = all(mesh_integrity.get(mesh.get("id"), {}).get("normalConsistency", {}).get("consistent") is True for mesh in meshes)
    topology_ready = bool(production_valid and joined_shells and structural.get("passed") is True and normals_valid)
    source = {"geometryReportDigest": report.get("reportDigest"), "modelBundleDigest": bundle.get("rootDigest"), "captureManifestDigest": capture.get("manifestDigest")}
    values = {
        "provenanceVerified": float(provenance_verified),
        "topologyReady": float(topology_ready),
        "handednessCorrect": float(handedness_ok),
        "finiteGeometry": float(all(all(isinstance(value, (int, float)) and value == value and abs(value) != float("inf") for vertex in mesh.get("vertices", []) for value in vertex) for mesh in meshes)),
        "selfIntersectionFree": float(all(not item.get("selfIntersection", {}).get("selfIntersecting", True) for item in structural.get("meshes", [])) and not any("self-intersection" in item for item in structural.get("failures", []))),
        "penetrationFree": float(collision.get("passed") is True and not collision.get("skippedMeshes")),
        "minimumThicknessMeasured": float(all(mesh.get("measurements", {}).get("minimumThickness", 0.0) >= 0.01 for mesh in meshes if isinstance(mesh, dict))),
        "uvMaterialOwnership": float(all(isinstance(mesh.get("uv0"), list) and mesh.get("material") for mesh in meshes if isinstance(mesh, dict))),
        "runtimeDeterministic": float(capture.get("finalized") is True and capture.get("repeatVerified") is True),
    }
    return {key: _metric(values[key], source) for key in METRIC_KINDS if key in values}


def _capture_precondition_failures(root: Path, capture: dict[str, Any]) -> list[str]:
    """Run the framing pre-flight as a precondition; a framing defect is never a model defect."""
    failures: list[str] = []
    for item in capture.get("captures", []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "unknown"))
        if role in QUARANTINED_CAPTURE_ROLES:
            continue
        path_value = item.get("path")
        if not isinstance(path_value, str):
            continue
        png = (root / path_value).resolve()
        if not png.is_file():
            continue
        for reason in capture_sanity_check(capture_sanity_measure(png), None):
            failures.append(f"capture-sanity:{role}:{reason}")
    return failures


def _verify_capture_manifest(capture_path: Path, bundle: dict[str, Any], scene: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    capture = _load_json(capture_path, "captureManifest")
    failures: list[str] = []
    unsigned = dict(capture)
    recorded_digest = unsigned.pop("manifestDigest", None)
    if recorded_digest != canonical_hash(unsigned):
        failures.append("artifact-chain:capture-manifest-digest-mismatch")
    if capture.get("version") != "capture-manifest.v2" or capture.get("modelBundleDigest") != bundle["rootDigest"]:
        failures.append("artifact-chain:capture-manifest-bundle-mismatch")
    if capture.get("sceneVersion") != scene.get("version"):
        failures.append("artifact-chain:capture-manifest-scene-mismatch")
    if capture.get("sceneDigest") != canonical_hash(scene):
        failures.append("artifact-chain:capture-manifest-scene-digest-mismatch")
    scene_artifact = capture.get("sceneArtifact")
    if not isinstance(scene_artifact, dict):
        failures.append("artifact-chain:scene-artifact-missing")
    else:
        try:
            scene_path = _artifact_path(capture_path.parent.resolve(), scene_artifact.get("path"), "sceneArtifact")
            if scene_artifact.get("sha256") != canonical_hash(_load_json(scene_path, "sceneArtifact")) or _load_json(scene_path, "sceneArtifact") != scene:
                failures.append("artifact-chain:scene-artifact-mismatch")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            failures.append(f"artifact-chain:scene-artifact-invalid:{error}")
    if capture.get("finalized") is not True:
        failures.append("runtime:capture-manifest-not-finalized")
        return capture, failures
    if capture.get("repeatVerified") is not True:
        failures.append("runtime:repeat-capture-not-verified")
    captures = capture.get("captures")
    if not isinstance(captures, list):
        return capture, failures + ["runtime:capture-list-missing"]
    roles = {item.get("role") for item in captures if isinstance(item, dict)}
    missing = sorted(REQUIRED_CAPTURE_ROLES - roles)
    if missing:
        failures.append("capture-missing:" + ",".join(missing))
    if sum(1 for item in captures if isinstance(item, dict) and str(item.get("role", "")).startswith("orbit-")) < 2:
        failures.append("capture-orbit-coverage")
    root = capture_path.parent.resolve()
    for item in captures:
        if not isinstance(item, dict):
            failures.append("runtime:invalid-capture-record")
            continue
        if item.get("modelBundleDigest") != bundle["rootDigest"]:
            failures.append(f"runtime:capture-bundle-mismatch:{item.get('id', 'unknown')}")
        path_value = item.get("path")
        if not isinstance(path_value, str) or Path(path_value).is_absolute() or ".." in Path(path_value).parts:
            failures.append(f"runtime:capture-path-invalid:{item.get('id', 'unknown')}")
            continue
        png = (root / path_value).resolve()
        try:
            png.relative_to(root)
        except ValueError:
            failures.append(f"runtime:capture-path-escapes:{item.get('id', 'unknown')}")
            continue
        if not png.is_file() or _sha256(png) != item.get("sha256"):
            failures.append(f"runtime:capture-hash-invalid:{item.get('id', 'unknown')}")
        image = item.get("image")
        snapshot = item.get("browserSnapshot")
        actual_pixels = 0
        if png.is_file():
            try:
                with Image.open(png) as rendered:
                    actual_pixels = sum(1 for red, green, blue, alpha in rendered.convert("RGBA").getdata() if alpha > 0 and (red < 248 or green < 248 or blue < 248))
            except OSError:
                failures.append(f"runtime:capture-unreadable:{item.get('id', 'unknown')}")
                continue
        if (
            not isinstance(image, dict) or image.get("width") != 1024 or image.get("height") != 1024
            or not isinstance(snapshot, dict) or snapshot.get("nonBackgroundPixels") != actual_pixels or actual_pixels <= 0
            or not isinstance(snapshot.get("renderEnvironment"), dict)
            or any(snapshot["renderEnvironment"].get(key) != value for key, value in REQUIRED_RENDER_ENVIRONMENT.items())
        ):
            failures.append(f"runtime:capture-pixels-invalid:{item.get('id', 'unknown')}")
    return capture, failures


def _artifact_path(root: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or any(part in {"", ".", ".."} for part in Path(value).parts):
        raise ValueError(f"{field} must be a root-relative path")
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} escapes artifact root") from exc
    if not candidate.is_file() or candidate.is_symlink():
        raise ValueError(f"{field} is missing or a symlink")
    return candidate


def _verify_bundle_provenance(bundle: dict[str, Any], bundle_path: Path, manifest: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    """Re-resolve and re-hash upstream provenance, returning the recovered spec when present."""
    upstream = bundle.get("upstream")
    if not isinstance(upstream, dict) or not upstream:
        if bundle.get("evidenceTier") != "evidence-backed":
            return False, None
        raise ValueError("evidence-backed model bundle upstream provenance is missing")
    sources: dict[str, dict[str, Any]] = {}
    for name in ("manifest", "assessment", "assembly", "spec"):
        record = upstream.get(name)
        if not isinstance(record, dict):
            raise ValueError(f"model bundle upstream {name} is missing")
        path = _artifact_path(bundle_path.parent.resolve(), record.get("path"), f"upstream.{name}")
        payload = _load_json(path, f"upstream.{name}")
        if record.get("sha256") != canonical_hash(payload):
            raise ValueError(f"model bundle upstream {name} digest mismatch")
        sources[name] = payload
    if sources["manifest"] != manifest:
        raise ValueError("provided manifest does not match the root-contained admitted manifest")
    return True, sources["spec"]


def _spec_failures(spec: dict[str, Any] | None) -> list[str]:
    """Digest binding proves the spec is the builder's; it does not prove the spec is valid."""
    if spec is None:
        return ["surface-contract:spec-unavailable"]
    failures: list[str] = []
    errors, _warnings = validate_spec(spec)
    failures.extend(f"surface-contract:spec-invalid:{error}" for error in errors)
    routing = spec.get("pipelineRouting")
    if not isinstance(routing, dict) or routing.get("track") != "wearable-v1.0":
        failures.append("surface-contract:spec-track-mismatch")
    return failures


def _threshold_failures(metrics: dict[str, dict[str, Any]], scene: Any) -> list[str]:
    thresholds = scene.get("thresholds") if isinstance(scene, dict) else None
    if not isinstance(thresholds, dict) or not thresholds:
        # No fallback to module constants: a silent default is what made these gates inert.
        return ["calibration:thresholds-absent"]
    failures: list[str] = []
    if set(thresholds) != set(METRIC_KINDS):
        failures.append("calibration:threshold-set-mismatch")
    for key in sorted(set(thresholds) & set(METRIC_KINDS)):
        record = thresholds[key]
        kind = record.get("kind") if isinstance(record, dict) else None
        raw = record.get("threshold") if isinstance(record, dict) else None
        if (
            kind != METRIC_KINDS[key]
            or not isinstance(raw, (int, float)) or isinstance(raw, bool)
            or raw != raw or abs(float(raw)) == float("inf") or not 0.0 <= float(raw) <= 1.0
            or (kind == "boolean" and float(raw) != 1.0)
        ):
            failures.append(f"calibration:threshold-invalid:{key}")
            continue
        metric = metrics.get(key)
        if not metric or metric.get("status") != "measured":
            continue
        if kind == "boolean":
            if float(metric["value"]) != 1.0:
                failures.append(key)
        elif float(metric["value"]) < float(raw):
            failures.append(key)
    return failures


def _calibration_provenance_failures(scene: Any, root: Path | None, bundle: dict[str, Any], report: dict[str, Any], capture: dict[str, Any]) -> list[str]:
    if not isinstance(scene, dict) or scene.get("thresholdStatus") != "verified-artifact-calibration-v2":
        return []
    calibration = scene.get("calibration")
    digests = calibration.get("artifactDigests") if isinstance(calibration, dict) else None
    expected = {
        "modelBundleDigest": bundle.get("rootDigest"),
        "geometryReportDigest": report.get("reportDigest"),
        "captureManifestDigest": capture.get("manifestDigest"),
    }
    if not isinstance(digests, dict) or not digests or any(digests.get(key) != value for key, value in expected.items()):
        return ["calibration:threshold-provenance-unbound"]
    record = calibration.get("measurements") if isinstance(calibration, dict) else None
    if not isinstance(record, dict) or root is None:
        return ["calibration:measurements-unbound"]
    try:
        path = _artifact_path(root, record.get("path"), "calibration.measurements")
        if record.get("sha256") != canonical_hash(_load_json(path, "calibration.measurements")):
            return ["calibration:measurements-digest-mismatch"]
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"calibration:measurements-invalid:{error}"]
    return []


def evaluate_glove_review(manifest: dict[str, Any], artifacts: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any]:
    failed: list[str] = []
    if manifest.get("itemFamily") != "glove":
        failed.append(f"unsupported-family:{manifest.get('itemFamily', 'missing')}")
    if manifest.get("subtype") != "sport-gloves":
        failed.append(f"unsupported-subtype:{manifest.get('subtype', 'missing')}")
    failed.extend(f"intake:{error}" for error in glove_manifest_errors(manifest, require_complete_views=True))
    failed.extend(f"coverage:{error}" for error in glove_readiness_errors(manifest.get("extensions", {}).get("glove")))
    bundle: dict[str, Any] = {}
    report: dict[str, Any] = {}
    capture: dict[str, Any] = {}
    metrics: dict[str, dict[str, Any]] = {}
    root: Path | None = None
    # Every derivation and every threshold read happens inside this boundary: an unreadable
    # image or a malformed threshold must become a named failure, never a traceback.
    try:
        root = Path(artifacts["artifactRoot"]).expanduser().resolve()
        if not root.is_dir() or root.is_symlink():
            raise ValueError("artifactRoot must be a real directory")
        bundle_path = _artifact_path(root, artifacts["modelBundlePath"], "modelBundlePath")
        report_path = _artifact_path(root, artifacts["geometryReport"], "geometryReport")
        capture_path = _artifact_path(root, artifacts["captureManifest"], "captureManifest")
        bundle, meshes = load_verified_meshes(bundle_path)
        report = verify_geometry_report(report_path, bundle_path)
        production_errors = validate_geometry_report(report, require_production=True)
        # topologyReady must measure topology alone. Where the numbers came from is already reported
        # by evidence-tier:diagnostic, and folding it in here would name an evidence verdict after a
        # topology property.
        topology_errors = validate_geometry_report(report, require_production=True, require_evidence_tier=False)
        provenance_verified, spec = _verify_bundle_provenance(bundle, bundle_path, manifest)
        capture, capture_failures = _verify_capture_manifest(capture_path, bundle, scene)
        capture_failures.extend(f"geometry-production:{error}" for error in production_errors)
        capture_failures.extend(_capture_precondition_failures(capture_path.parent.resolve(), capture))
        spec_failures = _spec_failures(spec)
        surface_errors = validate_glove_surface_contract(report, spec if isinstance(spec, dict) else {})
        capture_failures.extend(f"surface-contract:{error}" for error in surface_errors)
        capture_failures.extend(spec_failures)
        handedness_ok = spec is not None and not any(error.startswith(("handedness:", "asymmetry:", "blank-form:")) for error in surface_errors)
        metrics = _derived_metrics(report, bundle, capture, meshes, provenance_verified, not topology_errors, handedness_ok)
        failed.extend(capture_failures)
        failed.extend(_threshold_failures(metrics, scene))
        failed.extend(_calibration_provenance_failures(scene, root, bundle, report, capture))
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        failed.append(f"artifact-chain:{error}")
    failed.extend(f"metric-inconclusive:{key}" for key in sorted(METRIC_KINDS) if metrics.get(key, {}).get("status") != "measured")
    if report.get("evidenceTier") != "evidence-backed":
        failed.append("evidence-tier:diagnostic")
    if validate_glove_scene(scene, calibrated=True):
        failed.append("calibration:unverified")
    action = "ready" if not failed else ("request-input" if "evidence-tier:diagnostic" in failed or any(item.startswith("intake:") for item in failed) else "refine-code")
    output = {
        "version": REPORT_VERSION,
        "verdict": "ready" if not failed else "reject",
        "action": action,
        "family": manifest.get("itemFamily"),
        "subtype": manifest.get("subtype"),
        "modelBundleDigest": bundle.get("rootDigest"),
        "scene": {"version": scene.get("version"), "fixtureId": scene.get("fixtureId"), "thresholdStatus": scene.get("thresholdStatus")},
        "metrics": metrics,
        "unmeasured": dict(UNMEASURED_CONCERNS),
        "quarantinedCaptureRoles": dict(QUARANTINED_CAPTURE_ROLES),
        "failedGates": sorted(set(failed)),
        "evidenceTier": report.get("evidenceTier"),
    }
    output["reportDigest"] = canonical_hash(output)
    return output


def verify_review_report(review_report: Any) -> None:
    """Raise unless the payload is a self-consistent ready report this evaluator produced.

    This lives beside the producer so the digest scheme has one definition: a second
    implementation in the consumer could drift and silently reject valid reports.
    """
    if not isinstance(review_report, dict) or review_report.get("verdict") != "ready":
        raise ValueError("adapter activation requires a ready review report")
    if review_report.get("version") != REPORT_VERSION:
        raise ValueError(f"adapter activation requires a {REPORT_VERSION} review report")
    if not isinstance(review_report.get("modelBundleDigest"), str) or not review_report["modelBundleDigest"]:
        raise ValueError("adapter activation requires a model bundle digest")
    if review_report.get("failedGates"):
        raise ValueError("adapter activation requires a review report with no failed gates")
    unsigned = {key: value for key, value in review_report.items() if key != "reportDigest"}
    if review_report.get("reportDigest") != canonical_hash(unsigned):
        raise ValueError("adapter activation requires a report whose digest matches its payload")


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser().resolve(); path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate verified CS2 Sport Gloves v3 artifacts")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--artifacts", "--metrics", dest="artifacts", type=Path, required=True, help="v2 artifact locator; scalar metrics are ignored")
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = _load_json(args.manifest, "manifest")
        artifacts = _load_json(args.artifacts, "artifacts")
        scene = _load_json(args.scene, "scene")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        # Exit 2 is reserved for conditions that prevent producing a report at all.
        print(f"error: {error}", file=sys.stderr)
        return 2
    report = evaluate_glove_review(manifest, artifacts, scene)
    _write_atomic(args.out, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["verdict"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
