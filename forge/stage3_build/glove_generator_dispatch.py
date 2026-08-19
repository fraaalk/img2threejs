"""Fail-closed dispatch from a validated glove spec/assembly to stage-3 artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from forge._shared.glove_silhouette import resolve_target_views
from forge.stage1_intake.glove_contracts import GLOVE_ASSEMBLY_VERSION, glove_manifest_errors
from forge.stage2_spec.glove_assembly import build_glove_assembly, canonical_hash, validate_glove_assembly, write_json_atomic
from forge.stage3_build.glove_artifacts import build_bundle_from_geometry
from forge.stage3_build.glove_armature_shell import build_glove_armature_geometry


def _digest(payload: Any) -> str:
    return canonical_hash(payload)


def validate_glove_build_inputs(manifest: dict[str, Any], assessment: dict[str, Any], spec: dict[str, Any], assembly: dict[str, Any]) -> list[str]:
    """Return boundary errors before a generator is allowed to consume the inputs."""
    errors: list[str] = []
    errors.extend(f"manifest:{item}" for item in glove_manifest_errors(manifest, require_complete_views=True))
    routing = spec.get("pipelineRouting")
    if not isinstance(routing, dict) or routing.get("track") != "wearable-v1.0" or routing.get("status") != "resolved":
        errors.append("spec:pipelineRouting must resolve to wearable-v1.0")
    wearable = spec.get("wearable")
    if not isinstance(wearable, dict) or wearable.get("template") != "glove-shell-v1" or not wearable.get("subtype"):
        errors.append("spec:glove-shell-v1 template declaring a subtype is required")
    elif wearable.get("subtype") != manifest.get("subtype"):
        # The spec must be for the item that was intaken. Without this, opening the subtype gate would let a
        # spec built for one glove be built against another manifest and every downstream gate would agree,
        # because each checks self-consistency against the spec rather than against the plate.
        errors.append(f"spec:wearable subtype {wearable.get('subtype')!r} does not match manifest subtype {manifest.get('subtype')!r}")
    object_class = spec.get("preSpecAssessment", {}).get("objectClass", {})
    if not isinstance(object_class, dict) or object_class.get("itemFamily") != "glove":
        errors.append("spec:objectClass.itemFamily must be glove")
    if assessment.get("intakeOnly") is True or manifest.get("state") != "proceed":
        errors.append("state:only a proceed manifest may reach stage-3")
    if assembly.get("version") != GLOVE_ASSEMBLY_VERSION:
        errors.append(f"assembly:version must be {GLOVE_ASSEMBLY_VERSION}")
    errors.extend(f"assembly:{item}" for item in validate_glove_assembly(assembly))
    panel_ids = {panel.get("id") for panel in assembly.get("panelGraph", {}).get("nodes", []) if isinstance(panel, dict)}
    component_ids = {component.get("id") for component in spec.get("componentTree", []) if isinstance(component, dict)}
    required_components = {"palm-panel", "dorsal-panel", "thumb-saddle", "cuff", "closure-strap"}
    missing = sorted(required_components - component_ids)
    if missing:
        errors.append("spec:missing required glove components " + ", ".join(missing))
    if not panel_ids:
        errors.append("assembly:panelGraph has no panel IDs")
    errors.extend(f"capability:{item}" for item in unbuildable_capabilities(manifest))
    return errors


# What the armature can actually end a digit with. `glove_contracts` has admitted `grouped-chamber` and
# `cuff` openings since before there was a builder for any of them, and there still is not one.
BUILDABLE_DIGIT_OPENINGS: frozenset[str] = frozenset({"closed-tip", "open-cut"})


def unbuildable_capabilities(manifest: dict[str, Any]) -> list[str]:
    """Name what the observation asks for and the builder cannot do.

    Subtype is no longer an admission decision, so this is what stands between "we do not gate on the
    name" and "we silently produce the wrong glove". Removing the subtype allowlist without this turns an
    honest `unsupported-subtype` into a full-finger model wearing a half-finger glove's texture, and every
    downstream gate agrees with it, because each one checks the model against the spec rather than against
    the plate.
    """
    profile = manifest.get("extensions", {}).get("glove", {}).get("formProfile")
    if not isinstance(profile, dict):
        return []
    # An unobserved profile asks for nothing. `build_glove_extension` seeds every manifest with
    # `classificationState: "unknown"` and one placeholder digit `unclassified-digits` carrying
    # `opening: "cuff"` -- a stand-in for "not classified yet", not a demand the armature must meet.
    # Only a profile an observation actually classified can be short of a capability.
    if profile.get("classificationState") not in {"observed", "supported"}:
        return []
    missing: list[str] = []
    for index, digit in enumerate(profile.get("digitTopology", []) or []):
        if not isinstance(digit, dict):
            continue
        opening = digit.get("opening")
        if opening is not None and opening not in BUILDABLE_DIGIT_OPENINGS:
            missing.append(f"digit {digit.get('id', index)} declares opening {opening!r}, which the armature cannot build")
    return missing


def observed_digit_openings(manifest: dict[str, Any]) -> dict[str, str]:
    """The per-digit endings the observation declared, or nothing when it declared none.

    An unclassified profile returns `{}`, which builds the digits the way they were always built.
    """
    profile = manifest.get("extensions", {}).get("glove", {}).get("formProfile")
    if not isinstance(profile, dict) or profile.get("classificationState") not in {"observed", "supported"}:
        return {}
    return {
        str(digit["id"]): str(digit["opening"])
        for digit in profile.get("digitTopology", []) or []
        if isinstance(digit, dict) and digit.get("id") and digit.get("opening")
    }


def declared_hands(manifest: dict[str, Any]) -> tuple[str, ...]:
    """The hands the observation declared, defaulting to the pair a CS2 plate ships."""
    hands = manifest.get("extensions", {}).get("glove", {}).get("hands")
    if isinstance(hands, list) and hands:
        return tuple(str(hand) for hand in hands)
    return ("left", "right")


def build_glove_model_from_artifacts(
    manifest: dict[str, Any],
    assessment: dict[str, Any],
    spec: dict[str, Any],
    output_dir: Path,
    *,
    assembly: dict[str, Any] | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    """Build a deterministic bundle and geometry report with all upstream hashes bound."""
    if assembly is None:
        source_ids = [view.get("id") for view in manifest.get("sourceViews", []) if isinstance(view, dict)]
        profile = manifest.get("extensions", {}).get("glove", {}).get("formProfile", {})
        kind = profile.get("kind") if isinstance(profile, dict) else None
        # `unknown` is a real value in the intake vocabulary and means "not observed yet", not a form the
        # builder must attempt. It falls back to the default rather than reaching the assembly as a demand
        # the assembly is right to refuse.
        assembly = build_glove_assembly(
            str(manifest.get("subtype") or ""),
            [item for item in source_ids if isinstance(item, str)],
            form_profile=kind if kind in {"full-finger", "fingerless", "mitten"} else "full-finger",
        )
    errors = validate_glove_build_inputs(manifest, assessment, spec, assembly)
    if errors:
        raise ValueError("glove generator dispatch rejected inputs: " + "; ".join(errors))
    output_dir = output_dir.expanduser().resolve()
    provenance_dir = output_dir / "provenance"
    sources = {
        "manifest": (manifest, manifest.get("schemaVersion")),
        "assessment": (assessment, "pre-spec-assessment.v1"),
        "assembly": (assembly, assembly.get("version")),
        "spec": (spec, spec.get("schemaVersion", 1)),
    }
    upstream: dict[str, dict[str, Any]] = {}
    for name, (payload, version) in sources.items():
        path = provenance_dir / f"{name}.json"
        write_json_atomic(path, payload)
        upstream[name] = {
            "version": version,
            "path": path.relative_to(output_dir).as_posix(),
            "sha256": _digest(payload),
        }
    # The assembly is now the semantic panel/material inventory that surface regions map onto; the
    # geometry itself is measured from the reference rather than read from its hardcoded loops.
    outline, palmar = resolve_target_views(manifest)
    if outline is None:
        raise ValueError("no admitted target view with a readable image to measure the shell outline from")
    geometry = build_glove_armature_geometry(
        outline[0], source_view_id=outline[1],
        palmar_reference=palmar[0] if palmar else None,
        palmar_source_view_id=palmar[1] if palmar else None,
        atlas_output=output_dir / "surface-atlas.png",
        digit_openings=observed_digit_openings(manifest),
        hands=declared_hands(manifest),
        required_digits=len(observed_digit_openings(manifest)) or 5,
    )
    # Carried from the assembly, not re-asserted downstream: the armature builder measures a plate and
    # knows nothing about which item it is. Without this the bundle falls back to the pilot subtype and a
    # Hydra bundle would name itself `sport-gloves-pair`.
    geometry = {
        **geometry,
        "subtype": assembly.get("subtype"),
        "formProfile": assembly.get("formProfile"),
        "allowedBoundaryKinds": list(assembly.get("policy", {}).get("allowedBoundaryKinds", ["cuff"])),
    }
    bundle, report = build_bundle_from_geometry(geometry, output_dir, upstream=upstream)
    descriptor = json.loads(bundle.read_text(encoding="utf-8"))
    if descriptor.get("upstream") != upstream:
        raise ValueError("glove model bundle dropped upstream identity")
    return bundle, report, upstream
