"""Versioned contracts shared by the CS2 glove intake and downstream stages.

The module is deliberately stdlib-only.  It validates evidence and artifact shape; it does not
infer hidden sewing patterns or metric dimensions from photographs.
"""

from __future__ import annotations

from typing import Any, Final

GLOVE_EXTENSION_VERSION: Final[int] = 1
GLOVE_ASSEMBLY_VERSION: Final[str] = "glove-assembly-v2"
GLOVE_MODEL_BUNDLE_VERSION: Final[str] = "glove-model-bundle.v2"
REQUIRED_GLOVE_VIEW_ROLES: Final[tuple[str, ...]] = (
    "dorsal",
    "palmar",
    "thumb-side-profile",
    "three-quarter",
)
OPTIONAL_GLOVE_VIEW_ROLES: Final[frozenset[str]] = frozenset(
    {"opposite-profile", "back", "left-three-quarter", "right-three-quarter", "orbit"}
)
# There is deliberately no subtype allowlist. `sport-gloves` was the pilot used to prove the gates, and a
# name-based list would need a commit per glove while saying nothing about whether the builder can build the
# thing. A glove is admitted on the evidence it carries; what refuses is CAPABILITY -- an observed form
# profile or digit opening with no implementation path -- which is checked where the geometry is built.
VALID_FORM_PROFILES: Final[frozenset[str]] = frozenset({"full-finger", "fingerless", "mitten", "unknown"})
VALID_OPENING_KINDS: Final[frozenset[str]] = frozenset({"closed-tip", "open-cut", "grouped-chamber", "cuff"})
VALID_EPISTEMIC_STATES: Final[frozenset[str]] = frozenset(
    {"observed", "supported", "inferred", "implementation", "unknown"}
)
# Real CS2 sources ship two plates of the target item. The remaining required roles are filled by
# technical views of the same glove model at another wear tier, which are sound for geometry and
# must never supply surface evidence -- that would paint the wrong finish onto the target.
VALID_EVIDENCE_USE: Final[frozenset[str]] = frozenset(
    {"target-geometry-and-surface", "technical-geometry-only"}
)
SURFACE_BEARING_EVIDENCE_USE: Final[str] = "target-geometry-and-surface"
TARGET_REQUIRED_VIEW_ROLES: Final[tuple[str, ...]] = ("dorsal", "palmar")


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_single_hand(extension: Any) -> bool:
    """Whether the observation declared one hand rather than a pair.

    Declared, never inferred. `glove_silhouette.measure_silhouette` reads only the LARGEST foreground
    component, so a single-glove plate and a pair plate look the same to it -- it would report one hand for
    both. A guess here would silently halve a pair.
    """
    if not isinstance(extension, dict):
        return False
    hands = extension.get("hands")
    return isinstance(hands, list) and len(hands) == 1


def validate_glove_view(view: Any, *, require_admitted: bool = False) -> list[str]:
    if not isinstance(view, dict):
        return ["source view must be an object"]
    errors: list[str] = []
    for field in ("id", "role", "path", "hash"):
        if not _nonempty_string(view.get(field)) and not isinstance(view.get(field), int):
            errors.append(f"source view {field} is required")
    if view.get("role") not in set(REQUIRED_GLOVE_VIEW_ROLES) | OPTIONAL_GLOVE_VIEW_ROLES:
        errors.append(f"unsupported source view role: {view.get('role')!r}")
    for field in ("width", "height"):
        rejected_missing = view.get("admission") == "rejected" and view.get(field) == 0
        if (not isinstance(view.get(field), int) or view[field] <= 0) and not rejected_missing:
            errors.append(f"source view {field} must be a positive integer")
    if require_admitted and view.get("admission") != "admitted":
        errors.append(f"source view {view.get('id', '<missing>')} is not admitted")
    if "duplicateOf" in view and view["duplicateOf"] is not None and not _nonempty_string(view["duplicateOf"]):
        errors.append("source view duplicateOf must be a string or null")
    if "evidenceUse" in view and view["evidenceUse"] not in VALID_EVIDENCE_USE:
        errors.append(f"source view evidenceUse must be one of {', '.join(sorted(VALID_EVIDENCE_USE))}")
    return errors


