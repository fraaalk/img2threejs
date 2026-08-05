# GLB-mediated v2 render-fidelity distillation

Date: 2026-08-03  
NotebookLM notebook: `f0fc65fa-10ce-42a2-a4e5-5a7d04ffa2a1`  
Research task: `c9dd830c-0eb4-431a-a7e9-05a7c37bab63`

This is an implementation distillation, not a claim that a reference GLB contains
semantic labels that are absent from its scene graph. Claims are marked so later
agents do not silently promote a hypothesis to observed evidence.

## Source table

| Source | Authority | Claims used |
| --- | --- | --- |
| [Three.js WebGLRenderer](https://threejs.org/docs/#api/en/renderers/WebGLRenderer) | Three.js official API | renderer output color space, tone mapping/exposure, viewport/DPR, render-target pixel readback |
| [Three.js MeshPhysicalMaterial](https://threejs.org/docs/#api/en/materials/MeshPhysicalMaterial) | Three.js official API | PBR extensions including clearcoat, sheen, transmission and related maps |
| [Three.js GLTFLoader](https://threejs.org/docs/#examples/en/loaders/GLTFLoader) | Three.js official API | glTF scene loading and material/texture integration boundary |
| [Three.js PMREMGenerator](https://threejs.org/docs/#api/en/extras/PMREMGenerator) | Three.js official API | prefiltered environment maps and GGX-compatible image-based lighting |
| [Three.js BufferGeometry](https://threejs.org/docs/#api/en/core/BufferGeometry) | Three.js official API | indexed attributes, normals and runtime geometry representation |
| [Three.js ExtrudeGeometry](https://threejs.org/docs/#api/en/geometries/ExtrudeGeometry) | Three.js official API | proposed profile/section extrusion building block |
| [Three.js CatmullRomCurve3](https://threejs.org/docs/#api/en/extras/curves/CatmullRomCurve3) | Three.js official API | proposed path-driven tail/staff/ribbon building block |
| [Khronos glTF 2.0 specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html) | Khronos normative specification | scene/node/mesh/primitive/material boundaries, PBR texture color encoding, skins/animations |
| [Blender BMesh API](https://docs.blender.org/api/current/bmesh.html) | Blender official API | optional offline adjacency/editing evidence adapter; not browser pixel authority |
| [Blender Mesh API](https://docs.blender.org/api/current/bpy.types.Mesh.html) | Blender official API | optional mesh attribute/UV inspection adapter |

NotebookLM also surfaced forums, blogs and secondary examples. Those were excluded
from normative API claims. The implementation below uses only the official sources
in the table for renderer/glTF behavior; region segmentation and scoring are explicitly
marked `PROPOSED`.

## 1. Shared render parity profile

**OBSERVED/NORMATIVE:** Three.js has explicit renderer fields for `outputColorSpace`,
`toneMapping`, `toneMappingExposure`, viewport size and pixel ratio. glTF's base-color
texture is an sRGB color input; metallic-roughness data is linear and conventionally
stores roughness in G and metalness in B. These values must be identical for the GLB
reference route and the procedural route.

**PROPOSED:** Use [render-profile.v2.example.json](../specs/render-profile.v2.example.json)
as the shared contract. The validator requires the following values to be recorded,
not inferred from defaults:

- `colorManagementEnabled: true`, working space `Linear-sRGB`, output `SRGBColorSpace`;
- explicit tone mapping and exposure;
- viewport, DPR, antialias and background;
- camera projection, transform, target, near/far and focal settings;
- PMREM environment source and intensity;
- six pass definitions and fixed region IDs;
- ordered feedback groups, one group per correction loop.

`NoToneMapping` remains useful for diagnostic buffers; it is not an acceptable substitute
for a declared beauty profile. HDR/EXR values and data maps must not be judged using the
same display-space metric as beauty PNGs.

## 2. Semantic decomposition decision

```text
named nodes/meshes with stable boundaries?
  yes -> preserve names as evidence, then validate with browser ID-mask
  no
multiple primitives/materials/UV texture boundaries?
  yes -> treat as partial boundaries; never invent labels; validate ID-mask
  no
one merged node + mesh + primitive + material?
  -> metadata is insufficient for reliable head/scarf/kasa/staff labels
  -> connected-component/curvature/normal/UV analysis may produce hypotheses only
  -> request multipart GLB or make a browser multiview ID-mask before factory work
```

**OBSERVED/NORMATIVE:** glTF represents scenes through nodes; meshes contain primitives;
primitives bind vertex attributes and a material. These are real boundaries when present.

**INFERRED:** A one-node/one-mesh/one-primitive/one-material asset may still have geometric
connectivity or shading discontinuities, but the glTF metadata cannot identify those as
`face`, `kasa`, `scarf`, or `staff`.

**PROPOSED:** `probe_glb.py` now emits `semanticDecomposition`. For the current merged
Mouse Warrior export it must report `insufficient` and `multipart-glb-required`. A
connected-component or curvature region-growing result may be attached as a hypothesis,
never as a reliable semantic map. A browser-rendered semantic ID pass is the admissible
runtime evidence when a multipart export is unavailable.

## 3. Continuous geometry strategy matrix

| Region | Strategy | Status / gate |
| --- | --- | --- |
| body/head/muzzle | indexed ring sections or lofted custom `BufferGeometry`; merge continuous organic volumes; preserve controlled edge planes | PROPOSED; validate silhouette and normal pass |
| face features | surface-conforming regions/attached landmark forms; avoid arbitrary floating primitives | PROPOSED; face close-up is required |
| scarf/tunic/bandage | layered shell or extruded cloth profiles with explicit folds and thickness | PROPOSED; semantic ID and self-intersection gate |
| kasa | radial section/cone shell plus ribs/weave detail as real geometry or controlled material relief | PROPOSED; rear/profile captures required |
| staff | tapered section loft or curve-driven tube with placed grip/socket | PROPOSED; attachment and silhouette gate |
| tail/ribbon | `CatmullRomCurve3` path with section radius/taper and separate ribbon module when evidence conflicts | PROPOSED; profile/rear and deformation gates |
| implicit/SDF/marching cubes | optional offline blockout/repair when primitives cannot produce a manifold form; do not hide resolution artifacts | PROPOSED; not a default browser dependency |

Three.js `BufferGeometry` is the runtime representation. Manifoldness, bevels and
curvature continuity are reconstruction decisions, not properties that GLTFLoader can
recover from a merged asset.

## 4. Region material strategy

**OBSERVED/NORMATIVE:** `MeshPhysicalMaterial` exposes PBR and extension controls such as
clearcoat, sheen, transmission and anisotropy. The exact numbers for a supplied lit image
are not normative; color/roughness/normal/AO/metalness map color-space declarations are.

| Region | Base/response starting point | Evidence limitation |
| --- | --- | --- |
| skin | non-metal, controlled roughness, optional transmission/SSS-like treatment, cavity only where observed | lit pixels do not uniquely solve PBR parameters |
| cloth/scarf/tunic | high roughness, sheen where supported, fold normal/bump, low specular edge | needs unlit/de-lit crop or neutral material pass |
| straw/kasa | high roughness, directional weave/rib relief, restrained specular | back/underside can be hidden |
| wood/staff | rough dielectric, longitudinal grain/normal, localized wear | lighting can mimic grain |
| leather/eyepatch | semi-matte dielectric, seam/cavity and edge response | patch color can be tone-mapped |
| emissive eye | explicit emissive pass and controlled bloom; compare pre-bloom ID/color separately | display RGB is tone-mapped |

**PROPOSED:** If exact material likeness is required, allow a separately approved de-lit
projection/baked texture route. Under the code-only rule, report material confidence as
limited rather than claiming that a roughness number came from a beauty image.

## 5. Six-pass capture and scoring contract

Every view in the manifest has paired GLB-baseline and procedural records for:

1. `beauty` — display-space visual comparison;
2. `alpha-silhouette` — foreground occupancy/IoU;
3. `semantic-id` — flat, non-tone-mapped region IDs;
4. `depth` — linearized depth comparison;
5. `normal` — view/object-space normal comparison;
6. `roughness-material-id` — scalar/material-region diagnostic.

**PROPOSED:** `compare_region_passes.py` calculates global metrics and per-region metrics
using the reference semantic-ID pass as the region mask. Without a readable semantic-ID
pass and declared region colors, it returns `regionEvidence: unavailable` and blocks any
per-region confidence claim. It is intentionally not an AI likeness score.

The accepted loop is:

```text
camera -> capture all passes -> compare -> fix one group
silhouette -> capture all passes -> compare -> fix one group
face -> capture all passes -> compare -> fix one group
clothing -> capture all passes -> compare -> fix one group
accessory -> capture all passes -> compare -> fix one group
materials -> capture all passes -> compare -> fix one group
lighting -> capture all passes -> compare -> stop or request input
```

## False-confidence blockers

- comparing a procedural PNG to an unrendered GLB;
- changing camera, DPR, exposure, tone mapping or HDRI between baseline and render;
- using beauty/sRGB pixels to score depth, normals or roughness;
- using the whole foreground as a proxy for every semantic part;
- assigning semantic labels to a merged mesh from geometry hypotheses alone;
- allowing missing/transparent/black passes to count as perfect matches;
- letting multiple feedback groups change in one iteration;
- accepting generated code, GLB loading, `__READY__`, or typecheck as visual evidence;
- counting a failed or stale screenshot as a fresh capture.

## Implemented v2 artifacts

- `docs/specs/render-profile.v2.schema.json` — machine-readable profile shape;
- `docs/specs/render-profile.v2.example.json` — default shared profile with regions and ID colors;
- `forge/stage4_review/validate_render_profile.py` — strict dependency-free validator;
- `forge/stage1_intake/semantic_decomposition.py` — conservative GLB semantic readiness classifier;
- `forge/stage4_review/multi_pass.py` — six-pass manifest records and readback/hash gate;
- `forge/stage4_review/compare_region_passes.py` — deterministic global/per-region pass comparison;
- `forge/stage4_review/render_bridge.py` — optional v2 profile initialization and `record-pass` command;
- `forge/stage1_intake/probe_glb.py` — emits semantic decomposition and warns on merged boundaries.
