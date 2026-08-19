#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from forge.stage1_intake.check_reference_admission import check_admission
from forge.stage1_intake.cs2_foundation import enrich_manifest_with_metadata, normalize_cs2_metadata, resolve_identity
from forge.stage1_intake.cs2_review_contract import build_review_scene
from forge.stage1_intake.detect_cs2 import detect_cs2_signals
from forge.stage1_intake.probe_image import probe
from forge.stage2_spec.cs2_adapters import get_family_adapter
from forge.stage1_intake.glove_contracts import (
    REQUIRED_GLOVE_VIEW_ROLES,
    TARGET_REQUIRED_VIEW_ROLES,
    build_glove_extension,
    glove_manifest_errors,
    glove_source_view_id,
)

SCHEMA_VERSION: Final[int] = 1
SUPPORTED_FAMILIES: Final[frozenset[str]] = frozenset({"knife", "pistol", "rifle", "glove"})
UNSUPPORTED_FAMILIES: Final[frozenset[str]] = frozenset(
    {"pistol", "rifle", "smg", "sniper", "heavy"}
)
# Knife subtypes that have a dedicated geometry adapter. A subtype absent here is
# `unsupported-subtype`, never silently routed through another subtype's tree.
KNIFE_SUBTYPES: Final[frozenset[str]] = frozenset(
    {"karambit", "butterfly", "bayonet", "m9", "flip", "gut", "falchion", "bowie", "navaja",
     "talon", "classic"}
)
PISTOL_SUBTYPES: Final[frozenset[str]] = frozenset({"glock-18"})
RIFLE_SUBTYPES: Final[frozenset[str]] = frozenset({"awp"})
ROUTES: Final[frozenset[str]] = frozenset(
    {"reference-projection", "authored-texture", "procedural-finish"}
)
TIERS: Final[frozenset[str]] = frozenset(
    {"image-only", "metadata-assisted", "exact-texture"}
)
STATES: Final[frozenset[str]] = frozenset(
    {"proceed", "request-input", "fallback", "rejected", "unsupported-family", "unsupported-subtype"}
)
PAIR_LAYOUT_MIN_LARGEST_COMPONENT_FRACTION: Final[float] = 0.45
PAIR_LAYOUT_MAX_LARGEST_COMPONENT_FRACTION: Final[float] = 0.55


def build_classification_record(
    item_family: str,
    subtype: str | None,
    confidence: float,
    evidence_refs: list[str],
    *,
    provider: str = "offline-fixture",
    version: str = "1",
    timeout: bool = False,
) -> dict[str, Any]:
    if item_family not in SUPPORTED_FAMILIES | UNSUPPORTED_FAMILIES:
        raise ValueError(f"unsupported item family label: {item_family}")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("classification confidence must be between 0 and 1")
    return {
        "itemFamily": item_family,
        "subtype": subtype,
        "confidence": round(confidence, 4),
        "evidenceRefs": list(evidence_refs),
        "provider": provider,
        "version": version,
        "timedOut": timeout,
    }


def _classification_error(record: Any) -> str | None:
    if not isinstance(record, dict):
        return "authoritative classification record is required"
    family = record.get("itemFamily")
    confidence = record.get("confidence")
    refs = record.get("evidenceRefs")
    if not isinstance(family, str) or family not in SUPPORTED_FAMILIES | UNSUPPORTED_FAMILIES:
        return "classification itemFamily is missing or invalid"
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        return "classification confidence is missing or invalid"
    if not isinstance(refs, list) or not refs or not all(isinstance(item, str) and item for item in refs):
        return "classification evidenceRefs must contain at least one reference"
    if not isinstance(record.get("provider"), str) or not isinstance(record.get("version"), str):
        return "classification provider/version are required"
    for key in ("adapterRoute", "componentAdapter"):
        if key in record and record[key] is not None and (
            not isinstance(record[key], str) or not record[key].strip()
        ):
            return f"classification {key} must be a non-empty string when supplied"
    return None


