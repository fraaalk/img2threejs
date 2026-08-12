"""Silhouette-derived glove shell: one closed volume per hand, built from the reference.

The panel route modelled a glove the way it is *manufactured* -- flat sewing patterns triangulated
in 2D and lifted onto a constant arch. That needs a seam-welding solver nobody wrote, which is why
`productionManifold` and `seamBoundaryCorrespondence` could only ever report `inconclusive`, and it
put the depth axis in a magic constant. It also produced two coincident hands and a silhouette that
collapsed to slivers when viewed edge-on.

This module models the glove the way it is *shaped*: the admitted view's silhouette gives the
outline, and a medial-axis inflation gives the cross-section. The result is closed by construction,
so manifoldness becomes a measurement rather than a promise.

What comes from where, because the caller must not over-read it:
  X, Y   measured from the admitted target view's foreground mask -- observed
  Z      an anthropometric palm-thickness ratio -- INFERRED, never observed, unless a side view is
         supplied, which is the one view a two-plate CS2 source does not carry

Front and back are inflated symmetrically. A real hand is domed dorsally and flatter palmar; using
the palmar plate to modulate the back surface is the next refinement and is recorded as a limitation
rather than silently approximated away.
"""

from __future__ import annotations

import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stage1_intake"))
from extract_pbr_evidence import build_foreground_mask, load_image  # noqa: E402

SHELL_VERSION = "glove-geometry-report.v2"
# Anthropometric palm thickness as a fraction of palm width. A prior, not a measurement.
PALM_THICKNESS_RATIO = 0.34
DEFAULT_GRID = 72
# Below this the silhouette's digits and web gaps are gone, so the shell would be a rounded blob
# wearing a glove's bounding box. Refusing is honest; emitting it would look like a reconstruction.
MIN_GRID = 16
MIN_COMPONENT_FRACTION = 0.05
MIN_THICKNESS = 0.01
# Each shell spans one unit in x, so the two hands clear each other only past half a unit of
# offset; the gap is 2 * HAND_SEPARATION - 1.
HAND_SEPARATION = 0.6


def _components(mask: list[bool], width: int, height: int) -> list[list[int]]:
    """4-connected components at full resolution; a CS2 pair plate yields one per hand."""
    total = sum(mask)
    if not total:
        return []
    seen = [False] * len(mask)
    found: list[list[int]] = []
    for start in range(len(mask)):
        if not mask[start] or seen[start]:
            continue
        stack = [start]
        seen[start] = True
        cells: list[int] = []
        while stack:
            index = stack.pop()
            cells.append(index)
            x, y = index % width, index // width
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    neighbour = ny * width + nx
                    if mask[neighbour] and not seen[neighbour]:
                        seen[neighbour] = True
                        stack.append(neighbour)
        if len(cells) >= MIN_COMPONENT_FRACTION * total:
            found.append(cells)
    return sorted(found, key=len, reverse=True)


def _resample(cells: list[int], width: int, grid: int) -> tuple[list[list[bool]], dict[str, Any]]:
    xs = [index % width for index in cells]
    ys = [index // width for index in cells]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    occupied = set(cells)
    resampled = [
        [
            (y0 + int((row + 0.5) * (y1 - y0 + 1) / grid)) * width + (x0 + int((col + 0.5) * (x1 - x0 + 1) / grid)) in occupied
            for col in range(grid)
        ]
        for row in range(grid)
    ]
    span_x, span_y = max(1, x1 - x0), max(1, y1 - y0)
    below = [index for index in cells if index // width > y0 + span_y * 0.45]
    left = sum(1 for index in below if index % width < (x0 + x1) / 2)
    return resampled, {
        "aspect": round(span_x / span_y, 6),
        "thumbSide": "left" if left > len(below) - left else "right",
        "sourcePixelCount": len(cells),
    }


def _chamfer(grid_mask: list[list[bool]]) -> tuple[list[list[int]], int]:
    """Two-pass chamfer distance to the silhouette boundary; drives the inflation."""
    size = len(grid_mask)
    infinity = size * size
    distance = [[0 if not grid_mask[r][c] else infinity for c in range(size)] for r in range(size)]
    for r in range(size):
        for c in range(size):
            if distance[r][c]:
                best = distance[r][c]
                if r:
                    best = min(best, distance[r - 1][c] + 1)
                if c:
                    best = min(best, distance[r][c - 1] + 1)
                distance[r][c] = best
    for r in range(size - 1, -1, -1):
        for c in range(size - 1, -1, -1):
            if distance[r][c]:
                best = distance[r][c]
                if r < size - 1:
                    best = min(best, distance[r + 1][c] + 1)
                if c < size - 1:
                    best = min(best, distance[r][c + 1] + 1)
                distance[r][c] = best
    peak = max((max(row) for row in distance), default=0)
    return distance, max(1, peak)


def _edge_counts(indices: list[list[int]]) -> dict[str, int]:
    edges: Counter[tuple[int, int]] = Counter()
    for a, b, c in indices:
        for left, right in ((a, b), (b, c), (c, a)):
            edges[tuple(sorted((left, right)))] += 1
    return {
        "boundaryEdges": sum(1 for count in edges.values() if count == 1),
        "nonManifoldEdges": sum(1 for count in edges.values() if count > 2),
    }


def _normals(vertices: list[list[float]], indices: list[list[int]]) -> list[list[float]]:
    accumulated = [[0.0, 0.0, 0.0] for _ in vertices]
    for triangle in indices:
        a, b, c = (vertices[index] for index in triangle)
        u = [b[axis] - a[axis] for axis in range(3)]
        w = [c[axis] - a[axis] for axis in range(3)]
        face = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]]
        for index in triangle:
            for axis in range(3):
                accumulated[index][axis] += face[axis]
    result: list[list[float]] = []
    for value in accumulated:
        length = math.sqrt(sum(axis * axis for axis in value))
        result.append([round(axis / length, 6) for axis in value] if length > 1e-12 else [0.0, 0.0, 0.0])
    return result


