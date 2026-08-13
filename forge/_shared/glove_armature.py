"""Fit a hand armature to the measured silhouette, as an SDF the runtime already knows how to mesh.

Why this replaces the inflation. A chamfer medial-axis inflation makes thickness proportional to the
2D distance to the silhouette boundary, so a narrow feature is always thin: measured on the real
Slingshot plates, the finger bands came out at a depth-to-width ratio of 0.13-0.18 where a finger is
round (about 1.0), and the thumb's z range sat *inside* the palm's, meaning it lay in the same plane
as the fingers rather than rotated out of it. Both are properties of inflating a silhouette, not
tuning problems: the shape it produces is a puffed sticker, and it only looks right from the one
camera axis the silhouette was measured on.

A hand is a palm plus five tapered digits, each with a roughly circular cross-section and its own
direction. `geometryDescriptor.sdf` already expresses exactly that -- capsules, a box, smooth-union --
and `generate_threejs_factory`'s `polygonizeSdf` already meshes it, closed by construction.

What the silhouette supplies and what a prior supplies is recorded per part, because the split is the
honest part of this: the outline gives proportions, and anatomy gives the third axis that two
front-axis plates cannot.
"""

from __future__ import annotations

import math
from typing import Any

from forge._shared.sdf_mesh import _apply_quaternion, _quaternion_from_euler_xyz

# Anthropometric ratios, all relative to palm width. Priors, not measurements.
PALM_DEPTH_RATIO = 0.30
THUMB_RADIUS_RATIO = 0.135
# Where the thumb's root sits when the outline could not measure it, as fractions of the height from the
# top. Only reached for a silhouette with no thumb-side reach at all.
THUMB_ROOT_FALLBACK = (0.33, 0.61)
# Ordered from the thumb outward: the index finger is the one beside the thumb.
DIGITS = ("index", "middle", "ring", "pinky")
# Digit length as a fraction of the middle finger. Measured anthropometry, not invented: Colombian and
# US-Army 50th-percentile hand surveys agree to within 0.02 (index 0.899-0.901, ring 0.930-0.949,
# little 0.756-0.772). Reported via NotebookLM from the ratio-scaling survey (Dialnet, Tables 5 and 10).
DIGIT_LENGTH = {"index": 0.90, "middle": 1.0, "ring": 0.94, "pinky": 0.77}
# The gap between two digits, measured in POLYGONISATION CELLS rather than as a fraction of a diameter.
#
# The constraint comes from the grid, so the unit has to be the grid's. An extractor sampling a field on
# a lattice has exactly two representable states for two nearby solids: a gap wider than a cell, or a real
# overlap. A gap NARROWER than a cell is neither -- the cell straddling it contains two surface sheets,
# naive surface nets gives that cell one vertex, and the two sheets are welded into a non-manifold pinch.
# Expressed as a fraction of a diameter the gap silently fell under a cell whenever the digits were slim
# or the resolution coarse: measured at resolution 64, a 0.10-diameter gap came out at half a cell and
# pinched along the entire seam between the index and middle fingers, six edges of it.
#
# Why a gap at all, when the reference photograph shows the fingers touching with only creases between
# them: a crease is visible only through shading, and the review runtime renders unlit on purpose
# (`MeshBasicMaterial`, so a repeat capture is byte-identical). Under a material with no lighting a
# creased mitten and a solid mitten are the same picture, so the separation has to be geometric. That is
# a property of the renderer, not of the hand.
DIGIT_GROOVE_CELLS = 1.5
# The margin the bounds add around the content, in digit radii. It feeds back into the cell size, so the
# digit diameter below is solved for rather than assigned.
BOUNDS_MARGIN_RADII = 1.6
# The thumb web's blend radius, as a fraction of the thumb's radius.
THUMB_WEB_OF_RADIUS = 0.6
# The blend must stay well under a finger radius. At 0.7x the finger radius the smooth union melts
# the four digits into one slab, which is the same fused-finger look the inflation produced.
SMOOTH_UNION_RADIUS_OF_FINGER = 0.16
# Slices thinner than this are the outline's closing edge, not a cross-section of the hand.
MIN_PROFILE_SLICE_WIDTH = 0.15
# How deeply consecutive palm slices must overlap, in POLYGONISATION CELLS -- the same unit, and for the same
# reason, as `DIGIT_GROOVE_CELLS`. Two solids can be a real overlap or a gap wider than a cell; an overlap
# THINNER than a cell is neither, and the extractor welds the two surfaces into a non-manifold pinch.
#
# This was a dimensionless 1.15 multiple of the slice spacing, which sounds safe and was not: solved out, the
# overlap it produces is `H * 0.15 / (slices - 1 + 1.15)` for a palm `H` tall, which on the real Slingshot
# plate is 0.0028 against a cell of 0.0179 -- six times too thin, for every slice junction on the stack. The
# sweep was manifold only by where the grid's samples happened to land, which is why every unrelated change to
# the thumb flipped the mesh's non-manifold count: the thumb's reach sets the bounds, the bounds set the cell,
# and the cell decided whether the palm's own seams welded that time.
#
# Two cells rather than one, and the second is not padding. At one cell both plates sit on the threshold and
# fall off it unpredictably: the real Slingshot plate welded one edge between `palm-slice-21` and `-22` at
# 1.0 cells and was clean at 1.5, and the fixture was the other way round. Two is the smallest whole number
# that is manifold on both, and it is chosen against those two plates only -- a third plate could need more.
PROFILE_SLICE_OVERLAP_CELLS = 2.0
# The THUMB's radius, in cells. It is singled out because it is the one digit whose separation is not already
# solved against the grid: the four fingers grow out of the palm's top, where the palm ends, and are held apart
# from each other by `DIGIT_GROOVE_CELLS`, so their diameter shrinks with the cell. The thumb grows out of the
# palm's SIDE and has to stand clear of the palm's own surface, and its radius is an anthropometric fraction of
# palm width that does not shrink with the grid at all.
MIN_THUMB_RADIUS_CELLS = 2.0
DEFAULT_RESOLUTION = 64