def _heuristic_signal(reference: Path) -> dict[str, Any]:
    try:
        return detect_cs2_signals(reference)
    except (OSError, ValueError) as exc:
        return {"is_cs2_candidate": False, "confidence": 0.0, "signals": [], "error": str(exc)}


def _paired_glove_plate_override(admission: dict[str, Any]) -> dict[str, Any] | None:
    """Recognize a two-glove catalogue plate without weakening generic admission.

    The generic gate correctly rejects scattered foreground for a single-object
    reference.  A catalogue plate showing a left/right glove pair is a bounded
    exception: its two coherent, similarly sized subjects are expected and the
    pair is the actual reconstruction target.  Keep the raw rejection intact so
    later evidence can distinguish this override from an ordinary admission.
    """
    if admission.get("admitted"):
        return None
    reasons = admission.get("reasons")
    provenance = admission.get("provenance")
    if not isinstance(reasons, list) or len(reasons) != 1 or not isinstance(provenance, dict):
        return None
    if not str(reasons[0]).startswith("mask coherence:") or provenance.get("duplicateOfHash") is not None:
        return None
    fraction = provenance.get("largestComponentFraction")
    if not isinstance(fraction, (int, float)):
        return None
    if not PAIR_LAYOUT_MIN_LARGEST_COMPONENT_FRACTION <= fraction <= PAIR_LAYOUT_MAX_LARGEST_COMPONENT_FRACTION:
        return None
    return {
        "id": "paired-glove-plate-v1",
        "reason": "two similarly sized disconnected foreground components are the intended left/right glove pair",
        "rawAdmission": "rejected",
        "epistemicState": "observed",
    }


def _admit_glove_views(references: list[tuple[Path, str]]) -> list[dict[str, Any]]:
    """Admit ordered glove views and preserve duplicate relations without dropping inputs."""
    views: list[dict[str, Any]] = []
    admitted_hashes: list[int] = []
    admitted_ids: list[str] = []
    for index, (path, role) in enumerate(references):
        resolved = path.expanduser().resolve()
        technical = probe(resolved) if resolved.exists() else {"width": 0, "height": 0, "warnings": ["file does not exist"]}
        admission = check_admission(resolved, viewpoint=role, against_hashes=admitted_hashes) if resolved.exists() else {
            "admitted": False,
            "reasons": ["reference does not exist"],
            "provenance": {"pHash": None, "width": 0, "height": 0},
        }
        provenance = admission.get("provenance", {})
        raw_hash = provenance.get("pHash")
        view_id = glove_source_view_id(role, index)
        override = _paired_glove_plate_override(admission)
        admitted = bool(admission.get("admitted")) or override is not None
        duplicate_of = provenance.get("duplicateOfHash")
        duplicate_id = None
        if duplicate_of is not None:
            duplicate_id = next(
                (admitted_ids[pos] for pos, admitted_hash in enumerate(admitted_hashes) if admitted_hash == duplicate_of),
                str(duplicate_of),
            )
        view = {
            "id": view_id,
            "role": role,
            "path": str(resolved),
            "hash": str(raw_hash) if raw_hash is not None else "missing",
            "width": int(provenance.get("width") or technical.get("width") or 0),
            "height": int(provenance.get("height") or technical.get("height") or 0),
            "coverage": provenance.get("foregroundCoverage"),
            "admission": "admitted" if admitted else "rejected",
            "admissionReasons": list(admission.get("reasons", [])),
            "duplicateOf": duplicate_id,
            "technical": technical,
        }
        if override is not None:
            view["admissionOverride"] = override
            view["rawAdmission"] = admission
        views.append(view)
        if admitted and isinstance(raw_hash, int):
            admitted_hashes.append(raw_hash)
            admitted_ids.append(view_id)
    return views


