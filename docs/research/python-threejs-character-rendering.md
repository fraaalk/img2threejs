# Python-assisted Three.js character rendering — research distillation

Status: distilled 2026-08-02
Scope: Python orchestration/evidence around a browser-rendered Three.js character.
Non-goal: replacing the code-only procedural Three.js factory with a downloaded mesh,
photogrammetry result, or a Blender render that is never verified in the target browser.

## Executive conclusion

The reusable pattern across the strongest repositories is a split pipeline:

```text
reference + parameters
        |
        v
Python manifest / job controller / deterministic diagnostics
        |
        v
Three.js runtime in a real browser
        |
        v
fixed + orbit + diagnostic renders
        |
        v
Python image checks + side-by-side packaging + agent vision
```

Python should own reproducibility, file manifests, camera batches, hashes, masks,
diagnostic reports, and optional service endpoints. Three.js should remain the source of
truth for the character hierarchy, geometry, materials, animation clock, camera, and final
browser pixels. A Python process cannot prove that a Three.js character is correct merely by
serializing parameters or by rendering an unrelated Blender scene.

## Repository findings

| Repository | What it actually contributes | Adopt in img2threejs | Do not adopt blindly |
|---|---|---|---|
| [CharacterGen](https://github.com/zjp-shadow/CharacterGen) | A Python-driven character-generation project with a separate Three.js/three-vrm render script, a FastAPI backend, and browser-side rendering. Its README describes VRM input, multi-view pose canonicalization, depth-map rendering, and a frontend/backend split. | A render-job manifest, explicit frontend/backend boundary, numbered multi-view outputs, and a character-specific camera batch. | Its neural/VRM/asset pipeline is not the code-only procedural factory contract. Do not copy generated topology or treat its depth renderer as likeness proof. |
| [pythreejs](https://github.com/jupyter-widgets/pythreejs) | A Python/Three.js bridge implemented as Jupyter widgets. Python can construct and update a browser-side scene interactively. | A notebook parameter-tuning surface for inspecting hair, camera, proportions, and material parameters before committing them to TypeScript. | It is stateful notebook UI, not a deterministic headless acceptance renderer; it should not replace the showcase capture gate. |
| [Playwright](https://github.com/microsoft/playwright) | Browser automation with navigation, evaluate, screenshots, tracing, and cross-browser execution. The project documents both an MCP server and a library API. | A fallback capture adapter when Chrome DevTools MCP is unavailable or cross-browser reproducibility is explicitly required. | Do not install a second browser stack by default; the project contract prefers the existing Chrome MCP and keeps Python core dependency-free. |
| [BlenderProc](https://github.com/DLR-RM/BlenderProc) | Python-controlled Blender scene construction and batch rendering of RGB, depth, normals, and semantic segmentation from multiple camera poses. | A reference-evidence adapter for synthetic data, neutral/depth/normal passes, or asset preprocessing when explicitly requested. | Blender output is not automatically the target Three.js output. It must not bypass browser capture or silently turn the project into an asset-import workflow. |
| [Khronos glTF Blender converter](https://github.com/KhronosGroup/glTF-Tutorials/tree/main/BlenderGltfConverter) | Headless Blender Python automation that imports/edits a scene and exports glTF/GLB. | A documented optional handoff boundary for external assets, with explicit provenance and a browser-side GLTFLoader smoke test. | glTF export is transport, not proof of visual fidelity. It is disallowed as a silent replacement for procedural code in the default route. |
| [three-vrm](https://github.com/pixiv/three-vrm) | A Three.js runtime loader/plugin for VRM, with animation and material integration in the browser. | A reference for character runtime contracts: load completion, animation update, material plugin selection, and camera framing. | VRM-specific semantics must not leak into a plain procedural `THREE.Group` factory unless the user explicitly requests VRM. |
| [three.js glTF example](https://github.com/mrdoob/three.js/blob/dev/examples/webgl_loader_gltf.html) | The canonical browser-side pattern for `GLTFLoader`, environment, tone mapping, animation, and fit-to-selection camera setup. | Camera fit, renderer setup, explicit load readiness, and animation settling concepts. | The example loads remote sample assets; img2threejs must preserve local/reference provenance and avoid remote asset substitution. |

## Distilled skills

### 1. Python render-manifest skill

Every capture batch should have a JSON manifest rather than a directory of ambiguous PNGs.
The minimum record is:

```json
{
  "schemaVersion": 1,
  "runtime": {
    "url": "http://127.0.0.1:5175/...",
    "route": "character-demo",
    "viewport": [620, 1000],
    "devicePixelRatio": 1,
    "renderer": "WebGLRenderer",
    "threeVersion": "project-pinned"
  },
  "reference": {"path": "reference.jpg", "sha256": "..."},
  "captures": [
    {"id": "hero", "azimuth": 0, "elevation": 0, "path": "hero.png"},
    {"id": "orbit-plus35", "azimuth": 35, "elevation": 0, "path": "orbit-plus35.png"},
    {"id": "orbit-minus35", "azimuth": -35, "elevation": 0, "path": "orbit-minus35.png"},
    {"id": "profile", "azimuth": 78, "elevation": 0, "path": "profile.png"},
    {"id": "rear", "azimuth": 180, "elevation": 0, "path": "rear.png"}
  ],
  "evidence": {"readySignal": "window.__IMG2THREEJS_READY__", "diagnostics": []}
}
```

The manifest records camera transforms, target, near/far planes, exposure, tone mapping,
background, browser identity, source hash, output hash, and the exact diagnostic command.
The PNG filename is never the only provenance record.

### 2. Browser-first render skill

The capture adapter must render the actual Three.js app:

1. select an isolated browser context and the named showcase route;
2. wait for `window.__IMG2THREEJS_READY__` and the expected viewer keys;
3. assert there are no fatal console errors and the canvas has non-zero dimensions;
4. set the camera and controls through the runtime capture contract;
5. set `near`/`far` to contain the selected subject, update the projection matrix, and wait
   for at least two settled frames;
6. capture the canvas/viewport to a named file;
7. reopen the saved file with an image-capable reader and reject background-only output.

This explicitly covers the failure mode where a head close-up renders only the background
because the old camera near plane clips the subject, and the failure mode where a stale page
or stale screenshot is mistaken for a new render.

### 3. Character camera-batch skill

For a character, one image is not a render protocol. The default batch is:

- fixed reference-matched hero;
- `+35°` and `-35°` three-quarter views;
- right profile (`~78°`) and rear (`180°`);
- head hero and head three-quarter close-ups;
- optional neutral-light, grazing-light, silhouette, depth, and normal passes.

Only the fixed view is compared to the supplied reference angle. Orbit views are checked for
attachment, volume, rear hair, silhouette continuity, and non-degenerate form. Do not compare an
unknown rear reference against a made-up camera angle as if it were a pixel-aligned reference.

### 4. Python diagnostics skill

Python scripts remain deterministic and do not pretend to be an art critic:

- validate image existence, dimensions, decodability, and source/render hashes;
- produce masks, silhouette area, scale/proportion, symmetry, edge, tonal and colour signals;
- run `diagnose_render.py` before a comparison-sheet review;
- run `diagnose_render_multi_angle.py` to catch billboard/flat-plane collapse;
- produce side-by-side sheets with `make_comparison_sheet.py`;
- let agent vision judge identity features and record exactly one next action.

The existing `img2threejs` rule remains authoritative: deterministic gates can block or route a
pass, but they cannot grant likeness from a global score when hair, eyes, pose, or a weapon fail.

### 5. Optional Python service boundary

If rendering is batch-driven, a small FastAPI service may accept a job manifest and return paths
to completed captures, following CharacterGen's frontend/backend split. The service must be:

- local-only by default;
- explicit about input/output paths;
- idempotent by job id and source hash;
- bounded by a timeout and finite camera list;
- unable to mutate source TypeScript or silently download assets;
- required to return `ready`, `capture`, `diagnostic`, and `error` records.

This is an optional orchestration layer, not a new model-generation route.

### 6. glTF/VRM handoff skill

When the user explicitly provides or requests a GLB/VRM asset, use glTF as a transport boundary:

```text
Python/Blender preprocessing (optional)
        -> GLB/VRM + manifest + provenance
        -> Three.js GLTFLoader/VRMLoaderPlugin
        -> browser runtime smoke + fixed/orbit captures
```

Record coordinate system, unit scale, texture colour space, animation clips, material plugin,
and hidden-region confidence. Never copy the imported mesh topology into a code-only factory and
never call an imported asset “reference matched” before browser evidence passes.

### 7. GLB-mediated reference variant

The explicit prototype variant is:

```text
image (optional) -> GLB -> stdlib probe + provenance -> Three.js GLB baseline captures
-> procedural TypeScript factory -> same camera batch -> baseline/procedural diagnostics
```

This is a controlled reference-mesh route, not a conversion of GLB into procedural code. The
baseline must be captured by the same browser renderer because an unrendered GLB has no comparable
pixels. The manifest therefore stores `reference.kind: "glb"` and a separate baseline record per
camera. Without the original image, the resulting score is agreement with the intermediate GLB,
not evidence that the original image-to-GLB generation was accurate.

## Adoption policy for img2threejs

Adopt now:

- camera-batch manifests and source/output hashes;
- explicit readiness and settle-frame checks;
- Python-side deterministic diagnostics before vision review;
- optional Playwright fallback only when already installed or explicitly approved;
- optional notebook parameter inspection based on pythreejs, without making it an acceptance gate;
- explicit GLB/VRM provenance when an external asset route is requested.

Do not adopt as the default route:

- neural CharacterGen inference or downloaded weights;
- Blender/VRM output in place of the procedural TypeScript factory;
- remote sample assets from Three.js examples;
- a Python-only “render” claim when no browser Three.js screenshot exists;
- global pixel scores as a substitute for per-feature character review.

## Source and license notes

The repositories above were reviewed from their public project documentation and repository
pages on 2026-08-02. CharacterGen is Apache-2.0, pythreejs is BSD-3-Clause, three-vrm is MIT,
Playwright is Apache-2.0, BlenderProc is BSD-3-Clause, and the Khronos tutorial is Apache-2.0.
This document distills workflow ideas and does not copy source code into img2threejs.
