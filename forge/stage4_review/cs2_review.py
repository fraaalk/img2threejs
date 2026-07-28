from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from forge.stage2_spec.cs2_adapters import resolve_family_adapter  # noqa: E402
from forge.stage1_intake.cs2_manifest import validate_glove_multiview  # noqa: E402

REQUIRED_SCENE_KEYS = {
    "version",
    "fixtureId",
    "reference",
    "identity",
    "camera",
    "transform",
    "environment",
    "resolution",
    "background",
    "rendererVersion",
    "calibration",
    "thresholds",
}
REQUIRED_THRESHOLDS = {
    "silhouetteIoU",
    "aspectRatioDelta",
    "scaleDelta",
    "projectionCoverage",
    "finishMaterialResponse",
    "identityDetail",
    "paintedRegion",
    "maxOrbitCollapseRatio",
}
GLOVE_CAPTURE_IDS = frozenset({"left-dorsal", "left-palmar", "right-dorsal", "right-palmar", "left-orbit-35", "right-orbit-35"})


def _glove_scene(scene: dict[str, Any]) -> bool:
    resolution = scene.get("resolution")
    return (
        scene.get("version") == "glove-review-scene-v1"
        and isinstance(resolution, dict)
        and resolution.get("width") == 1600
        and resolution.get("height") == 1000
        and isinstance(scene.get("captureMasks"), dict)
        and isinstance(scene.get("sourceHashes"), dict)
    )


def evaluate_glove_review(manifest: dict[str, Any], review_scene: dict[str, Any], captures: dict[str, Any]) -> dict[str, Any]:
    failed: list[str] = []
    validation_error = validate_glove_multiview(manifest)
    if validation_error is not None:
        failed.append(validation_error)
    if not _glove_scene(review_scene):
        failed.append("GLOVE_REVIEW_SCENE_INVALID")
    resolved_identity = manifest.get("resolvedIdentity")
    identity = resolved_identity if isinstance(resolved_identity, dict) else manifest
    if identity.get("itemFamily") != "glove" or manifest.get("componentAdapter") != "cs2-glove-v1":
        failed.append("GLOVE_HAND_MISMATCH")
    if set(captures) != GLOVE_CAPTURE_IDS:
        failed.append("GLOVE_MISSING_VIEW")
    fixed_pairs = {"left-dorsal": ("left", "dorsal", [0, 0, 1]), "left-palmar": ("left", "palmar", [0, 0, -1]), "right-dorsal": ("right", "dorsal", [0, 0, 1]), "right-palmar": ("right", "palmar", [0, 0, -1])}
    for capture_id, (hand, role, position) in fixed_pairs.items():
        capture = captures.get(capture_id)
        if not isinstance(capture, dict):
            continue
        if capture.get("hand") != hand:
            failed.append("GLOVE_HAND_MISMATCH")
        if capture.get("role") != role:
            failed.append("GLOVE_SURFACE_SWAP")
        if capture.get("cameraPosition") != position or capture.get("inspectionRotationY") not in {None, 0}:
            failed.append("GLOVE_SURFACE_SWAP")
        region_coverage = capture.get("regionCoverage")
        if not isinstance(region_coverage, dict) or any(not _number(value) or not isinstance(value, (int, float)) or float(value) < 0.95 for value in region_coverage.values()):
            failed.append("GLOVE_MISSING_VIEW")
        required_occupancy = capture.get("requiredOccupancy")
        if not isinstance(required_occupancy, dict) or any(not _number(value) or not isinstance(value, (int, float)) or float(value) < 0.98 for value in required_occupancy.values()):
            failed.append("GLOVE_REQUIRED_DIGIT_NOT_OBSERVED")
        if capture.get("textureOwnership") != 1:
            failed.append("GLOVE_TEXTURE_OWNERSHIP_CONFLICT")
        if capture.get("reversedFacePixels") != 0:
            failed.append("GLOVE_REVERSED_CULLING")
    for capture_id in ("left-orbit-35", "right-orbit-35"):
        capture = captures.get(capture_id)
        silhouette_xor = capture.get("silhouetteXor") if isinstance(capture, dict) else None
        normal_direction_change = capture.get("normalDirectionChange") if isinstance(capture, dict) else None
        if not isinstance(capture, dict) or not isinstance(silhouette_xor, (int, float)) or isinstance(silhouette_xor, bool) or silhouette_xor < 0.05 or not isinstance(normal_direction_change, (int, float)) or isinstance(normal_direction_change, bool) or normal_direction_change < 0.10:
            failed.append("GLOVE_DEGENERATE_ORBIT")
    failed = list(dict.fromkeys(failed))
    return {
        "verdict": "pass" if not failed else "reject",
        "action": "continue" if not failed else "request-input",
        "family": "glove",
        "reviewScene": review_scene,
        "captures": captures,
        "failedGates": failed,
    }


