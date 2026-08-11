"""Run the reproducible Sport Gloves golden or seeded-negative pipeline."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from forge.stage1_intake.cs2_manifest import build_classification_record, build_manifest
from forge.stage2_spec.glove_assembly import build_glove_assembly
from forge.stage2_spec.new_pre_spec_assessment import make_payload
from forge.stage2_spec.new_sculpt_spec import apply_cs2_manifest_evidence, apply_glove_template, make_spec
from forge.stage2_spec.validate_sculpt_spec import validate_spec
from forge.stage3_build.glove_generator_dispatch import build_glove_model_from_artifacts
from forge.stage4_review.glove_review import build_calibrated_scene
from forge.stage4_review.glove_capture_evidence import finalize_glove_capture_manifest, init_glove_capture_manifest
from forge.stage4_review.render_bridge import write_manifest
from scripts.capture_threejs_playwright import capture


FIXTURE = ROOT / "forge" / "tests" / "fixtures" / "glove_sport_v1"


def _references() -> list[tuple[Path, str]]:
    return [(FIXTURE / f"{name}.png", role) for name, role in (
        ("dorsal", "dorsal"),
        ("palmar", "palmar"),
        ("thumb-side-profile", "thumb-side-profile"),
        ("three-quarter", "three-quarter"),
    )]


def _write(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _build_inputs(out_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path, Path, Path]:
    refs = _references()
    manifest = build_manifest(refs[0][0], build_classification_record("glove", "sport-gloves", 0.99, ["fixture:glove-sport-v1"]), references=refs)
    assessment = make_payload(
        "Sport Gloves | Golden Fixture",
        manifest["sourceImage"],
        "ultra-complex",
        True,
        manifest,
        source_images=[view["path"] for view in manifest["sourceViews"]],
    )
    spec = make_spec("Sport Gloves | Golden Fixture", manifest["sourceImage"], assessment)
    apply_glove_template(spec, manifest=manifest)
    apply_cs2_manifest_evidence(spec, manifest)
    errors, warnings = validate_spec(spec)
    strict_quality = [warning for warning in warnings if warning.startswith("quality:")]
    if errors or strict_quality:
        raise ValueError("e2e spec validation failed: " + "; ".join(errors + strict_quality))
    manifest_path = _write(out_dir / "cs2-intake.v1.json", manifest)
    assessment_path = _write(out_dir / "pre-spec-assessment.v1.json", assessment)
    spec_path = _write(out_dir / "object-sculpt-spec.json", spec)
    assembly = build_glove_assembly("sport-gloves", [view["id"] for view in manifest["sourceViews"]])
    bundle_path, geometry_path, _upstream = build_glove_model_from_artifacts(manifest, assessment, spec, out_dir / "bundle", assembly=assembly)
    return manifest, assessment, spec, manifest_path, assessment_path, spec_path


def _run_runtime(bundle_path: Path, reference: Path, scene: dict[str, Any], out_dir: Path) -> Path:
    viewer = out_dir / "glove-review-runtime.html"
    subprocess.run(["node", str(ROOT / "runtime" / "glove-review" / "src" / "index.mjs"), "--viewer", str(bundle_path), str(viewer)], cwd=ROOT, check=True)
    server = subprocess.Popen(["node", str(ROOT / "runtime" / "glove-review" / "serve.mjs"), str(out_dir)], stdout=subprocess.PIPE, text=True)
    try:
        assert server.stdout is not None
        runtime_url = server.stdout.readline().strip()
        if not runtime_url.startswith("http://127.0.0.1:"):
            raise RuntimeError("glove runtime server did not expose localhost URL")
        bridge = out_dir / "glove-render-bridge.v2.json"
        write_manifest(bridge, init_glove_capture_manifest(bundle_path, reference, f"{runtime_url}/{viewer.name}", bridge, scene))
        captured = capture(bridge, [], False, 30000, "procedural")
        if captured["consoleErrors"]:
            raise RuntimeError("browser runtime produced console errors: " + "; ".join(captured["consoleErrors"]))
        repeated = out_dir / "glove-render-bridge-repeat.v2.json"
        write_manifest(repeated, init_glove_capture_manifest(bundle_path, reference, f"{runtime_url}/{viewer.name}", repeated, scene, capture_dir="captures-repeat"))
        repeated_capture = capture(repeated, [], False, 30000, "procedural")
        if repeated_capture["consoleErrors"]:
            raise RuntimeError("repeat browser runtime produced console errors: " + "; ".join(repeated_capture["consoleErrors"]))
        output = out_dir / "capture-manifest.v2.json"
        finalize_glove_capture_manifest(bridge, repeated, bundle_path, scene, output)
        return output
    finally:
        server.terminate()
        server.wait(timeout=10)
        if server.stdout is not None:
            server.stdout.close()


def _run_review(manifest_path: Path, metrics_path: Path, scene_path: Path, report_path: Path, expected_exit: int) -> dict[str, Any]:
    completed = subprocess.run(
        ["python3", str(ROOT / "forge" / "stage4_review" / "glove_review.py"), "--manifest", str(manifest_path), "--metrics", str(metrics_path), "--scene", str(scene_path), "--out", str(report_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != expected_exit:
        raise RuntimeError(f"review exit {completed.returncode}, expected {expected_exit}: {completed.stdout}\n{completed.stderr}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def run_golden(out_dir: Path) -> dict[str, Any]:
    manifest, _assessment, _spec, manifest_path, _assessment_path, _spec_path = _build_inputs(out_dir)
    bundle_path = out_dir / "bundle" / "glove-model-bundle.v2.json"
    geometry_path = out_dir / "bundle" / "geometry-report.v2.json"
    scene_path = out_dir / "glove-review-scene-v2.json"
    scene = build_calibrated_scene()
    _write(scene_path, scene)
    capture_path = _run_runtime(bundle_path, FIXTURE / "dorsal.png", scene, out_dir)
    artifacts = {
        "artifactRoot": str(out_dir), "modelBundlePath": "bundle/glove-model-bundle.v2.json",
        "geometryReport": "bundle/geometry-report.v2.json", "captureManifest": "capture-manifest.v2.json",
    }
    metrics_path = _write(out_dir / "artifact-locator.v2.json", artifacts)
    report = _run_review(manifest_path, metrics_path, scene_path, out_dir / "glove-review-report.v2.json", 1)
    if report.get("verdict") != "reject" or report.get("action") != "request-input":
        raise RuntimeError("synthetic fixture did not fail closed as diagnostic-only")
    return {"fixture": "diagnostic", "verdict": report["verdict"], "action": report["action"], "report": str(out_dir / "glove-review-report.v2.json"), "modelBundleDigest": report.get("modelBundleDigest")}


def run_seeded_negative(out_dir: Path) -> dict[str, Any]:
    manifest, _assessment, _spec, manifest_path, _assessment_path, _spec_path = _build_inputs(out_dir)
    bundle_path = out_dir / "bundle" / "glove-model-bundle.v2.json"
    geometry_path = out_dir / "bundle" / "geometry-report.v2.json"
    scene_path = out_dir / "glove-review-scene-v2.json"
    scene = build_calibrated_scene()
    _write(scene_path, scene)
    capture_path = _run_runtime(bundle_path, FIXTURE / "dorsal.png", scene, out_dir)
    reports: dict[str, Any] = {}
    for case in ("diagnostic-v1",):
        artifacts = {
            "artifactRoot": str(out_dir), "modelBundlePath": "bundle/glove-model-bundle.v2.json",
            "geometryReport": "bundle/geometry-report.v2.json", "captureManifest": "capture-manifest.v2.json",
        }
        metrics_path = _write(out_dir / f"negative-{case}-artifacts.json", artifacts)
        report_path = out_dir / f"negative-{case}-review.json"
        report = _run_review(manifest_path, metrics_path, scene_path, report_path, 1)
        if report.get("verdict") != "reject":
            raise RuntimeError(f"seeded fixture {case} unexpectedly passed")
        reports[case] = {"verdict": report["verdict"], "failedGates": report["failedGates"], "report": str(report_path)}
    return {"fixture": "seeded-negative", "cases": reports, "allRejected": all(item["verdict"] == "reject" for item in reports.values())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fixture", choices=("golden",))
    group.add_argument("--suite", choices=("seeded-negative",))
    parser.add_argument("--expect", choices=("ready", "reject"), required=True)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args(argv)
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        if args.fixture:
            result = run_golden(args.out_dir)
        else:
            result = run_seeded_negative(args.out_dir)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        passed = result.get("verdict") == args.expect if args.fixture else (args.expect == "reject" and result.get("allRejected") is True)
        return 0 if passed else 1
    with tempfile.TemporaryDirectory(prefix="img2-glove-e2e-") as directory:
        output = Path(directory)
        result = run_golden(output) if args.fixture else run_seeded_negative(output)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        passed = result.get("verdict") == args.expect if args.fixture else (args.expect == "reject" and result.get("allRejected") is True)
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
