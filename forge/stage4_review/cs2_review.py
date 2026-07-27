from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from forge.stage2_spec.cs2_adapters import resolve_family_adapter  # noqa: E402

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
    if not _number(value):
        return True
    return float(value) > threshold if maximum else float(value) < threshold


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
        if not _number(score) or float(score) < threshold:
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
    identity = manifest.get("resolvedIdentity") if isinstance(manifest.get("resolvedIdentity"), dict) else manifest
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
    fixture_identity = review_scene.get("identity") if isinstance(review_scene.get("identity"), dict) else {}
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
