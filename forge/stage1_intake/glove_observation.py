#!/usr/bin/env python3
"""Apply a source-grounded glove observation record to an intake manifest.

The observation is deliberately separate from the manifest produced by admission:
it lets a reviewer distinguish automatic reference admission from a human-verified
claim about anatomy, coverage, or target-condition material.  It never creates
new source views, and it verifies every coverage claim against the admitted
view's stable perceptual hash before writing.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from forge.stage1_intake.glove_contracts import glove_manifest_errors, validate_glove_extension


def apply_glove_observation(manifest: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    """Return a manifest enriched by an explicit, source-consistent observation."""
    if manifest.get("itemFamily") != "glove":
        raise ValueError("glove observation can only be applied to a glove manifest")
    extension = manifest.get("extensions", {}).get("glove")
    if not isinstance(extension, dict):
        raise ValueError("manifest has no extensions.glove")
    source_views = extension.get("sourceViews")
    if not isinstance(source_views, list):
        raise ValueError("manifest glove extension has no source views")
    known = {str(view.get("id")): view for view in source_views if isinstance(view, dict) and isinstance(view.get("id"), str)}
    if not known:
        raise ValueError("manifest glove extension has no identifiable source views")

    for field in ("formProfile", "coverageMatrix", "surfaceRegionEvidence", "evidence"):
        if field not in observation:
            raise ValueError(f"observation.{field} is required")
    source_use = observation.get("sourceUse", {})
    if not isinstance(source_use, dict):
        raise ValueError("observation.sourceUse must be an object")
    unknown_source_use = sorted(set(source_use) - set(known))
    if unknown_source_use:
        raise ValueError("observation.sourceUse names unknown views: " + ", ".join(unknown_source_use))

    for index, entry in enumerate(observation["coverageMatrix"]):
        if not isinstance(entry, dict):
            raise ValueError(f"observation.coverageMatrix[{index}] must be an object")
        source_id = entry.get("sourceViewId")
        view = known.get(str(source_id))
        if view is None:
            raise ValueError(f"coverageMatrix[{index}] names unknown source view {source_id!r}")
        if str(entry.get("sourceHash")) != str(view.get("hash")):
            raise ValueError(f"coverageMatrix[{index}] sourceHash does not match {source_id}")

    for index, claim in enumerate(observation["evidence"]):
        if not isinstance(claim, dict) or not isinstance(claim.get("sourceRefs"), list):
            raise ValueError(f"observation.evidence[{index}] must name sourceRefs")
        missing = sorted(str(ref) for ref in claim["sourceRefs"] if str(ref) not in known)
        if missing:
            raise ValueError(f"observation.evidence[{index}] names unknown source views: " + ", ".join(missing))

    result = copy.deepcopy(manifest)
    glove = result["extensions"]["glove"]
    glove["formProfile"] = copy.deepcopy(observation["formProfile"])
    glove["coverageMatrix"] = copy.deepcopy(observation["coverageMatrix"])
    glove["surfaceRegionEvidence"] = copy.deepcopy(observation["surfaceRegionEvidence"])
    existing_evidence = glove.get("evidence", [])
    existing_ids = {item.get("id") for item in existing_evidence if isinstance(item, dict)}
    glove["evidence"] = existing_evidence + [
        copy.deepcopy(claim) for claim in observation["evidence"]
        if isinstance(claim, dict) and claim.get("id") not in existing_ids
    ]
    for view in glove["sourceViews"]:
        if isinstance(view, dict) and view.get("id") in source_use:
            view["evidenceUse"] = source_use[view["id"]]
    result["sourceViews"] = glove["sourceViews"]

    errors = validate_glove_extension(glove) + glove_manifest_errors(result)
    if errors:
        raise ValueError("observation creates an invalid glove manifest: " + "; ".join(errors))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--observation", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if args.out.exists() and not args.force:
        parser.error(f"output already exists: {args.out}; use --force")
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        observation = json.loads(args.observation.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not isinstance(observation, dict):
            raise ValueError("manifest and observation must be JSON objects")
        result = apply_glove_observation(manifest, observation)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"state": result.get("state"), "out": str(args.out), "sourceViewCount": len(result.get("sourceViews", []))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
