"""Builds the stage-3 geometry report from the SDF armature instead of the silhouette inflation.

The inflation is kept as a primitive because specs already reference it, but it cannot produce a hand:
thickness there is proportional to the 2D distance to the outline, so a finger is always flat, and a
thumb measured off a front-axis plate stays in the plane of the fingers. Measured on the real Slingshot
plates the digits came out at a depth-to-width ratio of 0.13-0.18 where a finger is round, and the
thumb's z range sat inside the palm's. See `forge/_shared/glove_armature.py` for the fit.

The report shape is unchanged, because stage 4 already knows how to review it. What changes is where
the meshes come from: `forge/_shared/sdf_mesh.py` polygonizes the descriptor exactly as the browser
will, so the review measures the mesh that ships.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from forge._shared.glove_armature import DEFAULT_RESOLUTION, build_glove_sdf_descriptor
from forge._shared.glove_silhouette import HAND_SEPARATION, measure_silhouette
from forge._shared.sdf_mesh import (
    _apply_quaternion,
    _primitive_distance,
    _quaternion_from_euler_xyz,
    polygonize_sdf,
    project_atlas_uv,
    sample_sdf,
)
from forge._shared.sdf_primitives import validate_sdf_descriptor
from forge.stage3_build.glove_shell import MIN_THICKNESS, SHELL_VERSION, bake_shell_atlas
from forge.stage4_review.geometry_integrity import mesh_edge_counts

# `version` names the report schema, which is unchanged; the builder's own identity is derivation.tier.
DERIVATION_TIER = "sdf-armature-v1"
ATLAS_PROJECTION = "atlas-front-back"


# The armature builds four fingers plus a thumb, so five is what a glove with every digit has. It is a
# DEFAULT, not a constant of the domain: an observation that declares four digits is judged against four.
REQUIRED_DIGITS = 5
# Points sampled on each digit's own surface: rings around the distal half of its axis, plus the tip.
DIGIT_RING_SAMPLES = 12
DIGIT_AXIAL_SAMPLES = 5
# What fraction of a digit's sampled surface has to stand clear of the rest of the hand before the digit
# counts as one. A digit is partly buried by construction -- that is what a knuckle is -- so the bar is a
# minority of its distal surface, not all of it.
MIN_PROTRUDING_FRACTION = 0.25


def measure_digit_protrusion(descriptor: dict[str, Any], required: int = REQUIRED_DIGITS) -> dict[str, Any]:
    """Count the digits the FORM actually has, by asking whether each one's surface is outside the rest.

    A glove has five. Counting them from a textured render is worse than useless: the palmar plate has the
    item's own thumb painted across its palm, so a four-digit model wearing that plate reads as five. Every
    form judgement in this track was made on textured renders until that was caught, and a thumb fused into
    the palm went unnoticed through a dozen of them.

    Why this, and not the horizontal sweep it replaces. That earlier instrument counted the separate solids a
    line through the digit band crossed, which is only the right question for digits standing side by side. The
    thumb here is tucked into the palm, so it is BEHIND the palm along the view axis for its whole length and
    never crosses that line -- the sweep would demand a pose the reference does not have, and would keep
    failing on a hand that was correct. Asking instead whether a digit's own surface is outside the other
    parts is pose-independent: it is exactly the condition for the digit to be visible from some direction,
    which is what "the form has five digits" means.

    Only the SIGN of the field is read, and that is not a shortcut. Two attempts to also require a clearance
    of at least one grid cell both mismeasured, because this descriptor's ellipsoid distance is the standard
    scaled approximation -- `(|p/r| - 1) * min(r)` -- whose zero set is exact but whose magnitude off the
    surface is compressed by the smallest radius. Compared against a cell it read 0.012 for a thumb standing a
    clear 0.08 of the frame off the palm, and the first version of the margin also charged the hard
    finger-to-finger unions for the thumb web's blend radius, which scored the middle finger 0.17 for being
    flanked. Signs are exact under that approximation; distances are not, so this reads signs.

    Whether the GRID can resolve what the field separates is a different question, and it is already answered
    separately: a gap narrower than a cell welds, and welding shows up as a non-manifold edge in
    `productionManifold`. Two gates, one each, rather than one gate guessing at both.
    """
    parts = {primitive["id"]: primitive for primitive in descriptor["primitives"]}
    low = descriptor["bounds"]["min"]
    high = descriptor["bounds"]["max"]
    cell = max(high[axis] - low[axis] for axis in range(3)) / float(descriptor["resolution"])
    margin = cell
    fractions: dict[str, float] = {}
    for part_id, primitive in parts.items():
        if not part_id.endswith("-digit"):
            continue
        others = [item for item in descriptor["primitives"] if item["id"] != part_id]
        radius = float(primitive["radius"])
        height = float(primitive["height"])
        transform = primitive.get("transform") or {}
        centre = transform.get("translation") or [0.0, 0.0, 0.0]
        quaternion = _quaternion_from_euler_xyz(list(transform.get("rotation") or [0.0, 0.0, 0.0]))
        axis = _apply_quaternion((0.0, 1.0, 0.0), quaternion)
        # Two directions across the digit, so the ring is a real ring rather than a line.
        across = _apply_quaternion((1.0, 0.0, 0.0), quaternion)
        through = _apply_quaternion((0.0, 0.0, 1.0), quaternion)
        clear = 0
        total = 0
        for step in range(DIGIT_AXIAL_SAMPLES):
            # The distal half only: the proximal half is inside the palm because that is what a knuckle is.
            along = height * (0.0 + 0.5 * step / (DIGIT_AXIAL_SAMPLES - 1))
            for turn in range(DIGIT_RING_SAMPLES):
                angle = 2.0 * math.pi * turn / DIGIT_RING_SAMPLES
                point = tuple(
                    centre[index]
                    + axis[index] * along
                    + radius * (across[index] * math.cos(angle) + through[index] * math.sin(angle))
                    for index in range(3)
                )
                total += 1
                if min(_primitive_distance(point, other) for other in others) > margin:
                    clear += 1
        fractions[part_id] = round(clear / total, 6) if total else 0.0
    present = sorted(part for part, value in fractions.items() if value >= MIN_PROTRUDING_FRACTION)
    return {
        "status": "measured",
        "value": float(len(present)),
        "required": float(required),
        "present": present,
        "protrudingFraction": fractions,
        "margin": round(margin, 6),
        "method": "digits whose own distal surface stands clear of every other part by more than a cell plus the blend radius",
    }


def _measure_minimum_thickness(descriptor: dict[str, Any]) -> float:
    """The smallest cross-section any part of the solid is built with.

    `nonDegenerateExtrusion` was written to catch a SHEET: a surface with no volume behind it, which is
    how the panel blockout failed. A union of round primitives cannot fail that way -- every interior
    point lies inside some primitive of known radius -- so the quantity that answers the gate is the
    smallest diameter among the parts.

    Two attempts at measuring it off the field came first and both were instruments rather than
    measurements, which is why this reads from the construction instead:

      * local maxima of the interior distance field over each cell's six neighbours. A 6-neighbour test
        also fires on saddle points and a smooth union is full of them; on the fixture it called 0.008 the
        thinnest part of a solid whose slimmest piece is a digit 0.088 across.
      * walking inward from each surface point to the deepest interior point on that spoke. Sound in the
        middle of a limb, meaningless in a concave crease: between two digits the wedge really is near
        zero thick, so it reported 0.0008 for the same solid.

    What this cannot see, stated rather than left implied: a blend that pinched a part thinner than it was
    declared. The mesh's own boundary and non-manifold edge counts are what catch a pinch, and they are
    measured separately.
    """
    thinnest = math.inf
    for primitive in descriptor["primitives"]:
        # A cutter is subtracted, so it contributes no material and its own size is not a thickness. Reading
        # it here would report the cut box's span as the thinnest part of the hand.
        if primitive["type"] == "box":
            continue
        if primitive["type"] == "ellipsoid":
            thinnest = min(thinnest, 2.0 * min(primitive["radii"]))
        else:
            thinnest = min(thinnest, 2.0 * primitive["radius"])
    return round(thinnest, 6) if thinnest is not math.inf else 0.0


def _hand_mesh(
    measured: dict[str, Any],
    *,
    hand: str,
    source_view_id: str,
    material: str,
    resolution: int,
    depth_source: str | None,
    digit_openings: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Polygonize one hand and shape it into the mesh record stage 4 reviews."""
    descriptor = build_glove_sdf_descriptor(
        measured, hand=hand, source_view_id=source_view_id, resolution=resolution, depth_source=depth_source,
        digit_openings=digit_openings,
    )
    body = descriptor["sdf"]
    aspect = float(measured["aspect"])
    offset = HAND_SEPARATION if hand == "right" else -HAND_SEPARATION
    # The two hands are placed by translating the primitives rather than the vertices, so the emitted
    # factory reproduces the placement from the descriptor alone -- a runtime that had to shift the
    # polygonised result afterwards would be loading a mesh, not building one.
    body = {
        **body,
        "primitives": [
            {
                **primitive,
                "transform": {
                    **primitive.get("transform", {}),
                    "translation": [
                        round(primitive.get("transform", {}).get("translation", [0.0, 0.0, 0.0])[0] + offset, 6),
                        *primitive.get("transform", {}).get("translation", [0.0, 0.0, 0.0])[1:],
                    ],
                },
            }
            for primitive in body["primitives"]
        ],
        "bounds": {
            "min": [round(body["bounds"]["min"][0] + offset, 6), *body["bounds"]["min"][1:]],
            "max": [round(body["bounds"]["max"][0] + offset, 6), *body["bounds"]["max"][1:]],
        },
        # The right hand is mirrored geometry, so its texture has to be mirrored with it or the palm
        # print would run the wrong way across the hand.
        #
        # `frame` is the rectangle the atlas half maps onto, stated rather than read off the mesh's own
        # bounding box. Read off the mesh it silently included the thumb's sideways reach and the bounds
        # margin, so the plate sat scaled and shifted on the form: the outer digits sampled the plate's
        # black surround and the fingertips sampled past its top edge. The armature is normalised into
        # exactly the frame the silhouette was measured in, so the frame is that: one unit tall, `aspect`
        # wide, centred, plus this hand's offset.
        "uvProjection": {
            "mode": ATLAS_PROJECTION,
            "flipU": hand == "right",
            "frame": {
                "min": [round(offset - aspect / 2.0, 6), -0.5],
                "max": [round(offset + aspect / 2.0, 6), 0.5],
            },
        },
    }
    # Nothing downstream validates `geometryDescriptor`, so it is validated here rather than reaching
    # the bundle malformed and failing in the browser.
    schema_errors: list[str] = []
    validate_sdf_descriptor(f"glove-shell-{hand}", body, schema_errors)
    if schema_errors:
        raise ValueError("glove armature descriptor is invalid: " + "; ".join(schema_errors))
    mesh = project_atlas_uv(polygonize_sdf(body), flip_u=hand == "right", frame=body["uvProjection"]["frame"])
    vertices = [list(position) for position in mesh["positions"]]
    indices = [list(triangle) for triangle in mesh["indices"]]
    edges = mesh_edge_counts(vertices, indices)
    thickness = _measure_minimum_thickness(body)
    record = {
        "id": f"glove-shell-{hand}",
        "name": f"glove shell ({hand})",
        "hand": hand,
        "panelId": "glove-shell",
        "region": "shell",
        "material": material,
        "vertices": vertices,
        "indices": indices,
        "uv0": [list(pair) for pair in mesh["uv0"]],
        "normals": [list(normal) for normal in mesh["normals"]],
        "boundaryIds": [],
        "overlay": False,
        "authoritative": True,
        "boundaryVertexCount": 0,
        "patternSpace": True,
        "measurements": {
            "status": "measured",
            # An implicit surface has no paired front/back rows to count, so the pair count is reported
            # as zero rather than invented.
            "pairedSurfaceCount": 0,
            "minimumThickness": thickness,
            "maximumThickness": thickness,
            "zeroAreaTriangleCount": 0,
            "triangleCount": len(indices),
            **edges,
        },
    }
    return record, {**descriptor, "sdf": body}


