"""Build a marketplace-composite fixture: ONE half-finger glove, two views, a caption band, a watermark.

Structurally identical to the listing image the acceptance case uses -- a single left glove photographed
dorsal and palmar, stacked vertically on a dark ground, with a caption band between them and a tiled
watermark over the whole thing. Synthetic, so the repository still carries no game art and the fixture
license claim in `../glove_sport_v1/LICENSE.md` stays true.

What it is FOR is the split and the half-finger form, not resemblance: the digits stop short and are open
at the tip, there are four of them plus a thumb, and there is exactly one hand.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from forge.stage1_intake.extract_pbr_evidence import write_png_rgb

ROOT = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[4]
WIDTH, HEIGHT = 368, 896
BAND_TOP, BAND_HEIGHT = 432, 40
BACKGROUND = (26, 27, 46)
# Four fingers plus a thumb. `cut` is the fraction of full length the digit is cut off at, which is what
# makes this fixture half-finger rather than full-finger.
DIGITS = ((-45, 108, 12), (-16, 128, 13), (13, 122, 12), (40, 100, 11))
CUT = 0.52


KNUCKLE_Y = -58.0


def _glove(px: float, py: float, palmar: bool) -> bool:
    """Membership for one glove in local pixel space; origin at the palm centre, +y downward."""
    if (px / 62) ** 2 + (py / 78) ** 2 <= 1:
        return True
    # Cuff, below the palm.
    if 74 <= py <= 104 and abs(px) <= 64:
        return True
    thumb_x = 66 if palmar else -66
    if ((px - thumb_x) / 26) ** 2 + ((py - 4) / 42) ** 2 <= 1:
        return True
    for finger_x, length, radius in DIGITS:
        # Cut off at CUT of full length: a half-finger glove ends flat, above the knuckle line.
        tip_y = KNUCKLE_Y - length * CUT
        if abs(px - finger_x) <= radius and tip_y <= py <= KNUCKLE_Y + 26:
            return True
    return False


def render() -> bytes:
    rgb = bytearray()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            red, green, blue = BACKGROUND
            # Caption band: a wide, short, near-background bar. The splitter must reject it by shape, so it
            # has to be genuinely wide and genuinely short, exactly like the real listing's.
            if BAND_TOP <= y < BAND_TOP + BAND_HEIGHT and 8 <= x < WIDTH - 8:
                # A SOLID bar, as the real listing's caption is. Drawn faintly it was rejected as speckle
                # by area before the wide-and-short shape rule ever ran, which left that rule -- the one
                # that has to hold when a caption is somewhere other than the middle -- unexercised.
                red, green, blue = (60, 64, 92)
                if (x // 7 + y // 9) % 3 == 0 and BAND_TOP + 12 <= y < BAND_TOP + 28:
                    red, green, blue = (208, 214, 226)
            else:
                # Tiled watermark. Bright enough to survive the subject mask, because a watermark that the
                # mask already filters out never reaches the area rule and leaves it untested -- and a real
                # listing's watermark is plainly visible. Small islands, so area is what rejects them.
                if (x // 46 + y // 58) % 2 == 0 and (x % 46) < 12 and (y % 58) < 10:
                    red, green, blue = (56, 58, 80)
                centre_y = 216 if y < BAND_TOP else 664
                px, py = x - WIDTH / 2, y - centre_y
                if _glove(px, py, palmar=y >= BAND_TOP):
                    shade = 150 + int(38 * (1.0 - min(1.0, abs(py) / 150)))
                    red, green, blue = (shade, shade - 6, max(0, shade - 26))
            rgb += bytes((red, green, blue))
    return bytes(rgb)


def build_observation(manifest: dict) -> dict:
    views = {view["role"]: view for view in manifest["sourceViews"]}
    target = ["dorsal", "palmar"]
    refs = [views[role]["id"] for role in target]
    fingers = ("index", "middle", "ring", "pinky")
    return {
        "schemaVersion": 1,
        "target": "Hydra Gloves | Case Hardened (Factory New)",
        "purpose": "Half-finger, single left hand, split from one marketplace composite.",
        "formProfile": {
            "kind": "fingerless",
            "classificationState": "observed",
            "digitTopology": (
                [{"id": digit, "opening": "open-cut", "path": "curved", "evidenceRefs": refs} for digit in fingers]
                + [{"id": "thumb", "opening": "open-cut", "path": "curved", "evidenceRefs": refs}]
            ),
            "openingPolicy": {"allowedBoundaryKinds": ["cuff", "open-cut"]},
        },
        "hands": ["left"],
        "coverageMatrix": [
            {
                "ownerId": f"region-{role}", "sourceViewId": views[role]["id"], "sourceHash": str(views[role]["hash"]),
                "cropDigest": f"hydra-crop-{role}", "visibility": "visible", "state": "covered",
                "renderCameras": [role],
            }
            for role in target
        ],
        "surfaceRegionEvidence": [
            {
                "id": f"{role}-shell", "sourceViewId": views[role]["id"], "sourceHash": str(views[role]["hash"]),
                "sourceCropDigest": f"hydra-crop-{role}", "comparisonMaskDigest": f"hydra-mask-{role}",
                "orientation": role, "projectionTransform": {"kind": "uv"},
                "channels": {"baseColor": {"source": f"{role}.png", "colorSpace": "sRGB"}},
            }
            for role in target
        ],
        "evidence": [{
            "id": "hydra-observation", "sourceRefs": refs, "region": "shell-and-hand-anatomy",
            "visibility": "multi-view", "epistemicState": "observed", "confidence": 0.85, "contradictions": [],
        }],
        "sourceUse": {views[role]["id"]: "target-geometry-and-surface" for role in views},
    }


def main() -> None:
    composite = ROOT / "composite.png"
    write_png_rgb(composite, WIDTH, HEIGHT, render())

    from forge.stage1_intake.split_composite_plate import split_composite

    plates = split_composite(composite, ROOT / "plates", ["dorsal", "palmar"])
    (ROOT / "split-provenance.json").write_text(
        json.dumps({"version": "composite-split-v1", "plates": [
            {**plate,
             "path": Path(plate["path"]).relative_to(REPO_ROOT).as_posix(),
             "sourceImage": Path(plate["sourceImage"]).relative_to(REPO_ROOT).as_posix()}
            for plate in plates
        ]}, indent=2) + "\n", encoding="utf-8")

    from forge.stage1_intake.cs2_manifest import build_classification_record, build_manifest

    references = [(ROOT / "plates" / f"{role}.png", role) for role in ("dorsal", "palmar")]
    manifest = build_manifest(
        references[0][0],
        build_classification_record("glove", "hydra-gloves", 0.99, ["fixture:glove-hydra-v1"]),
        references=references,
    )
    (ROOT / "observation.json").write_text(json.dumps(build_observation(manifest), indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"composite": composite.relative_to(REPO_ROOT).as_posix(),
                      "plates": [Path(p["path"]).relative_to(REPO_ROOT).as_posix() for p in plates]}, indent=2))


if __name__ == "__main__":
    main()
