# CS2 Sport Gloves workflow

This checkout implements a diagnostic v3 review path for **any CS2 glove subtype**, normalized scale,
full-finger or half-finger, a canonical-left pair or a single declared hand. It still cannot return
`ready`: depth comes from an anthropometric prior rather than a side view, which pins `evidenceTier` to
`diagnostic`.

Subtype is not an admission decision anywhere in the track. `sport-gloves` was the pilot that proved the
gates; the allowlist is gone and a new subtype needs no code change. **Capability** is what refuses: an
observed form profile or per-digit opening the builder has no path for fails closed with a named error,
so removing the name gate never turns a refusal into a silently wrong model.

| observed | built |
|---|---|
| `formProfile.kind` `full-finger` / `fingerless` / `mitten` | assembly panels; `unknown` falls back to full-finger |
| `digitTopology[].opening` `closed-tip` | the capsule's own hemispherical cap |
| `digitTopology[].opening` `open-cut` | that cap subtracted away by a box — a digit ending flat at full width |
| `digitTopology[].opening` `grouped-chamber` | refused, named: the armature has no path for it |
| `hands` `["left"]` | one hand, no derived mirror, no right-hand overrides demanded |

Run a real item with `forge/tests/run_glove_item.py`:

```bash
python3 forge/tests/run_glove_item.py \
    --composite listing.png --roles dorsal palmar --hand left \
    --subtype hydra-gloves --observation observation.json \
    --out-dir .img2threejs/hydra-fn-v1
```

`--composite` splits one marketplace image into per-role plates first, because the same path submitted
twice yields one pHash, sets `duplicateOfHash`, and is refused. The split records its crop rectangle and
the backdrop it replaced with neutral white — the one pixel change it makes, and it is declared, because a
saturated backdrop makes `build_foreground_mask` report `foregroundCoverage 1.000` and the plate is then
rejected as not isolable. `--no-runtime` stops after the bundle, which is the fast loop.

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
agent performing a reconstruction, and its tooling is not glove-specific.

That absence is now a measured decision rather than a gap waiting to be filled. Against the real Hedge Maze
dorsal plate, with clean foreground masks on both sides:

| render | raw IoU | bbox-normalised IoU | fidelity | `divine_eye` |
|---|---|---|---|---|
| current hand armature | 0.3007 | **0.6559** | 0.2693 | `reject` |
| panel-era slab (`captures-v3/hero.png`) | 0.8480 | **0.8656** | 0.7494 | `low-confidence` |

The panel-era geometry is the silhouette-inflation route this document records as unable to produce a hand
at all — digits 0.13–0.18 as deep as they are wide. It wins on every signal, and normalising away scale and
translation does not reverse it, because silhouette inflation traces the plate's outline by construction.
A conformance gate on these signals would have passed the geometry this track spent four commits replacing.
See the `glove-reference-conformance` change for what a usable signal would have to do first.

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

### The palm is not as wide as the outline

Below the knuckles the outline is palm AND thumb, so a palm swept across all of it contains the thumb. That is
what made the hand read as a slab with a bump on it, and it is also why the fingers looked far too slim: their
diameter was being compared against the outline's full width rather than the palm's own breadth.

`palmProfile` is the same outline with the thumb's band removed, cut at the four digits' envelope on the thumb
side. On the real Slingshot plate the palm's breadth is 0.83 of the frame against the outline's 0.97. An
arithmetic check says the cut is in the right place, and it is the check four earlier attempts at this failed:
the widest row less the thumb's reach should equal the span the four digits occupy, because the widest row is
the knuckle line, where the palm is at full breadth and the thumb's lobe adds its reach.

| plate | widest row − thumb reach | four-digit span | apart |
| --- | --- | --- | --- |
| Slingshot dorsal | 0.8299 | 0.8322 | 0.3% |
| fixture dorsal | 0.7652 | 0.7913 | 3.3% |
| Slingshot **palmar** | 0.7494 | 0.6388 | **17.3%** |

It holds on the dorsal plates and fails on the palmar one, where the hand is cupped and the fingers flexed
toward the camera so the four-digit span is foreshortened, and the thumb is opposed across the palm rather
than alongside it. The measurement is therefore used for dorsal-measured geometry and is not claimed beyond
that.

Measured against the palm's own breadth afterwards, the proportions land where anthropometry puts them: finger
diameter 0.2085 against 0.226, thumb diameter 0.270 against 0.274. The thumb also splays — its base at the
palm's edge by the wrist, its tip at the outline's edge — because pinning both ends to the outline left the
base standing off the narrowed palm as a separate solid.

### The extractor does not guarantee a manifold mesh

Worth knowing before chasing geometry that is not at fault. Naive surface nets places one vertex per cell,
which cannot represent two surface sheets crossing the same cell, so an edge occasionally ends up shared by
four triangles. On this armature the count is 0 to 2 out of 10,000–20,000 edges and it tracks the grid's
PHASE rather than any geometric margin: nudging the bounds by 5% of a cell clears it, thumb radii of 2.5, 2.7,
3.1, 3.6 and 4.4 cells give 1, 1, 1, 0 and 1 welded edges, and six different digit spacings each moved the weld
to a different pair of parts instead of removing it. Every one of those meshes was still closed — no boundary
edges, V − E + F = 2.

At the shipping resolution both plates come out at zero, which is why `productionManifold` still demands zero
rather than a tolerance. The parity suite now runs at that same resolution instead of a coarser one, because a
parity test at a resolution nothing ships at can only prove the two implementations agree about a mesh nobody
sees. The real fix is multiple vertices per cell where a cell's surface has more than one component, which
would have to land in all three ports at once to keep parity.

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
`referenceResemblance` carries the measurement above as its reason — not "not built yet", but "no threshold
over these signals ranks a correct model first".

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
