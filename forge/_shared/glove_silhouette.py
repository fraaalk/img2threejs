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
# Heights at which the palm-and-cuff outline is measured. Measurement only: how many of these a given
# descriptor can actually use is decided by the builder, because that depends on the polygonisation grid.
# Sampled finely here so the builder has something to thin out rather than something to interpolate.
PROFILE_SLICES = 48
# How far past the digits' envelope the outline has to reach before that row counts as the thumb's root
# rather than a wobble in the silhouette's edge.
THUMB_REACH_FRACTION = 0.02
# A run narrower than this is a wobble in the outline, not a digit.
MIN_DIGIT_RUN_FRACTION = 0.015
DIGIT_TRACKS = 4
# The narrowest a digit's distal section may read relative to its base. Below this the reading is the tip's
# own rounding rather than the digit's width.
MIN_TIP_WIDTH_RATIO = 0.65


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
    # The profile loop below rebinds `width` to a fraction of the span, so the image's own width is kept
    # here. It is not a style point: passing the rebound name to the digit tracker fed it a float where it
    # wanted a row stride, every index missed, and the tracker returned no digits at all rather than failing.
    image_width = width
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
    # Row widths locate the knuckle line: the digits occupy everything above the first row that
    # reaches near-maximum width. It is the one anatomical landmark a pressed-together silhouette
    # still gives up, since it needs no per-digit separation.
    rows: dict[int, tuple[int, int]] = {}
    for index in cells:
        y, x = index // width, index % width
        low, high = rows.get(y, (x, x))
        rows[y] = (min(low, x), max(high, x))
    widths = {y: (high - low) / span_x for y, (low, high) in rows.items()}
    peak = max(widths.values())
    # The knuckle line is the widest row, not the first row within 2% of it. A glove silhouette widens
    # as a smooth dome, so a near-peak threshold fires wherever noise first brushes it: on the real
    # Slingshot plate that was 0.373 of the height against a peak at 0.408, and the difference showed up
    # as fingers a tenth of the hand too short. The widest row is a landmark; a tolerance band is a knob.
    outline_knuckle = max(widths, key=lambda y: (widths[y], -y))
    # How wide the four digits actually sit. Sampled halfway down the digit band, which on both plates
    # in this repository is the last height that still resolves separate digit runs while the thumb has
    # not yet widened the span: a quarter of the way down the digits are still tapering to their tips and
    # read 0.62-0.67 of the silhouette, and past two thirds the thumb joins and it reads 0.93-0.96.
    # Halfway gives 0.82 and 0.74.
    #
    # Without any measurement the digit row was a constant 0.86 of the palm width centre-to-centre,
    # which with the radius prior made it 1.07 palm widths wide -- wider than the palm, so the outer
    # digits sat off the glove entirely and sampled the plate's background.
    digit_row = y0 + max(1, int((outline_knuckle - y0) * 0.5))
    digit_bounds = rows.get(digit_row) or rows[outline_knuckle]
    # The width of the silhouette at each height below the knuckle line, as a fraction of the widest
    # row, plus where that row's centre sits. This is the one part of the form the plate really does
    # observe, and fitting a single ellipsoid to it instead threw it away: on the real Slingshot plate
    # the palm reads as a trapezoid tapering from 0.97 at the knuckles to 0.66 at the cuff, and an
    # ellipsoid of palm width by palm height is a circle. A circle wider than the plate's own palm maps
    # its edges onto whatever lies outside the glove in the plate, which is why parts of the render
    # sampled background.
    # Which side the thumb is on, measured from the OUTLINE rather than from pixel mass. The mass test
    # this replaces -- more foreground left of the bbox midline than right, below 0.45 of the height --
    # is dominated by the palm, and a palm is roughly symmetric: on the real Slingshot plate it answered
    # "right" for a hand whose thumb is on the left, so the thumb was built against the pinky.
    #
    # The outline gives one unambiguous signal instead. The four digits define an envelope; the thumb is
    # the side where the hand reaches PAST that envelope. On the same plate that reads 0.0179 of the frame
    # on the left against 0.0000 on the right.
    reach = {
        "left": [(y, digit_bounds[0] - low) for y, (low, _high) in rows.items()],
        "right": [(y, high - digit_bounds[1]) for y, (_low, high) in rows.items()],
    }
    areas = {side: sum(max(0, value) for _y, value in entries) for side, entries in reach.items()}
    thumb_side = "left" if areas["left"] > areas["right"] else "right"
    thumb_left = thumb_side == "left"
    # The knuckle line is the widest row of the PALM, not of the whole outline, and on a plate with a thumb
    # those are different rows. The outline's widest row is wherever the hand reaches furthest, which on the
    # real Slingshot plate is 0.42 of the height -- the thumb's own widest point, since the thumb's reach peaks
    # at 0.44. The palm on its own peaks at 0.28 and narrows monotonically below that, which is the metacarpal
    # heads, which is the knuckles.
    #
    # Taking the outline's row put the knuckle line 46% too low and stretched every digit to match: the digits
    # ran separate down to 0.41 where the plate merges them at 0.22 to 0.27, right above the palm's own peak.
    # Two passes rather than one, because the digit envelope that removes the thumb is itself derived from a
    # provisional knuckle -- the first pass locates the envelope, the second locates the knuckle behind it.
    palm_widths = {
        y: ((high - max(low, digit_bounds[0])) if thumb_left else (min(high, digit_bounds[1]) - low)) / span_x
        for y, (low, high) in rows.items()
    }
    knuckle = max(palm_widths, key=lambda y: (palm_widths[y], -y))
    profile: list[tuple[float, float]] = []
    palm_profile: list[tuple[float, float]] = []
    for step in range(PROFILE_SLICES):
        y = knuckle + int((y1 - knuckle) * step / max(1, PROFILE_SLICES - 1))
        bounds = rows.get(y)
        if bounds is None:
            continue
        width = (bounds[1] - bounds[0] + 1) / span_x
        centre = ((bounds[0] + bounds[1]) / 2.0 - x0) / span_x - 0.5
        profile.append((round(width, 6), round(centre, 6)))
        # The same row with the THUMB's band taken off, which is the palm on its own. `widthProfile` is the
        # whole outline, and below the knuckles the outline is palm AND thumb: sweeping the palm across all of
        # it makes a slab that contains the thumb, which is how this form spent a dozen renders with four
        # digits and a lobe. The cut is at the four digits' envelope on the thumb side, because that is where
        # the palm ends and the thumb begins.
        palm_low = max(bounds[0], digit_bounds[0]) if thumb_left else bounds[0]
        palm_high = bounds[1] if thumb_left else min(bounds[1], digit_bounds[1])
        if palm_high > palm_low:
            palm_profile.append((
                round((palm_high - palm_low + 1) / span_x, 6),
                round(((palm_low + palm_high) / 2.0 - x0) / span_x - 0.5, 6),
            ))
    # Where along the height that reach is real rather than a wobble in the outline. This is the thumb's
    # root: a thumb tucked into the palm is hidden behind the palm for its whole length except where it
    # leaves the hand, so this band is the only part of it a front-axis plate observes at all.
    band = sorted(y for y, value in reach[thumb_side] if value > THUMB_REACH_FRACTION * span_x)
    bulge = max((value for _y, value in reach[thumb_side]), default=0)
    return resampled, {
        "aspect": round(span_x / span_y, 6),
        "thumbSide": thumb_side,
        "thumbRootFraction": [round((band[0] - y0) / span_y, 6), round((band[-1] - y0) / span_y, 6)] if band else None,
        "thumbReachFraction": round(max(0, bulge) / span_x, 6),
        "fingerBandFraction": round((knuckle - y0) / span_y, 6),
        "fingerSpanFraction": round((digit_bounds[1] - digit_bounds[0] + 1) / span_x, 6),
        "widthProfile": [list(entry) for entry in profile],
        "palmProfile": [list(entry) for entry in palm_profile],
        "digitRuns": _digit_tracks(occupied, image_width, x0, x1, y0, y1, span_x, span_y),
        "widestRowFraction": round(peak, 6),
        "sourcePixelCount": len(cells),
    }

