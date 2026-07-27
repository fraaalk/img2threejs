#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

GOLDEN_THRESHOLDS = {
    "silhouetteIoU": 0.85,
    "aspectRatioDelta": 0.05,
    "scaleDelta": 0.08,
    "projectionCoverage": 0.85,
    "finishMaterialResponse": 0.80,
    "identityDetail": 0.80,
    "paintedRegion": 0.80,
    "maxOrbitCollapseRatio": 0.15,
}


def build_review_scene(
    environment_hash: str,
    family: str = "knife",
    subtype: str = "karambit",
    adapter_id: str = "cs2-knife-v1",
) -> dict[str, Any]:
    return {
        "version": 1,
        "fixtureId": f"cs2-{family}-front-v1",
        "rightsSafeStatus": "user-supplied-review-required",
        "reference": f"assets/{family}_reference/{family}_front.png",
        "identity": {"family": family, "subtype": subtype, "adapterId": adapter_id},
        "camera": {
            "projection": "orthographic",
            "azimuthDegrees": 0,
            "elevationDegrees": 0,
            "rollDegrees": 0,
            "target": [0, 0, 0],
        },
        "transform": {"position": [0, 0, 0], "rotationDegrees": [0, 0, 0], "scale": [1, 1, 1]},
        "environment": {"hash": environment_hash, "exposure": 0, "toneMapping": "ACESFilmic"},
        "resolution": {"width": 1024, "height": 1024},
        "background": "neutral-white",
        "rendererVersion": "three-runtime-contract-v1",
        "calibration": {
            "status": "calibrated",
            "positiveFixtures": [f"{family}-positive-v1"],
            "negativeFixtures": [f"{family}-negative-v1"],
        },
        "thresholds": dict(GOLDEN_THRESHOLDS),
    }


def validate_review_scene(scene: dict[str, Any]) -> list[str]:
    required = {
        "version", "fixtureId", "reference", "identity", "camera", "transform", "environment",
        "resolution", "background", "rendererVersion", "calibration", "thresholds",
    }
    errors = [f"missing {field}" for field in sorted(required - set(scene))]
    if scene.get("version") != 1:
        errors.append("unsupported review scene version")
    if scene.get("thresholds") != GOLDEN_THRESHOLDS:
        errors.append("golden thresholds do not match the frozen fixture contract")
    identity = scene.get("identity")
    if not isinstance(identity, dict) or not identity.get("family") or not identity.get("subtype") or not identity.get("adapterId"):
        errors.append("review scene identity is incomplete")
    calibration = scene.get("calibration")
    if not isinstance(calibration, dict) or calibration.get("status") != "calibrated":
        errors.append("review scene calibration is incomplete")
    return errors
