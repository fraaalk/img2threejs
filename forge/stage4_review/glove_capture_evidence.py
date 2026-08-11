"""Bridge browser-rendered glove captures into the closed v2 evidence manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from forge.stage2_spec.glove_assembly import canonical_hash, write_json_atomic
from forge.stage3_build.glove_artifacts import sha256_file, verify_model_bundle
from forge.stage4_review.render_bridge import init_manifest, read_manifest, write_manifest


GLOVE_CAMERAS = (
    ("dorsal", 0), ("palmar", 180), ("thumb-side-profile", 90),
    ("left-three-quarter", 35), ("right-three-quarter", -35),
    ("orbit-a", 120), ("orbit-b", -120),
)


def derive_profile_capture_plan(coverage_matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Derive acceptance cameras from anatomy/surface coverage owners, never a magic count."""
    if not coverage_matrix:
        raise ValueError("coverage matrix is required for a profile-driven capture plan")
    cameras: dict[str, list[str]] = {}
    for entry in coverage_matrix:
        if not isinstance(entry, dict) or entry.get("state") != "covered" or entry.get("visibility") in {"occluded", "hidden"}:
            raise ValueError(f"coverage owner is not observable: {entry.get('ownerId') if isinstance(entry, dict) else '<invalid>'}")
        owner, requested = entry.get("ownerId"), entry.get("renderCameras")
        if not isinstance(owner, str) or not isinstance(requested, list) or not requested:
            raise ValueError("coverage owner must declare render cameras")
        for camera in requested:
            if not isinstance(camera, str) or not camera:
                raise ValueError(f"coverage camera is invalid for {owner}")
            cameras.setdefault(camera, []).append(owner)
    # Orbits are structural probes, not substitutes for evidence owners.
    for role, _angle in GLOVE_CAMERAS:
        if role.startswith("orbit-"):
            cameras.setdefault(role, [])
    known_angles = {role: angle for role, angle in GLOVE_CAMERAS}
    return [
        {"id": f"capture-{camera}", "role": camera, "owners": sorted(owners),
         "azimuthDegrees": known_angles.get(camera, 0), "elevationDegrees": 8.0,
         "target": [0, 0, 0], "near": 0.01, "far": 100}
        for camera, owners in sorted(cameras.items())
    ]

_REQUIRED_RENDER_ENVIRONMENT = {
    "viewport": [1024, 1024], "devicePixelRatio": 1, "settleFrames": 2,
    "renderer": "WebGLRenderer", "threeRevision": "185", "antialias": False,
    "preserveDrawingBuffer": True, "clearColor": "#ffffff",
}


def _png_non_background_pixels(path: Path) -> int:
    """Independently inspect saved pixels; browser metadata is never evidence by itself."""
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        return sum(1 for red, green, blue, alpha in rgba.getdata() if alpha > 0 and (red < 248 or green < 248 or blue < 248))


def _verify_recorded_capture(capture: dict[str, Any], root: Path, bundle_digest: str) -> Path:
    """Validate evidence at the finalization boundary, not only in the bridge."""
    if capture.get("status") != "recorded" or capture.get("modelBundleDigest") != bundle_digest:
        raise ValueError(f"capture is not a recorded bundle-bound image: {capture.get('id')}")
    path = capture.get("path")
    if not isinstance(path, str) or Path(path).is_absolute() or ".." in Path(path).parts:
        raise ValueError(f"capture path is not portable: {capture.get('id')}")
    image_path = (root / path).resolve()
    if root not in image_path.parents or not image_path.is_file():
        raise ValueError(f"capture path is not a local image: {capture.get('id')}")
    if capture.get("readySignal") is not True or capture.get("consoleErrors"):
        raise ValueError(f"capture runtime evidence failed: {capture.get('id')}")
    image = capture.get("image")
    if not isinstance(image, dict) or image.get("width") != 1024 or image.get("height") != 1024:
        raise ValueError(f"capture has unexpected dimensions: {capture.get('id')}")
    screenshot_digest = capture.get("screenshotSha256")
    if not isinstance(screenshot_digest, str) or sha256_file(image_path) != screenshot_digest:
        raise ValueError(f"capture hash does not match image bytes: {capture.get('id')}")
    snapshot = capture.get("browserSnapshot")
    actual_pixels = _png_non_background_pixels(image_path)
    if (
        not isinstance(snapshot, dict)
        or not isinstance(snapshot.get("nonBackgroundPixels"), int)
        or snapshot["nonBackgroundPixels"] != actual_pixels
        or actual_pixels <= 0
        or not isinstance(snapshot.get("userAgent"), str)
        or not snapshot["userAgent"]
        or not isinstance(snapshot.get("renderEnvironment"), dict)
        or any(snapshot["renderEnvironment"].get(key) != value for key, value in _REQUIRED_RENDER_ENVIRONMENT.items())
    ):
        raise ValueError(f"capture has incomplete browser evidence: {capture.get('id')}")
    return image_path


