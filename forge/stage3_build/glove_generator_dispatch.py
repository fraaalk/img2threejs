"""Fail-closed dispatch from a validated glove spec/assembly to stage-3 artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from forge.stage1_intake.glove_contracts import GLOVE_ASSEMBLY_VERSION, glove_manifest_errors
from forge.stage2_spec.glove_assembly import build_glove_assembly, canonical_hash, validate_glove_assembly, write_json_atomic
from forge.stage3_build.glove_artifacts import build_bundle_from_assembly


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
    if not isinstance(wearable, dict) or wearable.get("template") != "glove-shell-v1" or wearable.get("subtype") != "sport-gloves":
        errors.append("spec:glove-shell-v1 sport-gloves template is required")
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
    return errors


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
        assembly = build_glove_assembly("sport-gloves", [item for item in source_ids if isinstance(item, str)])
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
    bundle, report = build_bundle_from_assembly(assembly, output_dir, upstream=upstream)
    descriptor = json.loads(bundle.read_text(encoding="utf-8"))
    if descriptor.get("upstream") != upstream:
        raise ValueError("glove model bundle dropped upstream identity")
    return bundle, report, upstream
