#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from forge.stage1_intake.check_reference_admission import check_admission  # noqa: E402
from forge.stage1_intake.cs2_foundation import enrich_manifest_with_metadata, normalize_cs2_metadata  # noqa: E402
from forge.stage1_intake.detect_cs2 import detect_cs2_signals  # noqa: E402
from forge.stage1_intake.probe_image import probe  # noqa: E402
from forge.stage2_spec.cs2_adapters import resolve_family_adapter  # noqa: E402

SCHEMA_VERSION: Final[int] = 2
ROUTES: Final[frozenset[str]] = frozenset({"reference-projection", "authored-texture", "procedural-finish"})
TIERS: Final[frozenset[str]] = frozenset({"image-only", "metadata-assisted", "exact-texture"})
STATES: Final[frozenset[str]] = frozenset({"proceed", "request-input", "rejected"})
CONFIRMATION_ACTIONS: Final[frozenset[str]] = frozenset({"accept", "none-of-these", "continue-generically", "add-secondary"})
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
    if not item_family.strip() or not 0.0 <= confidence <= 1.0:
        raise ValueError("classification requires a family and confidence from 0 to 1")
    return {"itemFamily": item_family, "subtype": subtype, "confidence": round(confidence, 4), "evidenceRefs": list(evidence_refs), "provider": provider, "version": version, "timedOut": timeout}


def _signal(reference: Path) -> dict[str, Any]:
    try:
        return detect_cs2_signals(reference)
    except (OSError, ValueError) as error:
        return {"is_cs2_candidate": False, "confidence": 0.0, "signals": [], "error": str(error)}


def _source_view(reference: Path, role: str, against_hashes: list[int] | None = None) -> dict[str, Any]:
    resolved = reference.expanduser().resolve()
    technical: dict[str, Any] = probe(resolved) if resolved.exists() else {"path": str(resolved), "warnings": ["file-does-not-exist"]}
    admission: dict[str, Any] = check_admission(resolved, against_hashes=against_hashes) if resolved.exists() else {"admitted": False, "reasons": ["reference-does-not-exist"]}
    provenance: dict[str, Any] = admission.get("provenance", {}) if isinstance(admission.get("provenance"), dict) else {}
    return {
        "role": role,
        "path": str(resolved),
        "hash": provenance.get("pHash"),
        "width": technical.get("width"),
        "height": technical.get("height"),
        "coverage": provenance.get("foregroundCoverage"),
        "duplicate": provenance.get("duplicateOfHash") is not None,
        "admission": admission,
        "probe": technical,
        "orientation": "unknown",
    }


def _candidate_id(candidate: dict[str, Any], index: int) -> str:
    seed = "|".join(str(candidate.get(key, "")) for key in ("itemFamily", "subtype", "provider", "version", "name"))
    return f"candidate-{index + 1}-{hashlib.sha256(seed.encode()).hexdigest()[:12]}"


def normalize_identity_candidates(candidates: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates or []):
        family = candidate.get("itemFamily")
        confidence = candidate.get("confidence")
        if not isinstance(family, str) or not family.strip() or not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            continue
        if not 0 <= confidence <= 1:
            continue
        provider = candidate.get("provider")
        version = candidate.get("version")
        if not isinstance(provider, str) or not isinstance(version, str):
            continue
        normalized.append({
            "id": candidate.get("id") if isinstance(candidate.get("id"), str) else _candidate_id(candidate, index),
            "itemFamily": family,
            "subtype": candidate.get("subtype") if isinstance(candidate.get("subtype"), str) else None,
            "name": candidate.get("name") if isinstance(candidate.get("name"), str) else None,
            "confidence": round(float(confidence), 4),
            "evidenceRefs": [item for item in candidate.get("evidenceRefs", []) if isinstance(item, str)] if isinstance(candidate.get("evidenceRefs"), list) else [],
            "provider": provider,
            "version": version,
        })
    return sorted(normalized, key=lambda item: (-float(item["confidence"]), str(item["id"])))[:5]


