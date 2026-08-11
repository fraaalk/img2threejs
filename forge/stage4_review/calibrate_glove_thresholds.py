"""Validate/freeze a calibrated glove review scene from recorded measurements."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from forge.stage4_review.glove_review import REQUIRED_METRICS, build_uncalibrated_scene
from forge.stage4_review.glove_seeded_fixtures import load_measurements


def calibrate(measurements: dict[str, Any]) -> dict[str, Any]:
    golden = measurements.get("golden")
    negatives = measurements.get("seededNegative")
    if measurements.get("evidenceTier") != "evidence-backed" or not isinstance(measurements.get("artifactDigests"), dict):
        raise ValueError("v1/synthetic measurements are diagnostic-only; verified evidence-backed artifact digests are required")
    if not isinstance(golden, dict) or not isinstance(negatives, dict) or not negatives:
        raise ValueError("calibration requires golden and seeded-negative measurements")
    missing = sorted(set(REQUIRED_METRICS) - set(golden))
    if missing:
        raise ValueError("golden measurements missing: " + ", ".join(missing))
    scene = build_uncalibrated_scene()
    scene["thresholdStatus"] = "verified-artifact-calibration-v2"
    scene["thresholdSource"] = measurements["artifactDigests"]
    scopes: dict[str, Any] = {}
    for metric in REQUIRED_METRICS:
        golden_value = float(golden[metric])
        negative_values = [float(case[metric]) for case in negatives.values() if isinstance(case, dict) and metric in case]
        if not negative_values:
            raise ValueError(f"calibration {metric} has no named negative measurement")
        highest_negative = max(negative_values)
        if not golden_value > highest_negative:
            raise ValueError(f"calibration {metric} positive does not separate from negatives")
        threshold = round((golden_value + highest_negative) / 2.0, 6)
        scopes[metric] = {
            "golden": golden_value,
            "negativeMeasurements": negative_values,
            "negativeFixtureCount": len(negative_values),
            "threshold": threshold,
            "marginToGolden": round(golden_value - threshold, 6),
            "source": "recorded golden/seeded-negative measurements",
        }
    scene["thresholds"] = {metric: scopes[metric]["threshold"] for metric in REQUIRED_METRICS}
    scene["calibration"] = {"eligibleForReadiness": True, "perGateScope": scopes, "measurementVersion": measurements.get("version"), "artifactDigests": measurements["artifactDigests"], "thresholdDerivation": "midpoint between verified positive and highest named artifact-level negative"}
    return scene


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurements", type=Path, default=Path("forge/tests/fixtures/glove_review_measurements_v1.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    scene = calibrate(load_measurements(args.measurements))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(scene, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
