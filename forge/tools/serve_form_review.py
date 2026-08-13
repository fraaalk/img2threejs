#!/usr/bin/env python3
"""Serve the glove form in a browser so a human can turn it and say what is wrong.

Why this exists. Every form defect in this track was found by a person looking at the shape, and missed
by the numbers: a texture mounted upside down, a thumb fused into the palm, and a pair whose thumbs faced
outward all passed their gates. The still renders that caught two of those took a code change each to
re-aim, so the loop was minutes long and only covered the angles I thought to ask for.

What it shows is the runtime's own mesh, not a preview of it: the page imports `runtime/glove-review/src/
sdf.mjs`, the same polygonizer the shipped factory uses, and feeds it the same descriptor stage 3 emits.
Untextured by default and deliberately -- a plate projected onto a wrong form paints the missing parts
back on, which is exactly how the fused thumb stayed hidden. The texture is a toggle, off first.

    python3 forge/tools/serve_form_review.py <dorsal-plate> [--port 8765]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from forge._shared.glove_armature import DEFAULT_RESOLUTION, build_glove_sdf_descriptor  # noqa: E402
from forge._shared.glove_silhouette import HAND_SEPARATION, measure_silhouette  # noqa: E402
from forge.stage3_build.glove_armature_shell import measure_digit_protrusion  # noqa: E402

RUNTIME = ROOT / "runtime" / "glove-review"
PAGE = ROOT / ".img2threejs" / "form-review"
# Copied rather than imported across directories, so the served tree is self-contained and the static
# server needs no route into node_modules.
VENDOR = {
    "three.module.js": RUNTIME / "node_modules" / "three" / "build" / "three.module.js",
    "three.core.js": RUNTIME / "node_modules" / "three" / "build" / "three.core.js",
    "sdf.mjs": RUNTIME / "src" / "sdf.mjs",
}

VIEWER = """
import * as THREE from './three.module.js';
import { polygonizeSdfAttributes } from './sdf.mjs';

const report = await (await fetch('./form.json')).json();
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x101014);
const camera = new THREE.PerspectiveCamera(38, innerWidth / innerHeight, 0.01, 40);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(devicePixelRatio);
renderer.setSize(innerWidth, innerHeight);
document.body.append(renderer.domElement);
scene.add(new THREE.HemisphereLight(0xffffff, 0x404048, 1.5));
const key = new THREE.DirectionalLight(0xffffff, 1.5);
key.position.set(-1.4, 1.8, 3.2);
scene.add(key);

const material = new THREE.MeshStandardMaterial({ color: 0xe8e4dd, roughness: 0.62, metalness: 0.0 });
const wire = new THREE.MeshBasicMaterial({ color: 0x66d9c0, wireframe: true });
const group = new THREE.Group();
for (const [hand, entry] of Object.entries(report.hands)) {
  const { positions, triangles } = polygonizeSdfAttributes(THREE, entry.descriptor);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(positions), 3));
  geometry.setIndex(triangles.flat());
  geometry.computeVertexNormals();
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.x = hand === 'right' ? report.handSeparation : -report.handSeparation;
  group.add(mesh);
}
scene.add(group);

// Turned by dragging, so no addon is needed and the page stays two files.
let azimuth = 0; let elevation = 0.08; let distance = 3.1; let dragging = false; let last = [0, 0];
renderer.domElement.addEventListener('pointerdown', (event) => { dragging = true; last = [event.clientX, event.clientY]; });
addEventListener('pointerup', () => { dragging = false; });
addEventListener('pointermove', (event) => {
  if (!dragging) return;
  azimuth -= (event.clientX - last[0]) * 0.008;
  elevation = Math.max(-1.5, Math.min(1.5, elevation + (event.clientY - last[1]) * 0.008));
  last = [event.clientX, event.clientY];
});
renderer.domElement.addEventListener('wheel', (event) => {
  event.preventDefault();
  distance = Math.max(1.1, Math.min(9, distance * (1 + event.deltaY * 0.001)));
}, { passive: false });
addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});
addEventListener('keydown', (event) => {
  const views = { '1': [0, 0.08, 'dorsal'], '2': [Math.PI, 0.08, 'palmar'], '3': [Math.PI / 2, 0.08, 'thumb side'], '4': [-0.6, 0.5, 'three-quarter'] };
  if (views[event.key]) { [azimuth, elevation] = views[event.key]; }
  if (event.key === 'w') { group.traverse((node) => { if (node.isMesh) node.material = node.material === material ? wire : material; }); }
});

