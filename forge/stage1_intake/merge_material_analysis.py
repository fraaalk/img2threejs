#!/usr/bin/env python3
"""Merge completed material-analysis batches without weakening their gates."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


def merge_material_analyses(analyses: list[dict[str, Any]]) -> dict[str, Any]:
    if not analyses:
        raise ValueError("at least one material analysis is required")
    if any(analysis.get("status") != "proceed" for analysis in analyses):
        raise ValueError("only completed material analyses can be merged")
    registry = analyses[0].get("registry")
    threshold = analyses[0].get("targetThreshold")
    regions: list[dict[str, Any]] = []
    ids: set[str] = set()
    not_observed: list[Any] = []
    for analysis in analyses:
        if analysis.get("registry") != registry or analysis.get("targetThreshold") != threshold:
            raise ValueError("material analysis batches must use the same registry and threshold")
        for region in analysis.get("regions", []):
            if not isinstance(region, dict) or not isinstance(region.get("regionId"), str):
                raise ValueError("each material analysis region needs a regionId")
            if region["regionId"] in ids:
                raise ValueError(f"duplicate material regionId {region['regionId']!r}")
            ids.add(region["regionId"])
            if region.get("assignment", {}).get("status") != "proceed":
                raise ValueError(f"material region {region['regionId']!r} is not proceed")
            regions.append(copy.deepcopy(region))
        not_observed.extend(copy.deepcopy(analysis.get("notObservedMaterials", [])))
    unresolved = [item for item in not_observed if isinstance(item, dict) and item.get("status") in {"probe", "request-input", "unknown"}]
    return {
        "schemaVersion": 1,
        "kind": "img2threejs.material-analysis",
        "referenceId": "merged-material-analysis",
        "registry": registry,
        "targetThreshold": threshold,
        "regions": regions,
        "notObservedMaterials": not_observed,
        "unresolvedNotObservedMaterials": unresolved,
        "status": "proceed" if not unresolved else "probe",
        "limitations": ["Merged only from independently completed analysis batches; source-specific PBR limits remain on every region."],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        analyses = [json.loads(path.read_text(encoding="utf-8")) for path in args.analysis]
        if not all(isinstance(item, dict) for item in analyses):
            raise ValueError("each analysis must be a JSON object")
        merged = merge_material_analyses(analyses)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    merged["artifact"] = str(args.out.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": merged["status"], "regions": len(merged["regions"]), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
