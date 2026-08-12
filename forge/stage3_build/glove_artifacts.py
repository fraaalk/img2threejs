"""Portable v2 artifact chain for generated glove diagnostics and production runs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from forge.stage2_spec.glove_assembly import canonical_hash, write_json_atomic
from forge.stage3_build.glove_geometry import build_glove_geometry, validate_geometry_report


MODEL_BUNDLE_VERSION = "glove-model-bundle.v2"
GEOMETRY_REPORT_VERSION = "glove-geometry-report.v2"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text_atomic(path: Path, text: str) -> str:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return sha256_file(path)


def _digest(payload: dict[str, Any], field: str) -> str:
    unsigned = dict(payload)
    unsigned.pop(field, None)
    return canonical_hash(unsigned)


def _relative_descendant(root: Path, value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(f"{label} must be a non-empty relative path")
    candidate = Path(value)
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError(f"{label} contains traversal")
    root = root.resolve()
    resolved = (root / candidate).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes artifact root") from exc
    # Existing symlinks are rejected even when they happen to point inward: they make
    # identical descriptors mean different byte sources on different machines.
    current = root
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} traverses a symlink")
    return resolved


def _root_digest(descriptor: dict[str, Any]) -> str:
    return _digest(descriptor, "rootDigest")


def _mesh_digest(meshes: list[dict[str, Any]]) -> str:
    return canonical_hash([mesh for mesh in sorted(meshes, key=lambda item: str(item.get("id")))])


def write_model_bundle(
    geometry_report: dict[str, Any],
    output_dir: Path,
    *,
    upstream: dict[str, Any] | None = None,
    scene_version: str = "glove-review-scene-v2",
) -> Path:
    # Diagnostic geometry is intentionally serializable, but provenance marks it as
    # non-ready. Production validation is enforced by the reviewer, not bypassed.
    errors = validate_geometry_report(geometry_report, require_production=False)
    if errors:
        raise ValueError("cannot write invalid canonical glove geometry: " + "; ".join(errors))
    output_dir = output_dir.expanduser().resolve()
    mesh_dir, factory_dir = output_dir / "meshes", output_dir / "factory"
    payloads: list[dict[str, Any]] = []
    for mesh in sorted(geometry_report["meshes"], key=lambda item: str(item.get("id"))):
        mesh_path = mesh_dir / f"{mesh['id']}.mesh.json"
        write_json_atomic(mesh_path, mesh)
        payloads.append({"id": mesh["id"], "kind": "canonical-triangle-mesh", "path": mesh_path.relative_to(output_dir).as_posix(), "sha256": sha256_file(mesh_path), "component": mesh.get("region"), "hand": mesh.get("hand")})
    factory_content = """// Deterministic generated glove factory contract.\nexport const modelBundleVersion = 'glove-model-bundle.v2';\nexport function createGloveModel(bundle, payloads = []) {\n  if (!bundle || bundle.version !== modelBundleVersion) throw new Error('invalid glove model bundle');\n  if (!Array.isArray(payloads) || payloads.length !== bundle.payloads.length) throw new Error('canonical payloads are required');\n  return { type: 'Group', name: bundle.sceneRoot, meshes: payloads.map((payload) => ({ id: payload.id, vertices: payload.vertices, indices: payload.indices, normals: payload.normals })) };\n}\n"""
    factory_path = factory_dir / "glove_factory.mjs"
    factory_hash = _write_text_atomic(factory_path, factory_content)
    descriptor: dict[str, Any] = {
        "version": MODEL_BUNDLE_VERSION,
        "schemaVersion": 2,
        "subtype": "sport-gloves",
        "evidenceTier": geometry_report.get("evidenceTier", "diagnostic"),
        "pair": {"canonicalHand": "left", "derivedHand": "right", "rightOverrides": geometry_report.get("handedness", {}).get("rightOverrides", [])},
        "sceneRoot": "sport-gloves-pair",
        "sceneVersion": scene_version,
        "factoryModule": {"path": factory_path.relative_to(output_dir).as_posix(), "sha256": factory_hash},
        "payloads": payloads,
        "upstream": upstream or {},
        "geometrySummary": {"meshCount": len(geometry_report["meshes"]), "seamCount": len(geometry_report.get("seams", [])), "mainShellPolicy": geometry_report.get("mainShellPolicy"), "canonicalMeshDigest": _mesh_digest(geometry_report["meshes"]), "geometryClaimsDigest": canonical_hash(geometry_report)},
        "toolchain": {"generator": "forge.stage3_build.glove_artifacts", "python": "3.10+", "deterministic": True},
    }
    descriptor["rootDigest"] = _root_digest(descriptor)
    bundle_path = output_dir / "glove-model-bundle.v2.json"
    write_json_atomic(bundle_path, descriptor)
    return bundle_path


