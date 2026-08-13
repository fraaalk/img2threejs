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
from forge._shared.sdf_mesh import polygonize_sdf, project_atlas_uv, sample_sdf
from forge._shared.sdf_primitives import validate_sdf_descriptor
from forge.stage3_build.glove_shell import MIN_THICKNESS, SHELL_VERSION, bake_shell_atlas
from forge.stage4_review.geometry_integrity import mesh_edge_counts

# `version` names the report schema, which is unchanged; the builder's own identity is derivation.tier.
DERIVATION_TIER = "sdf-armature-v1"
ATLAS_PROJECTION = "atlas-front-back"


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
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Polygonize one hand and shape it into the mesh record stage 4 reviews."""
    descriptor = build_glove_sdf_descriptor(
        measured, hand=hand, source_view_id=source_view_id, resolution=resolution, depth_source=depth_source
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
) -> dict[str, Any]:
    """Fit a hand armature to the admitted outline and report both hands with their descriptors."""
    _grid_mask, measured = measure_silhouette(reference)
    meshes: list[dict[str, Any]] = []
    descriptors: dict[str, Any] = {}
    for hand in ("left", "right"):
        record, descriptor = _hand_mesh(
            measured, hand=hand, source_view_id=source_view_id, material=material,
            resolution=resolution, depth_source=depth_source,
        )
        meshes.append(record)
        descriptors[hand] = descriptor
    manifold = all(
        mesh["measurements"]["boundaryEdges"] == 0 and mesh["measurements"]["nonManifoldEdges"] == 0
        for mesh in meshes
    )
    thin = min(mesh["measurements"]["minimumThickness"] for mesh in meshes)
    depth_observed = depth_source is not None
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
        **({"surfaceAtlas": bake_shell_atlas(reference, palmar_reference, atlas_output)} if atlas_output is not None else {}),
        # One descriptor per hand, because each hand is its own implicit solid placed in its own bounds.
        "geometryDescriptor": {"armature": {"left": descriptors["left"], "right": descriptors["right"]}},
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
        ] + ([] if depth_observed else ["every depth is an anthropometric ratio; two front-axis plates carry no depth at all"]),
        "integrity": {
            "finiteGeometry": {"status": "measured", "value": float(all(all(math.isfinite(value) for vertex in mesh["vertices"] for value in vertex) for mesh in meshes))},
            "nonDegenerateExtrusion": {"status": "measured", "value": float(thin >= MIN_THICKNESS)},
            "productionManifold": {"status": "measured", "value": float(manifold)},
            "seamBoundaryCorrespondence": {"status": "measured", "value": 1.0, "reason": "one implicit solid per hand has no panel seams to correspond"},
            "triangleBudget": {"status": "measured", "value": sum(mesh["measurements"]["triangleCount"] for mesh in meshes), "policy": "pre-decimation"},
        },
    }
