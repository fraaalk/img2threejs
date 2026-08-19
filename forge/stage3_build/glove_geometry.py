"""Measured, canonical panel geometry for the Sport Gloves diagnostic route.

The v1 route treated a list of polygon ``faces`` and self-authored seam flags as
geometry evidence.  This module emits the one triangle representation consumed by
the integrity gates and deliberately labels an un-welded panel assembly as
diagnostic.  It is therefore safe to inspect or render, but cannot become a
production/readiness artifact until a real welding stage supplies the required
post-weld topology.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any


MIN_THICKNESS = 0.01
MIN_TRIANGLE_AREA = 1e-10
SEAM_RESIDUAL_TOLERANCE = 0.018


def polygon_area(loop: list[list[float]]) -> float:
    return sum(loop[index][0] * loop[(index + 1) % len(loop)][1] - loop[(index + 1) % len(loop)][0] * loop[index][1] for index in range(len(loop))) / 2.0


def _cross(a: list[float], b: list[float], c: list[float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _point_in_triangle(point: list[float], a: list[float], b: list[float], c: list[float]) -> bool:
    signs = (_cross(point, a, b), _cross(point, b, c), _cross(point, c, a))
    return all(value >= -1e-9 for value in signs) or all(value <= 1e-9 for value in signs)


def triangulate_panel_loop(loop: list[list[float]]) -> list[list[int]]:
    if len(loop) < 3 or polygon_area(loop) <= 0:
        raise ValueError("panel loop must be counter-clockwise and contain at least three points")
    remaining = list(range(len(loop)))
    triangles: list[list[int]] = []
    guard = len(loop) * len(loop)
    while len(remaining) > 3 and guard > 0:
        guard -= 1
        for position, current in enumerate(remaining):
            previous, following = remaining[position - 1], remaining[(position + 1) % len(remaining)]
            if _cross(loop[previous], loop[current], loop[following]) <= 1e-9:
                continue
            if any(candidate not in {previous, current, following} and _point_in_triangle(loop[candidate], loop[previous], loop[current], loop[following]) for candidate in remaining):
                continue
            triangles.append([previous, current, following])
            del remaining[position]
            break
        else:
            raise ValueError("panel loop is self-intersecting or cannot be triangulated")
    if len(remaining) != 3:
        raise ValueError("panel triangulation did not converge")
    triangles.append(remaining)
    return triangles


def _lift(point: list[float], *, hand: str, thickness: float) -> tuple[float, float, float]:
    """Lift a pattern point onto the normalized underform with real z separation."""
    x, y = point
    x *= 0.72
    y *= 0.78
    if hand == "right":
        x = -x
    arch = 0.105 * max(0.0, 1.0 - (x / 0.78) ** 2 - (y / 1.0) ** 2)
    return (round(x, 6), round(y, 6), round(arch + thickness, 6))


def _triangle_area(vertices: list[list[float]], triangle: list[int]) -> float:
    a, b, c = (vertices[index] for index in triangle)
    ab = [b[axis] - a[axis] for axis in range(3)]
    ac = [c[axis] - a[axis] for axis in range(3)]
    cross = [ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0]]
    return math.sqrt(sum(value * value for value in cross)) / 2.0


def _normals(vertices: list[list[float]], indices: list[list[int]]) -> list[list[float]]:
    values = [[0.0, 0.0, 0.0] for _ in vertices]
    for triangle in indices:
        a, b, c = (vertices[index] for index in triangle)
        ab = [b[axis] - a[axis] for axis in range(3)]
        ac = [c[axis] - a[axis] for axis in range(3)]
        face = [ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0]]
        for index in triangle:
            for axis in range(3):
                values[index][axis] += face[axis]
    result: list[list[float]] = []
    for value in values:
        length = math.sqrt(sum(axis * axis for axis in value))
        result.append([round(axis / length, 6) for axis in value] if length > 1e-12 else [0.0, 0.0, 0.0])
    return result


def _edge_counts(indices: list[list[int]]) -> dict[str, int]:
    edges: Counter[tuple[int, int]] = Counter()
    for a, b, c in indices:
        for left, right in ((a, b), (b, c), (c, a)):
            edges[tuple(sorted((left, right)))] += 1
    return {"boundaryEdges": sum(count == 1 for count in edges.values()), "nonManifoldEdges": sum(count > 2 for count in edges.values())}


def _mesh_measurements(vertices: list[list[float]], indices: list[list[int]], paired_count: int) -> dict[str, Any]:
    separations = [abs(vertices[index][2] - vertices[index + paired_count][2]) for index in range(paired_count)]
    areas = [_triangle_area(vertices, triangle) for triangle in indices]
    edges = _edge_counts(indices)
    return {
        "status": "measured",
        "pairedSurfaceCount": paired_count,
        "minimumThickness": round(min(separations), 6) if separations else 0.0,
        "maximumThickness": round(max(separations), 6) if separations else 0.0,
        "zeroAreaTriangleCount": sum(area <= MIN_TRIANGLE_AREA for area in areas),
        "minimumTriangleArea": round(min(areas), 12) if areas else 0.0,
        "triangleCount": len(indices),
        **edges,
    }


def build_panel_mesh(panel: dict[str, Any], *, hand: str = "left", overlay: bool = False) -> dict[str, Any]:
    loop = panel.get("boundaryLoop")
    if not isinstance(loop, list) or len(loop) < 3:
        raise ValueError(f"panel {panel.get('id')} has no boundary loop")
    triangles = triangulate_panel_loop(loop)
    thickness = 0.035 if not overlay else 0.022
    top = [_lift(point, hand=hand, thickness=thickness / 2.0) for point in loop]
    bottom = [_lift(point, hand=hand, thickness=-thickness / 2.0) for point in loop]
    vertices = [list(point) for point in top + bottom]
    indices: list[list[int]] = []
    for triangle in triangles:
        front = list(triangle)
        back = [index + len(loop) for index in reversed(triangle)]
        if hand == "right":
            front.reverse()
            back.reverse()
        indices.extend((front, back))
    for index in range(len(loop)):
        next_index = (index + 1) % len(loop)
        side = [index, next_index, next_index + len(loop), index + len(loop)]
        if hand == "right":
            side.reverse()
        indices.extend(([side[0], side[1], side[2]], [side[0], side[2], side[3]]))
    uvs = [[round((point[0] + 1.0) / 2.0, 6), round((point[1] + 1.1) / 2.2, 6)] for point in loop]
    uvs += list(uvs)
    boundary_ids = [f"{panel['id']}-boundary-{index}" for index in range(len(loop))]
    measurements = _mesh_measurements(vertices, indices, len(loop))
    return {
        "id": f"{panel['id']}-{hand}",
        "name": f"{panel.get('region', panel['id'])} ({hand})",
        "hand": hand,
        "panelId": panel["id"],
        "region": panel.get("region"),
        "material": panel.get("material"),
        "vertices": vertices,
        "indices": indices,
        "uv0": uvs,
        "boundaryIds": boundary_ids,
        "normals": _normals(vertices, indices),
        "overlay": overlay,
        "authoritative": bool(panel.get("authoritative", True)) and not overlay,
        "boundaryVertexCount": len(loop),
        "patternSpace": True,
        "measurements": measurements,
    }


def _finite_mesh(mesh: dict[str, Any]) -> bool:
    return all(isinstance(value, (int, float)) and math.isfinite(value) for vertex in mesh.get("vertices", []) for value in vertex)


def _diagnostic_seams(assembly: dict[str, Any]) -> list[dict[str, Any]]:
    """Record the missing operation honestly until the production weld stage exists."""
    result: list[dict[str, Any]] = []
    for seam in assembly.get("seamGraph", {}).get("nodes", []):
        if isinstance(seam, dict):
            spans_a, spans_b = seam.get("orderedBoundarySpansA", []), seam.get("orderedBoundarySpansB", [])
            result.append({
                "id": seam.get("id"), "mode": seam.get("mode"),
                "pairedSpanCount": min(len(spans_a), len(spans_b)),
                "residual": None, "welded": False, "status": "inconclusive",
                "reason": "v2 requires emitted shared vertices and removed internal seam faces",
                "correspondence": seam.get("correspondencePolicy"),
            })
    return result


def build_glove_geometry(assembly: dict[str, Any]) -> dict[str, Any]:
    panels = assembly.get("panelGraph", {}).get("nodes", [])
    meshes: list[dict[str, Any]] = []
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        overlay = str(panel.get("region", "")).endswith("guard") or panel.get("side") == "shared" and panel.get("region") == "closure"
        meshes.extend((build_panel_mesh(panel, hand="left", overlay=overlay), build_panel_mesh(panel, hand="right", overlay=overlay)))
    seams = _diagnostic_seams(assembly)
    right_overrides = [
        {"id": "right-closure-orientation", "target": "overlay-closure-right", "reason": "closure placement is side-specific", "evidenceRefs": ["three-quarter"], "status": "diagnostic"},
        {"id": "right-thumb-side", "target": "panel-thumb-saddle-right", "reason": "thumb-side relationship is corrected after reflection", "evidenceRefs": ["thumb-side-profile"], "status": "diagnostic"},
    ]
    all_measured = [mesh["measurements"] for mesh in meshes]
    return {
        "version": "glove-geometry-report.v2",
        # Carried from the assembly, not re-asserted: the bundle and the review both need to know which
        # glove this is and what form it was built for, and the only honest source is what stage 2 decided.
        "subtype": assembly.get("subtype"),
        "formProfile": assembly.get("formProfile"),
        "allowedBoundaryKinds": list(assembly.get("policy", {}).get("allowedBoundaryKinds", ["cuff"])),
        "evidenceTier": "diagnostic",
        "mainShellPolicy": "production-weld-required",
        "meshes": meshes,
        "seams": seams,
        "attachments": assembly.get("attachmentGraph", {}).get("nodes", []),
        "handedness": {"base": "canonical-left-reflected", "windingCorrected": True, "normalsCorrected": True, "tangentPolicy": "recomputed-after-reflection", "rightOverrides": right_overrides},
        "routes": assembly.get("routeGraph", {}).get("nodes", []),
        "diagnosticOverlapSeparate": True,
        "integrity": {
            "finiteGeometry": {"status": "measured", "value": float(all(_finite_mesh(mesh) for mesh in meshes))},
            "nonDegenerateExtrusion": {"status": "measured", "value": float(all(item["minimumThickness"] >= MIN_THICKNESS and item["zeroAreaTriangleCount"] == 0 for item in all_measured))},
            "productionManifold": {"status": "inconclusive", "value": 0.0, "reason": "production seam welding has not been emitted"},
            "seamBoundaryCorrespondence": {"status": "inconclusive", "value": 0.0, "reason": "seam topology has not been emitted"},
            "triangleBudget": {"status": "measured", "value": sum(item["triangleCount"] for item in all_measured), "policy": "normalized-diagnostic"},
        },
    }


def validate_geometry_report(report: Any, *, require_production: bool = True, require_evidence_tier: bool = True) -> list[str]:
    """Validate the report. `require_evidence_tier` is separable on purpose: topology readiness and
    evidence tier are different claims, and a caller measuring topology must not inherit a verdict
    about where the numbers came from."""
    if not isinstance(report, dict):
        return ["geometry report must be an object"]
    errors: list[str] = []
    if report.get("version") != "glove-geometry-report.v2":
        errors.append("geometry report must use v2 canonical schema")
    meshes = report.get("meshes")
    if not isinstance(meshes, list) or not meshes:
        return ["geometry report must contain meshes"]
    ids: set[str] = set()
    for mesh in meshes:
        if not isinstance(mesh, dict):
            errors.append("mesh must be an object")
            continue
        if mesh.get("id") in ids:
            errors.append(f"duplicate mesh id: {mesh.get('id')}")
        ids.add(mesh.get("id"))
        vertices, indices = mesh.get("vertices"), mesh.get("indices")
        if not _finite_mesh(mesh):
            errors.append(f"mesh {mesh.get('id')} has non-finite vertices")
        if not isinstance(indices, list) or not indices:
            errors.append(f"mesh {mesh.get('id')} has no canonical triangle indices")
            continue
        vertex_count = len(vertices) if isinstance(vertices, list) else 0
        for triangle in indices:
            if not isinstance(triangle, list) or len(triangle) != 3 or any(not isinstance(index, int) or index < 0 or index >= vertex_count for index in triangle):
                errors.append(f"mesh {mesh.get('id')} has invalid triangle index")
        if not isinstance(mesh.get("normals"), list) or len(mesh["normals"]) != vertex_count:
            errors.append(f"mesh {mesh.get('id')} normals are missing or incomplete")
        measurement = mesh.get("measurements")
        if not isinstance(measurement, dict) or measurement.get("status") != "measured":
            errors.append(f"mesh {mesh.get('id')} geometry was not measured")
        elif measurement.get("minimumThickness", 0.0) < MIN_THICKNESS or measurement.get("zeroAreaTriangleCount", 1):
            errors.append(f"mesh {mesh.get('id')} has degenerate extrusion")
    if require_production:
        if require_evidence_tier and report.get("evidenceTier") != "evidence-backed":
            errors.append("diagnostic geometry cannot satisfy production validation")
        for seam in report.get("seams", []):
            if seam.get("status") != "measured" or seam.get("residual") is None or seam.get("residual") > SEAM_RESIDUAL_TOLERANCE or not seam.get("welded"):
                errors.append(f"seam {seam.get('id')} failed emitted boundary correspondence")
        integrity = report.get("integrity", {})
        for key in ("productionManifold", "seamBoundaryCorrespondence"):
            if integrity.get(key, {}).get("status") != "measured" or integrity.get(key, {}).get("value") != 1.0:
                errors.append(f"integrity {key} is not a passing measurement")
    return errors