def _association(primary: dict[str, Any], secondary: dict[str, Any] | None) -> dict[str, Any] | None:
    if secondary is None:
        return None
    admitted = bool(secondary["admission"].get("admitted"))
    primary_hash = primary.get("hash")
    secondary_hash = secondary.get("hash")
    if not admitted:
        return {"method": "admission-v1", "score": 0.0, "threshold": 0.7, "status": "contradicted", "sharedCues": [], "contradictoryCues": list(secondary["admission"].get("reasons", ["secondary-not-admitted"])), "replacementRequested": True}
    if primary_hash and secondary_hash and primary_hash == secondary_hash:
        return {"method": "phash-v1", "score": 1.0, "threshold": 0.7, "status": "contradicted", "sharedCues": [], "contradictoryCues": ["duplicate-primary"], "replacementRequested": True}
    return {"method": "user-associated-v1", "score": 1.0, "threshold": 0.7, "status": "associated", "sharedCues": ["user-supplied-secondary"], "contradictoryCues": [], "replacementRequested": False}


def _generic_handoff(primary: dict[str, Any], observation: dict[str, Any], route: str, tier: str) -> dict[str, Any]:
    return {"kind": "generic-image-handoff-v1", "primarySource": {"role": "primary", "path": primary["path"], "hash": primary.get("hash")}, "observedGeometry": observation["geometry"], "observedMaterials": observation["materials"], "observedDetails": observation["details"], "inferredRegions": observation["inferredRegions"], "route": route, "exactnessTier": tier, "resolvedIdentity": None, "componentAdapter": None}