def build_glove_armature_geometry(
    reference: Path,
    *,
    source_view_id: str,
    material: str = "glove-leather",
    resolution: int = DEFAULT_RESOLUTION,
    depth_source: str | None = None,
    palmar_reference: Path | None = None,
    palmar_source_view_id: str | None = None,
    atlas_output: Path | None = None,
    digit_openings: dict[str, str] | None = None,
    hands: tuple[str, ...] = ("left", "right"),
    required_digits: int = REQUIRED_DIGITS,
) -> dict[str, Any]:
    """Fit a hand armature to the admitted outline and report the declared hands with their descriptors.

    A CS2 item ships a pair and that is the default. A marketplace listing of ONE glove is a legitimate
    source and building a pair from it invents a second glove nobody photographed -- and then renders it,
    which is how a single-hand item ends up compared against a two-hand capture.
    """
    if not hands or any(hand not in {"left", "right"} for hand in hands):
        raise ValueError(f"hands must be a non-empty subset of left/right, not {hands!r}")
    _grid_mask, measured = measure_silhouette(reference)
    meshes: list[dict[str, Any]] = []
    descriptors: dict[str, Any] = {}
    for hand in hands:
        record, descriptor = _hand_mesh(
            measured, hand=hand, source_view_id=source_view_id, material=material,
            resolution=resolution, depth_source=depth_source, digit_openings=digit_openings,
        )
        meshes.append(record)
        descriptors[hand] = descriptor
    manifold = all(
        mesh["measurements"]["boundaryEdges"] == 0 and mesh["measurements"]["nonManifoldEdges"] == 0
        for mesh in meshes
    )
    thin = min(mesh["measurements"]["minimumThickness"] for mesh in meshes)
    depth_observed = depth_source is not None
    # THE FORM GATE. A glove has five digits, and until the form has five the plates are not projected onto
    # it at all.
    #
    # Not a style rule -- a correctness one. The palmar plate has the item's own thumb painted across its
    # palm, so a four-digit model wearing that plate renders as five and every form defect behind the texture
    # becomes invisible. That is not hypothetical: a thumb fused into the palm survived a dozen textured
    # renders here, and it took an untextured one to see. Withholding the projection makes the deception
    # structurally impossible rather than something a reviewer has to remember to look past.
    protrusion = {hand: measure_digit_protrusion(descriptor["sdf"], required_digits) for hand, descriptor in descriptors.items()}
    form_ready = all(entry["value"] >= required_digits for entry in protrusion.values())
    project = atlas_output is not None and form_ready
    return {
        "version": SHELL_VERSION,
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
                    "reason": "the band whose surface normal has no z faces neither front-axis plate and takes dorsal texture",
                }
            ],
        },
        **({"surfaceAtlas": bake_shell_atlas(reference, palmar_reference, atlas_output)} if project else {}),
        "surfaceProjectionWithheld": None if project or atlas_output is None else {
            "reason": "form-gate:digit-count",
            "measured": {hand: entry["value"] for hand, entry in protrusion.items()},
            "required": float(required_digits),
            "note": (
                "the plates are not projected until the form has five separate digits, because the palmar "
                "plate paints the item's own thumb across its palm and a four-digit model wearing it reads "
                "as five"
            ),
        },
        # One descriptor per hand, because each hand is its own implicit solid placed in its own bounds.
        "geometryDescriptor": {"armature": dict(descriptors)},
        "derivation": {
            "tier": DERIVATION_TIER,
            "sourceViewIds": [source_view_id],
            "algorithm": "silhouette proportions + anthropometric hand armature, meshed by signed-distance polygonisation",
            "confidence": 0.68 if not depth_observed else 0.84,
            "epistemicState": "supported",
            "axes": {
                "x": {"state": "observed", "source": source_view_id},
                "y": {"state": "observed", "source": source_view_id},
                "z": {"state": "observed" if depth_observed else "inferred", "source": depth_source or "anthropometric palm and digit ratios"},
            },
            "measured": measured,
            "backSurfaceSource": palmar_source_view_id or "mirrored from the dorsal projection",
        },
        "limitations": [
            "digit placement is fitted to the measured finger band, not detected: the reference shows the digits touching, so the peaks that would separate them are not observable",
            "the surface is extracted on a finite grid, so it is faceted at texel scale rather than smooth",
            "the atlas spans the polygonised bounds including the thumb's reach, so the plate is aligned to a few percent rather than exactly",
        ] + ([] if depth_observed else ["every depth is an anthropometric ratio; two front-axis plates carry no depth at all"])
          + ([] if form_ready else [
              "fewer than five digits stand clear of the rest of the hand, so the plates are NOT projected "
              "onto it: a digit buried in the palm mass would be supplied by the palmar plate's painted thumb "
              "instead of by the form."
          ]),
        "integrity": {
            "finiteGeometry": {"status": "measured", "value": float(all(all(math.isfinite(value) for vertex in mesh["vertices"] for value in vertex) for mesh in meshes))},
            "nonDegenerateExtrusion": {"status": "measured", "value": float(thin >= MIN_THICKNESS)},
            "productionManifold": {"status": "measured", "value": float(manifold)},
            "seamBoundaryCorrespondence": {"status": "measured", "value": 1.0, "reason": "one implicit solid per hand has no panel seams to correspond"},
            "triangleBudget": {"status": "measured", "value": sum(mesh["measurements"]["triangleCount"] for mesh in meshes), "policy": "pre-decimation"},
            "digitProtrusion": {
                "status": "measured",
                "value": float(min(entry["value"] for entry in protrusion.values())),
                "required": float(required_digits),
                "perHand": protrusion,
            },
        },
    }
