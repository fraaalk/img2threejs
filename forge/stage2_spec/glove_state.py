"""Explicit state/action boundaries for the staged Sport Gloves workflow."""

from __future__ import annotations

from typing import Any


STATE_ACTIONS = {
    "rejected": "stop",
    "unsupported-family": "stop",
    "unsupported-subtype": "stop",
    "request-input": "request-input",
    "proceed": "build",
    "refine-spec": "refine-spec",
    "refine-code": "refine-code",
    "ready": "ready",
    "stop": "stop",
}


def state_action(state: str) -> str:
    return STATE_ACTIONS.get(state, "stop")


def can_emit_spec(manifest: dict[str, Any]) -> bool:
    return manifest.get("state") == "proceed"


def can_emit_build(manifest: dict[str, Any], assessment: dict[str, Any] | None = None) -> bool:
    return can_emit_spec(manifest) and not (isinstance(assessment, dict) and assessment.get("intakeOnly") is True)


def intake_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    state = str(manifest.get("state", "rejected"))
    return {
        "state": state,
        "action": state_action(state),
        "intakeOnly": state == "request-input",
        "canEmitSpec": can_emit_spec(manifest),
        "canEmitBuild": can_emit_build(manifest),
        "retryable": state in {"request-input", "refine-spec", "refine-code"},
    }