def init_glove_capture_manifest(bundle_path: Path, reference: Path, runtime_url: str, output: Path, scene: dict[str, Any], *, capture_dir: str = "captures", coverage_matrix: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    bundle = verify_model_bundle(bundle_path)
    manifest = init_manifest(reference, runtime_url, output, (1024, 1024), 1.0, "captures")
    plan = derive_profile_capture_plan(coverage_matrix) if coverage_matrix is not None else [
        {"id": f"capture-{role}", "role": role, "azimuthDegrees": azimuth,
         "elevationDegrees": 8.0, "target": [0, 0, 0], "near": 0.01, "far": 100}
        for role, azimuth in GLOVE_CAMERAS
    ]
    manifest["captures"] = [
        {
            **camera, "path": f"{capture_dir}/{camera['role']}.png", "status": "pending", "passes": {},
            "modelBundleDigest": bundle["rootDigest"],
        }
        for camera in plan
    ]
    manifest["gloveEvidence"] = {"version": "capture-manifest.v2", "modelBundleDigest": bundle["rootDigest"], "sceneDigest": canonical_hash(scene), "coveragePlanDigest": canonical_hash(coverage_matrix) if coverage_matrix is not None else None}
    return manifest


def finalize_glove_capture_manifest(render_manifest_path: Path, repeat_render_manifest_path: Path, bundle_path: Path, scene: dict[str, Any], output: Path) -> dict[str, Any]:
    bundle = verify_model_bundle(bundle_path)
    manifest = read_manifest(render_manifest_path)
    repeated = read_manifest(repeat_render_manifest_path)
    captures = manifest.get("captures")
    repeated_captures = repeated.get("captures")
    expected_roles = {role for role, _azimuth in GLOVE_CAMERAS}
    if not isinstance(captures, list) or not isinstance(repeated_captures, list) or len(captures) != len(GLOVE_CAMERAS) or len(repeated_captures) != len(GLOVE_CAMERAS):
        raise ValueError("glove render manifest has incomplete camera coverage")
    records: list[dict[str, Any]] = []
    root = render_manifest_path.parent.resolve()
    repeat_by_role = {item.get("role"): item for item in repeated_captures if isinstance(item, dict)}
    if set(repeat_by_role) != expected_roles or {item.get("role") for item in captures if isinstance(item, dict)} != expected_roles:
        raise ValueError("glove render manifest has duplicate or missing required roles")
    for capture in captures:
        if not isinstance(capture, dict):
            raise ValueError(f"capture is not a recorded bundle-bound image: {capture.get('id') if isinstance(capture, dict) else '<invalid>'}")
        _verify_recorded_capture(capture, root, bundle["rootDigest"])
        snapshot = capture.get("browserSnapshot")
        repeated_capture = repeat_by_role[capture["role"]]
        _verify_recorded_capture(repeated_capture, root, bundle["rootDigest"])
        if repeated_capture.get("status") != "recorded" or repeated_capture.get("screenshotSha256") != capture.get("screenshotSha256"):
            raise ValueError(f"capture repeat is non-deterministic: {capture.get('id')}")
        if repeated_capture.get("browserSnapshot", {}).get("userAgent") != snapshot.get("userAgent") or repeated_capture.get("browserSnapshot", {}).get("renderEnvironment") != snapshot.get("renderEnvironment"):
            raise ValueError(f"capture environment changed between repeats: {capture.get('id')}")
        records.append({key: capture.get(key) for key in ("id", "role", "path", "screenshotSha256", "image", "readySignal", "consoleErrors", "browserSnapshot", "modelBundleDigest")})
        records[-1]["sha256"] = records[-1].pop("screenshotSha256")
    result = {
        "version": "capture-manifest.v2", "modelBundleDigest": bundle["rootDigest"],
        "sceneVersion": scene.get("version"), "sceneDigest": canonical_hash(scene),
        "renderEnvironment": {"runtime": manifest.get("runtime"), "browser": manifest.get("evidence", {}).get("browser"), "userAgent": records[0]["browserSnapshot"].get("userAgent"), "lock": records[0]["browserSnapshot"].get("renderEnvironment")}, "captures": records, "finalized": True, "repeatVerified": True,
    }
    scene_path = output.parent / "provenance" / "review-scene.json"
    write_json_atomic(scene_path, scene)
    result["sceneArtifact"] = {"path": scene_path.relative_to(output.parent).as_posix(), "sha256": canonical_hash(scene)}
    result["renderEnvironmentDigest"] = canonical_hash(result["renderEnvironment"])
    result["manifestDigest"] = canonical_hash(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--bundle", type=Path, required=True); init.add_argument("--reference", type=Path, required=True)
    init.add_argument("--runtime-url", required=True); init.add_argument("--scene", type=Path, required=True); init.add_argument("--out", type=Path, required=True); init.add_argument("--capture-dir", default="captures")
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--render-manifest", type=Path, required=True); finalize.add_argument("--repeat-render-manifest", type=Path, required=True); finalize.add_argument("--bundle", type=Path, required=True)
    finalize.add_argument("--scene", type=Path, required=True); finalize.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    scene = json.loads(args.scene.read_text(encoding="utf-8"))
    if args.command == "init":
        write_manifest(args.out, init_glove_capture_manifest(args.bundle, args.reference, args.runtime_url, args.out, scene, capture_dir=args.capture_dir))
        print(args.out)
    else:
        finalize_glove_capture_manifest(args.render_manifest, args.repeat_render_manifest, args.bundle, scene, args.out)
        print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