def _capsule(part_id: str, *, radius: float, height: float, translation: list[float], rotation: list[float]) -> dict[str, Any]:
    return {
        "id": part_id,
        "type": "capsule",
        "radius": round(radius, 6),
        "height": round(height, 6),
        "transform": {"translation": [round(value, 6) for value in translation], "rotation": [round(value, 6) for value in rotation]},
    }


def _content_extents(primitives: list[dict[str, Any]]) -> list[list[float]]:
    """The assembled solid's reach per axis, from the primitives rather than from a polygonisation."""
    extents = [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]
    for primitive in primitives:
        offset = primitive.get("transform", {}).get("translation", [0.0, 0.0, 0.0])
        if primitive["type"] == "ellipsoid":
            reach = list(primitive["radii"])
        else:
            # A rotated capsule reaches its half-length plus its radius along any axis, so this is the
            # bound rather than the exact silhouette. Being conservative here only pads the frame.
            span = primitive["height"] / 2.0 + primitive["radius"]
            reach = [span, span, span]
        for axis in range(3):
            extents[axis][0] = min(extents[axis][0], offset[axis] - reach[axis])
            extents[axis][1] = max(extents[axis][1], offset[axis] + reach[axis])
    return extents


def build_glove_sdf_descriptor(
    measured: dict[str, Any],
    *,
    hand: str,
    source_view_id: str,
    resolution: int = DEFAULT_RESOLUTION,
    depth_source: str | None = None,
) -> dict[str, Any]:
    """Fit palm, four fingers, an opposed thumb and a cuff to the measured outline."""
    if hand not in {"left", "right"}:
        raise ValueError(f"hand must be left or right, not {hand!r}")
    aspect = float(measured["aspect"])
    finger_band = float(measured.get("fingerBandFraction", 0.37))
    if not 0.05 < finger_band < 0.9:
        raise ValueError(f"fingerBandFraction {finger_band} is outside the range a hand can occupy")
    thumb_side = measured.get("thumbSide", "right")
    # WHICH hand the measurement came from, rather than assuming it was the left one. A pair plate holds two
    # gloves and the silhouette measures the largest component, which on the real Slingshot plates is the
    # RIGHT glove; every offset measured from it was then applied to the left hand unmirrored. Rendered
    # untextured that put both thumbs on the outside of the pair, where the plate plainly shows them facing
    # each other.
    #
    # Handedness is not a guess here: seen from the back of the hand, the thumb lies on the side away from
    # the body, so a dorsal view whose thumb reaches toward image-left is a right hand. The track's target
    # view is the dorsal plate, which is what makes this readable at all -- a palmar view would invert it.
    observed_hand = "right" if thumb_side == "left" else "left"
    mirror = 1.0 if hand == observed_hand else -1.0
    # The outline is normalised to unit height, so palm width follows from the measured aspect.
    palm_width = aspect
    palm_depth = PALM_DEPTH_RATIO * palm_width
    finger_length = finger_band * 1.0
    # The digit row's width is measured, so the digit radius follows from it rather than from a ratio:
    # four digits packed edge to edge across the measured span, which is what the reference shows. The
    # ratio prior is the fallback for a silhouette that could not supply the span, and it was wrong on
    # the real plate by enough to push the outer digits off the glove.
    digit_row_width = float(measured["fingerSpanFraction"]) * palm_width
    if digit_row_width <= 0.0:
        raise ValueError("the silhouette measured a digit row of zero width; there is nothing to place digits across")
    # Four diameters and three gaps fill the measured row, with each gap a fixed number of cells. The cell
    # size depends on the bounds, the bounds margin depends on the digit radius, and the radius is what is
    # being solved for -- so solve it rather than iterate. With the frame one unit tall and the margin
    # `BOUNDS_MARGIN_RADII` radii at each end, the bounds are `1 + BOUNDS_MARGIN_RADII * diameter` tall,
    # and substituting `gap = DIGIT_GROOVE_CELLS * bounds / resolution` into
    # `row = 4 * diameter + 3 * gap` gives one linear equation in the diameter.
    gaps = len(DIGITS) - 1
    cells_per_gap = DIGIT_GROOVE_CELLS / resolution
    diameter = (digit_row_width - gaps * cells_per_gap) / (len(DIGITS) + gaps * cells_per_gap * BOUNDS_MARGIN_RADII)
    if diameter <= 0.0:
        raise ValueError(
            f"a digit row {digit_row_width:.4f} wide cannot hold {len(DIGITS)} digits separated by "
            f"{DIGIT_GROOVE_CELLS} cells at resolution {resolution}"
        )
    finger_radius = diameter / 2.0
    digit_gap = cells_per_gap * (1.0 + BOUNDS_MARGIN_RADII * diameter)
    # The knuckle line is the measured boundary between digits and palm, so it anchors both.
    palm_top = 0.5 - finger_band

    # The palm and cuff are a stack of ellipsoid slices following the measured outline, not one
    # ellipsoid. A single ellipsoid of palm width by palm height is a circle -- radii 0.309 by 0.294 on
    # the real plate -- where the plate shows a trapezoid tapering from 0.95 of full width at the
    # knuckles to 0.68 at the cuff. The circle was both the "squat and fat" silhouette and the reason
    # parts of the render sampled background: its edges mapped onto plate columns outside the glove.
    #
    # Width and centre per slice are OBSERVED. Depth is not: it is the palm-depth prior, scaled by each
    # slice's own width so a narrow slice is also shallow rather than a wide disc on edge.
    profile = [(width, centre) for width, centre in
               (tuple(entry) for entry in measured.get("widthProfile") or [])
               if width >= MIN_PROFILE_SLICE_WIDTH]
    if len(profile) < 2:
        raise ValueError(
            f"the silhouette supplied {len(profile)} usable outline slices below the knuckle line; "
            "the palm cannot be swept from fewer than two, and substituting a plain ellipsoid would "
            "put back the circular palm this replaces"
        )
    # How many of the measured outline slices this grid can carry. A slice thinner than a cell is the
    # same defect as a gap narrower than a cell: the cell straddles two surface sheets and the extractor
    # welds them into a non-manifold pinch. Measured on the real plate at resolution 64, 24 slices put the
    # slice half-height at 0.0141 against a cell of 0.0176 and brought back three pinches, while 10 slices
    # were manifold but coarse enough that the steps between consecutive arcs showed as a scalloped edge.
    # So the count is not a choice: it is the palm's height divided by the cell size, which samples the
    # outline exactly as finely as the grid can represent.
    cell = (1.0 + BOUNDS_MARGIN_RADII * diameter) / resolution
    affordable = max(2, min(len(profile), int((palm_top + 0.5) / cell)))
    if affordable < len(profile):
        profile = [profile[round(index * (len(profile) - 1) / (affordable - 1))] for index in range(affordable)]

    primitives: list[dict[str, Any]] = []
    widest = max(width for width, _centre in profile)
    # Slices overlap so the union is a continuous sweep rather than a stack of beads.
    #
    # The slice CENTRES span [-0.5 + half_height, palm_top - half_height], not [-0.5, palm_top], so the
    # swept surface ends exactly at the knuckle line and at the bottom of the plate. Centring the slices
    # on the sampled heights instead made the stack overshoot by half a slice at each end: the top slice
    # bulged above the knuckle line into the digit band and ate a tenth of the hand's height off the
    # fingers -- the plate says the digits are 40.8% of the height and the render gave 29.5%.
    # Solving "the covered span is exactly palm_top down to -0.5" and "each slice is OVERLAP times half
    # the centre spacing" together gives the half-height directly, with no knob left over.
    #
    # The overlap multiple is SOLVED for rather than assigned, so the constraint above holds at whatever slice
    # count and cell size this plate and grid produce. Writing the covered span as `H`, the gaps between slice
    # centres as `k = slices - 1`, and the multiple as `O`, the two equations give
    # `overlap = H * (O - 1) / (k + O)`; setting that equal to the required cells and solving for `O` gives the
    # line below. `H > required` is what makes it positive, and a palm shorter than one cell has no sweep.
    palm_span = palm_top + 0.5
    required = PROFILE_SLICE_OVERLAP_CELLS * cell
    if palm_span <= required:
        raise ValueError(
            f"the palm is {palm_span:.4f} tall, under the {required:.4f} that {PROFILE_SLICE_OVERLAP_CELLS} "
            f"polygonisation cells need; at resolution {resolution} this grid cannot carry a swept palm"
        )
    overlap = (palm_span + required * (len(profile) - 1)) / (palm_span - required)
    half_height = palm_span / (2.0 * (len(profile) - 1) / overlap + 2.0)
    top = palm_top - half_height
    bottom = -0.5 + half_height
    for index, (width, centre) in enumerate(profile):
        y = top - (top - bottom) * index / (len(profile) - 1)
        primitives.append({
            "id": f"palm-slice-{index}",
            "type": "ellipsoid",
            "radii": [round(width * aspect / 2.0, 6), round(half_height, 6),
                      round(palm_depth / 2.0 * (width / widest), 6)],
            "transform": {"translation": [round(mirror * centre * aspect, 6), round(y, 6), 0.0]},
        })
    # Centre-to-centre, so the outer digits' outer edges land exactly on the measured span.
    span = (len(DIGITS) - 1) * (diameter + digit_gap)
    if span <= 0.0:
        raise ValueError(f"measured digit row {digit_row_width} leaves no width to place {len(DIGITS)} digits across")
    thumb_direction = 1.0 if thumb_side == "right" else -1.0
    for index, digit in enumerate(DIGITS):
        # Digit placement is fitted, not detected: the reference shows the fingers pressed together,
        # and the skyline peaks that would separate them are not reliably there.
        #
        # The ORDER, though, is anatomy: the index finger is the one beside the thumb, so the row runs
        # from the thumb's side outward. Laying it out index-to-pinky in increasing x regardless put the
        # pinky next to the thumb and the middle finger -- the longest -- on the wrong side of centre.
        # It also crowded the thumb against the pinky closely enough to pinch the surface there, which is
        # how it was found: all three non-manifold edges sat between `thumb-digit` and `pinky-digit`.
        position = index if thumb_direction < 0.0 else (len(DIGITS) - 1 - index)
        offset = (position - (len(DIGITS) - 1) / 2.0) * (span / (len(DIGITS) - 1))
        length = finger_length * DIGIT_LENGTH[digit]
        primitives.append(_capsule(
            f"{digit}-digit",
            radius=finger_radius * (0.86 if digit == "pinky" else 1.0),
            height=length,
            translation=[mirror * offset, palm_top + length / 2.0 - finger_radius, 0.0],
            # Fingers curl slightly forward, which is what a worn glove does at rest.
            rotation=[math.radians(-9.0), 0.0, 0.0],
        ))
    thumb_radius = THUMB_RADIUS_RATIO * palm_width
    # The thumb runs ALONGSIDE the palm on the thumb side, rotated onto the palmar side of it -- which is why
    # the dorsal plate barely shows it and the palmar plate shows a whole digit. Both readings have to hold at
    # once, and only this pose does: standing in the digit row it would need width the measured span does not
    # have, and folded across the palm it reads as a lump rather than a digit, which is what the first version
    # here rendered.
    #
    # So the pose is a segment, and the outline supplies most of it. The thumb's own lobe -- the stretch where
    # the hand reaches past the four digits' envelope -- is 0.50 of the hand's height on the real Slingshot
    # plate, and the segment spans exactly that, at the palm's thumb-side edge so the thumb's outer surface
    # lands on the outline where the plate puts it. The one prior left is the depth: the axis leaves the palm's
    # own surface at the wrist, which is the web, and stands a radius clear of it at the tip. Angles are then
    # derived from the segment rather than chosen -- a pair of Euler priors cannot express "clear of the palm"
    # at all, since where the palmar surface sits depends on the palm's depth.
    root = measured.get("thumbRootFraction") or list(THUMB_ROOT_FALLBACK)
    thumb_x = mirror * thumb_direction * (palm_width / 2.0 - thumb_radius)
    # The TIP height comes from the lobe, the BASE from the wrist, and the asymmetry is not a shortcut. The
    # lobe is where the outline reaches past the four digits' envelope, and that test fails at both ends for
    # opposite reasons: near the knuckles the hand is wider than the tapered fingers so the lobe starts too
    # high, and below mid-palm the hand narrows back inside the envelope while the thumb is still there, so
    # the lobe stops too low. The tip survives the first error because the plate can be read directly -- the
    # thumb's tip sits at 0.22-0.27 of the height, which is what the lobe's top says. The base cannot, so it
    # takes the anatomical anchor instead: a thumb's metacarpal starts at the wrist. Measured from the lobe's
    # bottom the base sat at 0.17 above the frame's middle and the thumb rendered as a 2.4:1 pill stuck on the
    # palm; from the wrist it spans 3.9 diameters, which is a digit.
    # The base sits at the palm's MID-DEPTH, embedded, not tangent to its palmar surface. That is the web on a
    # real hand, and it is also the only numerically safe end: tangency is a near-touch, the gap it leaves runs
    # under one grid cell, and the extractor welds the two surfaces there. Measured on the fixture, a tangent
    # base put two non-manifold edges between `thumb-digit` and `palm-slice-10` at the wrist.
    proximal = (thumb_x, -0.5 + thumb_radius, 0.0)
    distal = (thumb_x, 0.5 - min(root), -(palm_depth / 2.0 + thumb_radius))
    span_vector = [distal[axis] - proximal[axis] for axis in range(3)]
    reach = math.sqrt(sum(value * value for value in span_vector))
    if reach <= 2.0 * thumb_radius:
        raise ValueError(
            f"the measured thumb root spans {reach:.4f} of the frame, which a thumb {2 * thumb_radius:.4f} "
            "across cannot be posed along; the silhouette did not resolve a thumb"
        )
    axis = [value / reach for value in span_vector]
    # A capsule's own axis is its local +Y, so the rotation is whichever one carries +Y onto that segment.
    # With the x rotation left at zero, `setFromEuler` XYZ sends +Y to (-sin z * cos y, cos z, sin z * sin y),
    # which inverts in closed form -- no search, and the emitted Eulers stay the same three numbers the
    # runtime already reads.
    thumb_rotation = [0.0, math.atan2(axis[2], -axis[0]), math.acos(max(-1.0, min(1.0, axis[1])))]
    primitives.append(_capsule(
        "thumb-digit",
        radius=thumb_radius,
        # The caps are part of the reach, so the cylinder is the segment less one diameter.
        height=reach - 2.0 * thumb_radius,
        translation=[(proximal[axis_index] + distal[axis_index]) / 2.0 for axis_index in range(3)],
        rotation=thumb_rotation,
    ))
    # No rescale here, deliberately. An earlier version fitted the assembled parts into the frame by
    # uniform scale, because they were built from ratios that did not respect it and overran the plate.
    # They respect it now: the palm sweeps the measured outline from the knuckle line down to the bottom,
    # and the digits run from the knuckle line up to the top, so the hand already occupies y -0.5 to 0.5.
    # Rescaling on top of that fought the construction -- the thumb hangs slightly below the frame, so the
    # fit read the content as taller than a unit and shrank everything, which pushed the knuckle line
    # down and cost the fingers a tenth of the hand. Measured: the plate says the digits are 40.8% of the
    # height and the rescaled mesh rendered them at 29.5%.

    # The operation TREE, not a flat chain, and the difference is what makes fingers read as fingers.
    #
    # A flat chain of smooth-unions blends every part with everything already accumulated, and
    # smooth-union blends by proximity: two digits that are merely adjacent melt into one mitten, which
    # is what the render showed. Anatomy says which junctions are smooth and which are creases -- a
    # digit meeting the palm has a fillet at the knuckle, a digit meeting the digit beside it has a
    # crease -- so the tree says it too. This is the non-learned form of what LISA gets from per-bone
    # fields blended by skinning weights rather than by distance: adjacency stops implying fusion.
    # Radii are read off the primitives AFTER the frame fit, not from the pre-scale ratios: the fit
    # rescales every dimension, so a radius computed before it is in the wrong units. The blend was
    # already being computed from the pre-scale finger radius, which made it larger than intended
    # relative to the digits it was blending.
    fillet = min(item["radius"] for item in primitives if item["type"] == "capsule") * SMOOTH_UNION_RADIUS_OF_FINGER
    operations: list[dict[str, Any]] = []

    def combine(name: str, parts: list[str], kind: str, radius: float | None = None) -> str:
        previous = parts[0]
        for index, part in enumerate(parts[1:]):
            output = f"{name}-{index}"
            operation: dict[str, Any] = {"id": output, "type": kind, "left": previous, "right": part}
            if radius is not None:
                operation["radius"] = round(radius, 6)
            operations.append(operation)
            previous = output
        return previous

    slice_ids = [item["id"] for item in primitives if item["id"].startswith("palm-slice")]
    # A HARD union along the sweep, now that consecutive slices are guaranteed to overlap by a full cell.
    # Smooth-union was here to hide the junctions of barely-overlapping beads, and once the overlap became
    # real it turned into the defect: `smin` ADDS material near a junction, and this is a chain of 31 of them,
    # so the additions accumulate outward. Measured on the real plate the palm's widest slice is 0.601 across
    # and the extracted mesh spanned 0.703 -- a silhouette 14% wider than the plate's own, from the blend
    # alone. With a cell of real overlap the crease a hard union leaves is finer than the grid can express.
    palm = combine("palm-sweep", slice_ids, "union") if len(slice_ids) > 1 else slice_ids[0]
    digits = combine("digit-row", [f"{digit}-digit" for digit in DIGITS], "union")
    hand = combine("knuckles", [palm, digits], "smooth-union", fillet)
    # The thumb web is a broad transition on a real hand, and it has to be broad here for a second
    # reason: a fillet narrower than the gap between the thumb and the palm leaves them nearly-touching
    # rather than merged, which is the same sub-cell pinch the digit gaps had. Measured at resolution 64,
    # the small fillet left two non-manifold edges between `thumb-digit` and the palm slices.
    combine("thumb-web", [hand, "thumb-digit"], "smooth-union", thumb_radius * THUMB_WEB_OF_RADIUS)

    # Bounds hug the content instead of being a cube around the longest reach. A cube wastes most of
    # its cells on empty space, and the gap between two digits is only a fraction of a finger
    # diameter: at the previous cube bounds one cell was as wide as the gap, so the digits could not
    # be resolved apart no matter how they were placed.
    # Read the margin off the normalised primitives rather than the pre-scale ratio, so it stays a
    # constant number of finger radii after the frame fit rather than shrinking with it. Indexing a
    # fixed position would break the moment the palm stopped being one primitive, which it has.
    margin = min(item["radius"] for item in primitives if item["type"] == "capsule") * BOUNDS_MARGIN_RADII
    extents = _content_extents(primitives)
    # Refuse a grid too coarse to carry the thumb, rather than emitting a welded mesh and leaving stage 4 to
    # discover it. Measured across resolutions on the fixture: at 24 the thumb's radius is 1.76 cells and the
    # extraction welds three edges -- one at the thumb's web and one at each of the index and pinky knuckles --
    # while 32, 48 and 64 are all clean, with the thumb at 2.32 cells and up. Guarding the slimmest capsule
    # instead was wrong and the numbers said so: at 32 that is a FINGER at 1.0 cells, on a mesh with no welds
    # at all, because the fingers' own separation is already solved in cells.
    if thumb_radius < MIN_THUMB_RADIUS_CELLS * cell:
        raise ValueError(
            f"resolution {resolution} gives a cell of {cell:.4f} and a thumb radius of {thumb_radius:.4f}, "
            f"under the {MIN_THUMB_RADIUS_CELLS} cells the extractor needs to keep the thumb clear of the "
            "palm it grows out of; raise the resolution"
        )
    return {
        "sdf": {
            "primitives": primitives,
            "operations": operations,
            "resolution": resolution,
            "bounds": {
                "min": [round(extents[axis][0] - margin, 6) for axis in range(3)],
                "max": [round(extents[axis][1] + margin, 6) for axis in range(3)],
            },
            "derivation": {
                "hand": hand,
                "observed": {
                    "source": source_view_id,
                    "aspect": aspect,
                    "fingerBandFraction": finger_band,
                    "fingerSpanFraction": measured.get("fingerSpanFraction"),
                    "thumbSide": thumb_side,
                    "thumbRootFraction": measured.get("thumbRootFraction"),
                    "measuredHand": observed_hand,
                },
                "inferred": {
                    "palmDepthRatio": PALM_DEPTH_RATIO,
                    "fingerRadius": "derived from the measured digit-row width, four digits edge to edge"
                    if digit_row_width > 0.0
                    else f"ratio prior {FINGER_RADIUS_RATIO}; the silhouette supplied no digit-row width",
                    "digitPlacement": "evenly spaced across the measured digit-row width; the skyline of the real plate yields two valleys, not four, so per-digit centres would be fitting noise",
                    "thumbPose": "alongside the palm's thumb-side edge, rotated onto its palmar side; the lobe "
                    f"it spans is measured{'' if measured.get('thumbRootFraction') else f' (absent here, prior {THUMB_ROOT_FALLBACK})'} "
                    "and the depth is the palm-depth prior",
                    "depth": depth_source or "anthropometric ratios; two front-axis plates carry no depth",
                },
            },
        }
    }