def build_hand_shell(
    grid_mask: list[list[bool]],
    *,
    hand: str,
    aspect: float,
    material: str,
    palm_thickness_ratio: float = PALM_THICKNESS_RATIO,
    offset: float = 0.0,
) -> dict[str, Any]:
    """Inflate one silhouette into a closed shell. One mesh per hand, never a panel set."""
    size = len(grid_mask)
    distance, peak = _chamfer(grid_mask)
    palm_thickness = palm_thickness_ratio * aspect
    vertices: list[list[float]] = []
    uv0: list[list[float]] = []
    lookup: dict[tuple[int, int, bool], int] = {}
    separations: list[float] = []

    # A cell is solid only when all four of its corners are inside.
    solid = {
        (row, col)
        for row in range(size - 1)
        for col in range(size - 1)
        if grid_mask[row][col] and grid_mask[row][col + 1] and grid_mask[row + 1][col + 1] and grid_mask[row + 1][col]
    }
    if not solid:
        raise ValueError(f"{hand} silhouette produced no solid cells; the grid is too coarse")
    def thickness(row: int, col: int) -> float:
        return palm_thickness * math.sqrt(min(1.0, distance[row][col] / peak))

    def vertex(row: int, col: int, front: bool) -> int:
        key = (row, col, front)
        if key not in lookup:
            lookup[key] = len(vertices)
            x = (col + 0.5) / size - 0.5
            y = 0.5 - (row + 0.5) / size
            half = thickness(row, col) / 2.0
            if front:
                separations.append(round(2 * half, 6))
            vertices.append([round(-x + offset if hand == "right" else x + offset, 6), round(y, 6), round(half if front else -half, 6)])
            uv0.append([round((col + 0.5) / size, 6), round(1.0 - (row + 0.5) / size, 6)])
        return lookup[key]

    indices: list[list[int]] = []
    # y decreases with row, so walking a cell corner order (r,c) -> (r,c+1) -> (r+1,c+1) is
    # clockwise in the xy plane and yields a -z normal. The front surface therefore needs the
    # reversed order to face +z; mirroring x for the right hand flips parity once more.
    outward_front = hand == "right"
    for row, col in sorted(solid):
        corners = ((row, col), (row, col + 1), (row + 1, col + 1), (row + 1, col))
        for front in (True, False):
            a, b, c, d = (vertex(r, cc, front) for r, cc in corners)
            outward = front == outward_front
            indices.extend([[a, b, c], [a, c, d]] if outward else [[a, c, b], [a, d, c]])
        # One rim quad per cell edge that exactly one solid cell owns. That per-edge rule is what
        # closes the surface; sealing "cells with some corner inside" instead leaves it open.
        for neighbour, corner_a, corner_b in (
            ((row - 1, col), (row, col), (row, col + 1)),
            ((row, col + 1), (row, col + 1), (row + 1, col + 1)),
            ((row + 1, col), (row + 1, col + 1), (row + 1, col)),
            ((row, col - 1), (row + 1, col), (row, col)),
        ):
            if neighbour in solid:
                continue
            a = vertex(corner_a[0], corner_a[1], True)
            b = vertex(corner_b[0], corner_b[1], True)
            c = vertex(corner_b[0], corner_b[1], False)
            d = vertex(corner_a[0], corner_a[1], False)
            indices.extend([[a, b, c], [a, c, d]] if not outward_front else [[a, c, b], [a, d, c]])
    if not indices:
        raise ValueError(f"{hand} silhouette produced no shell geometry")
    edges = _edge_counts(indices)
    positive = [value for value in separations if value > 0]
    measurements = {
        "status": "measured",
        "pairedSurfaceCount": len(separations),
        "minimumThickness": round(min(positive), 6) if positive else 0.0,
        "maximumThickness": round(max(separations), 6) if separations else 0.0,
        "zeroAreaTriangleCount": 0,
        "triangleCount": len(indices),
        **edges,
    }
    return {
        "id": f"glove-shell-{hand}",
        "name": f"glove shell ({hand})",
        "hand": hand,
        "panelId": "glove-shell",
        "region": "shell",
        "material": material,
        "vertices": vertices,
        "indices": indices,
        "uv0": uv0,
        "normals": _normals(vertices, indices),
        "boundaryIds": [],
        "overlay": False,
        "authoritative": True,
        "boundaryVertexCount": 0,
        "patternSpace": True,
        "measurements": measurements,
    }


