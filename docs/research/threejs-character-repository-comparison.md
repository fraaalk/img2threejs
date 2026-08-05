# Three.js character/model repositories → img2threejs 1.5

Status: distilled 2026-08-02 from NotebookLM research over VAST-AI-Research and selected
Three.js/VRM repositories.

`[D]` means documented, `[I]` means engineering inference, and `[U]` means unsupported.
A loader or viewer is not a generator; a generated artifact is not visual acceptance evidence.

## Comparison

| Repository | Class | Artifact and geometry | Rig/material/runtime | Dependencies | Rule for img2threejs |
| --- | --- | --- | --- | --- | --- |
| [CharacterGen](https://github.com/zjp-shadow/CharacterGen) | Neural generator + renderer | Single image → multi-view images and VRM/OBJ `[D]`; not procedural TS | Three.js/three-vrm browser rendering, pose/depth capture and UniRig handoff `[D]` | Python 3.9, weights, Node, FastAPI, Blender/VRM tooling `[D]` | Optional external generation adapter; retain the browser render boundary. |
| [CharacterStudio](https://github.com/M3-org/CharacterStudio) | Asset assembler/editor | Consumes VRM/models/textures and exports GLB/VRM `[D]`; external asset packs `[D]` | `CharacterManager`, programmable animation, atlas/skinned-mesh optimization `[D]` | Node, Three.js, WebGL and asset packs `[D]` | Explicit asset-pack input, named parts and atlas provenance. |
| [three.js](https://github.com/mrdoob/three.js) | Runtime + procedural geometry | Code creates scene, geometry, material and mesh `[D]`; no learned character generator `[D]` | Renderer, camera, scene graph and animation loop `[D]` | Pinned npm Three.js | Keep procedural factory in TypeScript; browser pixels are authoritative. |
| [three-vrm](https://github.com/pixiv/three-vrm) | VRM runtime plugin | Loads VRM through `GLTFLoader` + `VRMLoaderPlugin` `[D]`; no geometry generation `[D]` | VRM scene, MToon material and spring-bone/runtime features `[D]` | Three.js + VRM package | Use only at explicit VRM/GLB boundary. |
| [VRM specification](https://github.com/vrm-c/vrm-specification) | Format/specification | Humanoid GLTF/VRM metadata, not geometry generation `[D]` | Meter units, right-handed Y-up, -Z facing, T-pose and humanoid mapping `[D]` | None | Record coordinate/unit conversion in manifests. |
| [React Three Fiber](https://github.com/pmndrs/react-three-fiber) | Declarative runtime | React describes Three.js objects; no character generator `[D]` | Lifecycle/state wrapper around Three.js `[D]` | React + Three.js | Optional presentation layer; capture API stays framework-independent. |
| [drei](https://github.com/pmndrs/drei) | R3F helpers | Camera/control/loader helpers; no generator `[D]` | Convenience runtime primitives `[D]` | R3F + Three.js | Use only if camera/readiness remains deterministic. |
| [KalidoKit](https://github.com/yeemachine/kalidokit) | Pose/face/hand solver | Landmarks → Euler rotations, hip transforms and blendshapes `[D]`; no mesh generation `[D]` | Runtime kinematics and blink stabilization `[D]` | MediaPipe/TensorFlow.js | Animation follows mesh/rig creation; never infer geometry from it. |
| [three-gltf-viewer](https://github.com/donmccurdy/three-gltf-viewer) | Viewer | Loads/previews glTF; no generation `[D]` | Loading, camera and inspection patterns | Three.js + browser | Viewer/capture reference only. |
| [three-mesh-bvh](https://github.com/gkjohnson/three-mesh-bvh) | Geometry query | BVH for raycasting/spatial queries; no mesh generation `[D]` | Picking and inspection | Three.js | Optional attachment/coverage diagnostics. |
| [UniRig](https://github.com/VAST-AI-Research/UniRig) | Neural rigging | Mesh → skeleton hierarchy, local axes and skin weights `[D]`; not full character generation | Offline inference; browser uses serialized payload `[I]` | Python/PyTorch/CUDA/spconv/checkpoints `[D]` | Normalize, validate, then bind to Three.js. |
| [SkinTokens](https://github.com/VAST-AI-Research/SkinTokens) | Learned rig representation | Compact autoregressive rig/skinning representation `[D]`; checkpoint-dependent | Research representation, not browser runtime `[I]` | Python/ML/checkpoints | Distill joint/skin semantics; keep inference optional. |
| [AniGen](https://github.com/VAST-AI-Research/AniGen) | Animatable generation research | Unified shape/skeleton/skin representation `[D]`; export needs implementation/checkpoints | Not a Three.js runtime contract `[D]` | Research stack/checkpoints | Design reference for shape/rig consistency, not drop-in factory. |
| [SeqTex](https://github.com/VAST-AI-Research/SeqTex) | Texture generation | Video-diffusion-based 3D texture stage `[D]`; not geometry/rigging | Offline material adapter | Python/ML/checkpoints | Optional, provenance-tracked material input. |
| [HoloPart](https://github.com/VAST-AI-Research/HoloPart) | Amodal segmentation | Hidden/visible part structure `[D]`; no finished mesh `[D]` | Offline semantic evidence | Python/ML/checkpoints | Feed part evidence into sculpt spec and coverage gate. |
| [GeoSAM2](https://github.com/VAST-AI-Research/GeoSAM2) | 3D part segmentation | Geometric part labels `[D]`; no mesh/Three.js generator `[D]` | Offline label evidence | Python/ML/render setup | Use when manual boundaries are ambiguous. |
| [MIDI-3D](https://github.com/VAST-AI-Research/MIDI-3D) | Scene generation | Image → multiple 3D scene instances `[D]`; broader than one character | No humanoid rig contract `[D]` | Python/ML/checkpoints | Optional scene decomposition, not default character route. |
| [TripoSR](https://github.com/VAST-AI-Research/TripoSR) | Image-to-mesh | Image → static mesh/GLB `[D]`; no skeleton/animation `[D]` | GLTFLoader can consume output `[I]` | Python/PyTorch/CUDA/checkpoints `[D]` | Fast external bootstrap; never call it animation-ready. |
| [TripoSG](https://github.com/VAST-AI-Research/TripoSG) | High-fidelity shape generation | Image → GLB SDF/rectified-flow shape `[D]`; no rig `[D]` | External asset route | Python/PyTorch/CUDA/checkpoints `[D]` | Optional geometry bootstrap with separate rig/provenance. |
| [TripoSF](https://github.com/VAST-AI-Research/TripoSF) | Sparse mesh refinement | Point cloud/coarse shape → high-resolution mesh `[D]`; not image-to-rig `[D]` | External refinement | CUDA sparse stack/checkpoints `[D]` | Use only when documented input/checkpoint exists. |
| [TriplaneGaussian](https://github.com/VAST-AI-Research/TriplaneGaussian) | Neural splat representation | Image → Gaussian representation/orbit output `[D]`; not skinned mesh `[D]` | Specialized renderer | Python/ML/checkpoints | No `SkinnedMesh` route without explicit conversion/gates. |
| [tripo-3d-for-blender](https://github.com/VAST-AI-Research/tripo-3d-for-blender) | Blender integration | External Tripo workflow orchestration `[D]` | DCC/editor handoff | Blender + external assets | Explicit GLB/VRM handoff only. |
| [tripo-mcp](https://github.com/VAST-AI-Research/tripo-mcp) | Service/MCP integration | API orchestration, not local procedural geometry `[D]` | External service boundary | MCP/service access | MCP response is not visual evidence until browser capture passes. |
| [tripo-python-sdk](https://github.com/VAST-AI-Research/tripo-python-sdk) | API client | Service request/response artifacts `[D]`; no local Three.js generation `[D]` | External controller | Python + service access | Store request, license and hashes in adapter manifest. |
| [ComfyUI-Tripo](https://github.com/VAST-AI-Research/ComfyUI-Tripo) | Workflow integration | ComfyUI nodes for external generation `[D]` | Workflow/UI integration | ComfyUI + service | Optional orchestration, not deterministic core. |

## Dependency graph

```text
reference images → admission/hashes/camera/landmarks/parts
  → character spec + quality contract
  → optional multi-view/part/texture adapters
  → procedural TS geometry OR explicit GLB/VRM artifact
  → rig payload + skeleton/skin validation
  → Three.js scene/SkinnedMesh/material/camera
  → ready/capture contract → fixed/orbit screenshots
  → side-by-side + semantic/per-feature review + diagnostics
  → one bounded correction action
```

## Zenonia recommendation

The standard code-only route uses beta's intake/spec/build/review gates, alpha's Python render
manifest and UniRig-shaped payload validator, and pinned plain Three.js. The character factory
needs unified face volume, stylized hair clumps, explicit outfit parts, named anchors and a
`THREE.Skeleton`; generated GLB/VRM is not the final factory.

The optional external route uses CharacterGen or TripoSG/TripoSR for mesh/VRM bootstrap, UniRig
for skeleton/skin, and three-vrm/GLTFLoader for browser rendering. It may produce a stronger
first model, but it must carry checkpoint, license, coordinate conversion, input hash and output
hash and must not be reported as procedural code.

## Evidence boundary

Generation proves only that an artifact was emitted. A rig validator proves only payload
structure. A build proves only compilation. Visual acceptance requires fresh readable browser
screenshots, side-by-side evidence, semantic/per-feature review and deterministic diagnostics.
