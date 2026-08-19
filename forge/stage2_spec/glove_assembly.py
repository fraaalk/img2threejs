"""Versioned panel/seam/attachment assembly graph for the first glove subtype."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

from forge.stage1_intake.glove_contracts import GLOVE_ASSEMBLY_VERSION, REQUIRED_GLOVE_VIEW_ROLES


def _panel(panel_id: str, region: str, material: str, loop: list[list[float]], seams: list[str], *, side: str = "left") -> dict[str, Any]:
    return {
        "id": panel_id,
        "region": region,
        "side": side,
        "boundaryLoop": loop,
        "material": material,
        "patternSpaceUV": [[point[0], point[1]] for point in loop],
        "evidenceRefs": ["glove-evidence-shell-regions"],
        "derivation": {
            "tier": "diagnostic",
            "sourceViewIds": [],
            "landmarkIds": [],
            "algorithm": "normalized-sport-glove-pattern-v1",
            "confidence": 0.0,
            "epistemicState": "implementation",
        },
        "seamIds": seams,
        "authoritative": True,
    }


def _seam(seam_id: str, panel_a: str, panel_b: str, *, span_count: int = 5, mode: str = "production") -> dict[str, Any]:
    spans = list(range(span_count))
    return {
        "id": seam_id,
        "panelA": panel_a,
        "panelB": panel_b,
        "orderedBoundarySpansA": spans,
        "orderedBoundarySpansB": list(spans),
        "orientation": "same-after-panel-normalization",
        "correspondencePolicy": "ordered-equal-cardinality",
        "allowance": 0.012,
        "mode": mode,
        "residualTolerance": 0.018,
    }


def resample_ordered_spans(spans: list[int], target_count: int) -> list[int]:
    """Boundedly resample an ordered seam span list while retaining endpoint order."""
    if target_count < 2 or len(spans) < 2:
        raise ValueError("seam resampling requires at least two source and target spans")
    if len(spans) == target_count:
        return list(spans)
    return [spans[round(index * (len(spans) - 1) / (target_count - 1))] for index in range(target_count)]


def build_glove_assembly(
    subtype: str = "sport-gloves",
    source_view_ids: list[str] | None = None,
    *,
    form_profile: str = "full-finger",
    curved_digits: bool = False,
) -> dict[str, Any]:
    if not subtype:
        raise ValueError("glove assembly requires a subtype")
    if form_profile not in {"full-finger", "fingerless", "mitten"}:
        raise ValueError(f"unsupported or unobservable glove form profile: {form_profile}")
    source_refs = source_view_ids or list(REQUIRED_GLOVE_VIEW_ROLES)
    regions = [
        ("palm", "palm-shell", "glove-leather"),
        ("dorsal", "dorsal-shell", "glove-textile"),
        ("cuff", "cuff", "glove-textile"),
        ("thumb-saddle", "thumb-saddle", "glove-textile"),
        ("index", "finger-stall", "glove-leather"),
        ("middle", "finger-stall", "glove-leather"),
        ("ring", "finger-stall", "glove-leather"),
        ("pinky", "finger-stall", "glove-leather"),
        ("thumb-fourchette", "fourchette-gusset", "glove-leather"),
        ("finger-fourchettes", "fourchette-gusset", "glove-leather"),
        ("knuckle-guard", "guard-overlay", "glove-guard"),
        ("closure", "closure-overlay", "glove-closure"),
    ]
    region_nodes = [
        {"id": f"region-{region}", "name": region, "topologyClass": "conforming-shell" if "overlay" not in role else "assembled-solid", "required": True, "evidenceRefs": source_refs}
        for region, role, _material in regions
    ]
    panels = [
        _panel("panel-palm", "palm", "glove-leather", [[-0.64, -0.72], [0.64, -0.72], [0.72, 0.55], [0.0, 0.82], [-0.72, 0.55]], ["seam-palm-dorsal", "seam-palm-cuff", "seam-thumb-palm"]),
        _panel("panel-dorsal", "dorsal", "glove-textile", [[-0.68, -0.66], [0.68, -0.66], [0.72, 0.58], [0.0, 0.84], [-0.72, 0.58]], ["seam-palm-dorsal", "seam-dorsal-cuff"]),
        _panel("panel-cuff", "cuff", "glove-textile", [[-0.76, -0.18], [0.76, -0.18], [0.76, 0.22], [-0.76, 0.22]], ["seam-palm-cuff", "seam-dorsal-cuff"]),
        _panel("panel-thumb-saddle", "thumb-saddle", "glove-textile", [[-0.34, -0.36], [0.36, -0.26], [0.54, 0.28], [0.08, 0.56], [-0.46, 0.24]], ["seam-thumb-palm", "seam-thumb-fourchette"]),
    ]
    finger_x = {"index": -0.45, "middle": -0.15, "ring": 0.15, "pinky": 0.43}
    for finger, x in finger_x.items():
        panel_id = f"panel-{finger}-stall"
        seam_id = f"seam-{finger}-fourchette"
        tip = 1.08
        loop = [[x - 0.11, 0.25], [x + 0.11, 0.25], [x + 0.095, 0.96], [x, tip], [x - 0.095, 0.96]]
        if curved_digits:
            loop[2][0] += 0.06 if finger in {"index", "middle"} else -0.06
            loop[3][0] += 0.12 if finger in {"index", "middle"} else -0.12
        panels.append(_panel(panel_id, finger, "glove-leather", loop, [seam_id]))
    panels.extend([
        _panel("panel-thumb-fourchette", "thumb-fourchette", "glove-leather", [[-0.48, -0.18], [-0.23, -0.32], [-0.02, 0.30], [-0.24, 0.58]], ["seam-thumb-fourchette"]),
        _panel("panel-fourchettes", "finger-fourchettes", "glove-leather", [[-0.55, 0.18], [0.55, 0.18], [0.52, 0.62], [-0.52, 0.62]], ["seam-index-fourchette", "seam-middle-fourchette", "seam-ring-fourchette", "seam-pinky-fourchette"]),
        _panel("overlay-knuckle-guard", "knuckle-guard", "glove-guard", [[-0.55, 0.12], [0.55, 0.12], [0.48, 0.38], [-0.48, 0.38]], [], side="shared"),
        _panel("overlay-closure", "closure", "glove-closure", [[-0.45, -0.2], [0.45, -0.2], [0.45, 0.0], [-0.45, 0.0]], [], side="shared"),
    ])
    seams = [
        _seam("seam-palm-dorsal", "panel-palm", "panel-dorsal"),
        _seam("seam-palm-cuff", "panel-palm", "panel-cuff", span_count=4),
        _seam("seam-dorsal-cuff", "panel-dorsal", "panel-cuff", span_count=4),
        _seam("seam-thumb-palm", "panel-thumb-saddle", "panel-palm"),
        _seam("seam-thumb-fourchette", "panel-thumb-saddle", "panel-thumb-fourchette"),
        _seam("seam-index-fourchette", "panel-index-stall", "panel-fourchettes", span_count=5),
        _seam("seam-middle-fourchette", "panel-middle-stall", "panel-fourchettes", span_count=5),
        _seam("seam-ring-fourchette", "panel-ring-stall", "panel-fourchettes", span_count=5),
        _seam("seam-pinky-fourchette", "panel-pinky-stall", "panel-fourchettes", span_count=5),
    ]
    if form_profile == "fingerless":
        omitted = {"index", "middle", "ring", "pinky", "finger-fourchettes", "thumb-fourchette"}
        panels = [panel for panel in panels if panel.get("region") not in omitted]
        regions = [region for region in regions if region[0] not in omitted]
        seams = [seam for seam in seams if "fourchette" not in seam["id"]]
    elif form_profile == "mitten":
        omitted = {"index", "middle", "ring", "pinky", "finger-fourchettes", "thumb-fourchette"}
        panels = [panel for panel in panels if panel.get("region") not in omitted]
        regions = [region for region in regions if region[0] not in omitted]
        panels.append(_panel("panel-mitten-chamber", "mitten-chamber", "glove-leather", [[-0.58, 0.22], [0.58, 0.22], [0.64, 0.88], [0.34, 1.14], [-0.34, 1.14], [-0.64, 0.88]], ["seam-mitten-dorsal"]))
        regions.append(("mitten-chamber", "grouped-digit-chamber", "glove-leather"))
        seams = [seam for seam in seams if "fourchette" not in seam["id"]]
        seams.append(_seam("seam-mitten-dorsal", "panel-mitten-chamber", "panel-dorsal", span_count=5))
    attachments = [
        {"id": "attach-thumb-saddle", "child": "panel-thumb-saddle", "parent": "panel-palm", "parentSocket": "thumb-saddle-socket", "localFrame": {"origin": [-0.48, 0.05, 0.0], "normal": [0.0, 0.0, 1.0]}, "contactType": "overlap", "embed": 0.018, "gapTolerance": 0.01},
        {"id": "attach-cuff", "child": "panel-cuff", "parent": "panel-palm", "parentSocket": "cuff-opening", "localFrame": {"origin": [0.0, -0.7, 0.0], "normal": [0.0, -1.0, 0.0]}, "contactType": "sewn-boundary", "embed": 0.012, "gapTolerance": 0.01},
        {"id": "attach-knuckle-guard", "child": "overlay-knuckle-guard", "parent": "panel-dorsal", "parentSocket": "knuckle-overlay", "localFrame": {"origin": [0.0, 0.35, 0.04], "normal": [0.0, 0.0, 1.0]}, "contactType": "surface-contact", "embed": 0.004, "gapTolerance": 0.012},
        {"id": "attach-closure", "child": "overlay-closure", "parent": "panel-cuff", "parentSocket": "closure-strap", "localFrame": {"origin": [0.0, 0.0, 0.04], "normal": [0.0, 0.0, 1.0]}, "contactType": "surface-contact", "embed": 0.004, "gapTolerance": 0.012},
    ]
    evidence = [
        {"id": "glove-evidence-shell-regions", "sourceRefs": source_refs, "epistemicState": "observed", "confidence": 0.9},
        {"id": "glove-evidence-hidden-seams", "sourceRefs": [source_refs[0]], "epistemicState": "unknown", "confidence": 0.0},
    ]
    routes = []
    for region, role, _material in regions:
        authoritative = "overlay" not in role and role not in {"guard-overlay", "closure-overlay"}
        routes.append({"id": f"route-{region}", "region": region, "topologyClass": "conforming-shell" if authoritative else "assembled-solid", "authoritativeRoute": "panel-seam-surface" if authoritative else "overlay-geometry", "supportingRoutes": ["underform-lift"] if authoritative else ["profile-extrusion"], "evidenceRefs": source_refs, "rejectedAlternatives": ["generic-knife-component-tree", "visual-hull-as-shell", "sdf-as-sewn-shell"]})
    region_nodes = [
        {"id": f"region-{region}", "name": region, "topologyClass": "conforming-shell" if "overlay" not in role else "assembled-solid", "required": True, "evidenceRefs": source_refs}
        for region, role, _material in regions
    ]
    assembly = {
        "version": GLOVE_ASSEMBLY_VERSION,
        "subtype": subtype,
        "formProfile": form_profile,
        "digitTopology": {
            "curvedDigits": curved_digits,
            "regions": [panel["region"] for panel in panels if panel.get("region") in {"index", "middle", "ring", "pinky", "mitten-chamber"}],
        },
        "canonicalHand": "left",
        "evidenceTier": "diagnostic",
        "normalizedScale": True,
        "regionGraph": {"nodes": region_nodes, "edges": [{"from": "region-palm", "to": "region-dorsal", "relation": "sewn-boundary"}, {"from": "region-palm", "to": "region-thumb-saddle", "relation": "parent-surface"}]},
        "panelGraph": {"nodes": panels, "edges": [{"from": seam["panelA"], "to": seam["panelB"], "seamId": seam["id"]} for seam in seams]},
        "seamGraph": {"nodes": seams, "edges": []},
        "attachmentGraph": {"nodes": attachments, "edges": [{"from": item["parent"], "to": item["child"], "attachmentId": item["id"]} for item in attachments]},
        "evidenceGraph": {"nodes": evidence, "edges": []},
        "routeGraph": {"nodes": routes, "edges": []},
        "policy": {"mainShell": "production-manifold", "allowedBoundaryKinds": ["cuff", "open-cut"] if form_profile == "fingerless" else ["cuff"], "reviewOverlap": "diagnostic-only", "sdf": "supporting-underform-or-padding-only", "visualHull": "silhouette-envelope-only"},
    }
    errors = validate_glove_assembly(assembly)
    if errors:
        raise ValueError("invalid generated glove assembly: " + "; ".join(errors))
    return assembly


def _loop_area(loop: list[list[float]]) -> float:
    return sum(loop[index][0] * loop[(index + 1) % len(loop)][1] - loop[(index + 1) % len(loop)][0] * loop[index][1] for index in range(len(loop))) / 2.0


def _segments_intersect(a: list[float], b: list[float], c: list[float], d: list[float]) -> bool:
    def orient(p: list[float], q: list[float], r: list[float]) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0)


def validate_glove_assembly(assembly: Any) -> list[str]:
    if not isinstance(assembly, dict):
        return ["assembly must be an object"]
    errors: list[str] = []
    if assembly.get("version") != GLOVE_ASSEMBLY_VERSION:
        errors.append(f"assembly version must be {GLOVE_ASSEMBLY_VERSION}")
    evidence_tier = assembly.get("evidenceTier")
    if evidence_tier not in {"diagnostic", "evidence-backed"}:
        errors.append("assembly evidenceTier must be diagnostic or evidence-backed")
    graphs = ["regionGraph", "panelGraph", "seamGraph", "attachmentGraph", "evidenceGraph", "routeGraph"]
    for graph_name in graphs:
        graph = assembly.get(graph_name)
        if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
            errors.append(f"{graph_name} must have nodes and edges lists")
    panels = assembly.get("panelGraph", {}).get("nodes", []) if isinstance(assembly.get("panelGraph"), dict) else []
    panel_ids = {panel.get("id") for panel in panels if isinstance(panel, dict)}
    if len(panel_ids) != len(panels):
        errors.append("panel IDs must be unique")
    for panel in panels:
        if not isinstance(panel, dict):
            errors.append("panel node must be an object")
            continue
        derivation = panel.get("derivation")
        if not isinstance(derivation, dict) or derivation.get("tier") not in {"diagnostic", "evidence-backed"}:
            errors.append(f"panel {panel.get('id')} has no derivation record")
        elif evidence_tier == "evidence-backed":
            required_derivation = {"sourceViewIds", "landmarkIds", "algorithm", "confidence", "epistemicState"}
            if not required_derivation.issubset(derivation) or not derivation.get("sourceViewIds"):
                errors.append(f"evidence-backed panel {panel.get('id')} has incomplete derivation")
        loop = panel.get("boundaryLoop")
        if not isinstance(loop, list) or len(loop) < 3:
            errors.append(f"panel {panel.get('id')} has no valid boundary loop")
            continue
        if not all(isinstance(point, list) and len(point) == 2 and all(isinstance(value, (int, float)) and math.isfinite(value) for value in point) for point in loop):
            errors.append(f"panel {panel.get('id')} loop has non-finite coordinates")
        if _loop_area(loop) <= 0:
            errors.append(f"panel {panel.get('id')} loop must be counter-clockwise")
        for index in range(len(loop)):
            a, b = loop[index], loop[(index + 1) % len(loop)]
            for other in range(index + 2, len(loop)):
                if other == (index - 1) % len(loop):
                    continue
                c, d = loop[other], loop[(other + 1) % len(loop)]
                if _segments_intersect(a, b, c, d):
                    errors.append(f"panel {panel.get('id')} loop self-intersects")
    for seam in assembly.get("seamGraph", {}).get("nodes", []) if isinstance(assembly.get("seamGraph"), dict) else []:
        if not isinstance(seam, dict):
            errors.append("seam node must be an object")
            continue
        if seam.get("panelA") not in panel_ids or seam.get("panelB") not in panel_ids:
            errors.append(f"seam {seam.get('id')} references an unknown panel")
        a, b = seam.get("orderedBoundarySpansA"), seam.get("orderedBoundarySpansB")
        if not isinstance(a, list) or not isinstance(b, list) or len(a) < 2 or len(b) < 2:
            errors.append(f"seam {seam.get('id')} has incompatible boundary cardinality")
        elif seam.get("correspondencePolicy") == "ordered-equal-cardinality" and len(a) != len(b):
            errors.append(f"seam {seam.get('id')} has incompatible boundary cardinality")
    known_nodes = panel_ids | {node.get("id") for node in assembly.get("regionGraph", {}).get("nodes", []) if isinstance(node, dict)}
    for attachment in assembly.get("attachmentGraph", {}).get("nodes", []) if isinstance(assembly.get("attachmentGraph"), dict) else []:
        if not isinstance(attachment, dict) or attachment.get("parent") not in known_nodes or attachment.get("child") not in known_nodes:
            errors.append(f"attachment {attachment.get('id') if isinstance(attachment, dict) else '<invalid>'} references unknown nodes")
        elif not isinstance(attachment.get("gapTolerance"), (int, float)) or attachment.get("gapTolerance") < 0:
            errors.append(f"attachment {attachment.get('id')} has invalid gap tolerance")
    return errors


def canonical_hash(payload: Any) -> str:
    def normalize(value: Any) -> Any:
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("canonical JSON does not support non-finite numbers")
            return 0 if value == 0 else int(value) if value.is_integer() else value
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, tuple):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in value.items()}
        return value
    encoded = json.dumps(normalize(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json_atomic(path: Path, payload: Any) -> str:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return canonical_hash(payload)