def load_review_scene(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("review scene must be a JSON object")
    if payload.get("version") == "cs2-knife-review-v1":
        payload = {
            "version": 1,
            "fixtureId": "cs2-knife-front-v1",
            "rightsSafeStatus": "legacy-knife-fixture",
            "reference": "legacy://knife-review-scene",
            "identity": {"family": "knife", "subtype": "karambit", "adapterId": "cs2-knife-v1"},
            "camera": payload.get("camera", {}),
            "transform": payload.get("objectTransform", {}),
            "environment": {"hash": payload.get("environmentHash", "legacy-knife-environment"), "exposure": payload.get("exposure", 0), "toneMapping": payload.get("toneMapping", "ACESFilmic")},
            "resolution": payload.get("resolution", {"width": 1024, "height": 1024}),
            "background": payload.get("background", "neutral-white"),
            "rendererVersion": payload.get("rendererVersion", "legacy-knife-runtime"),
            "calibration": {"status": "calibrated", "positiveFixtures": ["knife-positive-v1"], "negativeFixtures": ["knife-negative-v1"]},
            "thresholds": {
                "silhouetteIoU": 0.85, "aspectRatioDelta": 0.05, "scaleDelta": 0.08,
                "projectionCoverage": 0.85, "finishMaterialResponse": 0.8,
                "identityDetail": 0.8, "paintedRegion": 0.8, "maxOrbitCollapseRatio": 0.15,
            },
        }
    missing = REQUIRED_SCENE_KEYS - payload.keys()
    if missing:
        raise ValueError("review scene is missing: " + ", ".join(sorted(missing)))
    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, dict) or not REQUIRED_THRESHOLDS.issubset(thresholds):
        raise ValueError("review scene thresholds are incomplete")
    if payload.get("version") != 1:
        raise ValueError("unsupported review scene version")
    return payload


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _failed_threshold(metrics: dict[str, Any], key: str, threshold: float, *, maximum: bool) -> bool:
    value = metrics.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return True
    return value > threshold if maximum else value < threshold


def _region_results(inputs: dict[str, Any], threshold: float) -> tuple[list[dict[str, Any]], list[str]]:
    raw = inputs.get("paintedRegions", [])
    if not isinstance(raw, list):
        return [], ["painted-regions-invalid"]
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for region in raw:
        if not isinstance(region, dict) or not isinstance(region.get("id"), str):
            failures.append("painted-region-invalid")
            continue
        score = region.get("score")
        confidence = region.get("confidence")
        result = {"id": region["id"], "score": score, "confidence": confidence}
        results.append(result)
        if not _number(score) or not isinstance(score, (int, float)) or score < threshold:
            failures.append(f"painted-region:{region['id']}")
        if not _number(confidence):
            failures.append(f"painted-region-confidence:{region['id']}")
    return results, failures


def _critical_feature_failures(inputs: dict[str, Any], default_threshold: float) -> list[str]:
    raw = inputs.get("criticalFeatures", [])
    if not isinstance(raw, list):
        return ["critical-features-invalid"]
    failures: list[str] = []
    for feature in raw:
        if not isinstance(feature, dict) or not isinstance(feature.get("id"), str):
            failures.append("critical-feature-invalid")
            continue
        threshold = feature.get("threshold", default_threshold)
        if not _number(feature.get("score")) or not _number(threshold):
            failures.append(f"critical-feature:{feature['id']}")
        elif float(feature["score"]) < float(threshold):
            failures.append(f"critical-feature:{feature['id']}")
    return failures