const label = document.querySelector('#readout');
label.textContent = report.readout;

function frame() {
  camera.position.set(
    Math.sin(azimuth) * Math.cos(elevation) * distance,
    Math.sin(elevation) * distance,
    Math.cos(azimuth) * Math.cos(elevation) * distance,
  );
  camera.lookAt(0, 0, 0);
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}
frame();
"""

INDEX = """<!doctype html>
<meta charset="utf-8">
<title>glove form review</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; overflow: hidden; background: #101014; font: 13px/1.5 ui-monospace, monospace; color: #cfcbc4; }
  #readout { position: fixed; top: 0; left: 0; padding: 10px 14px; white-space: pre; pointer-events: none;
             background: linear-gradient(#101014e0, #10101400); }
  #keys { position: fixed; bottom: 0; left: 0; padding: 10px 14px; color: #7d7a74; pointer-events: none; }
</style>
<div id="readout"></div>
<div id="keys">drag to turn &middot; wheel to zoom &middot; 1 dorsal &middot; 2 palmar &middot; 3 thumb side &middot; 4 three-quarter &middot; w wireframe</div>
<script type="module" src="./viewer.mjs"></script>
"""


def build_page(plate: Path, resolution: int) -> dict[str, object]:
    _mask, measured = measure_silhouette(plate)
    hands: dict[str, object] = {}
    lines = [f"plate  {plate.name}", f"aspect {measured['aspect']}  thumb side {measured['thumbSide']}  root {measured['thumbRootFraction']}"]
    for hand in ("left", "right"):
        descriptor = build_glove_sdf_descriptor(measured, hand=hand, source_view_id=plate.name, resolution=resolution)["sdf"]
        protrusion = measure_digit_protrusion(descriptor)
        hands[hand] = {"descriptor": descriptor, "digitProtrusion": protrusion}
        clear = ", ".join(f"{part.removesuffix('-digit')} {value:.2f}" for part, value in sorted(protrusion["protrudingFraction"].items()))
        lines.append(f"{hand:<6} digits {protrusion['value']:.0f}/{protrusion['required']:.0f}   {clear}")
    return {"hands": hands, "handSeparation": HAND_SEPARATION, "readout": "\n".join(lines), "measured": measured}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plate", type=Path, help="the admitted dorsal plate to measure")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--resolution", type=int, default=DEFAULT_RESOLUTION)
    arguments = parser.parse_args()
    if not arguments.plate.is_file():
        parser.error(f"{arguments.plate} is not a readable file")
    missing = [name for name, source in VENDOR.items() if not source.is_file()]
    if missing:
        parser.error(f"missing runtime files {missing}; run `npm install` in {RUNTIME}")

    PAGE.mkdir(parents=True, exist_ok=True)
    report = build_page(arguments.plate, arguments.resolution)
    (PAGE / "form.json").write_text(json.dumps(report), encoding="utf-8")
    (PAGE / "index.html").write_text(INDEX, encoding="utf-8")
    (PAGE / "viewer.mjs").write_text(VIEWER.lstrip(), encoding="utf-8")
    for name, source in VENDOR.items():
        shutil.copyfile(source, PAGE / name)
    print(report["readout"])
    print(f"serving {PAGE}")
    return subprocess.call(["node", str(RUNTIME / "serve.mjs"), str(PAGE), str(arguments.port)])


if __name__ == "__main__":
    raise SystemExit(main())
