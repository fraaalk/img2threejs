from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from forge.stage1_intake.extract_pbr_evidence import write_png_rgb


ROOT = Path(__file__).resolve().parent
SIZE = 256
VIEWS = (
    ("dorsal", 0, 0),
    ("palmar", 7, 3),
    ("thumb-side-profile", 14, 6),
    ("three-quarter", 21, 9),
)


def render_view(dx: int, dy: int) -> bytes:
    rgb = bytearray(SIZE * SIZE * 3)
    for y in range(SIZE):
        for x in range(SIZE):
            index = (y * SIZE + x) * 3
            # light neutral background keeps the deterministic admission mask isolated
            rgb[index:index + 3] = bytes((242, 242, 242))
            px = x - 128 - dx
            py = y - 132 - dy
            palm = (px / 44) ** 2 + (py / 55) ** 2 <= 1
            cuff = -70 <= py <= -42 and abs(px) <= 45
            fingers = any(
                ((px - finger_x) / 12) ** 2 + ((py + finger_length) / 33) ** 2 <= 1
                for finger_x, finger_length in ((-31, 76), (-11, 91), (10, 98), (30, 83))
            )
            thumb = ((px + 48) / 22) ** 2 + ((py + 7) / 34) ** 2 <= 1
            if palm or cuff or fingers or thumb:
                shade = 42 + max(0, min(28, int((128 - py) / 7)))
                rgb[index:index + 3] = bytes((shade, shade + 3, shade + 5))
    return bytes(rgb)


REPO_ROOT = Path(__file__).resolve().parents[4]


def build_observation(manifest: dict) -> dict:
    """Emit an observation that MERGES, generated from the manifest so its hashes cannot drift.

    The documentation used to cite `.img2threejs/hedge-maze-bs-v1/glove-observation.json` as the worked
    example. That path is gitignored, so a fresh checkout had no example at all -- and the local copy did
    not load: `glove_observation.py` reads `sourceViewId` and `sourceHash` at the top level of every
    `surfaceRegionEvidence` entry, and that file nested `sourceViewId` under `projectionTransform` and had
    no `sourceHash`. Nothing loaded it, so nothing caught it. This one is generated and test-loaded.
    """
    views = {view["role"]: view for view in manifest["sourceViews"]}
    target = [role for role in ("dorsal", "palmar")]
    digits = ("thumb", "index", "middle", "ring", "pinky")
    return {
        "schemaVersion": 1,
        "target": "Sport Gloves | Golden Fixture",
        "purpose": "Generated with the fixture plates so every sourceHash matches by construction.",
        "formProfile": {
            "kind": "full-finger",
            "classificationState": "observed",
            "digitTopology": [
                {"id": digit, "opening": "closed-tip", "path": "curved", "evidenceRefs": [views["dorsal"]["id"], views["palmar"]["id"]]}
                for digit in digits
            ],
            "openingPolicy": {"allowedBoundaryKinds": ["cuff"]},
        },
        "coverageMatrix": [
            {
                "ownerId": f"region-{role}", "sourceViewId": views[role]["id"], "sourceHash": str(views[role]["hash"]),
                "cropDigest": f"fixture-crop-{role}", "visibility": "visible", "state": "covered",
                "renderCameras": [role],
            }
            for role in target
        ],
        "surfaceRegionEvidence": [
            {
                "id": f"{role}-shell", "sourceViewId": views[role]["id"], "sourceHash": str(views[role]["hash"]),
                "sourceCropDigest": f"fixture-crop-{role}", "comparisonMaskDigest": f"fixture-mask-{role}",
                "orientation": role, "projectionTransform": {"kind": "uv"},
                "channels": {"baseColor": {"source": f"{role}.png", "colorSpace": "sRGB"}},
            }
            for role in target
        ],
        "evidence": [{
            "id": "fixture-observation",
            "sourceRefs": [views[role]["id"] for role in target],
            "region": "shell-and-hand-anatomy",
            "visibility": "multi-view",
            "epistemicState": "observed",
            "confidence": 0.9,
            "contradictions": [],
        }],
        "sourceUse": {
            views[role]["id"]: ("target-geometry-and-surface" if role in target else "technical-geometry-only")
            for role in views
        },
    }


def main() -> None:
    records = []
    for role, dx, dy in VIEWS:
        path = ROOT / f"{role}.png"
        write_png_rgb(path, SIZE, SIZE, render_view(dx, dy))
        # Repository-relative: an absolute path is true on one machine and false everywhere else, which is
        # the same defect the CS2 intake carries and CLAUDE.md forbids.
        records.append({"role": role, "path": path.relative_to(REPO_ROOT).as_posix(), "generated": True})
    (ROOT / "metadata.json").write_text(json.dumps({"version": 1, "license": "MIT", "views": records}, indent=2) + "\n", encoding="utf-8")

    from forge.stage1_intake.cs2_manifest import build_classification_record, build_manifest

    references = [(ROOT / f"{role}.png", role) for role, _dx, _dy in VIEWS]
    manifest = build_manifest(
        references[0][0],
        build_classification_record("glove", "sport-gloves", 0.99, ["fixture:glove-sport-v1"]),
        references=references,
    )
    (ROOT / "observation.json").write_text(json.dumps(build_observation(manifest), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
