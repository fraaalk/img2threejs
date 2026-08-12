"""Silhouette measurement and the shell descriptor, shared by spec authoring and the builder.

Stage 2 decides *what* geometry the spec declares, stage 3 *builds* it, and both need the same
silhouette measurement and the same descriptor shape. Keeping it here means neither stage imports the
other, and the descriptor the spec publishes is byte-identical to the one the builder consumes.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stage1_intake"))
from extract_pbr_evidence import build_foreground_mask, load_image  # noqa: E402

# Anthropometric palm thickness as a fraction of palm width. A prior, not a measurement.
PALM_THICKNESS_RATIO = 0.34
# A hand is domed on the back of the hand and flatter across the palm, so the two halves of the
# shell do not share the thickness evenly. Both are priors and are declared as such.
DORSAL_SHARE = 0.6
PALMAR_SHARE = 0.4
DEFAULT_GRID = 72
# Below this the silhouette's digits and web gaps are gone, so the shell would be a rounded blob
# wearing a glove's bounding box. Refusing is honest; emitting it would look like a reconstruction.
MIN_GRID = 16
MIN_COMPONENT_FRACTION = 0.05
# Each shell spans one unit in x, so the two hands clear each other only past half a unit of
# offset; the gap is 2 * HAND_SEPARATION - 1.
HAND_SEPARATION = 0.6
DESCRIPTOR_KIND = "silhouetteInflation"


def measure_silhouette(reference: Path, grid: int = DEFAULT_GRID) -> tuple[list[list[bool]], dict[str, Any]]:
    """Resample the largest foreground component of an admitted view onto the shell grid."""
    if grid < MIN_GRID:
        raise ValueError(f"grid {grid} is below the {MIN_GRID} needed to retain digits and web gaps")
    width, height, pixels, _warnings = load_image(reference)
    mask, _diagnostics, _mask_warnings = build_foreground_mask(width, height, pixels)
    found = _components(mask, width, height)
    if not found:
        raise ValueError(f"no glove silhouette found in {reference}")
    grid_mask, measured = _resample(found[0], width, grid)
    if not any(any(row) for row in grid_mask):
        raise ValueError(f"resampled silhouette from {reference} is empty; the grid is too coarse")
    return grid_mask, measured


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

def build_shell_descriptor(
    grid_mask: list[list[bool]],
    *,
    aspect: float,
    palm_thickness_ratio: float,
    source_view_id: str,
    depth_source: str | None,
    back_mask: list[list[bool]] | None = None,
    front_share: float = 0.5,
    back_share: float = 0.5,
    palmar_source_view_id: str | None = None,
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
            **({"backMask": ["".join("1" if cell else "0" for cell in row) for row in back_mask]} if back_mask is not None else {}),
            "frontShare": front_share,
            "backShare": back_share,
            "palmThicknessRatio": palm_thickness_ratio,
            "aspect": aspect,
            "handSeparation": HAND_SEPARATION,
            "hands": ["left", "right"],
            "inflation": "chamfer-medial-axis-sqrt",
            "sourceViewIds": [source_view_id] + ([palmar_source_view_id] if palmar_source_view_id else []),
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
    back = body.get("backMask")
    if back is not None:
        if not isinstance(back, list) or (isinstance(grid, int) and len(back) != grid):
            errors.append(f"{label}.backMask must have exactly grid rows when present")
        elif any(not isinstance(row, str) or any(bit not in {"0", "1"} for bit in row) for row in back):
            errors.append(f"{label}.backMask rows must contain only '0' and '1'")
    shares = [body.get("frontShare"), body.get("backShare")]
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not 0.0 < value < 1.0 for value in shares):
        errors.append(f"{label}.frontShare and backShare must each be between 0 and 1")
    elif abs(sum(shares) - 1.0) > 1e-6:
        errors.append(f"{label}.frontShare and backShare must sum to 1")
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


SURFACE_BEARING_EVIDENCE_USE = "target-geometry-and-surface"


def resolve_target_views(manifest: dict[str, Any]) -> tuple[tuple[Path, str] | None, tuple[Path, str] | None]:
    """Return the (dorsal-or-primary, palmar) admitted target views with readable images.

    Both the spec author and the builder need the same answer, so neither is allowed to pick its own:
    a spec that declares a descriptor measured from one view while stage 3 measures another would
    publish a geometry the runtime does not build.
    """
    views = [view for view in manifest.get("sourceViews", []) if isinstance(view, dict)]
    primary = manifest.get("primarySourceViewId")

    def usable(view: dict[str, Any]) -> Path | None:
        if view.get("admission") != "admitted":
            return None
        if view.get("evidenceUse") not in {None, SURFACE_BEARING_EVIDENCE_USE}:
            return None
        path = Path(str(view.get("path")))
        return path if path.is_file() else None

    outline: tuple[Path, str] | None = None
    for view in sorted(views, key=lambda item: (item.get("id") != primary, str(item.get("id")))):
        path = usable(view)
        if path is not None:
            outline = (path, str(view.get("id")))
            break
    palmar: tuple[Path, str] | None = None
    for view in views:
        if view.get("role") != "palmar":
            continue
        path = usable(view)
        if path is not None and (outline is None or str(view.get("id")) != outline[1]):
            palmar = (path, str(view.get("id")))
            break
    return outline, palmar
