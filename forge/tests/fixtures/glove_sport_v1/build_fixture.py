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


def main() -> None:
    records = []
    for role, dx, dy in VIEWS:
        path = ROOT / f"{role}.png"
        write_png_rgb(path, SIZE, SIZE, render_view(dx, dy))
        records.append({"role": role, "path": str(path), "generated": True})
    (ROOT / "metadata.json").write_text(json.dumps({"version": 1, "license": "MIT", "views": records}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
