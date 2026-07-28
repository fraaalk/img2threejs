#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class FamilyAdapter:
    family: str
    subtype: str
    adapter_id: str
    contract_version: str
    activation: str
    topology: tuple[str, ...]
    painted_regions: tuple[str, ...]
    material_assignments: tuple[str, ...]
    feature_targets: tuple[str, ...]
    attachment_rules: tuple[str, ...]
    review_viewpoints: tuple[str, ...]

    def component_tree_contract(self) -> dict[str, Any]:
        return {"family": self.family, "subtype": self.subtype, "adapterId": self.adapter_id, "contractVersion": self.contract_version, "activation": self.activation, "topology": self.topology, "paintedRegions": self.painted_regions, "materialAssignments": self.material_assignments, "featureTargets": self.feature_targets, "attachmentRules": self.attachment_rules, "reviewViewpoints": self.review_viewpoints}


_KNIFE = FamilyAdapter(
    "knife", "generic-supported", "cs2-knife-v1", "1", "production-eligible", ("ground-blade", "curve-sweep", "extrude", "assembled-solid"),
    ("blade-painted", "grip-painted", "guard-bare-metal", "pommel-bare-metal"),
    ("skin-finish", "substrate"),
    ("silhouette", "blade-edge-spine", "grip", "guard-quillon", "fastener", "pommel"),
    ("guard-to-blade", "grip-to-guard", "pommel-to-grip"),
    ("reference", "orbit-left", "orbit-right"),
)
SUPPORTED_KNIFE_SUBTYPES = frozenset({"karambit", "butterfly", "bayonet", "m9", "flip", "gut", "falchion", "bowie", "navaja", "talon", "classic"})

# A pistol is not a knife with different proportions: it is a two-body assembly (slide riding a
# frame) with a through-hole in the trigger guard, an internal mechanism the shell may reveal,
# and controls that stand proud of the broad faces. It gets its own tree rather than the knife
# tree with renamed parts.
_PISTOL = FamilyAdapter(
    "pistol", "generic-supported", "cs2-pistol-v1", "1", "production-eligible",
    ("extrude-traced-outline", "outline-with-hole", "assembled-solid", "revolve"),
    ("slide-painted", "frame-painted", "magazine-painted", "grip-panel-painted",
     "breech-bare-metal", "barrel-bare-metal", "controls-bare-polymer"),
    ("skin-finish", "substrate", "translucent-shell", "internal-mechanism"),
    ("silhouette", "slide-frame-parting-line", "ejection-port", "sights",
     "trigger-and-safety-blade", "trigger-guard-loop", "grip-rake-and-panel",
     "magazine-extension", "pin-and-control-placement", "muzzle-and-barrel"),
    ("slide-to-frame", "magazine-to-magwell", "trigger-to-pin",
     "grip-panel-to-frame", "internals-inside-shell"),
    ("reference", "orbit-left", "orbit-right", "muzzle-on", "top-down"),
)
SUPPORTED_PISTOL_SUBTYPES = frozenset({"glock-18"})

# A rifle (specifically a sniper rifle like the AWP) is a long-barrel firearm with a
# telescopic scope, bolt-action mechanism, detachable magazine, skeleton/thumbhole stock,
# and a bipod. The Dragon Lore skin covers the receiver/body with intricate artwork while
# the barrel, scope, and hardware remain bare metal/polymer.
_RIFLE = FamilyAdapter(
    "rifle", "generic-supported", "cs2-rifle-v1", "1", "production-eligible",
    ("cylinder-sweep", "extrude-traced-outline", "assembled-solid", "revolve"),
    ("body-painted", "barrel-shroud-painted", "scope-painted", "stock-painted",
     "barrel-bare-metal", "scope-lens-glass", "bolt-bare-metal", "magazine-bare-polymer",
     "bipod-bare-metal", "trigger-bare-metal"),
    ("skin-finish", "substrate", "bare-metal", "glass", "polymer"),
    ("silhouette", "barrel-length-and-muzzle", "scope-mount-and-lenses", "receiver-body-shape",
     "skeleton-stock-thumbhole", "magazine-well", "bolt-handle", "trigger-guard",
     "bipod-attachment", "dragon-lore-artwork-placement"),
    ("scope-to-receiver", "barrel-to-receiver", "stock-to-receiver", "magazine-to-well",
     "bipod-to-barrel", "bolt-to-receiver"),
    ("reference", "orbit-left", "orbit-right", "muzzle-on", "top-down"),
)
SUPPORTED_RIFLE_SUBTYPES = frozenset({"awp"})

_GLOVE = FamilyAdapter(
    "glove", "generic-supported", "cs2-glove-v1", "1", "production-eligible",
    ("continuous-sculpt", "capsule-cluster", "conforming-shell", "assembled-solid"),
    ("dorsal-armor", "palm-padding", "green-textile", "black-grip", "wrist-frame", "wear-zones"),
    ("textile", "synthetic-leather", "rubber", "stitched-seam", "wear-mask"),
    ("paired-glove-silhouette", "five-finger-stalls", "thumb-gusset", "dorsal-knuckle-guards",
     "palm-pad-layout", "wrist-frame-and-cuff", "seam-routing", "field-tested-wear"),
    ("finger-stalls-to-palm", "thumb-to-palm", "guards-to-dorsal-shell", "cuff-to-wrist-shell",
     "wrist-frame-to-cuff"),
    ("dorsal-reference", "palm-reference", "orbit-left", "orbit-right", "wrist-on"),
)
SUPPORTED_GLOVE_SUBTYPES = frozenset({"sport-gloves"})

_ADAPTERS = {
    "knife": (_KNIFE, SUPPORTED_KNIFE_SUBTYPES),
    "pistol": (_PISTOL, SUPPORTED_PISTOL_SUBTYPES),
    "rifle": (_RIFLE, SUPPORTED_RIFLE_SUBTYPES),
    "glove": (_GLOVE, SUPPORTED_GLOVE_SUBTYPES),
}
RECOGNIZED_FAMILIES = frozenset({"knife", "pistol", "rifle", "smg", "sniper", "heavy", "glove"})
FAMILY_ALIASES = {"sniper": "rifle"}


def get_family_adapter(family: str, subtype: str | None = None) -> FamilyAdapter:
    entry = _ADAPTERS.get(family)
    if entry is None:
        raise ValueError(f"unsupported-family: {family}")
    adapter, supported = entry
    if subtype and subtype not in supported:
        raise ValueError(f"unsupported-subtype: {subtype}")
    return adapter if subtype is None else replace(adapter, subtype=subtype)


def resolve_family_adapter(family: str, subtype: str | None) -> FamilyAdapter:
    canonical_family = FAMILY_ALIASES.get(family, family)
    if canonical_family not in _ADAPTERS:
        if family in RECOGNIZED_FAMILIES:
            raise ValueError(f"unsupported-family: {family}")
        raise ValueError(f"unsupported-family: {family}")
    if subtype is None or not subtype.strip():
        raise ValueError(f"unsupported-subtype: missing for {canonical_family}")
    normalized_subtype = subtype.strip().lower()
    adapter, supported = _ADAPTERS[canonical_family]
    if normalized_subtype not in supported:
        raise ValueError(f"unsupported-subtype: {subtype}")
    return replace(adapter, family=canonical_family, subtype=normalized_subtype)