def _validate_form_profile(profile: Any) -> list[str]:
    if not isinstance(profile, dict):
        return ["extensions.glove.formProfile must be an object"]
    errors: list[str] = []
    kind = profile.get("kind")
    if kind not in VALID_FORM_PROFILES:
        errors.append("formProfile.kind is invalid")
    topology = profile.get("digitTopology")
    if not isinstance(topology, list) or not topology:
        errors.append("formProfile.digitTopology must be a non-empty list")
    else:
        for index, digit in enumerate(topology):
            if not isinstance(digit, dict) or not _nonempty_string(digit.get("id")):
                errors.append(f"formProfile.digitTopology[{index}] requires an id")
                continue
            if digit.get("opening") not in VALID_OPENING_KINDS:
                errors.append(f"formProfile.digitTopology[{index}].opening is invalid")
            if digit.get("path") not in {"straight", "curved", "grouped", "unknown"}:
                errors.append(f"formProfile.digitTopology[{index}].path is invalid")
            if not isinstance(digit.get("evidenceRefs"), list) or not digit["evidenceRefs"]:
                errors.append(f"formProfile.digitTopology[{index}].evidenceRefs is required")
    openings = profile.get("openingPolicy")
    if not isinstance(openings, dict) or not isinstance(openings.get("allowedBoundaryKinds"), list):
        errors.append("formProfile.openingPolicy.allowedBoundaryKinds is required")
    if profile.get("classificationState") not in {"observed", "supported", "unknown", "contradictory"}:
        errors.append("formProfile.classificationState is invalid")
    return errors


def _validate_coverage_matrix(matrix: Any) -> list[str]:
    if not isinstance(matrix, list):
        return ["extensions.glove.coverageMatrix must be a list"]
    errors: list[str] = []
    for index, entry in enumerate(matrix):
        if not isinstance(entry, dict):
            errors.append(f"coverageMatrix[{index}] must be an object")
            continue
        for field in ("ownerId", "sourceViewId", "sourceHash", "cropDigest", "visibility", "state"):
            if not _nonempty_string(entry.get(field)):
                errors.append(f"coverageMatrix[{index}].{field} is required")
        if not isinstance(entry.get("renderCameras"), list) or not entry["renderCameras"]:
            errors.append(f"coverageMatrix[{index}].renderCameras is required")
        if entry.get("visibility") not in {"visible", "partial", "occluded", "hidden"}:
            errors.append(f"coverageMatrix[{index}].visibility is invalid")
        if entry.get("state") not in {"covered", "inconclusive", "missing"}:
            errors.append(f"coverageMatrix[{index}].state is invalid")
    return errors


def _validate_surface_regions(regions: Any, views: Any = None) -> list[str]:
    if not isinstance(regions, list):
        return ["extensions.glove.surfaceRegionEvidence must be a list"]
    by_id = {
        str(view.get("id")): view
        for view in (views if isinstance(views, list) else [])
        if isinstance(view, dict) and _nonempty_string(view.get("id"))
    }
    errors: list[str] = []
    for index, region in enumerate(regions):
        if not isinstance(region, dict):
            errors.append(f"surfaceRegionEvidence[{index}] must be an object")
            continue
        for field in ("id", "sourceCropDigest", "comparisonMaskDigest", "orientation", "sourceViewId", "sourceHash"):
            if not _nonempty_string(region.get(field)):
                errors.append(f"surfaceRegionEvidence[{index}].{field} is required")
        source_view = by_id.get(str(region.get("sourceViewId")))
        if by_id and source_view is None:
            errors.append(f"surfaceRegionEvidence[{index}].sourceViewId names an unknown source view")
        elif source_view is not None:
            if str(region.get("sourceHash")) != str(source_view.get("hash")):
                errors.append(f"surfaceRegionEvidence[{index}].sourceHash does not match its source view")
            if source_view.get("evidenceUse") != SURFACE_BEARING_EVIDENCE_USE:
                errors.append(f"surfaceRegionEvidence[{index}] takes surface evidence from a non-target view")
        transform = region.get("projectionTransform")
        if not isinstance(transform, dict) or transform.get("kind") not in {"uv", "planar", "projected"}:
            errors.append(f"surfaceRegionEvidence[{index}].projectionTransform is invalid")
        channels = region.get("channels")
        if not isinstance(channels, dict) or "baseColor" not in channels:
            errors.append(f"surfaceRegionEvidence[{index}].channels.baseColor is required")
        if region.get("orientation") not in {"dorsal", "palmar", "radial", "ulnar", "thumb"}:
            errors.append(f"surfaceRegionEvidence[{index}].orientation is invalid")
    return errors


