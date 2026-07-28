## Context

The completed subtype sheets describe components, but not how two broadside images become one handed, five-digit object. Hedge Maze exposes the failure: broadside `front`/`back` labels, a centre crop, and independent projections can silently drop the inward thumb or put palmar pixels on a dorsal shell.

This change owns the glove-specific extension to the existing schema-v2 generic intake. `pipeline-geometry-lockdown` remains the authority for the frozen runtime asset; this change makes its glove input, bake handoff, and review evidence deterministic.

## Goals / Non-Goals

**Goals**

- Admit and associate a dorsal/palmar pair for one physical glove before any crop, BM25/spec search, or projection.
- Preserve hand, view, crop, evidence, and texture ownership from manifest through sculpt spec, bake, preview, and review.
- Make a full-finger crop prove four finger stalls and a thumb; missing or occluded required evidence requests new input.
- Derive a homologous pair without negative-scale runtime rendering, duplicated texture uploads, or idle render loops.

**Non-Goals**

- Infer exact sidewall profile, lining, cavity, thickness, Valve maps, float, or pattern seed from the two supplied images.
- Treat Hand Wraps, Hydra, Broken Fang, or another non-full-finger topology as a five-stall glove.
- Validate animated deformation in this change. “Articulated” here means an anatomically separated static topology; an animation change must add pose/deformation fixtures.
- Replace geometry-lockdown or permit runtime primitive construction in a locked-down asset.

## Normative data contract

### Version and compatibility

Glove multi-view manifests SHALL be `schemaVersion: 3` and contain `gloveMultiView.version: "glove-multiview-v1"`. Schema v1/v2 remains readable as generic intake only. A v1/v2 manifest with a full-finger glove candidate SHALL return `request-input` with `GLOVE_MULTIVIEW_REQUIRED`; `primary` and `secondary` SHALL never be guessed as anatomical roles. A v3 reader rejects an unknown multi-view version, duplicate `viewId`, mixed `physicalObjectId`, or an incomplete required field. A v2 runtime rejects v3 with `UNSUPPORTED_MANIFEST_VERSION`; rollback selects the preserved v2 generic reader and produces `request-input`, never a broadside glove build.

### Accepted input topology

The input is either (a) two registered views of one physical glove, or (b) a composite that is first split into one registered object per hand and per view. Every view has `physicalObjectId`, `pairId`, `hand`, `poseId`, and `viewId`. A dorsal/palmar pair used for projection has the same `physicalObjectId` and `poseId`; different pose, duplicate image, unknown hand, or unpaired asymmetric object returns `request-input`. The first release accepts a canonical left physical glove plus its derived right counterpart; independently photographed non-mirrored left/right gloves are out of scope and return `GLOVE_ASYMMETRIC_PAIR_UNSUPPORTED`.

```json
{
  "schemaVersion": 3,
  "gloveMultiView": {
    "version": "glove-multiview-v1",
    "topologyKind": "full-finger",
    "canonicalHand": "left",
    "canonicalFrame": { "origin": "wrist-centre", "x": "thumb-side", "y": "wrist-to-tips", "z": "dorsal" },
    "views": [{
      "viewId": "left-dorsal-01", "physicalObjectId": "left-01", "pairId": "pair-01",
      "hand": "left", "role": "dorsal", "poseId": "open-flat-01",
      "image": { "path": "...", "contentHash": "...", "width": 2048, "height": 1365 },
      "crop": { "space": "normalized-image-v1", "x": 0.02, "y": 0.01, "width": 0.46, "height": 0.96 },
      "cameraToLocal": { "position": [0, 0, 1], "forward": [0, 0, -1], "up": [0, 1, 0] },
      "digits": { "thumb": "observed", "index": "observed", "middle": "observed", "ring": "observed", "little": "observed" }
    }],
    "regions": [], "textureAssignments": []
  }
}
```

Crop values are finite normalized image coordinates in `[0,1]`; their rectangle must remain in bounds. `role` is exactly `dorsal|palmar`; `hand` is exactly `left|right`; authoritative fields reject `front|back|primary|secondary`.

### Coordinate, camera, and reflection invariant

The canonical left mesh is wrist-centred: `+Y` wrist-to-tips, `+Z` dorsal, `-Z` palmar, and the dorsal thumb-side landmark is `+X`. Fixed dorsal capture is an unrotated mesh viewed from `(+Z → origin)`; fixed palmar capture is the same unrotated mesh viewed from `(-Z → origin)`, both with `up=+Y`. A local-Y rotation may exist only as named `inspectionTransform`; it is prohibited in source registration, UV projection, and fixed acceptance captures. The corresponding canonical palmar thumbnail is screen-reflected relative to the dorsal capture because the camera moves, not because the object changes hand.

The derived right is `M = diag(-1,1,1,1)` at authoring time. Release assets MUST bake that reflection into a separate positive-determinant GLTF: reverse winding, recompute normals and tangents (including tangent handedness), preserve named region IDs and one immutable UV set. Runtime negative scale and runtime UV generation are prohibited. Fixture assertions check left dorsal thumb `+X`, right dorsal thumb `-X`, `det(M)=-1` before bake, and positive determinant/correct culling after bake; a `R_y(PI)` test is separately required and must not satisfy reflection.

### Coverage, evidence, and ownership

