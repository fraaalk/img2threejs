#!/usr/bin/env python3
"""Apply the versioned volumetric Sport Gloves layout to an existing ObjectSculptSpec."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forge.stage2_spec.new_sculpt_spec import apply_glove_pair_layout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.in_place == (args.out is not None):
        parser.error("provide exactly one of --in-place or --out")
    source = args.spec.resolve()
    target = source if args.in_place else args.out.resolve()
    spec = json.loads(source.read_text(encoding="utf-8"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(apply_glove_pair_layout(spec), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