def glove_readiness_errors(extension: Any) -> list[str]:
    """Strict anatomy and surface proof required before an artifact may claim ready."""
    if not isinstance(extension, dict):
        return ["extensions.glove must be an object"]
    views = extension.get("sourceViews")
    errors = _validate_form_profile(extension.get("formProfile")) + _validate_coverage_matrix(extension.get("coverageMatrix")) + _validate_surface_regions(extension.get("surfaceRegionEvidence"), views)
    by_role = {
        view.get("role"): view
        for view in (views if isinstance(views, list) else [])
        if isinstance(view, dict)
    }
    for role in TARGET_REQUIRED_VIEW_ROLES:
        view = by_role.get(role)
        if view is None or view.get("evidenceUse") != SURFACE_BEARING_EVIDENCE_USE:
            errors.append(f"required target view {role} must be classed {SURFACE_BEARING_EVIDENCE_USE}")
    if not isinstance(extension.get("coverageMatrix"), list) or not extension["coverageMatrix"]:
        errors.append("coverage matrix must prove at least one observable owner")
    if not isinstance(extension.get("surfaceRegionEvidence"), list) or not extension["surfaceRegionEvidence"]:
        errors.append("surface region evidence must prove at least one visible material region")
    profile = extension.get("formProfile", {})
    if not isinstance(profile, dict) or profile.get("kind") == "unknown" or profile.get("classificationState") in {"unknown", "contradictory"}:
        errors.append("form profile is not observable enough for readiness")
    for entry in extension.get("coverageMatrix", []):
        if isinstance(entry, dict) and (entry.get("state") != "covered" or entry.get("visibility") in {"occluded", "hidden"}):
            errors.append(f"coverage owner {entry.get('ownerId', '<missing>')} is not ready")
    return errors