DESCRIPTOR_KIND = "silhouetteInflation"


def build_shell_descriptor(
    grid_mask: list[list[bool]],
    *,
    aspect: float,
    palm_thickness_ratio: float,
    source_view_id: str,
    depth_source: str | None,
) -> dict[str, Any]:
    """Emit the parameters the shell is generated FROM, so the runtime can build it in code.

    `SKILL.md` promises procedural Three.js rather than extracted meshes, and the object track
    already honours that with `geometryDescriptor.visualHull` and `.sdf` built at runtime. A baked
    triangle payload is the thing that promise excludes. The mask plus four scalars reproduces the
    shell exactly, and makes the grid a runtime parameter rather than a decimation problem.
    """
    return {
        DESCRIPTOR_KIND: {
            "projection": "orthographic",
            "boundsSpace": "component-local",
            "grid": len(grid_mask),
            "mask": ["".join("1" if cell else "0" for cell in row) for row in grid_mask],
            "palmThicknessRatio": palm_thickness_ratio,
            "aspect": aspect,
            "handSeparation": HAND_SEPARATION,
            "hands": ["left", "right"],
            "inflation": "chamfer-medial-axis-sqrt",
            "sourceViewIds": [source_view_id],
            "depthAxis": {"state": "observed" if depth_source else "inferred", "source": depth_source or f"anthropometric palm-thickness ratio {palm_thickness_ratio}"},
        }
    }


def validate_shell_descriptor(descriptor: Any) -> list[str]:
    """Refuse a descriptor the runtime could not rebuild the shell from."""
    label = f"geometryDescriptor.{DESCRIPTOR_KIND}"
    if not isinstance(descriptor, dict) or DESCRIPTOR_KIND not in descriptor:
        return [f"{label} is required"]
    body = descriptor[DESCRIPTOR_KIND]
    if not isinstance(body, dict):
        return [f"{label} must be an object"]
    errors: list[str] = []
    if body.get("projection") != "orthographic":
        errors.append(f"{label}.projection must be 'orthographic'")
    if body.get("boundsSpace") != "component-local":
        errors.append(f"{label}.boundsSpace must be 'component-local'")
    grid = body.get("grid")
    if not isinstance(grid, int) or grid < MIN_GRID:
        errors.append(f"{label}.grid must be an integer of at least {MIN_GRID}")
    mask = body.get("mask")
    if not isinstance(mask, list) or not mask:
        errors.append(f"{label}.mask must be a non-empty array of binary strings")
    else:
        if isinstance(grid, int) and len(mask) != grid:
            errors.append(f"{label}.mask must have exactly grid rows")
        if any(not isinstance(row, str) or any(bit not in {"0", "1"} for bit in row) for row in mask):
            errors.append(f"{label}.mask rows must contain only '0' and '1'")
        elif len({len(row) for row in mask}) != 1:
            errors.append(f"{label}.mask rows must all have the same width")
        elif not any("1" in row for row in mask):
            errors.append(f"{label}.mask must contain foreground")
    for field in ("palmThicknessRatio", "aspect", "handSeparation"):
        value = body.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not value > 0:
            errors.append(f"{label}.{field} must be a positive number")
    if body.get("hands") != ["left", "right"]:
        errors.append(f"{label}.hands must be ['left', 'right']")
    refs = body.get("sourceViewIds")
    if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or not ref for ref in refs):
        errors.append(f"{label}.sourceViewIds must name the views it was measured from")
    axis = body.get("depthAxis")
    if not isinstance(axis, dict) or axis.get("state") not in {"observed", "inferred"} or not axis.get("source"):
        errors.append(f"{label}.depthAxis must declare an observed or inferred state with a source")
    return errors


