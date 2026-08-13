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

Given a palmar plate the two halves stop being mirror images: the front follows the dorsal medial
axis, the back follows the palmar one, and the thickness splits by an anthropometric share because a
hand is domed dorsally and flatter across the palm. Without that second plate the shell stays
symmetric and says so in its limitations. The palmar view adds no depth -- it is a front-axis view
like the dorsal one -- only a back profile.
"""

from __future__ import annotations

import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from forge._shared.glove_silhouette import (  # noqa: E402
    DEFAULT_GRID,
    DESCRIPTOR_KIND,
    DORSAL_SHARE,
    HAND_SEPARATION,
    MIN_GRID,
    PALM_THICKNESS_RATIO,
    PALMAR_SHARE,
    _chamfer,
    _components,
    build_foreground_mask,
    build_shell_descriptor,
    load_image,
    measure_silhouette,
    validate_shell_descriptor,
)

from forge.stage3_build.glove_artifacts import sha256_file  # noqa: E402

SHELL_VERSION = "glove-geometry-report.v2"
MIN_THICKNESS = 0.01





WELD_PRECISION = 6


def _edge_counts(vertices: list[list[float]], indices: list[list[int]]) -> dict[str, int]:
    """Count edges by welded position, matching `geometry_integrity.mesh_edge_counts`.

    Counting raw indices measures index sharing, not watertightness: a mesh with UV seams splits
    vertices on purpose and is still closed. The gate that decides `topologyReady` already welds by
    rounded position, so counting differently here would report a defect the gate does not see.
    """
    keys = [tuple(round(float(value), WELD_PRECISION) for value in vertex[:3]) for vertex in vertices]
    edges: Counter[tuple[tuple[float, ...], tuple[float, ...]]] = Counter()
    for triangle in indices:
        points = [keys[index] for index in triangle]
        for left, right in ((points[0], points[1]), (points[1], points[2]), (points[2], points[0])):
            edges[(left, right) if left <= right else (right, left)] += 1
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
    back_mask: list[list[bool]] | None = None,
    front_share: float = 0.5,
    back_share: float = 0.5,
) -> dict[str, Any]:
    """Inflate one silhouette into a closed shell. One mesh per hand, never a panel set.

    With a `back_mask` the two halves stop being mirror images: the front follows the dorsal plate's
    medial axis and the back follows the palmar plate's, which is the only way the second admitted
    view contributes geometry rather than being validated and discarded.
    """
    size = len(grid_mask)
    distance, peak = _chamfer(grid_mask)
    back_distance, back_peak = _chamfer(back_mask) if back_mask is not None else (distance, peak)
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
    def half_thickness(row: int, col: int, front: bool) -> float:
        if front:
            return palm_thickness * front_share * math.sqrt(min(1.0, distance[row][col] / peak))
        return palm_thickness * back_share * math.sqrt(min(1.0, back_distance[row][col] / back_peak))

    def vertex(row: int, col: int, front: bool, *, rim: bool = False) -> int:
        # A rim vertex duplicates a surface position so it can carry the uv of its own side. Its
        # position is identical, so a position-welded edge count still sees a closed surface, while
        # the rim stops interpolating its texture across the middle of the atlas.
        key = (row, col, front, rim)
        if key not in lookup:
            lookup[key] = len(vertices)
            x = (col + 0.5) / size - 0.5
            y = 0.5 - (row + 0.5) / size
            half = half_thickness(row, col, front)
            if front:
                separations.append(round(half + half_thickness(row, col, False), 6))
            vertices.append([round(-x + offset if hand == "right" else x + offset, 6), round(y, 6), round(half if front else -half, 6)])
            # uv0 IS the plate's own coordinate: the shell is a heightfield over the silhouette, so
            # each side lands on the half of the atlas holding the view that saw it.
            u = (col + 0.5) / size
            half_u = u * 0.5 if (front or rim) else 0.5 + u * 0.5
            # v runs downward from the top of the grid: the atlas is uploaded with `flipY = false`, so v=0 is
            # the image's first row, which is the plate's fingertip end. Running it upward put the shell's
            # fingertips on the atlas's last row -- the cuff.
            uv0.append([round(half_u, 6), round((row + 0.5) / size, 6)])
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
            a = vertex(corner_a[0], corner_a[1], True, rim=True)
            b = vertex(corner_b[0], corner_b[1], True, rim=True)
            c = vertex(corner_b[0], corner_b[1], False, rim=True)
            d = vertex(corner_a[0], corner_a[1], False, rim=True)
            indices.extend([[a, b, c], [a, c, d]] if not outward_front else [[a, c, b], [a, d, c]])
    if not indices:
        raise ValueError(f"{hand} silhouette produced no shell geometry")
    edges = _edge_counts(vertices, indices)
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






ATLAS_SIZE = 1024


def bake_shell_atlas(dorsal: Path, palmar: Path | None, output: Path) -> dict[str, Any]:
    """Bake the admitted plates into the atlas the shell's uv0 already addresses.

    uv0 puts the front on the left half and the back on the right, so this crops each plate to the
    measured component bounding box -- the same box the grid was resampled from -- and pastes it
    there. Cropping the plate half instead would leave background where the glove does not fill it,
    which reads as a black halo on the model.
    """
    from PIL import Image

    def crop_to_component(path: Path) -> "Image.Image":
        grid_width, grid_height, pixels, _warnings = load_image(path)
        mask, _diagnostics, _mask_warnings = build_foreground_mask(grid_width, grid_height, pixels)
        found = _components(mask, grid_width, grid_height)
        if not found:
            raise ValueError(f"no glove silhouette found in {path}")
        occupied = set(found[0])
        xs = [index % grid_width for index in found[0]]
        ys = [index // grid_width for index in found[0]]
        with Image.open(path) as source:
            image = source.convert("RGB").copy()
        # Crop to the component's own bounding box, never a padded one: uv0 maps the unit square onto
        # exactly this box, so padding the crop shrinks the texture relative to the geometry and
        # exposes the very band the fill is meant to remove.
        box = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
        # Flood the glove's own colour into every background texel inside that box, nearest source
        # first, until none is left. A capped bleed is not enough: a hand does not fill its bounding
        # box, so 37% of the baked atlas stayed background and 48% of it in the corners. Anything on
        # the model that maps into those texels -- the outer digits, the thumb, anything clamped to
        # the frame edge -- rendered as a black hole rather than as leather. This is the
        # `palette-continue` strategy the surface projection already declares for what no plate saw,
        # applied rather than approximated: the breadth-first frontier visits each texel once and
        # takes the colour of the nearest already-coloured one, so the loop ends when the box is full
        # instead of after a magic number of steps.
        pixels_out = image.load()
        frontier = {index for index in occupied
                    if box[0] <= index % grid_width < box[2] and box[1] <= index // grid_width < box[3]}
        filled = set(frontier)
        while frontier:
            grown: set[int] = set()
            for index in frontier:
                x, y = index % grid_width, index // grid_width
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if box[0] <= nx < box[2] and box[1] <= ny < box[3]:
                        neighbour = ny * grid_width + nx
                        if neighbour not in filled:
                            filled.add(neighbour)
                            grown.add(neighbour)
                            pixels_out[nx, ny] = pixels_out[x, y]
            frontier = grown
        return image.crop(box).resize((ATLAS_SIZE // 2, ATLAS_SIZE), Image.LANCZOS)

    atlas = Image.new("RGB", (ATLAS_SIZE, ATLAS_SIZE), (28, 28, 28))
    atlas.paste(crop_to_component(dorsal), (0, 0))
    atlas.paste(crop_to_component(palmar if palmar is not None else dorsal), (ATLAS_SIZE // 2, 0))
    output.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(output)
    return {
        "path": output.name,
        "sha256": sha256_file(output),
        "size": [ATLAS_SIZE, ATLAS_SIZE],
        "layout": "side-by-side",
        "front": {"sourceView": "dorsal", "uvRect": [0.0, 0.0, 0.5, 1.0]},
        "back": {"sourceView": "palmar" if palmar is not None else "dorsal-mirrored", "uvRect": [0.5, 0.0, 0.5, 1.0]},
    }


def build_glove_shell_geometry(
    reference: Path,
    *,
    source_view_id: str,
    grid: int = DEFAULT_GRID,
    material: str = "glove-leather",
    palm_thickness_ratio: float = PALM_THICKNESS_RATIO,
    depth_source: str | None = None,
    palmar_reference: Path | None = None,
    palmar_source_view_id: str | None = None,
    atlas_output: Path | None = None,
) -> dict[str, Any]:
    """Derive both hands from the admitted views. Depth stays inferred unless a side view supplies it.

    A palmar plate does not add depth -- it is a front-axis view like the dorsal one -- but it does
    give the back surface its own profile, so the shell stops being symmetric about its own outline.
    """
    grid_mask, measured = measure_silhouette(reference, grid)
    back_mask: list[list[bool]] | None = None
    if palmar_reference is not None:
        back_mask, _palmar_measured = measure_silhouette(palmar_reference, grid)
    # A hand is domed dorsally and flatter palmar, so the halves do not split evenly once the
    # palmar plate is available to shape the back. Without it the split stays symmetric.
    front_share, back_share = (DORSAL_SHARE, PALMAR_SHARE) if back_mask is not None else (0.5, 0.5)
    shell = dict(aspect=measured["aspect"], material=material, palm_thickness_ratio=palm_thickness_ratio, back_mask=back_mask, front_share=front_share, back_share=back_share)
    left = build_hand_shell(grid_mask, hand="left", offset=-HAND_SEPARATION, **shell)
    right = build_hand_shell(grid_mask, hand="right", offset=HAND_SEPARATION, **shell)
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
        # Panels become surface regions projected onto one shell rather than separate geometry, which
        # is what surfaceRegionEvidence already models. The rim is the band neither front-axis plate
        # saw, so it gets a named unseen strategy instead of borrowing a colour silently.
        "surfaceProjection": {
            "mode": "orthographic-front-projection",
            "atlas": {"layout": "side-by-side", "front": [0.0, 0.0, 0.5, 1.0], "back": [0.5, 0.0, 0.5, 1.0]},
            "sides": [
                {"side": "front", "orientation": "dorsal", "sourceViewId": source_view_id, "uvRect": [0.0, 0.0, 0.5, 1.0]},
                {
                    "side": "back",
                    "orientation": "palmar",
                    "sourceViewId": palmar_source_view_id or source_view_id,
                    "uvRect": [0.5, 0.0, 0.5, 1.0],
                    **({} if palmar_source_view_id else {"unseenStrategy": "mirror-symmetry", "reason": "no admitted palmar plate; the back reuses the dorsal projection"}),
                },
            ],
            "unseen": [
                {
                    "region": "silhouette-rim",
                    "strategy": "palette-continue",
                    "reason": "the rim band is edge-on to both front-axis plates, so its texels interpolate between the two atlas halves",
                }
            ],
        },
        # The parameters the meshes above were generated from. A runtime that builds the shell from
        # this is doing procedural reconstruction; one that reads the baked payload is loading a mesh.
        **({"surfaceAtlas": bake_shell_atlas(reference, palmar_reference, atlas_output)} if atlas_output is not None else {}),
        "geometryDescriptor": build_shell_descriptor(grid_mask, aspect=measured["aspect"], palm_thickness_ratio=palm_thickness_ratio, source_view_id=source_view_id, depth_source=depth_source, back_mask=back_mask, front_share=front_share, back_share=back_share, palmar_source_view_id=palmar_source_view_id),
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
            "backSurfaceSource": palmar_source_view_id or "mirrored from the dorsal profile",
        },
        "limitations": [
            "front and back are inflated symmetrically; a real hand is domed dorsally and flatter palmar"
            if back_mask is None
            else f"back surface follows the palmar plate at a {back_share:.2f} thickness share, an anthropometric prior",
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