def validate_glove_extension(extension: Any, *, require_complete_views: bool = True) -> list[str]:
    if not isinstance(extension, dict):
        return ["extensions.glove must be an object"]
    errors: list[str] = []
    if extension.get("version") != GLOVE_EXTENSION_VERSION:
        errors.append("extensions.glove.version must be 1")
    target = extension.get("target")
    if not isinstance(target, dict):
        errors.append("extensions.glove.target must be an object")
    else:
        if not _nonempty_string(target.get("subtype")):
            errors.append("extensions.glove.target.subtype is required")
        if target.get("canonicalHand") != "left":
            errors.append("extensions.glove.target.canonicalHand must be left")
        if target.get("output") != "static-pair":
            errors.append("extensions.glove.target.output must be static-pair")
        if target.get("scale") not in {"normalized", "calibrated"}:
            errors.append("extensions.glove.target.scale must be normalized or calibrated")
    views = extension.get("sourceViews")
    if not isinstance(views, list) or not views:
        errors.append("extensions.glove.sourceViews must be a non-empty list")
        views = []
    ids: set[str] = set()
    roles: set[str] = set()
    for view in views:
        errors.extend(validate_glove_view(view))
        if isinstance(view, dict):
            view_id = view.get("id")
            if isinstance(view_id, str):
                if view_id in ids:
                    errors.append(f"duplicate source view id: {view_id}")
                ids.add(view_id)
            role = view.get("role")
            if isinstance(role, str):
                roles.add(role)
    primary = extension.get("primarySourceViewId")
    if not isinstance(primary, str) or primary not in ids:
        errors.append("primarySourceViewId must refer to an admitted source view")
    if require_complete_views:
        # A CS2 item ships two plates and the other two required roles are filled with technical views of the
        # same model. A single-hand listing supplies exactly the two plates and nothing else -- there is no
        # second wear tier to borrow a thumb-side view from -- so requiring four there does not raise the
        # evidence, it just refuses the item. Two admits, and what was supplied is recorded rather than
        # implied: `evidenceTier` stays diagnostic either way, and the depth axis is a prior either way.
        required = set(TARGET_REQUIRED_VIEW_ROLES) if _is_single_hand(extension) else set(REQUIRED_GLOVE_VIEW_ROLES)
        missing = sorted(required - roles)
        if missing:
            errors.append("missing required glove view roles: " + ", ".join(missing))
    evidence = extension.get("evidence")
    if not isinstance(evidence, list):
        errors.append("extensions.glove.evidence must be a list")
    else:
        for index, claim in enumerate(evidence):
            if not isinstance(claim, dict):
                errors.append(f"evidence[{index}] must be an object")
                continue
            if not _nonempty_string(claim.get("id")):
                errors.append(f"evidence[{index}].id is required")
            if claim.get("epistemicState") not in VALID_EPISTEMIC_STATES:
                errors.append(f"evidence[{index}].epistemicState is invalid")
            if not isinstance(claim.get("sourceRefs"), list) or not claim["sourceRefs"]:
                errors.append(f"evidence[{index}].sourceRefs is required")
            if not _is_finite_number(claim.get("confidence")) or not 0 <= claim["confidence"] <= 1:
                errors.append(f"evidence[{index}].confidence must be between 0 and 1")
    landmarks = extension.get("landmarks")
    if not isinstance(landmarks, list):
        errors.append("extensions.glove.landmarks must be a list")
    else:
        for index, landmark in enumerate(landmarks):
            if not isinstance(landmark, dict) or not _nonempty_string(landmark.get("id")):
                errors.append(f"landmarks[{index}] must have an id")
            elif not isinstance(landmark.get("coordinate"), list) or len(landmark["coordinate"]) != 2:
                errors.append(f"landmarks[{index}].coordinate must be [x, y]")
    policy = extension.get("policy")
    if not isinstance(policy, dict):
        errors.append("extensions.glove.policy must be an object")
    else:
        if policy.get("hiddenRegion") not in {"inferred", "request-input", "evidence-only"}:
            errors.append("extensions.glove.policy.hiddenRegion is invalid")
        if policy.get("allowedFallback") not in {"none", "single-dorsal-compatibility-only"}:
            errors.append("extensions.glove.policy.allowedFallback is invalid")
    if "formProfile" in extension:
        errors.extend(_validate_form_profile(extension["formProfile"]))
    if "coverageMatrix" in extension:
        errors.extend(_validate_coverage_matrix(extension["coverageMatrix"]))
    if "surfaceRegionEvidence" in extension:
        errors.extend(_validate_surface_regions(extension["surfaceRegionEvidence"], extension.get("sourceViews")))
    return errors


def glove_source_view_id(role: str, index: int) -> str:
    safe = "-".join(part for part in role.lower().replace("_", "-").split() if part)
    return f"glove-view-{index + 1}-{safe or 'reference'}"


