"""Payload-complete surface/handedness gate wrappers and named mutations."""

from __future__ import annotations

import copy
from typing import Any


MIN_HAND_SEPARATION = 0.02


def _bounds(mesh: dict[str, Any]) -> list[tuple[float, float]]:
    vertices = [vertex for vertex in mesh.get("vertices", []) if isinstance(vertex, (list, tuple)) and len(vertex) == 3]
    if not vertices:
        raise ValueError(f"mesh {mesh.get('id', 'unknown')} has no measurable vertices")
    return [(min(vertex[axis] for vertex in vertices), max(vertex[axis] for vertex in vertices)) for axis in range(3)]


def measure_hand_separation(geometry_report: dict[str, Any]) -> dict[str, Any]:
    """Measure per-panel left/right separation from vertices.

    The report's own ``diagnosticOverlapSeparate`` is a declaration, and a declaration is exactly
    what this gate must not accept: the shipped fixture sets it true while six of twelve panels
    have identical left/right bounds.
    """
    by_panel: dict[str, dict[str, dict[str, Any]]] = {}
    for mesh in geometry_report.get("meshes", []):
        if isinstance(mesh, dict) and mesh.get("hand") in {"left", "right"}:
            by_panel.setdefault(str(mesh.get("panelId")), {})[str(mesh["hand"])] = mesh
    separations: dict[str, float] = {}
    coincident: list[str] = []
    for panel, hands in sorted(by_panel.items()):
        if set(hands) != {"left", "right"}:
            coincident.append(panel)
            continue
        left, right = _bounds(hands["left"]), _bounds(hands["right"])
        gap = max(max(low[0] - high[1], high[0] - low[1]) for low, high in zip(left, right))
        separations[panel] = round(gap, 6)
        if gap < MIN_HAND_SEPARATION:
            coincident.append(panel)
    return {
        "status": "measured" if by_panel else "inconclusive",
        "minimumSeparation": round(min(separations.values()), 6) if separations else None,
        "panelSeparations": separations,
        "coincidentPanels": coincident,
        "separated": bool(by_panel) and not coincident,
    }


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
    try:
        separation = measure_hand_separation(geometry_report)
    except ValueError as error:
        errors.append(f"blank-form:hand-separation-unmeasurable:{error}")
    else:
        if separation["status"] != "measured":
            errors.append("blank-form:hand-separation-unmeasurable")
        elif not separation["separated"]:
            errors.append("blank-form:hands-coincident:" + ",".join(separation["coincidentPanels"]))
    materials = spec.get("materials") if isinstance(spec.get("materials"), list) else []
    material_ids = {material.get("id") for material in materials if isinstance(material, dict)}
    visible_materials = [material for material in materials if isinstance(material, dict) and material.get("qualityTier") != "utility"]
    if not visible_materials:
        errors.append("surface:spec-declares-no-inspectable-material")
    for mesh in geometry_report.get("meshes", []):
        if not isinstance(mesh, dict) or not mesh.get("material") or not mesh.get("patternSpace"):
            errors.append(f"surface:panel-owned-uv-or-material-missing:{mesh.get('id', 'unknown') if isinstance(mesh, dict) else 'unknown'}")
        elif mesh["material"] not in material_ids:
            errors.append(f"surface:mesh-material-not-in-spec:{mesh['id']}")
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
    elif mutation == "coincident-hands":
        for mesh in report.get("meshes", []):
            if mesh.get("hand") == "right":
                mesh["vertices"] = copy.deepcopy(next(item["vertices"] for item in report["meshes"] if item.get("panelId") == mesh.get("panelId") and item.get("hand") == "left"))
    elif mutation == "no-inspectable-material":
        for material in mutated_spec.get("materials", []):
            material["qualityTier"] = "utility"
    elif mutation == "mesh-material-not-in-spec":
        for mesh in report.get("meshes", []):
            mesh["material"] = "material-that-no-spec-declares"
    else:
        raise ValueError(f"unknown glove surface mutation: {mutation}")
    return report, mutated_spec
