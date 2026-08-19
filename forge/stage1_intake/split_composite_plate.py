"""Split one marketplace composite into per-role plates, recording what was cropped.

A CS2 item usually ships one plate per view. A marketplace listing does not: it ships one image with
several views stacked, a caption band naming the item, and a tiled watermark. That image cannot be fed to
`build_manifest` as-is for two independent reasons:

- the same path submitted twice yields the same pHash, which sets `duplicateOfHash` and makes
  `_paired_glove_plate_override` refuse outright (`cs2_manifest.py:118-132`);
- the caption band and the watermark are foreground to the admission mask, so they are measured as if they
  were part of the item.

So the split is explicit and its result is recorded. Every emitted plate carries the rectangle it came from,
because an unrecorded pixel edit is exactly the defect that let a whole-frame mask be scored as a subject.
The one pixel change it makes is stated in the record: everything outside the chosen region's own
connected component becomes neutral white. That covers the backdrop, the caption band, and any watermark
tile that does not touch the subject.

**What it cannot reach, stated rather than left to be discovered in a render:** a watermark tile that
OVERLAPS the subject is connected to it, so it survives into the plate and is then projected onto the
model by the surface bake. Removing it would mean inventing the pixels underneath, which is a different
thing from choosing a rectangle and is not done here. A listing whose watermark crosses the item leaves
its marks on the texture; judge form on an untextured render, as `SKILL.md` already requires.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from forge.stage1_intake.extract_pbr_evidence import (
    color_distance,
    load_image,
    sample_corner_background,
    write_png_rgb,
)

# A caption band is wide, short, and sits across the image. These are the two properties that separate it
# from a glove, and both are needed: a glove seen edge-on is also short, and a wide component is not
# automatically text.
BAND_MAX_HEIGHT_FRACTION = 0.12
BAND_MIN_WIDTH_FRACTION = 0.55
# Watermark tiles and compression speckle survive the mask as small islands.
MIN_AREA_FRACTION_OF_LARGEST = 0.08
# The bbox is grown by this much of the shorter side so a crop does not shave the silhouette it found.
CROP_MARGIN_FRACTION = 0.02


# Distance from the sampled backdrop, and NOT `build_foreground_mask`. That mask also admits any pixel
# that is merely saturated and not bright, which is correct for material evidence on a neutral plate and
# wrong here: a marketplace backdrop is saturated navy, so its watermark tiles differ from it by a colour
# distance of ~19 and are admitted, and the resulting lattice joins every subject in the image into one
# component. Splitting asks a narrower question -- where is the subject against THIS backdrop -- and the
# distance alone answers it.
SUBJECT_MIN_DISTANCE = 30.0
# What the backdrop becomes in the emitted plate. Neutral and bright, because that is what the admission
# check and every downstream mask expect to segment against.
NEUTRAL_BACKDROP = (255, 255, 255)


def _subject_mask(width: int, height: int, pixels: list[tuple[int, int, int, int]]) -> tuple[list[bool], dict[str, Any]]:
    background, noise = sample_corner_background(width, height, pixels)
    threshold = max(SUBJECT_MIN_DISTANCE, noise * 3.0)
    mask = [pixel[3] > 16 and color_distance(pixel[:3], background) > threshold for pixel in pixels]
    return mask, {
        "backgroundColor": background,
        "backgroundNoise": round(noise, 3),
        "subjectThreshold": round(threshold, 3),
        "subjectFraction": round(sum(1 for value in mask if value) / max(1, len(mask)), 4),
    }


def _components(mask: list[bool], width: int, height: int, stride: int) -> tuple[list[dict[str, int]], list[int], int]:
    """Label connected foreground on a strided grid, and report full-resolution bounding boxes.

    Strided because a marketplace image is millions of pixels and the component shapes we care about are
    hundreds of pixels across; the grid only has to resolve "are these two blobs joined".
    """
    gw, gh = max(1, width // stride), max(1, height // stride)
    grid = [mask[min(height - 1, y * stride) * width + min(width - 1, x * stride)] for y in range(gh) for x in range(gw)]
    seen = [False] * (gw * gh)
    # Which component each cell belongs to, so the crop can keep the region's own pixels and drop anything
    # that merely shares its bounding box. -1 is background.
    labels = [-1] * (gw * gh)
    found: list[dict[str, int]] = []
    for start in range(gw * gh):
        if not grid[start] or seen[start]:
            continue
        seen[start] = True
        labels[start] = len(found)
        queue = deque([start])
        xs, ys, area = [], [], 0
        while queue:
            index = queue.popleft()
            gx, gy = index % gw, index // gw
            xs.append(gx)
            ys.append(gy)
            area += 1
            for nx, ny in ((gx - 1, gy), (gx + 1, gy), (gx, gy - 1), (gx, gy + 1)):
                if 0 <= nx < gw and 0 <= ny < gh:
                    neighbour = ny * gw + nx
                    if grid[neighbour] and not seen[neighbour]:
                        seen[neighbour] = True
                        labels[neighbour] = len(found)
                        queue.append(neighbour)
        found.append({
            "label": len(found),
            "x0": min(xs) * stride, "y0": min(ys) * stride,
            "x1": min(width, (max(xs) + 1) * stride), "y1": min(height, (max(ys) + 1) * stride),
            "area": area * stride * stride,
        })
    return found, labels, gw


def find_view_regions(path: Path, expected: int, *, stride: int = 4) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    width, height, pixels, _warnings = load_image(path)
    mask, meta = _subject_mask(width, height, pixels)
    blobs, labels, grid_width = _components(mask, width, height, stride)
    if not blobs:
        raise ValueError(f"{path.name}: no foreground found to split")
    largest = max(blob["area"] for blob in blobs)
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for blob in blobs:
        blob_w, blob_h = blob["x1"] - blob["x0"], blob["y1"] - blob["y0"]
        reason = None
        if blob["area"] < largest * MIN_AREA_FRACTION_OF_LARGEST:
            reason = "speckle or watermark tile"
        elif blob_h <= height * BAND_MAX_HEIGHT_FRACTION and blob_w >= width * BAND_MIN_WIDTH_FRACTION:
            reason = "caption band"
        (rejected if reason else kept).append({**blob, "rejectedAs": reason})
    if len(kept) != expected:
        raise ValueError(
            f"{path.name}: found {len(kept)} view regions, expected {expected} "
            f"(rejected {len(rejected)} as caption band or watermark)"
        )
    kept.sort(key=lambda blob: (blob["y0"], blob["x0"]))
    return kept, {**meta, "width": width, "height": height, "rejected": rejected}


def split_composite(source: Path, out_dir: Path, roles: list[str], *, stride: int = 4) -> list[dict[str, Any]]:
    """Write one PNG per role and return a provenance record per plate."""
    source = source.expanduser().resolve()
    regions, meta = find_view_regions(source, len(roles), stride=stride)
    width, height, pixels, _warnings = load_image(source)
    mask, _meta = _subject_mask(width, height, pixels)
    _blobs, labels, grid_width = _components(mask, width, height, stride)
    margin = int(min(width, height) * CROP_MARGIN_FRACTION)
    out_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for role, region in zip(roles, regions):
        x0 = max(0, region["x0"] - margin)
        y0 = max(0, region["y0"] - margin)
        x1 = min(width, region["x1"] + margin)
        y1 = min(height, region["y1"] + margin)
        crop_w, crop_h = x1 - x0, y1 - y0
        # Everything that is not this region's own connected component becomes neutral white, and this is
        # the one pixel change the splitter makes.
        # It is necessary and it is DECLARED. `check_reference_admission` segments a subject by colour
        # distance from the corner background, and a marketplace backdrop is saturated navy: every one of
        # its pixels is "not bright and somewhat saturated", which `build_foreground_mask` admits, so a crop
        # keeping the backdrop reports `foregroundCoverage 1.000` and is refused as not isolable. Measured
        # on the fixture crop: exactly that, on both plates.
        #
        # Subject pixels are untouched, the rule is a threshold on distance from the sampled backdrop, and
        # the record below carries the backdrop colour, the threshold and the resulting digest, so the
        # transformation is reproducible from the provenance alone. An undeclared edit here would be the
        # same defect as scoring a whole-frame mask as a subject.
        rgb = bytearray()
        for y in range(y0, y1):
            row = y * width
            for x in range(x0, x1):
                cell = min(len(labels) - 1, (y // stride) * grid_width + min(grid_width - 1, x // stride))
                if mask[row + x] and labels[cell] == region["label"]:
                    red, green, blue, _alpha = pixels[row + x]
                else:
                    red, green, blue = NEUTRAL_BACKDROP
                rgb += bytes((red, green, blue))
        target = out_dir / f"{role}.png"
        write_png_rgb(target, crop_w, crop_h, bytes(rgb))
        records.append({
            "role": role,
            "path": target.as_posix(),
            "sourceImage": source.as_posix(),
            "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "cropRect": {"x": x0, "y": y0, "width": crop_w, "height": crop_h},
            "cropSha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "backdropReplaced": {
                "from": meta.get("backgroundColor"),
                "to": list(NEUTRAL_BACKDROP),
                "rule": "pixels within subjectThreshold colour distance of the sampled backdrop",
                "subjectThreshold": meta.get("subjectThreshold"),
            },
        })
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--roles", nargs="+", required=True, help="roles in top-to-bottom, left-to-right order")
    parser.add_argument("--provenance", type=Path, help="where to write the crop provenance record")
    args = parser.parse_args(argv)
    records = split_composite(args.image, args.out_dir, list(args.roles))
    payload = {"version": "composite-split-v1", "plates": records}
    if args.provenance:
        args.provenance.parent.mkdir(parents=True, exist_ok=True)
        args.provenance.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