def build_glove_extension(source_views: list[dict[str, Any]], subtype: str = "sport-gloves", *, hands: list[str] | None = None) -> dict[str, Any]:
    primary = next((view["id"] for view in source_views if view.get("role") == "dorsal"), source_views[0]["id"])
    roles = {view.get("role") for view in source_views}
    required = set(REQUIRED_GLOVE_VIEW_ROLES)
    evidence = [
        {
            "id": "glove-evidence-shell-regions",
            "sourceRefs": [view["id"] for view in source_views],
            "region": "shell-and-hand-anatomy",
            "visibility": "partial" if roles != required else "multi-view",
            "epistemicState": "observed",
            "confidence": 0.9 if required <= roles else 0.55,
            "contradictions": [],
        },
        {
            "id": "glove-evidence-hidden-seams",
            "sourceRefs": [primary],
            "region": "lining-and-hidden-seams",
            "visibility": "hidden",
            "epistemicState": "unknown",
            "confidence": 0.0,
            "contradictions": [],
        },
    ]
    return {
        "version": GLOVE_EXTENSION_VERSION,
        "target": {
            "subtype": subtype,
            "exactnessTier": "metadata-assisted",
            "output": "static-pair",
            "canonicalHand": "left",
            "scale": "normalized",
        },
        "sourceViews": source_views,
        "primarySourceViewId": primary,
        "evidence": evidence,
        "formProfile": {
            "kind": "unknown",
            "classificationState": "unknown",
            "digitTopology": [{"id": "unclassified-digits", "opening": "cuff", "path": "unknown", "evidenceRefs": [primary]}],
            "openingPolicy": {"allowedBoundaryKinds": ["cuff"]},
        },
        **({"hands": [str(hand) for hand in hands]} if hands else {}),
        "coverageMatrix": [],
        "surfaceRegionEvidence": [],
        "landmarks": [],
        "contradictions": [],
        "policy": {
            "requiredViewRoles": list(REQUIRED_GLOVE_VIEW_ROLES),
            "hiddenRegion": "evidence-only",
            "allowedFallback": "single-dorsal-compatibility-only",
            "retryableStates": ["request-input", "refine-spec", "refine-code"],
        },
    }


def glove_manifest_errors(manifest: dict[str, Any], *, require_complete_views: bool = True) -> list[str]:
    errors: list[str] = []
    if manifest.get("itemFamily") != "glove":
        errors.append("manifest itemFamily must be glove")
    if not _nonempty_string(manifest.get("subtype")):
        errors.append("manifest subtype is required")
    else:
        # Consistency, not an allowlist. This check used to read "must be sport-gloves", and dropping it to
        # a presence check would lose the one thing it was actually catching: the manifest and its glove
        # extension naming different items. Once no name is refused, divergence is the failure mode left.
        declared = manifest.get("extensions", {}).get("glove", {})
        target = declared.get("target") if isinstance(declared, dict) else None
        if isinstance(target, dict) and _nonempty_string(target.get("subtype")) and target["subtype"] != manifest["subtype"]:
            errors.append(f"extensions.glove.target.subtype {target['subtype']!r} does not match manifest subtype {manifest['subtype']!r}")
    errors.extend(validate_glove_extension(manifest.get("extensions", {}).get("glove"), require_complete_views=require_complete_views))
    if require_complete_views:
        for view in manifest.get("sourceViews", []):
            if isinstance(view, dict) and view.get("role") in REQUIRED_GLOVE_VIEW_ROLES and view.get("admission") != "admitted":
                errors.append(f"required source view {view.get('id', '<missing>')} is not admitted")
    if manifest.get("primarySourceViewId") != manifest.get("extensions", {}).get("glove", {}).get("primarySourceViewId"):
        errors.append("manifest primarySourceViewId must match glove extension")
    primary = manifest.get("sourceImage")
    if not isinstance(primary, str) or primary != next(
        (view.get("path") for view in manifest.get("sourceViews", []) if isinstance(view, dict) and view.get("id") == manifest.get("primarySourceViewId")),
        None,
    ):
        errors.append("sourceImage must be the primary dorsal compatibility alias")
    return errors