def evaluate_family_review(
    manifest: dict[str, Any],
    inputs: dict[str, Any],
    review_scene: dict[str, Any],
    expected_family: str | None = None,
) -> dict[str, Any]:
    thresholds = review_scene["thresholds"]
    failed: list[str] = []
    resolved_identity = manifest.get("resolvedIdentity")
    identity = resolved_identity if isinstance(resolved_identity, dict) else manifest
    family = identity.get("itemFamily")
    subtype = identity.get("subtype")
    if expected_family is not None and family != expected_family:
        failed.append(f"unsupported-family:{family or 'missing'}")
    try:
        adapter = resolve_family_adapter(family, subtype) if isinstance(family, str) else None
    except ValueError as error:
        adapter = None
        failed.append(str(error))
    if adapter is not None and manifest.get("componentAdapter") != adapter.adapter_id:
        failed.append("adapter-mismatch")
    scene_identity = review_scene.get("identity")
    fixture_identity = scene_identity if isinstance(scene_identity, dict) else {}
    if fixture_identity.get("family") != family or (fixture_identity.get("subtype") and fixture_identity.get("subtype") != subtype):
        failed.append("fixture-identity-mismatch")
    if fixture_identity.get("adapterId") and fixture_identity.get("adapterId") != manifest.get("componentAdapter"):
        failed.append("fixture-adapter-mismatch")
    if manifest.get("state") != "proceed":
        failed.append(f"manifest-state:{manifest.get('state', 'missing')}")
    calibration = review_scene.get("calibration")
    if not isinstance(calibration, dict) or calibration.get("status") != "calibrated" or not calibration.get("positiveFixtures") or not calibration.get("negativeFixtures"):
        failed.append("calibration-incomplete")

    for key in ("silhouetteIoU", "aspectRatioDelta", "scaleDelta"):
        maximum = key != "silhouetteIoU"
        if _failed_threshold(inputs, key, float(thresholds[key]), maximum=maximum):
            failed.append(key)
    for key in ("finishMaterialResponse", "identityDetail"):
        if _failed_threshold(inputs, key, float(thresholds[key]), maximum=False):
            failed.append(key)

    region_results, region_failures = _region_results(inputs, float(thresholds["paintedRegion"]))
    failed.extend(region_failures)
    failed.extend(_critical_feature_failures(inputs, float(thresholds["identityDetail"])))

    projection = inputs.get("projection")
    if manifest.get("route") == "reference-projection":
        if not isinstance(projection, dict) or projection.get("required") is not True:
            failed.append("projection-evidence-missing")
        elif _failed_threshold(projection, "coverage", float(thresholds["projectionCoverage"]), maximum=False):
            failed.append("projection-coverage")

    multi_angle = inputs.get("multiAngle")
    if not isinstance(multi_angle, dict) or multi_angle.get("degenerate") is True:
        failed.append("degenerate-orbit")
    elif len(multi_angle.get("angles", [])) < 2:
        failed.append("orbit-coverage-missing")
    elif _failed_threshold(multi_angle, "collapseRatio", float(thresholds["maxOrbitCollapseRatio"]), maximum=True):
        failed.append("orbit-collapse-ratio")

    notes = manifest.get("approximationNotes", inputs.get("approximationNotes", []))
    approximation_notes = [str(note) for note in notes] if isinstance(notes, list) else []
    hidden_confidence = manifest.get("confidence", {}).get("hiddenRegions")
    report = {
        "verdict": "pass" if not failed else "reject",
        "action": "continue" if not failed else ("request-input" if any(
            item.startswith(("unsupported-family", "manifest-state", "projection-evidence", "orbit-coverage"))
            for item in failed
        ) else "refine-code"),
        "family": family,
        "subtype": subtype,
        "exactnessTier": manifest.get("exactnessTier"),
        "route": manifest.get("route"),
        "reviewScene": {
            "version": review_scene["version"],
            "fixtureId": review_scene["fixtureId"],
            "camera": review_scene["camera"],
            "transform": review_scene["transform"],
            "environment": review_scene["environment"],
            "resolution": review_scene["resolution"],
            "background": review_scene["background"],
            "rendererVersion": review_scene["rendererVersion"],
            "calibration": review_scene["calibration"],
        },
        "metrics": inputs,
        "paintedRegions": region_results,
        "perRegionConfidence": {region["id"]: region["confidence"] for region in region_results},
        "hiddenRegionConfidence": hidden_confidence,
        "approximationNotes": approximation_notes,
        "failedGates": failed,
    }
    return report


def evaluate_knife_review(
    manifest: dict[str, Any],
    inputs: dict[str, Any],
    review_scene: dict[str, Any],
) -> dict[str, Any]:
    return evaluate_family_review(manifest, inputs, review_scene, expected_family="knife")
