# CS2 Sport Gloves workflow

This checkout implements a diagnostic v3 review path for one narrow target: static, full-finger
`sport-gloves`, normalized scale, canonical-left geometry plus a mirrored right hand. It still cannot
return `ready`: depth comes from an anthropometric prior rather than a side view, which pins
`evidenceTier` to `diagnostic`.

## How the geometry is built

A hand armature fitted to the admitted plate, expressed as `geometryDescriptor.sdf` and meshed by the
same extractor the browser runs. `forge/_shared/glove_armature.py` builds it, `forge/_shared/sdf_mesh.py`
meshes it in Python so stage 4 reviews the mesh that ships, and
`forge/tests/test_glove_armature_parity.py` pins Python, the emitted TypeScript and the review runtime's
`sdf.mjs` to each other vertex for vertex.

What the plate supplies and what a prior supplies, because the split is the honest part:

| observed from the plate | prior, declared as one |
|---|---|
| silhouette aspect, and the outline width and centre at each height below the knuckle line | palm depth, digit radius ratio, thumb out-of-plane angle |
| the knuckle line, as the widest row | digit placement across the measured row |
| the digit row's width, halfway down the digit band | per-digit length ratios (cited anthropometry, not measured here) |
| which side the thumb is on | the thumb's out-of-plane orientation |

The palm sweeps the measured outline as a stack of ellipsoid slices rather than one ellipsoid: an
ellipsoid of palm width by palm height is a circle, where the real plate shows a trapezoid tapering from
0.95 of full width at the knuckles to 0.68 at the cuff.

Two things are set by the polygonisation grid rather than chosen, because a grid extractor has exactly
two representable states for nearby solids -- a gap wider than a cell, or a real overlap:

- the gap between digits, in cells;
- how many outline slices the palm gets, being its height divided by the cell size.

An earlier route inflated the silhouette over a chamfer medial axis. It is kept as the
`silhouette-inflation` primitive because specs reference it, but it cannot produce a hand: thickness there
is proportional to the 2D distance to the outline, so a finger is always flat. Measured on the real
Slingshot plates its digits came out 0.13-0.18 as deep as they were wide, where a finger is about 1.0, and
the thumb's z range sat inside the palm's -- the same plane as the fingers.

**What this track does not claim.** No gate compares the render to the reference, so the review's verdict
says nothing about whether the model resembles the reference image. `CLAUDE.md`'s screenshot gate binds the
agent performing a reconstruction, and its tooling is not glove-specific — what is missing here is an
*automated* resemblance measurement inside the review. See the `glove-reference-conformance` follow-up.

## Reproducible commands

From `img2/`:

The review runtime needs its own dependencies once per checkout, because the browser route copies
three out of them:

```bash
npm ci --prefix runtime/glove-review
```

```bash
python3 forge/tests/fixtures/glove_sport_v1/build_fixture.py
python3 forge/tests/run_glove_e2e.py --fixture golden --expect reject --out-dir /tmp/img2-glove-diagnostic
python3 forge/tests/run_glove_e2e.py --suite seeded-negative --expect reject --out-dir /tmp/img2-glove-negative
```

`forge/tests/test_glove_e2e_harness.py` runs the golden invocation in the suite, so a regression that breaks
the harness fails the tests rather than going unnoticed. Spec readiness quality warnings do not abort the
harness: the review reports the same deficiencies as `coverage:` gates, so aborting at spec-build time would
suppress the run that reports them.

## Intake

The four required intake roles are `dorsal`, `palmar`, `thumb-side-profile`, and `three-quarter`. A missing or
unreadable required view remains `request-input` and is intake-only; it must not create a spec, geometry,
runtime capture, or ready verdict. Without verified camera calibration, the output is normalized/evidence-only.

A two-hand plate is admitted through the `paired-glove-plate-v1` override, which is why a pair photo whose
largest foreground blob is around half the foreground is not rejected as fragmented.

### Where the four views come from

A real CS2 item ships **two** plates — a dorsal and a palmar view of the pair. The remaining two required
roles are filled with *technical* views of the same glove model, which may be a different wear tier or
finish. Each view therefore declares how its evidence may be used, via `sourceUse` in the observation:

| classification | may supply | typical source |
|---|---|---|
| `target-geometry-and-surface` | geometry **and** surface/colour | the item's own two plates |
| `technical-geometry-only` | geometry only | another wear tier of the same glove model |

Two rules are enforced, not merely recommended:

- A `surfaceRegionEvidence` entry must name a `sourceViewId` and a `sourceHash` matching that view, and the
  view must be `target-geometry-and-surface`. Citing a technical view is refused — a well-worn plate's
  colours are not a battle-scarred item's colours.