For `topologyKind: full-finger`, `digits` contains `thumb|index|middle|ring|little`, each `observed|occluded|out_of_frame`. Only `observed` is admissible; `occluded` or `out_of_frame` returns `GLOVE_REQUIRED_DIGIT_NOT_OBSERVED`. Each observed digit's landmark box must be inside the crop with at least 2 source pixels or 0.25% of that image dimension, whichever is larger. The cuff must likewise be observed. `fingerless` and `wrap` bypass this validator and require their profile-specific edge evidence.

The exhaustive region vocabulary is `dorsal-shell`, `palmar-panel`, `thumb-dorsal`, `thumb-palmar`, `index`, `middle`, `ring`, `little`, `finger-gussets`, `thumb-saddle`, `cuff`, `sidewalls`, `lining`, `cavity`, and `thickness`. Every region record has `regionId`, `evidenceState: observed|inferred|untextured`, `sourceViewIds`, `confidence` in `[0,1]`, `reason`, and, when not observed, `inferenceMethod`. Hidden regions cannot be marked observed.

Each texture assignment names `regionId`, `materialSlot`, `uvIsland`, `sourceViewId|null`, `projectionMask`, `overlapPriority`, and channel mappings. `baseColor` is sRGB; `normal`, `roughness`, `metalness`, and `alpha` are linear. Dorsal source owns only dorsal regions and palmar source only palmar regions. Sidewalls/gussets cannot borrow a broadside projection unless their mask is directly evidenced; otherwise they are `untextured` or `inferred`. Overlap priority is `explicit region mask > same-role source > untextured/inferred`; a conflict fails `GLOVE_TEXTURE_OWNERSHIP_CONFLICT`.

## Review and runtime contract

`glove-review-scene-v1` uses the existing versioned review-scene record plus fixed 1600×1000 captures: `left-dorsal`, `left-palmar`, `right-dorsal`, `right-palmar` at the cameras above, and `left-orbit-35`, `right-orbit-35` with yaw ±35°, pitch 20°. It records camera/object transforms, environment hash, renderer version, source/de-lit hashes, region masks, normal/culling captures, and measured metrics. The fixed camera mask must cover ≥95% of every observed required region; a role-source assignment must have 100% of sampled masked texels owned by its matching role; a required cuff/digit mask has ≥98% rendered occupancy; orbit captures must differ by ≥5% silhouette XOR area and have a mean masked normal-direction change of ≥0.10; culling/normal capture has zero reversed-face pixels in each visible named region. These values are measured from the rendered capture and fixture masks, never supplied by the caller. It fails on `GLOVE_MISSING_VIEW`, `GLOVE_REQUIRED_DIGIT_NOT_OBSERVED`, `GLOVE_HAND_MISMATCH`, `GLOVE_SURFACE_SWAP`, `GLOVE_CUFF_TRUNCATED`, `GLOVE_UNDECLARED_INFERENCE`, `GLOVE_TEXTURE_OWNERSHIP_CONFLICT`, `GLOVE_REVERSED_CULLING`, or `GLOVE_DEGENERATE_ORBIT`. Critical failures cannot be overridden by a global silhouette score. A negative fixture must mutate the actual crop, hand transform, texture assignment, cuff, inference record, and baked tangent/winding data; self-reported metric JSON is not evidence.

Static paired preview keys a GPU source texture by `(contentHash, sampler, colorSpace)` and permits one upload per unique source key, a maximum 16 MiB source-texture allocation for the two-view pair, and `min(devicePixelRatio, 2)` pixel ratio. Per-hand flips live in baked UVs/material uniforms, never a mutable shared texture matrix. It renders once initially, once after each asset-settlement event, then zero scheduled frames while idle; user control or active animation invalidates exactly one next frame. Failed/partial texture loading produces `request-input` plus an explicit failed-asset state and does not render a falsely ready pair.

## Ownership and sequencing

`forge/stage1_intake/cs2_manifest.py` owns schema v3 validation and v1/v2 normalization; `forge/stage2_spec/new_sculpt_spec.py` and `cs2_adapters.py` carry the immutable `gloveMultiView` record; `forge/stage3_build/bake_projected_texture.py` owns region masks, immutable UV atlas, and positive-determinant bake; `forge/stage4_review/cs2_review.py` owns fixture measurement; `runtime/cs2-preview` consumes only validated v3 output. Sequence is schema/handoff → frozen bake contract → source-linked fixtures → preview/runtime. Until the frozen producer exists, a v3 glove is a non-production review result, never a runtime primitive substitute.

## Review resolution matrix

| Review gap | Decision in this design |
| --- | --- |
| Ambiguous camera plus Y rotation | Fixed captures move camera only; inspection rotation is excluded. |
| Relabelable/missing data | Schema-v3 shape, enums, IDs, transform, and legacy rejection are normative. |
| Lost thumb/crop ambiguity | Per-digit coverage state and crop margin gate are normative. |
| Unsupported regions and texture swaps | Exhaustive evidence/ownership records, UV masks, channel semantics, and precedence are normative. |
| Self-reported review/runtime numbers | Fixed scene, mutation fixtures, error codes, texture/DPR/render budgets are normative. |
| Fingerless and animation scope | Topology dispatch is explicit; animation is deferred. |