def build_manifest(
    reference: Path,
    classification: dict[str, Any] | None,
    *,
    route: str = "reference-projection",
    exactness_tier: str = "image-only",
    metadata: dict[str, Any] | None = None,
    texture_source: str = "image-only",
    explicit_identity: dict[str, Any] | None = None,
    references: list[tuple[Path, str]] | None = None,
    hands: list[str] | None = None,
) -> dict[str, Any]:
    resolved = reference.expanduser().resolve()
    technical: dict[str, Any] = probe(resolved) if resolved.exists() else {"path": str(resolved), "warnings": ["file does not exist"]}
    admission: dict[str, Any] = check_admission(resolved) if resolved.exists() else {"admitted": False, "reasons": ["reference does not exist"]}
    heuristic = _heuristic_signal(resolved) if resolved.exists() else {"is_cs2_candidate": False, "confidence": 0.0, "signals": []}
    warnings: list[str] = []
    if heuristic.get("is_cs2_candidate"):
        warnings.append("heuristicSignal")
    if technical.get("warnings"):
        warnings.extend(str(item) for item in technical["warnings"])
    if route not in ROUTES:
        raise ValueError(f"unknown route {route!r}")
    if exactness_tier not in TIERS:
        raise ValueError(f"unknown exactness tier {exactness_tier!r}")
    manifest: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "state": "rejected" if not admission.get("admitted") else "request-input",
        "sourceViews": [{
            "role": "reference",
            "path": str(resolved),
            "hash": admission.get("provenance", {}).get("pHash"),
            "width": technical.get("width"),
            "height": technical.get("height"),
            "coverage": admission.get("provenance", {}).get("foregroundCoverage"),
            "duplicate": admission.get("provenance", {}).get("duplicateOfHash") is not None,
        }],
        "admission": admission,
        "probe": technical,
        "heuristicSignal": heuristic,
        "exactnessTier": exactness_tier,
        "route": route,
        "textureSource": texture_source,
        "identity": {"provenance": "unknown", "confidence": 0.0},
        "finish": {"provenance": "visual-observation", "confidence": 0.0},
        "assets": {"source": texture_source, "records": []},
        "camera": {"status": "unknown", "provenance": "not-supplied"},
        "provenance": {"reference": "user-supplied", "metadata": "not-supplied"},
        "assumptions": {"float": "unknown", "paintSeed": "unknown", "hiddenRegions": "inferred"},
        "confidence": {"overall": 0.0, "hiddenRegions": 0.25},
        "warnings": warnings,
        "extensions": {},
        "reviewScene": build_review_scene("not-supplied"),
    }
    glove_request = isinstance(classification, dict) and classification.get("itemFamily") == "glove"
    if not admission.get("admitted") and not glove_request:
        manifest["rejectionReasons"] = admission.get("reasons", ["reference failed admission"])
        return manifest
    if not admission.get("admitted") and glove_request:
        manifest["warnings"].extend(str(item) for item in admission.get("reasons", []) if str(item) not in manifest["warnings"])
    error = _classification_error(classification)
    if error:
        manifest["warnings"].append(error)
        return manifest
    assert isinstance(classification, dict)
    family = classification["itemFamily"]
    subtype = classification.get("subtype")
    raw_family = family
    # Provider taxonomies sometimes call AWP "sniper". The production contract owns
    # it under canonical rifle; other sniper candidates remain explicitly unsupported.
    if family == "sniper" and subtype == "awp":
        family = "rifle"
        manifest["warnings"].append("family-alias:sniper->rifle")
    manifest["classification"] = classification
    manifest["itemFamily"] = family
    manifest["subtype"] = subtype
    manifest["rawItemFamily"] = raw_family
    manifest["identity"] = {"provenance": "classification-record", "confidence": classification["confidence"]}
    manifest["confidence"] = {"overall": classification["confidence"], "hiddenRegions": 0.25}
    manifest["identity"] = resolve_identity(explicit_identity, metadata, classification)
    if family not in SUPPORTED_FAMILIES:
        manifest["state"] = "unsupported-family"
        manifest["unsupportedReason"] = f"no adapter registered for {family}"
    elif family == "glove" and not subtype:
        manifest["state"] = "unsupported-subtype"
        manifest["unsupportedReason"] = "a glove must declare a subtype"
    elif family == "glove":
        ordered_references = references or [(reference, "dorsal")]
        glove_views = _admit_glove_views(ordered_references)
        manifest["sourceViews"] = glove_views
        primary = next((view for view in glove_views if view.get("role") == "dorsal"), glove_views[0])
        manifest["primarySourceViewId"] = primary["id"]
        manifest["sourceImage"] = primary["path"]
        manifest["extensions"]["glove"] = build_glove_extension(glove_views, subtype, hands=hands)
        manifest["extensions"]["glove"]["sourceViews"] = glove_views
        identity_payload = manifest.get("identity", {}).get("identity", {}) if isinstance(manifest.get("identity"), dict) else {}
        declared_hand = identity_payload.get("hand", identity_payload.get("canonicalHand")) if isinstance(identity_payload, dict) else None
        hand_conflict = declared_hand in {"left", "right"} and declared_hand != "left"
        if hand_conflict:
            manifest["extensions"]["glove"]["contradictions"].append({"field": "canonicalHand", "declared": declared_hand, "required": "left", "epistemicState": "contradiction"})
            manifest["warnings"].append("conflicting-hand-identity")
            manifest["state"] = "request-input"
            manifest["unsupportedReason"] = "hand identity conflicts with canonical-left MVP"
        role_set = {view.get("role") for view in glove_views if view.get("admission") == "admitted"}
        # A single-hand listing supplies the two plates and nothing else: there is no second wear tier
        # to borrow a thumb-side or three-quarter technical view from, so demanding four roles refuses
        # the item rather than raising its evidence. The hand is DECLARED by the caller -- the
        # silhouette measurement reads only the largest component, so it cannot tell one glove from two.
        required_roles = set(TARGET_REQUIRED_VIEW_ROLES) if hands is not None and len(hands) == 1 else set(REQUIRED_GLOVE_VIEW_ROLES)
        complete = required_roles.issubset(role_set)
        required_views = [view for view in glove_views if view.get("role") in required_roles]
        if not hand_conflict and complete and all(view.get("admission") == "admitted" for view in required_views):
            manifest["state"] = "proceed"
            manifest["stagedComponentAdapter"] = "cs2-glove-v1"
        else:
            manifest["state"] = "request-input"
            manifest["unsupportedReason"] = "glove requires all admitted " + "/".join(sorted(required_roles)) + " views"
    elif not subtype:
        manifest["state"] = "unsupported-subtype"
        manifest["unsupportedReason"] = f"a subtype is required for {family}"
    else:
        try:
            # An authoritative classification may select a concrete versioned adapter. If it
            # does not, preserve the legacy default route for existing manifests.
            requested_adapter = classification.get("adapterRoute") or classification.get("componentAdapter")
            if requested_adapter is not None and not isinstance(requested_adapter, str):
                raise ValueError("unsupported-adapter: classification adapterRoute must be a string")
            adapter = get_family_adapter(family, subtype, adapter_id=requested_adapter)
        except ValueError as error:
            manifest["state"] = "unsupported-subtype" if "unsupported-subtype" in str(error) else "unsupported-family"
            manifest["unsupportedReason"] = str(error)
        else:
            manifest["state"] = "proceed"
            manifest["componentAdapter"] = adapter.adapter_id
            manifest["adapterRoute"] = adapter.adapter_id
            manifest["adapterContractVersion"] = adapter.contract_version
            manifest["adapterFixtureId"] = adapter.fixture_id
            manifest["adapterContract"] = adapter.component_tree_contract()
    if manifest["state"] != "proceed" and family == "knife" and subtype and subtype not in KNIFE_SUBTYPES:
        manifest["state"] = "unsupported-subtype"
        manifest["unsupportedReason"] = f"no knife adapter fixture for {subtype}"
    if metadata:
        manifest = enrich_manifest_with_metadata(manifest, {"status": "resolved", "identity": metadata})
        manifest["metadata"] = normalize_cs2_metadata(metadata)
        manifest["provenance"]["metadata"] = metadata.get("source", "provided")
    return manifest