def _digit_tracks(
    occupied: set[int], width: int, x0: int, x1: int, y0: int, y1: int, span_x: int, span_y: int
) -> list[dict[str, float]]:
    """Follow each digit down from its own tip, and stop it where it merges into its neighbour.

    This is what replaces "four digits evenly spaced across the measured row, all the same width". That
    assumption was wrong in three ways at once on the real plate, and the plate says so plainly: the digits
    measure 0.226, 0.228, 0.204 and 0.129 of the frame rather than one width, their centres are 0.233, 0.226
    and 0.168 apart rather than evenly, and their tips are at 0.036, 0.000, 0.062 and 0.147 of the height,
    which orders them middle, index, ring, little without any anthropometric prior being consulted.

    A single row cannot supply this. Read at one height the digits are either not all present yet -- the
    little finger starts a seventh of the way down -- or already merging, and picking the lowest row with
    four runs lands in the merge, where one "run" 0.44 of the frame wide is two digits at once. Following
    each run from its tip and ending it at the merge measures each digit where that digit is actually
    separate.
    """
    minimum = max(2, round(span_x * MIN_DIGIT_RUN_FRACTION))

    def runs_at(y: int) -> list[tuple[int, int]]:
        found: list[list[int]] = []
        for x in range(x0, x1 + 1):
            if y * width + x not in occupied:
                continue
            if found and x == found[-1][1] + 1:
                found[-1][1] = x
            else:
                found.append([x, x])
        return [(low, high) for low, high in found if high - low + 1 >= minimum]

    def touching(a: tuple[int, int], b: tuple[int, int]) -> bool:
        return not (a[1] < b[0] or a[0] > b[1])

    finished: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    # Merged runs have to be remembered from row to row. Without that the run left over after two digits
    # merge belongs to no track, starts a fresh one, and that track is the merged mass -- which is how a
    # "digit" 0.97 of the frame wide got measured.
    merged: list[tuple[int, int]] = []
    for y in range(y0, y1 + 1):
        next_active: list[dict[str, Any]] = []
        next_merged: list[tuple[int, int]] = []
        for run in runs_at(y):
            owners = [track for track in active if touching(run, track["last"])]
            if len(owners) > 1 or any(touching(run, block) for block in merged):
                for track in owners:
                    track["mergeRow"] = y
                finished.extend(owners)
                next_merged.append(run)
            elif owners:
                owners[0]["last"] = run
                owners[0]["mergeRow"] = y
                owners[0]["rows"] += 1
                if run[1] - run[0] > owners[0]["width"]:
                    owners[0]["width"] = run[1] - run[0]
                    owners[0]["centre"] = (run[0] + run[1]) / 2.0
                owners[0]["widths"].append(run[1] - run[0])
                next_active.append(owners[0])
            else:
                next_active.append({"tip": y, "last": run, "rows": 1, "widths": [run[1] - run[0]], "mergeRow": y,
                                    "width": run[1] - run[0], "centre": (run[0] + run[1]) / 2.0})
        finished.extend(track for track in active if track not in next_active and track not in finished)
        active, merged = next_active, next_merged
    finished.extend(active)
    # The four highest tips. A plate can yield a fifth track -- on the fixture the thumb's lobe reads as one,
    # starting at 0.49 of the height against 0.005 to 0.124 for the digits -- and the digits are the ones that
    # reach the top of the frame.
    digits = sorted(finished, key=lambda track: (track["tip"], -track["rows"]))[:DIGIT_TRACKS]
    return [
        {
            "centre": round((track["centre"] - x0) / span_x - 0.5, 6),
            "width": round((track["width"] + 1) / span_x, 6),
            # The width HALFWAY down the digit's own visible length. A digit TAPERS, and that is not a
            # detail: the
            # gap between two neighbours is 0.1 to 0.9 of a grid cell at their widest, which is sub-cell and
            # unrepresentable, and 2.1 to 3.1 cells near their tips, which the grid carries easily. Modelled
            # as one cylinder of the widest section a hand fuses into a mitten; tapered, it separates where
            # the reference separates and merges where the reference merges.
            #
            # Floored at a fraction of the base, because a fifth of the way down is measured against each
            # digit's OWN tracked length and the little finger's track is a seventh as long as the middle
            # finger's: a fifth down it is still inside the tip's rounding, reading 0.057 of the frame against
            # a base of 0.128, and the digit rendered as a needle. Sampling at the halfway point instead cured
            # the needle and cost the separation -- the distal halves grew wide enough to touch at some heights
            # and not others, which put a tunnel through the hand and took V - E + F from 2 to 0.
            "tipWidth": round(max(
                track["widths"][max(0, min(len(track["widths"]) - 1, len(track["widths"]) // 5))] + 1,
                MIN_TIP_WIDTH_RATIO * (track["width"] + 1),
            ) / span_x, 6),
            "tipFraction": round((track["tip"] - y0) / span_y, 6),
            # Where this digit stops being separate, which is its web. The proximal segment ends here rather
            # than at some fraction of the digit's length: carried to the halfway point instead, the widened
            # knuckle segments merged the digits from 0.18 of the height where the plate merges them at 0.22.
            "mergeFraction": round((track["mergeRow"] - y0) / span_y, 6),
        }
        for track in sorted(digits, key=lambda track: track["centre"])
    ]


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