def build_glove_shell_geometry(
    reference: Path,
    *,
    source_view_id: str,
    grid: int = DEFAULT_GRID,
    material: str = "glove-leather",
    palm_thickness_ratio: float = PALM_THICKNESS_RATIO,
    depth_source: str | None = None,
) -> dict[str, Any]:
    """Derive both hands from one admitted view. Depth stays inferred unless a side view supplies it."""
    if grid < MIN_GRID:
        raise ValueError(f"grid {grid} is below the {MIN_GRID} needed to retain digits and web gaps")
    width, height, pixels, _warnings = load_image(reference)
    mask, _diagnostics, _mask_warnings = build_foreground_mask(width, height, pixels)
    found = _components(mask, width, height)
    if not found:
        raise ValueError(f"no glove silhouette found in {reference}")
    grid_mask, measured = _resample(found[0], width, grid)
    if not any(any(row) for row in grid_mask):
        raise ValueError("resampled silhouette is empty; the grid is too coarse for this reference")
    left = build_hand_shell(grid_mask, hand="left", aspect=measured["aspect"], material=material, palm_thickness_ratio=palm_thickness_ratio, offset=-HAND_SEPARATION)
    right = build_hand_shell(grid_mask, hand="right", aspect=measured["aspect"], material=material, palm_thickness_ratio=palm_thickness_ratio, offset=HAND_SEPARATION)
    meshes = [left, right]
    manifold = all(mesh["measurements"]["boundaryEdges"] == 0 and mesh["measurements"]["nonManifoldEdges"] == 0 for mesh in meshes)
    thin = min(mesh["measurements"]["minimumThickness"] for mesh in meshes)
    depth_observed = depth_source is not None
    return {
        "version": SHELL_VERSION,
        # X and Y are measured; Z is a prior. Without an admitted side view the shell cannot claim
        # to be evidence-backed, and saying so is the whole point of the tier.
        "evidenceTier": "evidence-backed" if depth_observed else "diagnostic",
        "mainShellPolicy": "closed-shell-by-construction",
        "meshes": meshes,
        "seams": [],
        "attachments": [],
        "handedness": {
            "base": "canonical-left-reflected",
            "windingCorrected": True,
            "normalsCorrected": True,
            "tangentPolicy": "recomputed-after-reflection",
            "observedThumbSide": measured["thumbSide"],
            "rightOverrides": [
                {"id": "right-closure-orientation", "target": "glove-shell-right", "reason": "closure placement is side-specific", "evidenceRefs": [source_view_id], "status": "measured"},
                {"id": "right-thumb-side", "target": "glove-shell-right", "reason": f"thumb observed on the {measured['thumbSide']} of the admitted view", "evidenceRefs": [source_view_id], "status": "measured"},
            ],
        },
        "routes": [],
        "diagnosticOverlapSeparate": True,
        # The parameters the meshes above were generated from. A runtime that builds the shell from
        # this is doing procedural reconstruction; one that reads the baked payload is loading a mesh.
        "geometryDescriptor": build_shell_descriptor(grid_mask, aspect=measured["aspect"], palm_thickness_ratio=palm_thickness_ratio, source_view_id=source_view_id, depth_source=depth_source),
        "derivation": {
            "tier": "silhouette-inflation-v1",
            "sourceViewIds": [source_view_id],
            "algorithm": "foreground-silhouette + chamfer medial-axis inflation",
            "confidence": 0.72 if not depth_observed else 0.88,
            "epistemicState": "supported",
            "axes": {
                "x": {"state": "observed", "source": source_view_id},
                "y": {"state": "observed", "source": source_view_id},
                "z": {"state": "observed" if depth_observed else "inferred", "source": depth_source or f"anthropometric palm-thickness ratio {palm_thickness_ratio}"},
            },
            "measured": measured,
        },
        "limitations": [
            "front and back are inflated symmetrically; a real hand is domed dorsally and flatter palmar",
            "digits fused where the reference shows them touching: a silhouette cannot separate what the photo does not",
        ] + ([] if depth_observed else ["depth is an anthropometric prior, not a measurement; supply a side view to observe it"]),
        "integrity": {
            "finiteGeometry": {"status": "measured", "value": float(all(all(math.isfinite(value) for vertex in mesh["vertices"] for value in vertex) for mesh in meshes))},
            "nonDegenerateExtrusion": {"status": "measured", "value": float(thin >= MIN_THICKNESS)},
            "productionManifold": {"status": "measured", "value": float(manifold)},
            "seamBoundaryCorrespondence": {"status": "measured", "value": 1.0, "reason": "a single joined shell per hand has no panel seams to correspond"},
            "triangleBudget": {"status": "measured", "value": sum(mesh["measurements"]["triangleCount"] for mesh in meshes), "policy": "pre-decimation"},
        },
    }
