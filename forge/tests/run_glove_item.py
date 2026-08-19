"""Run a REAL glove item end to end: plates in, review report out.

`run_glove_e2e.py` is bound to the synthetic fixture -- its references are a module constant -- so nothing in
this repository ran a real CS2 item through the pipeline, and the first attempt to do so exposed three
defects at once: the only documented observation example did not load, the manifest's recorded plate paths
were already dead on the machine that wrote them, and no command existed to try again with different plates.
This is that command.

    python3 forge/tests/run_glove_item.py \
        --composite listing.png --roles dorsal palmar \
        --subtype hydra-gloves --observation observation.json \
        --out-dir .img2threejs/hydra-fn-v1

    python3 forge/tests/run_glove_item.py \
        --reference dorsal.png:dorsal --reference palmar.png:palmar \
        --subtype sport-gloves --observation observation.json --out-dir <dir>

A composite is split first, because feeding one path twice yields one pHash, sets `duplicateOfHash`, and is
refused. `--no-runtime` stops after the bundle for a geometry-only look, which is the fast loop; the browser
capture and the review are the slow part.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from forge.stage1_intake.cs2_manifest import build_classification_record, build_manifest
from forge.stage1_intake.glove_observation import apply_glove_observation
from forge.stage1_intake.split_composite_plate import split_composite
from forge.stage2_spec.glove_assembly import build_glove_assembly
from forge.stage2_spec.new_pre_spec_assessment import make_payload
from forge.stage2_spec.new_sculpt_spec import apply_cs2_manifest_evidence, apply_glove_template, make_spec
from forge.stage2_spec.validate_sculpt_spec import validate_spec
from forge.stage3_build.glove_generator_dispatch import build_glove_model_from_artifacts
from forge.stage4_review.glove_review import build_uncalibrated_scene
from forge.tests.run_glove_e2e import _run_review, _run_runtime, _write


def _references(args: argparse.Namespace, out_dir: Path) -> list[tuple[Path, str]]:
    if args.composite:
        records = split_composite(args.composite, out_dir / "plates", list(args.roles))
        _write(out_dir / "split-provenance.json", {"version": "composite-split-v1", "plates": records})
        return [(Path(record["path"]), record["role"]) for record in records]
    pairs: list[tuple[Path, str]] = []
    for item in args.reference:
        raw, _, role = item.rpartition(":")
        if not raw or not role:
            raise ValueError(f"--reference must be PATH:ROLE, got {item!r}")
        pairs.append((Path(raw).expanduser().resolve(), role))
    return pairs


def run(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = args.out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    references = _references(args, out_dir)
    missing = [str(path) for path, _role in references if not path.is_file()]
    if missing:
        raise ValueError("unreadable reference images:\n  " + "\n  ".join(missing))

    manifest = build_manifest(
        references[0][0],
        build_classification_record("glove", args.subtype, 0.99, [f"item:{args.subtype}"]),
        references=references,
        hands=[args.hand] if args.hand else None,
    )
    if args.observation:
        manifest = apply_glove_observation(manifest, json.loads(args.observation.read_text(encoding="utf-8")))
    manifest_path = _write(out_dir / "cs2-intake.v1.json", manifest)
    if manifest.get("state") != "proceed":
        return {"item": args.subtype, "state": manifest["state"], "reason": manifest.get("unsupportedReason"),
                "manifest": str(manifest_path), "stoppedAt": "intake"}

    assessment = make_payload(
        args.title or args.subtype, manifest["sourceImage"], "ultra-complex", True, manifest,
        source_images=[view["path"] for view in manifest["sourceViews"]],
    )
    spec = make_spec(args.title or args.subtype, manifest["sourceImage"], assessment)
    apply_glove_template(spec, subtype=args.subtype, manifest=manifest)
    apply_cs2_manifest_evidence(spec, manifest)
    errors, warnings = validate_spec(spec)
    if errors:
        raise ValueError("spec validation failed: " + "; ".join(errors))
    _write(out_dir / "pre-spec-assessment.v1.json", assessment)
    _write(out_dir / "object-sculpt-spec.json", spec)

    profile = manifest.get("extensions", {}).get("glove", {}).get("formProfile", {})
    kind = profile.get("kind") if isinstance(profile, dict) else None
    assembly = build_glove_assembly(
        args.subtype, [view["id"] for view in manifest["sourceViews"]],
        form_profile=kind if kind in {"full-finger", "fingerless", "mitten"} else "full-finger",
    )
    bundle_path, geometry_path, _upstream = build_glove_model_from_artifacts(
        manifest, assessment, spec, out_dir / "bundle", assembly=assembly
    )
    result: dict[str, Any] = {
        "item": args.subtype, "specWarnings": len(warnings),
        "formProfile": kind, "bundle": str(bundle_path), "geometryReport": str(geometry_path),
    }
    if args.no_runtime:
        return {**result, "stoppedAt": "bundle"}

    scene = build_uncalibrated_scene(args.subtype)
    scene_path = _write(out_dir / "glove-review-scene-v2.json", scene)
    _run_runtime(bundle_path, references[0][0], scene, out_dir)
    metrics_path = _write(out_dir / "artifact-locator.v2.json", {
        "artifactRoot": str(out_dir), "modelBundlePath": "bundle/glove-model-bundle.v2.json",
        "geometryReport": "bundle/geometry-report.v2.json", "captureManifest": "capture-manifest.v2.json",
    })
    report = _run_review(manifest_path, metrics_path, scene_path, out_dir / "glove-review-report.v3.json", 1)
    return {
        **result, "stoppedAt": "review", "verdict": report.get("verdict"), "action": report.get("action"),
        "evidenceTier": report.get("evidenceTier"), "failedGates": report.get("failedGates"),
        "report": str(out_dir / "glove-review-report.v3.json"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--composite", type=Path, help="one image carrying several views, to be split")
    source.add_argument("--reference", action="append", default=[], metavar="PATH:ROLE")
    parser.add_argument("--roles", nargs="+", default=["dorsal", "palmar"], help="roles for --composite, in reading order")
    parser.add_argument("--subtype", required=True)
    parser.add_argument("--hand", choices=("left", "right"), help="declare a SINGLE-hand item; omit for a pair")
    parser.add_argument("--title")
    parser.add_argument("--observation", type=Path, help="observation to merge; without it evidenceUse is unset and readiness fails")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--no-runtime", action="store_true", help="stop after the bundle; skips the browser capture")
    args = parser.parse_args(argv)
    print(json.dumps(run(args), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
