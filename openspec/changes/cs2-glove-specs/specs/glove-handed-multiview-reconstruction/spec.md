## ADDED Requirements

### Requirement: Versioned anatomical glove manifest
The system SHALL use `schemaVersion: 3` and `gloveMultiView.version: glove-multiview-v1` for a multi-view glove. A view SHALL preserve `viewId`, physical/pair/pose identity, `left|right` hand, `dorsal|palmar` role, image dimensions/hash, normalized crop, camera-to-local basis, digit coverage, regions, and texture assignments through intake, sculpt spec, bake, preview, and review. `front`, `back`, `primary`, and `secondary` MUST NOT be accepted as authoritative glove roles.

#### Scenario: Legacy generic glove input
- **WHEN** a schema-v1 or schema-v2 generic manifest identifies a full-finger glove
- **THEN** it returns `request-input` with `GLOVE_MULTIVIEW_REQUIRED` and does not infer anatomy from `primary` or `secondary`

### Requirement: Full-finger crop and topology admission
For `topologyKind: full-finger`, a registered dorsal and palmar view of the same `physicalObjectId` and `poseId` SHALL each declare `thumb`, `index`, `middle`, `ring`, and `little` as `observed`; the cuff SHALL be observed. Each landmark box SHALL remain inside its crop by at least two pixels or 0.25% of the source dimension. `occluded` or `out_of_frame` required evidence SHALL request replacement input. `fingerless` and `wrap` SHALL bypass the five-digit gate.

#### Scenario: Centre split loses the inward thumb
- **WHEN** a composite-image crop ends before the visible thumb landmark
- **THEN** admission returns `GLOVE_REQUIRED_DIGIT_NOT_OBSERVED` before assessment, BM25 search, or projection

### Requirement: Handedness-preserving fixed views and bake
The canonical left frame SHALL be `+Y` wrist-to-tips, `+Z` dorsal, `-Z` palmar, with the dorsal thumb-side landmark at `+X`. Dorsal and palmar acceptance captures SHALL use an unrotated mesh from `+Z` and `-Z` respectively with `+Y` up. The right glove SHALL be authored from local-X reflection then baked as a positive-determinant asset with repaired winding, normals, and tangent handedness. Runtime negative scale is prohibited.

#### Scenario: Palmar capture does not re-expose dorsal surface
- **WHEN** the palmar fixed view is captured
- **THEN** it uses the `-Z` camera with no local-Y inspection rotation and reports the left palmar thumb identity

#### Scenario: Reflection is distinct from an inspection rotation
- **WHEN** a fixture substitutes a local-Y PI rotation for local-X reflection
- **THEN** handedness validation fails with `GLOVE_HAND_MISMATCH`

### Requirement: Evidence-safe texture ownership
Every named glove region SHALL declare evidence state, provenance, confidence, and inference method when not observed. Texture assignments SHALL bind source view, material slot, UV island, projection mask, overlap priority, and color-space channel semantics to the named region. Dorsal and palmar source pixels SHALL not overwrite the opposite role or an unsupported sidewall/gusset.

#### Scenario: Palmar source attempts to overwrite a dorsal knuckle shell
- **WHEN** a palmar assignment intersects a dorsal-region mask
- **THEN** bake/review fails with `GLOVE_TEXTURE_OWNERSHIP_CONFLICT`

### Requirement: Source-linked glove review
The system SHALL run `glove-review-scene-v1` at 1600×1000 with left/right dorsal/palmar fixed captures and yaw ±35°, pitch 20° orbit captures. It SHALL persist source/de-lit hashes, transforms, masks, culling/normal output, and measured feature metrics. Missing view/digit/cuff, wrong hand, swapped surface, undeclared inference, texture conflict, or degenerate orbit SHALL be a critical failure.

#### Scenario: Dorsal silhouette looks correct but palm is swapped
- **WHEN** a fixture swaps dorsal and palmar source assignments while retaining the dorsal silhouette
- **THEN** the palmar capture fails with `GLOVE_SURFACE_SWAP`; a global silhouette score cannot pass the result

### Requirement: Paired static runtime budget
The paired preview SHALL share each unique `(contentHash, sampler, colorSpace)` source texture, use at most 16 MiB source-texture allocation for the pair, cap pixel ratio at `min(devicePixelRatio, 2)`, render after initial and every asset-settlement event, and schedule no frame while idle. Failure or partial loading SHALL show a failed-asset/request-input state rather than an asset-ready render.

#### Scenario: Delayed palmar texture settles
- **WHEN** the palmar source finishes after the initial frame
- **THEN** exactly one asset-ready invalidation is scheduled and the idle renderer has zero queued frames after it completes