def build_manifest(
    primary_image: Path,
    classification: dict[str, Any] | None = None,
    *,
    secondary_image: Path | None = None,
    identity_candidates: list[dict[str, Any]] | None = None,
    provider_error: str | None = None,
    route: str = "reference-projection",
    exactness_tier: str = "image-only",
    metadata: dict[str, Any] | None = None,
    texture_source: str = "image-only",
    explicit_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if route not in ROUTES or exactness_tier not in TIERS:
        raise ValueError("unknown route or exactness tier")
    primary = _source_view(primary_image, "primary")
    primary_hash = primary.get("hash")
    secondary = _source_view(secondary_image, "secondary", [primary_hash] if isinstance(primary_hash, int) else None) if secondary_image else None
    legacy_candidates = [classification] if classification and not classification.get("timedOut") else []
    candidates = normalize_identity_candidates(identity_candidates if identity_candidates is not None else legacy_candidates)
    admitted = bool(primary["admission"].get("admitted"))
    observation = {"provenance": "primary-image", "geometry": {"status": "observed", "evidenceRefs": ["primary"]}, "materials": {"status": "observed", "evidenceRefs": ["primary"]}, "details": [], "inferredRegions": [{"region": "occluded-or-unseen", "confidence": 0.25, "status": "inferred"}]}
    decision = {"status": "provisional" if candidates else "unavailable", "reason": provider_error or ("no-provider-candidates" if not candidates else None)}
    manifest: dict[str, Any] = {"schemaVersion": SCHEMA_VERSION, "state": "proceed" if admitted else "rejected", "sourceViews": [primary] + ([secondary] if secondary else []), "primaryImage": primary, "secondaryImage": secondary, "secondaryAssociation": _association(primary, secondary), "admission": primary["admission"], "observedObject": observation, "identityCandidates": candidates, "resolvedIdentity": None, "identityDecision": decision, "route": route, "exactnessTier": exactness_tier, "textureSource": texture_source, "assets": {"source": texture_source, "records": []}, "camera": {"status": "unknown", "provenance": "not-supplied"}, "provenance": {"primary": "user-supplied", "metadata": "not-supplied"}, "confidence": {"overall": 0.0, "hiddenRegions": 0.25}, "warnings": [], "enrichment": {"provider": {"status": "error" if provider_error else "available" if candidates else "unavailable", "reason": provider_error}, "retrieval": {"status": "not-eligible", "reason": "identity-not-accepted"}}, "extensions": {}}
    manifest["genericHandoff"] = _generic_handoff(primary, observation, route, exactness_tier)
    signal = _signal(Path(primary["path"])) if admitted else {"is_cs2_candidate": False, "confidence": 0.0, "signals": []}
    manifest["heuristicSignal"] = signal
    if signal.get("is_cs2_candidate"):
        manifest["warnings"].append("heuristic-signal")
    if not admitted:
        manifest["rejectionReasons"] = primary["admission"].get("reasons", ["primary-admission-failed"])
    if metadata:
        manifest = enrich_manifest_with_metadata(manifest, {"status": "resolved", "identity": metadata})
        manifest["metadata"] = normalize_cs2_metadata(metadata)
    if explicit_identity:
        manifest["extensions"]["legacyExplicitIdentity"] = explicit_identity
    return manifest


def apply_confirmation(manifest: dict[str, Any], action: str, candidate_id: str | None = None) -> dict[str, Any]:
    if action not in CONFIRMATION_ACTIONS:
        raise ValueError(f"unknown confirmation action: {action}")
    result = normalize_manifest(manifest)
    if result["state"] == "rejected":
        return result
    result.pop("componentAdapter", None)
    result["resolvedIdentity"] = None
    if action == "add-secondary":
        result["state"] = "request-input"
        result["identityDecision"] = {"status": "awaiting-secondary"}
        return result
    if action == "accept":
        candidate = next((item for item in result["identityCandidates"] if item["id"] == candidate_id), None)
        if candidate is None:
            raise ValueError("candidate ID is not available")
        try:
            adapter = resolve_family_adapter(candidate["itemFamily"], candidate.get("subtype"))
        except ValueError as error:
            reason = str(error).split(":", 1)[0]
            result["identityDecision"] = {"status": reason, "candidateId": candidate_id, "reason": str(error)}
            result["state"] = "request-input"
            result["enrichment"]["retrieval"] = {"status": "not-eligible", "reason": reason}
            result["genericHandoff"]["resolvedIdentity"] = None
            result["genericHandoff"]["componentAdapter"] = None
            return result
        result["resolvedIdentity"] = {**candidate, "itemFamily": adapter.family, "subtype": adapter.subtype}
        result["componentAdapter"] = adapter.adapter_id
        result["identityDecision"] = {"status": "accepted", "candidateId": candidate_id}
        result["enrichment"]["retrieval"] = {"status": "eligible", "reason": None}
        result["itemFamily"] = adapter.family
        result["subtype"] = adapter.subtype
    elif action == "none-of-these":
        result["identityCandidates"] = []
        result["identityDecision"] = {"status": "rejected-all"}
        result["enrichment"]["retrieval"] = {"status": "not-eligible", "reason": "identity-rejected"}
    else:
        result["identityDecision"] = {"status": "skipped"}
        result["enrichment"]["retrieval"] = {"status": "not-eligible", "reason": "generic-continuation"}
    result["state"] = "proceed"
    result["genericHandoff"]["resolvedIdentity"] = result["resolvedIdentity"]
    result["genericHandoff"]["componentAdapter"] = result.get("componentAdapter")
    return result


def record_retrieval_outcome(manifest: dict[str, Any], status: str, reason: str | None = None) -> dict[str, Any]:
    result = normalize_manifest(manifest)
    if result["identityDecision"].get("status") != "accepted":
        result["enrichment"]["retrieval"] = {"status": "not-eligible", "reason": "identity-not-accepted"}
    else:
        result["enrichment"]["retrieval"] = {"status": status, "reason": reason}
    if result["state"] != "rejected":
        result["state"] = "proceed"
    return result


def normalize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schemaVersion") == SCHEMA_VERSION:
        return dict(manifest)
    if manifest.get("schemaVersion") != 1:
        raise ValueError("unsupported intake schema version")
    views = manifest.get("sourceViews")
    if not isinstance(views, list) or not views or not isinstance(views[0], dict):
        raise ValueError("v1 manifest has no source view")
    legacy_primary = dict(views[0])
    legacy_primary["role"] = "primary"
    admitted = bool(manifest.get("admission", {}).get("admitted")) if isinstance(manifest.get("admission"), dict) else manifest.get("state") != "rejected"
    observation = {"provenance": "legacy-v1", "geometry": {"status": "unknown", "evidenceRefs": ["primary"]}, "materials": {"status": "unknown", "evidenceRefs": ["primary"]}, "details": [], "inferredRegions": []}
    result = {**manifest, "schemaVersion": SCHEMA_VERSION, "state": "proceed" if admitted else "rejected", "sourceViews": [legacy_primary], "primaryImage": legacy_primary, "secondaryImage": None, "secondaryAssociation": None, "observedObject": observation, "identityCandidates": [], "resolvedIdentity": None, "identityDecision": {"status": "unavailable", "reason": "legacy-v1"}, "enrichment": {"provider": {"status": "unavailable", "reason": "legacy-v1"}, "retrieval": {"status": "not-eligible", "reason": "identity-not-accepted"}}}
    result["genericHandoff"] = _generic_handoff(legacy_primary, observation, str(result.get("route", "reference-projection")), str(result.get("exactnessTier", "image-only")))
    result.pop("componentAdapter", None)
    return result


def validate_manifest(manifest: dict[str, Any]) -> bool:
    try:
        normalized = normalize_manifest(manifest)
    except ValueError:
        return False
    primary = normalized.get("primaryImage")
    return isinstance(primary, dict) and primary.get("role") == "primary" and normalized.get("state") in STATES and normalized.get("route") in ROUTES and normalized.get("exactnessTier") in TIERS and isinstance(normalized.get("genericHandoff"), dict)


def _atomic_json(payload: dict[str, Any], output: Path) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, output)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def persist_manifest(manifest: dict[str, Any], output: Path) -> None:
    normalized = normalize_manifest(manifest)
    if not validate_manifest(normalized):
        raise ValueError("refusing to persist invalid intake manifest")
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    brief = {"version": 1, "authority": "report-only", "genericHandoff": normalized["genericHandoff"], "identityDecision": normalized["identityDecision"], "enrichment": normalized["enrichment"]}
    encoded = json.dumps(brief, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    brief["sha256"] = hashlib.sha256(encoded).hexdigest()
    brief_path = output.parent / "cs2-internal-brief.json"
    _atomic_json(brief, brief_path)
    normalized["internalBrief"] = {"path": str(brief_path), "sha256": brief["sha256"], "authority": "report-only"}
    _atomic_json(normalized, output)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("primary_image", type=Path)
    parser.add_argument("--secondary-image", type=Path)
    parser.add_argument("--classification", type=Path, help="legacy candidate JSON; it is not accepted automatically")
    parser.add_argument("--identity-candidates", type=Path, help="provider candidate array JSON")
    parser.add_argument("--provider-error", help="record a provider failure without blocking generic continuation")
    parser.add_argument("--confirm", choices=sorted(CONFIRMATION_ACTIONS))
    parser.add_argument("--candidate-id")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--route", choices=sorted(ROUTES), default="reference-projection")
    parser.add_argument("--exactness-tier", choices=sorted(TIERS), default="image-only")
    args = parser.parse_args(argv)
    classification = json.loads(args.classification.read_text(encoding="utf-8")) if args.classification else None
    loaded_candidates = json.loads(args.identity_candidates.read_text(encoding="utf-8")) if args.identity_candidates else None
    candidates = loaded_candidates if isinstance(loaded_candidates, list) else None
    manifest = build_manifest(args.primary_image, classification if isinstance(classification, dict) else None, secondary_image=args.secondary_image, identity_candidates=candidates, provider_error=args.provider_error, route=args.route, exactness_tier=args.exactness_tier)
    if args.confirm:
        manifest = apply_confirmation(manifest, args.confirm, args.candidate_id)
    persist_manifest(manifest, args.out)
    print(json.dumps({"state": manifest["state"], "out": str(args.out.resolve())}, ensure_ascii=False))
    return 0 if manifest["state"] in {"proceed", "request-input"} else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
