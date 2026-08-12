"""Validate/freeze a calibrated glove review scene from recorded measurements."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from forge.stage2_spec.glove_assembly import canonical_hash
from forge.stage4_review.glove_review import METRIC_KINDS, build_uncalibrated_scene
from forge.stage4_review.glove_seeded_fixtures import load_measurements

REQUIRED_ARTIFACT_DIGESTS = ("modelBundleDigest", "geometryReportDigest", "captureManifestDigest")


def calibrate(measurements: dict[str, Any], *, measurements_path: str = "provenance/measurements.json") -> dict[str, Any]:
    golden = measurements.get("golden")
    negatives = measurements.get("seededNegative")
    digests = measurements.get("artifactDigests")
    if measurements.get("evidenceTier") != "evidence-backed":
        raise ValueError("v1/synthetic measurements are diagnostic-only; verified evidence-backed artifact digests are required")
    if not isinstance(digests, dict) or any(not isinstance(digests.get(key), str) or not digests.get(key) for key in REQUIRED_ARTIFACT_DIGESTS):
        raise ValueError("calibration requires artifactDigests naming " + ", ".join(REQUIRED_ARTIFACT_DIGESTS))
    if not isinstance(golden, dict) or not isinstance(negatives, dict) or not negatives:
        raise ValueError("calibration requires golden and seeded-negative measurements")
    missing = sorted(set(METRIC_KINDS) - set(golden))
    if missing:
        raise ValueError("golden measurements missing: " + ", ".join(missing))
    scene = build_uncalibrated_scene()
    scene["thresholdStatus"] = "verified-artifact-calibration-v2"
    scene["thresholdSource"] = digests
    scopes: dict[str, Any] = {}
    for metric, kind in METRIC_KINDS.items():
        golden_value = float(golden[metric])
        negative_values = [float(case[metric]) for case in negatives.values() if isinstance(case, dict) and metric in case]
        if not negative_values:
            raise ValueError(f"calibration {metric} has no named negative measurement")
        highest_negative = max(negative_values)
        if kind == "boolean":
            # A boolean gate is satisfied only by 1.0, so a midpoint threshold would admit a
            # failing measurement. Separation is asserted instead of averaged.
            if golden_value != 1.0 or any(value != 0.0 for value in negative_values):
                raise ValueError(f"calibration {metric} is boolean and requires golden 1.0 with all negatives 0.0")
            threshold = 1.0
        else:
            if not golden_value > highest_negative:
                raise ValueError(f"calibration {metric} positive does not separate from negatives")
            threshold = round((golden_value + highest_negative) / 2.0, 6)
        scopes[metric] = {
            "kind": kind,
            "golden": golden_value,
            "negativeMeasurements": negative_values,
            "negativeFixtureCount": len(negative_values),
            "threshold": threshold,
            "marginToGolden": round(golden_value - threshold, 6),
            "source": "recorded golden/seeded-negative measurements",
        }
    scene["thresholds"] = {metric: {"kind": scopes[metric]["kind"], "threshold": scopes[metric]["threshold"]} for metric in METRIC_KINDS}
    scene["calibration"] = {
        "eligibleForReadiness": True,
        "perGateScope": scopes,
        "measurementVersion": measurements.get("version"),
        "artifactDigests": {key: digests[key] for key in REQUIRED_ARTIFACT_DIGESTS},
        "measurements": {"path": measurements_path, "sha256": canonical_hash(measurements)},
        "thresholdDerivation": "boolean gates require 1.0; continuous gates use the midpoint between the verified positive and the highest named artifact-level negative",
    }
    return scene


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurements", type=Path, default=Path("forge/tests/fixtures/glove_review_measurements_v1.json"))
    parser.add_argument("--measurements-artifact-path", default="provenance/measurements.json", help="root-relative location the measurements artifact will occupy in the review artifact root")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    scene = calibrate(load_measurements(args.measurements), measurements_path=args.measurements_artifact_path)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(scene, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