def validate_manifest(manifest: dict[str, Any]) -> bool:
    required = {"schemaVersion", "state", "sourceViews", "admission", "exactnessTier", "route", "warnings"}
    if not required.issubset(manifest):
        return False
    if manifest["schemaVersion"] != SCHEMA_VERSION or manifest["state"] not in STATES:
        return False
    if manifest["route"] not in ROUTES or manifest["exactnessTier"] not in TIERS:
        return False
    if not isinstance(manifest["sourceViews"], list) or not isinstance(manifest["warnings"], list):
        return False
    if manifest["state"] == "proceed" and manifest.get("itemFamily") not in SUPPORTED_FAMILIES:
        return False
    if manifest.get("itemFamily") == "glove":
        if manifest["state"] != "unsupported-subtype" and glove_manifest_errors(
            manifest, require_complete_views=manifest["state"] == "proceed"
        ):
            return False
    elif manifest["state"] == "proceed":
        adapter_id = manifest.get("componentAdapter")
        if not isinstance(adapter_id, str):
            return False
        try:
            adapter = get_family_adapter(
                str(manifest["itemFamily"]),
                manifest.get("subtype"),
                adapter_id=adapter_id,
            )
        except (TypeError, ValueError):
            return False
        if manifest.get("adapterRoute", adapter_id) != adapter.adapter_id:
            return False
        if str(manifest.get("adapterContractVersion", "")) != adapter.contract_version:
            return False
        if manifest.get("adapterFixtureId") != adapter.fixture_id:
            return False
    return True


