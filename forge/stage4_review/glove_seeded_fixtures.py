"""Constructible, single-defect review measurements for the Sport Gloves gates."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
MEASUREMENTS_PATH = FIXTURE_ROOT / "glove_review_measurements_v1.json"


def load_measurements(path: Path = MEASUREMENTS_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("thresholdsFrozen") is not True:
        raise ValueError("glove measurement fixture must declare thresholdsFrozen")
    return payload


def golden_metrics(path: Path = MEASUREMENTS_PATH) -> dict[str, float]:
    golden = load_measurements(path).get("golden")
    if not isinstance(golden, dict):
        raise ValueError("golden measurements are missing")
    return {str(key): float(value) for key, value in golden.items()}


def seeded_negative_metrics(case: str, path: Path = MEASUREMENTS_PATH) -> dict[str, float]:
    measurements = load_measurements(path)
    negatives = measurements.get("seededNegative", {})
    if not isinstance(negatives, dict) or case not in negatives:
        raise ValueError(f"unknown seeded glove fixture: {case}")
    result = golden_metrics(path)
    mutation = negatives[case]
    if not isinstance(mutation, dict):
        raise ValueError(f"seeded fixture {case} must be an object")
    for key, value in mutation.items():
        result[str(key)] = float(value)
    return result


def seeded_fixture_names(path: Path = MEASUREMENTS_PATH) -> tuple[str, ...]:
    negatives = load_measurements(path).get("seededNegative", {})
    if not isinstance(negatives, dict):
        return ()
    return tuple(str(key) for key in negatives)


def isolate_seeded_fixture(case: str, path: Path = MEASUREMENTS_PATH) -> dict[str, Any]:
    """Return an explicit defect record suitable for evaluator input and evidence."""
    measurements = load_measurements(path)
    mutation = measurements["seededNegative"][case]
    return {
        "fixtureId": f"sport-gloves-negative-{case}-v1",
        "case": case,
        "defect": copy.deepcopy(mutation),
        "metrics": seeded_negative_metrics(case, path),
        "expectedVerdict": "reject",
    }
