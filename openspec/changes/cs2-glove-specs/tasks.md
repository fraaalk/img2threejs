# Tasks: CS2 Glove Item Specifications

## Task 1: Sport Gloves Specification
- [x] Create `specs/sport.md` with full item spec
- [x] Define geometry breakdown (6 components)
- [x] Define material assignments (4 materials)
- [x] Define wear zones (4 zones)
- [x] Define UV mapping strategy
- [x] Define animation sockets (3 sockets)

## Task 2: Driver Gloves Specification
- [x] Create `specs/driver.md` with full item spec
- [x] Define geometry breakdown (6 components)
- [x] Define material assignments (3 materials)
- [x] Define wear zones (4 zones)
- [x] Define UV mapping strategy
- [x] Define animation sockets (4 sockets)

## Task 3: Specialist Gloves Specification
- [x] Create `specs/specialist.md` with full item spec
- [x] Define geometry breakdown (6 components)
- [x] Define material assignments (4 materials)
- [x] Define wear zones (4 zones)
- [x] Define UV mapping strategy
- [x] Define animation sockets (3 sockets)

## Task 4: Moto Gloves Specification
- [x] Create `specs/moto.md` with full item spec
- [x] Define geometry breakdown (6 components)
- [x] Define material assignments (4 materials)
- [x] Define wear zones (4 zones)
- [x] Define UV mapping strategy
- [x] Define animation sockets (3 sockets)

## Task 5: Hand Wraps Specification
- [x] Create `specs/handwraps.md` with full item spec
- [x] Define geometry breakdown (5 components)
- [x] Define material assignments (2 materials)
- [x] Define wear zones (4 zones)
- [x] Define UV mapping strategy
- [x] Define animation sockets (3 sockets)

## Task 6: Hydra Gloves Specification
- [x] Create `specs/hydra.md` with full item spec
- [x] Define geometry breakdown (6 components)
- [x] Define material assignments (4 materials)
- [x] Define wear zones (4 zones)
- [x] Define UV mapping strategy
- [x] Define animation sockets (3 sockets)

## Task 7: Broken Fang Gloves Specification
- [x] Create `specs/brokenfang.md` with full item spec
- [x] Define geometry breakdown (7 components)
- [x] Define material assignments (4 materials)
- [x] Define wear zones (4 zones)
- [x] Define UV mapping strategy
- [x] Define animation sockets (3 sockets)

## Task 8: Default Gloves Specification
- [x] Create `specs/default.md` with full item spec
- [x] Define geometry breakdown (5 components)
- [x] Define material assignments (3 materials)
- [x] Define wear zones (4 zones)
- [x] Define UV mapping strategy
- [x] Define animation sockets (3 sockets)

## Completion Criteria
- [x] All 8 Glove specs created
- [x] Each spec includes geometry, materials, wear, UV, sockets
- [x] Vertex budgets defined per item
- [x] Reference image requirements documented

## 9. Handed Multi-View Reconstruction Contract

- [ ] 9.1 Add schema-v3 `gloveMultiView` parsing/validation and v1/v2 `request-input` compatibility to `forge/stage1_intake/cs2_manifest.py`; add manifest fixtures under `forge/tests/fixtures/` for valid, legacy, duplicate, mixed-object, and bad-role inputs; verify with `python3 -m unittest forge.tests.test_cs2_manifest`.
- [ ] 9.2 Propagate the immutable validated record through `forge/stage2_spec/new_sculpt_spec.py` and `forge/stage2_spec/cs2_adapters.py`; add a handoff fixture that proves no view/crop/evidence field is dropped; verify with `python3 -m unittest forge.tests.test_cs2_foundation` plus the new handoff test.
- [ ] 9.3 Implement full-finger crop admission in the stage-1 validator with per-digit states, landmark margin, cuff evidence, and topology dispatch; add real image/crop fixtures for missing thumb, occluded digit, different pose, duplicate image, and fingerless bypass; verify `GLOVE_REQUIRED_DIGIT_NOT_OBSERVED`/`request-input` outcomes.
- [ ] 9.4 Update `docs/cs2-anatomy/gloves.md`, `openspec/changes/cs2-glove-specs/specs/sport.md`, and glove adapters to use only `dorsal`/`palmar` in emitted contracts; reject legacy role aliases at the manifest boundary; verify no authoritative emitted glove role matches `front|back|primary|secondary`.
- [ ] 9.5 Implement canonical-left/local-X bake in the `pipeline-geometry-lockdown` asset producer and `forge/stage3_build/bake_projected_texture.py`: separate positive-determinant right GLTF, fixed UV islands, region masks, channel semantics, and overlap precedence; add binary/GLTF and normal/culling mutation checks for reflection vs `R_y(PI)`, swapped surface, and tangent/winding corruption.
- [ ] 9.6 Add `glove-review-scene-v1` to `forge/stage4_review/cs2_review.py` and source-linked fixture assets under `forge/tests/fixtures/glove-review/`; emit left/right dorsal/palmar plus orbit captures and masks at 1600×1000; verify negative mutations fail the named error codes rather than caller-provided metrics.
- [ ] 9.7 Update `runtime/cs2-preview/src/main.ts` and `generatedGloveFactory.ts` to consume only validated v3 glove output, share texture keys, cap DPR, and use asset-settlement demand invalidation; test delayed/failed source loading, upload count, <=16 MiB allocation, and zero idle queued frames with the real preview harness.
- [ ] 9.8 Add migration/rollback tests: v2 generic reader remains usable, v2 full-finger glove requests input, v3 on v2 runtime is rejected, mixed versions are rejected, and rollback never broadside-builds a glove; run `python3 -m unittest forge.tests.test_cs2_manifest forge.tests.test_cs2_foundation forge.tests.test_cs2_review` and the preview harness.