def persist_manifest(manifest: dict[str, Any], output: Path) -> None:
    if not validate_manifest(manifest):
        raise ValueError("refusing to persist invalid cs2-intake manifest")
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, output)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, nargs="?")
    parser.add_argument("--image", action="append", dest="images", default=[], help="ordered reference view; repeat for N-view glove intake")
    parser.add_argument("--view-role", action="append", dest="view_roles", default=[], help="role for each --image: dorsal, palmar, thumb-side-profile, three-quarter")
    parser.add_argument("--classification", type=Path, help="offline authoritative classification JSON")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--route", choices=sorted(ROUTES), default="reference-projection")
    parser.add_argument("--exactness-tier", choices=sorted(TIERS), default="image-only")
    parser.add_argument("--cs2-pipeline", choices=("legacy", "manifest-v1"), default="manifest-v1")
    parser.add_argument("--resume", action="store_true", help="reuse a valid existing manifest at --out")
    args = parser.parse_args(argv)
    if args.resume and args.out.exists():
        existing = json.loads(args.out.read_text(encoding="utf-8"))
        if isinstance(existing, dict) and validate_manifest(existing):
            print(json.dumps({"state": existing["state"], "out": str(args.out.resolve()), "resumed": True}, ensure_ascii=False))
            return 0
    classification = json.loads(args.classification.read_text(encoding="utf-8")) if args.classification else None
    paths = list(args.images)
    if args.reference is not None:
        paths.insert(0, str(args.reference))
    if not paths:
        parser.error("provide a positional reference or at least one --image")
    roles = list(args.view_roles)
    if roles and len(roles) != len(paths):
        parser.error("--view-role must be supplied once per reference")
    if len(paths) > 1 or (classification and classification.get("itemFamily") == "glove"):
        default_roles = list(REQUIRED_GLOVE_VIEW_ROLES)
        roles = roles or [default_roles[index] if index < len(default_roles) else "orbit" for index in range(len(paths))]
        references = [(Path(path), roles[index]) for index, path in enumerate(paths)]
    else:
        references = None
    manifest = build_manifest(Path(paths[0]), classification, route=args.route, exactness_tier=args.exactness_tier, references=references)
    manifest["extensions"]["compatibilityMode"] = args.cs2_pipeline
    persist_manifest(manifest, args.out)
    print(json.dumps({"state": manifest["state"], "out": str(args.out.resolve())}, ensure_ascii=False))
    return 0 if manifest["state"] in {"proceed", "request-input", "fallback"} else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