- `dorsal` and `palmar` must be target-classed, because they are what the item actually is.

`evidenceUse` is a deliberate declaration, so it is set only by merging an observation
(`forge/stage1_intake/glove_observation.py`), never guessed at intake. A manifest built straight from images
carries no classification and will fail readiness with `required target view <role> must be classed
target-geometry-and-surface` until an observation supplies it. `.img2threejs/hedge-maze-bs-v1/glove-observation.json`
is a worked example from a real reconstruction.

## The form gate, and why the plates are withheld

`surfaceAtlas` is attached only when **all five digits stand clear of the rest of the hand** — for each digit,
whether any of its own surface lies outside every other part, sampled from the signed-distance field. Short of
that, the geometry report carries `surfaceProjectionWithheld` instead and the runtime renders the bare form.

The reason is specific. The palmar plate has the item's own thumb painted across its palm, so a four-digit
model wearing that plate renders as five digits and every form defect behind the texture becomes invisible. A
thumb fused into the palm mass survived a dozen textured renders here before an untextured one caught it.

The first version of this gate counted the separate solids a horizontal line crosses through the digit band,
and that instrument was wrong for this item: the thumb is tucked against the palm, so it lies behind the palm
along the view axis for its whole length and no such line ever reaches it. The gate demanded a pose the
reference does not have, and would have gone on failing a hand that was correct. Asking instead whether a
digit's own surface is outside the other parts is pose-independent, because it is exactly the condition for
that digit to be visible from some direction.

Only the sign of the field is read. Two attempts to also require a clearance of one grid cell both
mismeasured, because the ellipsoid distance in this descriptor is the scaled approximation
`(|p/r| - 1) * min(r)`: its zero set is exact but its magnitude off the surface is compressed by the smallest
radius, and compared against a cell it read 0.012 for a thumb standing a clear 0.08 of the frame off the palm.
Whether the grid can resolve what the field separates is a separate question, already answered by
`productionManifold` — a gap narrower than a cell welds, and welding shows up as a non-manifold edge.

**Current state: the gate passes**, on both the real Slingshot plates and the fixture, with the mesh closed
(no boundary and no non-manifold edges) and the extracted silhouette within 0.6% of the plate's own aspect.

Two things had to be right for that, and both were wrong before:

- **The pose.** The thumb runs alongside the palm's thumb-side edge, rotated onto its palmar side. That is the
  only pose consistent with both plates at once — the dorsal plate barely shows the thumb, the palmar plate
  shows a whole digit — and it took two wrong attempts to reach: standing the thumb in the digit row needs
  width the measured span does not have, and folding it across the palm renders a lump rather than a digit.
  The lobe the segment spans is measured from the outline; the tip's height comes from the lobe's top, the
  base from the wrist, and the asymmetry is deliberate because the lobe test fails at each end for its own
  reason. The depth is the palm-depth prior.
- **The handedness.** A pair plate holds two gloves and the silhouette measures the largest component, which
  on the real Slingshot plates is the *right* glove; every offset measured from it was then applied to the
  left hand unmirrored, which put both thumbs on the outside of the pair where the plate plainly shows them
  facing each other. Seen from the back of the hand the thumb lies on the side away from the body, so a
  dorsal view whose thumb reaches toward image-left is a right hand, and the plate's own handedness is read
  off that rather than assumed.

One caution when comparing a render against a palmar plate: the CS2 palmar plate is each glove **spun in
place**, not the dorsal arrangement seen from behind. Its thumbs point outward where the dorsal plate's point
inward, and both are the same physical pair — a camera orbited to the far side would show them still pointing
inward. So the two plates correspond through a mirror about *each hand's own centre*, not about the plate's,
and an azimuth-180 render is not directly comparable to the palmar plate with the hands in their dorsal
positions.

What is still off, stated rather than left to be discovered: the four fingers come out about 23% slimmer than
anthropometry, at 0.175 of the palm's width against a real 0.226. The cause is understood — the digit-row
span is measured halfway up the digits, which is the last height where they resolve apart and also a height
where they have already tapered — and no correction factor is applied for it, because the span at the knuckles
is not observable from a plate whose digits merge into the palm there.

## Review gates

The review publishes nine independent measurements, each named for what it measures:

| gate | kind | what it measures |
|---|---|---|
| `provenanceVerified` | boolean | upstream manifest/assessment/assembly/spec re-resolved and re-hashed |
| `topologyReady` | boolean | one joined shell per hand, structural integrity, consistent normals |
| `handednessCorrect` | boolean | the surface contract's handedness, asymmetry and blank-form result |
| `finiteGeometry` | boolean | every vertex finite |
| `selfIntersectionFree` | boolean | no measured self-intersection |
| `penetrationFree` | boolean | no measured pairwise penetration, nothing skipped |
| `minimumThicknessMeasured` | boolean | every mesh's measured minimum thickness meets the floor |
| `uvMaterialOwnership` | boolean | every mesh owns a UV set and a material |
| `runtimeDeterministic` | boolean | capture manifest finalized and repeat-verified |

Concerns that cannot be measured yet are published under `unmeasured` with a reason rather than as a derived
value: `seamBoundaryCorrespondence` and `productionManifold` await a real weld stage, and
`referenceResemblance` awaits the conformance follow-up.

Thresholds are typed records read from the review scene — `{"kind": "boolean", "threshold": 1.0}` or
`{"kind": "continuous", "threshold": <value>}`. A boolean gate is compared by identity. There is no fallback
to module constants: a scene with no thresholds fails `calibration:thresholds-absent`.

Scenes have exactly two threshold statuses:

- `uncalibrated` — the diagnostic scene. Metrics are still **measured** and published; `failedGates` carries
  `calibration:thresholds-absent` and `calibration:unverified`; verdict `reject`, action `request-input`.
- `verified-artifact-calibration-v2` — the only status that may authorize readiness, and only when
  `calibration.artifactDigests` names the bundle, geometry report and capture manifest digests the evaluator
  actually loaded, and `calibration.measurements` resolves root-relative and re-hashes.

`capture_sanity` runs as a **precondition**, emitting `capture-sanity:<role>:<reason>`. It is never a scored
metric: a framing or mask-collapse defect is a capture defect, not a model defect. The
`quarantinedCaptureRoles` is empty. `thumb-side-profile` used to be in it: the flat panel slabs of the older
geometry rendered edge-on at azimuth 90 as near-zero-width slivers and the foreground mask fell back to
whole-frame coverage. The armature has real depth and that capture now reads a subject fraction of 0.0406
against a floor of 0.02, in one connected component, so the role is scored again. The mechanism stays, since
a framing broken by a geometry defect should be recorded rather than charged to the model.

Every missing or invalid input is a named failure with a written report and exit `1`. Exit `2` is reserved for
conditions that prevent producing a report at all.

## Artifacts

The diagnostic run writes `cs2-intake.v1.json`, `pre-spec-assessment.v1.json`, `object-sculpt-spec.json`,
`glove-model-bundle.v2.json`, `geometry-report.v2.json`, `capture-manifest.v2.json`, and
`glove-review-report.v3.json`. The runtime loads the verified factory and payloads, and a browser bridge
attaches real PNG evidence before a v2 capture manifest is finalized. Calibration requires a separately
admitted evidence-backed positive artifact plus named artifact-level negatives; the v1 measurement JSON is
deliberately rejected.

## Known defects recorded rather than hidden

- **Depth is a prior, not a measurement.** Dorsal and palmar are both front-axis views and constrain the same
  silhouette, so two CS2 plates carry no depth information at all. Thickness comes from an anthropometric
  palm ratio, recorded as `derivation.axes.z.state: inferred`, and the tier stays `diagnostic` until a side
  view supplies it.
- **One pixel in five of the render was never photographed.** Measured on the real Slingshot plates from
  the dorsal camera: 80.8% of the visible area is surface a plate actually faced, 15.1% is the sides of
  the digits and palm, 4.1% is fingertip caps and the cuff's rim. Every remaining texturing artefact lives
  in that 19.2%.
- **The grazing band along the silhouette edge wears stretched texels.** Where the surface turns away from
  the plate's own camera, a projection along that camera's axis compresses its last texels into a band.
  Three alternatives were built and measured — the silhouette's hull edge per row, then per row and column
  by dominant face axis, then that stepped two cells inward — and none beat plain planar projection; the
  last moved 3,771 uvs by up to 8% of a plate and changed the render not at all. It is foreshortening, not
  a lookup mistake, so the simplest scheme is kept and the band is declared. A side view is the only cure.
- **The digits are separated by a gap where the reference shows them touching.** With the digits joined by
  a hard union they meet in a crease, which is what the reference shows, but a crease is visible only
  through shading and the review runtime renders unlit on purpose so a repeat capture is byte-identical.
  Under a material with no lighting a creased mitten and a solid mitten are the same picture, so the
  separation has to be geometric. A property of the renderer, not of the hand.
- **Fingertip caps are hemispheres.** The reference shows blunt, square, stitched caps.

Fixed since the panel route, and kept here because the review gates that caught them still guard them: the
two hands were coincident (six of twelve panels shared bounding boxes) and no input image affected any
vertex.
