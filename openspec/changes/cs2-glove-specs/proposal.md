## Why

The existing glove item sheets describe components and materials, but do not define how a handed, five-digit object is associated across dorsal and palmar reference views. This allowed a Sport Gloves reconstruction to crop away the thumb and to treat opposite views like interchangeable weapon broadsides.

## What Changes

- Add a normative multi-view handed-glove contract for intake, crop validation, transforms, texture ownership, review, and runtime performance.
- Define unambiguous `dorsal` and `palmar` view roles; deprecate ambiguous `front`/`back` labels for articulated gloves.
- Require a canonical left-glove frame, explicit right-glove mirroring, and an explicit distinction between a 180-degree rotation of one glove and reflection that changes handedness.
- Require five-digit crop validation before de-lighting, BM25/spec generation, projection, or silhouette scoring.
- Require per-region observed versus inferred evidence and fixed dorsal/palmar review views.
- Add runtime constraints that prevent mirrored gloves from duplicating identical source textures and prevent static glove previews from continuously rendering while idle.

## Capabilities

### New Capabilities

- `glove-handed-multiview-reconstruction`: Defines the evidence, coordinate-frame, handedness, texture, QA, and runtime-performance contract for image-matched articulated gloves.

### Modified Capabilities

- `uv-projection`: Anatomical glove views replace generic `front`/`back` projection angles for glove assets; legacy angle names stay available only to non-glove families.
- `geometry-lockdown`: The locked-down glove asset must be a positive-determinant, baked left/right GLTF pair with named anatomical regions and immutable UV ownership.

## Impact

- Affected guidance: `docs/cs2-anatomy/gloves.md`, CS2 intake/manifests, glove-family assessment/spec generation, projection descriptors, and review fixtures.
- Affected future runtime: `runtime/cs2-preview/` and generated Three.js factories for glove subtypes.
- Related but not replaced: `pipeline-geometry-lockdown` remains the authority for frozen/pre-baked geometry. This change defines the glove-specific data and review contract that a locked-down implementation must satisfy.
