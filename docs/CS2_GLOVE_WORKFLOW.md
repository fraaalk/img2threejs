# CS2 Sport Gloves workflow

This checkout implements a diagnostic v3 review path for one narrow target: static, full-finger
`sport-gloves`, normalized scale, canonical-left geometry plus a mirrored right hand. Geometry is derived
from the admitted view's silhouette and inflated over a chamfer medial axis, giving one closed shell per
hand, so manifoldness is measured rather than promised. It still cannot return `ready`: depth comes from
an anthropometric prior rather than a side view, which pins `evidenceTier` to `diagnostic`.

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
`thumb-side-profile` role is currently **quarantined** — at azimuth 90 the flat panel slabs render edge-on as
near-zero-width slivers and the foreground mask falls back to whole-frame coverage. That is a stage-3 geometry
defect, recorded in `quarantinedCaptureRoles` rather than scored.

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
- **The rim's UV sweeps across the atlas seam.** A rim quad joins front vertices (`u < 0.5`) to back vertices
  (`u > 0.5`), so its texture coordinate interpolates through the middle of the atlas. Visible as fringing at
  above-capture resolution. Fixing it means splitting rim vertices, which trades against `productionManifold`
  because edges are counted by vertex index — a decision about which gate measures what it names, not a tweak.
- **Digits fuse where the reference shows them touching.** A silhouette cannot separate what the photo does
  not separate.
- **Front and back inflate symmetrically without a palmar plate.** With one, the back follows the palmar
  medial axis at a declared 0.4 thickness share; measured 1.50x dorsal-to-palmar on real plates.

Fixed since the panel route, and kept here because the review gates that caught them still guard them: the
two hands were coincident (six of twelve panels shared bounding boxes) and no input image affected any
vertex.