def verify_model_bundle(bundle_path: Path) -> dict[str, Any]:
    bundle_path = bundle_path.expanduser().resolve()
    descriptor = json.loads(bundle_path.read_text(encoding="utf-8"))
    if not isinstance(descriptor, dict) or descriptor.get("version") != MODEL_BUNDLE_VERSION:
        raise ValueError("v1 glove artifacts are diagnostic-only; a v2 model bundle is required")
    if descriptor.get("rootDigest") != _root_digest(descriptor):
        raise ValueError("glove model bundle root digest mismatch")
    base = bundle_path.parent.resolve()
    factory = descriptor.get("factoryModule")
    if not isinstance(factory, dict):
        raise ValueError("glove model bundle factoryModule is missing")
    factory_path = _relative_descendant(base, factory.get("path"), label="factoryModule.path")
    if not factory_path.is_file() or sha256_file(factory_path) != factory.get("sha256"):
        raise ValueError("glove model bundle factory hash mismatch")
    payloads = descriptor.get("payloads")
    if not isinstance(payloads, list) or not payloads:
        raise ValueError("glove model bundle payloads are missing")
    for payload in payloads:
        if not isinstance(payload, dict):
            raise ValueError("glove model bundle payload is malformed")
        path = _relative_descendant(base, payload.get("path"), label=f"payload:{payload.get('id')}")
        if not path.is_file() or sha256_file(path) != payload.get("sha256"):
            raise ValueError(f"glove model bundle payload hash mismatch: {payload.get('id')}")
        mesh = json.loads(path.read_text(encoding="utf-8"))
        mesh_errors = validate_geometry_report({"version": "glove-geometry-report.v2", "meshes": [mesh]}, require_production=False)
        if mesh_errors:
            raise ValueError(f"glove model bundle canonical payload is invalid: {payload.get('id')}: {'; '.join(mesh_errors)}")
    return descriptor


def write_geometry_report(geometry_report: dict[str, Any], output: Path, bundle_path: Path, *, upstream: dict[str, Any] | None = None) -> Path:
    descriptor = verify_model_bundle(bundle_path)
    output = output.expanduser().resolve()
    root = bundle_path.parent.resolve()
    try:
        bundle_relative = bundle_path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("geometry report must be written inside its bundle root") from exc
    report = dict(geometry_report)
    report.update({"version": GEOMETRY_REPORT_VERSION, "modelBundleDigest": descriptor["rootDigest"], "modelBundlePath": bundle_relative, "upstream": upstream or {}, "evidenceTier": descriptor.get("evidenceTier"), "geometryClaimsDigest": descriptor["geometrySummary"]["geometryClaimsDigest"]})
    report["reportDigest"] = _digest(report, "reportDigest")
    write_json_atomic(output, report)
    return output


def verify_geometry_report(report_path: Path, bundle_path: Path) -> dict[str, Any]:
    report_path, bundle_path = report_path.expanduser().resolve(), bundle_path.expanduser().resolve()
    bundle = verify_model_bundle(bundle_path)
    root = bundle_path.parent.resolve()
    try:
        report_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("geometry report must be inside the model bundle root") from exc
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("version") != GEOMETRY_REPORT_VERSION:
        raise ValueError("v2 geometry report is required")
    if report.get("reportDigest") != _digest(report, "reportDigest"):
        raise ValueError("geometry report digest mismatch")
    if report.get("modelBundleDigest") != bundle["rootDigest"]:
        raise ValueError("geometry report bundle digest mismatch")
    if report.get("modelBundlePath") != bundle_path.name:
        raise ValueError("geometry report bundle path is not portable")
    payload_meshes: list[dict[str, Any]] = []
    for payload in bundle["payloads"]:
        path = _relative_descendant(root, payload.get("path"), label=f"payload:{payload.get('id')}")
        payload_meshes.append(json.loads(path.read_text(encoding="utf-8")))
    report_meshes = report.get("meshes")
    if not isinstance(report_meshes, list) or _mesh_digest(report_meshes) != _mesh_digest(payload_meshes):
        raise ValueError("geometry report meshes do not match verified model payloads")
    if bundle.get("geometrySummary", {}).get("canonicalMeshDigest") != _mesh_digest(payload_meshes):
        raise ValueError("model bundle canonical mesh digest mismatch")
    if report.get("geometryClaimsDigest") != bundle.get("geometrySummary", {}).get("geometryClaimsDigest"):
        raise ValueError("geometry report claims are not bound to the model bundle")
    report_claims = {
        key: value
        for key, value in report.items()
        if key not in {"modelBundleDigest", "modelBundlePath", "upstream", "geometryClaimsDigest", "reportDigest"}
    }
    if canonical_hash(report_claims) != report["geometryClaimsDigest"]:
        raise ValueError("geometry report content does not match the bundle-bound claims")
    return report


def load_verified_meshes(bundle_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    bundle = verify_model_bundle(bundle_path)
    root = bundle_path.expanduser().resolve().parent
    meshes = [json.loads(_relative_descendant(root, payload.get("path"), label=f"payload:{payload.get('id')}").read_text(encoding="utf-8")) for payload in bundle["payloads"]]
    return bundle, meshes


def build_bundle_from_geometry(geometry: dict[str, Any], output_dir: Path, *, upstream: dict[str, Any] | None = None) -> tuple[Path, Path]:
    """Write the bundle and report for an already-derived geometry report."""
    bundle = write_model_bundle(geometry, output_dir, upstream=upstream)
    report = write_geometry_report(geometry, output_dir / "geometry-report.v2.json", bundle, upstream=upstream)
    return bundle, report


def build_bundle_from_assembly(assembly: dict[str, Any], output_dir: Path, *, upstream: dict[str, Any] | None = None) -> tuple[Path, Path]:
    return build_bundle_from_geometry(build_glove_geometry(assembly), output_dir, upstream=upstream)
