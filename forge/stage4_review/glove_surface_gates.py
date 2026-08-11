"""Payload-complete surface/handedness gate wrappers and named mutations."""

from __future__ import annotations

import copy
from typing import Any


def validate_glove_surface_contract(geometry_report: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    handedness = geometry_report.get("handedness", {})
    if handedness.get("base") != "canonical-left-reflected":
        errors.append("handedness:canonical-left-reflection-missing")
    if handedness.get("windingCorrected") is not True or handedness.get("normalsCorrected") is not True:
        errors.append("handedness:orientation-correction-missing")
    overrides = handedness.get("rightOverrides")
    if not isinstance(overrides, list) or not {item.get("id") for item in overrides if isinstance(item, dict)} >= {"right-closure-orientation", "right-thumb-side"}:
        errors.append("asymmetry:right-hand-overrides-missing")
    if geometry_report.get("diagnosticOverlapSeparate") is not True:
        errors.append("blank-form:diagnostic-overlap-not-separated")
    for mesh in geometry_report.get("meshes", []):
        if not isinstance(mesh, dict) or not mesh.get("material") or not mesh.get("patternSpace"):
            errors.append(f"surface:panel-owned-uv-or-material-missing:{mesh.get('id', 'unknown') if isinstance(mesh, dict) else 'unknown'}")
    visible_materials = [material for material in spec.get("materials", []) if isinstance(material, dict) and material.get("qualityTier") != "utility"]
    for material in visible_materials:
        reference = material.get("referencePbr", {})
        maps = reference.get("maps", {}) if isinstance(reference, dict) else {}
        locators = [maps.get(channel, {}).get("path") for channel in ("albedo", "roughness", "height", "normal", "ao") if isinstance(maps.get(channel), dict)]
        if len(locators) != len(set(locators)):
            errors.append(f"surface:pbr-channel-alias:{material.get('id', 'unknown')}")
    return errors


def mutate_surface_contract(geometry_report: dict[str, Any], spec: dict[str, Any], mutation: str) -> tuple[dict[str, Any], dict[str, Any]]:
    report = copy.deepcopy(geometry_report)
    mutated_spec = copy.deepcopy(spec)
    if mutation == "rotation-only":
        report["handedness"]["windingCorrected"] = False
    elif mutation == "flipped-orientation":
        report["handedness"]["normalsCorrected"] = False
    elif mutation == "missing-overrides":
        report["handedness"]["rightOverrides"] = []
    elif mutation == "blind-finish-mirroring":
        report["handedness"]["rightOverrides"] = [{"id": "mirrored-finish", "target": "all-right-materials", "reason": "blind mirror"}]
    elif mutation == "pbr-channel-alias":
        for material in mutated_spec.get("materials", []):
            if material.get("qualityTier") != "utility" and isinstance(material.get("referencePbr"), dict):
                maps = material["referencePbr"].setdefault("maps", {})
                maps["roughness"] = maps.get("albedo")
                break
    else:
        raise ValueError(f"unknown glove surface mutation: {mutation}")
    return report, mutated_spec
