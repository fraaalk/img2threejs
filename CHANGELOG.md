# Changelog

All notable changes to **img2threejs** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `forge/tools/serve_form_review.py` serves the glove form in a browser, untextured, built by the runtime's
  own polygonizer so what is reviewed is what ships. Every form defect in this track was found by a person
  looking at the shape and missed by the numbers, and the still renders that caught two of them took a code
  change each to re-aim.

### Fixed
- The glove's **thumb is a fifth digit** now, and the form gate says so from the geometry. Three things were
  wrong at once. The thumb was posed as a fifth finger at the outline's edge where the palm's own sweep
  swallowed it, so the hand had four digits and a lobe. The pair's handedness came from the largest
  silhouette component without asking *which* hand that was — on the real plates it is the right glove — so
  both thumbs pointed outward where the plate shows them facing each other. And the palm's slice stack
  overlapped by 0.0028 against a grid cell of 0.0179, six times too thin, so the sweep was manifold only by
  where the samples happened to land; that is why unrelated changes to the thumb kept flipping the mesh's
  non-manifold count. The thumb now runs alongside the palm rotated onto its palmar side, handedness is read
  off the thumb side through anatomy, and both the slice overlap and the thumb's own radius are constrained in
  grid cells. Measured on the real Slingshot plates and the fixture: five digits clear, no boundary or
  non-manifold edges, silhouette aspect within 0.6% of the plate's.
- The form gate counts a digit by whether its own surface stands outside the rest of the hand, not by how many
  solids a line through the digit band crosses. The line test can only see digits standing side by side, and
  this glove's thumb is tucked against the palm — it would have failed a hand that was correct.
- `build_glove_sdf_descriptor` refuses a resolution too coarse to carry the thumb rather than emitting a
  welded mesh. At resolution 24 the thumb is 1.76 cells across and the extraction welds three edges.
- **The palm is swept at the palm's own breadth, not the outline's.** Below the knuckles the outline is palm
  AND thumb, so the palm swept across all of it contained the thumb — the hand read as a slab with a bump, and
  the fingers looked 23% slimmer than anthropometry because their diameter was being compared against the
  outline's full width instead of the palm's. `palmProfile` cuts the thumb's band off at the four digits'
  envelope, and an arithmetic check places the cut: the widest row less the thumb's reach equals the span the
  four digits occupy, within 0.3% and 3.3% on the two dorsal plates. Measured against the palm afterwards the
  proportions land on anthropometry — finger diameter 0.2085 against 0.226, thumb 0.270 against 0.274.
- The thumb splays, base at the palm's edge by the wrist and tip at the outline's edge. Pinning both ends to
  the outline left its base standing off the narrowed palm as a separate solid, which a horizontal line
  through the bottom quarter caught as two solids where a hand has one.
- The parity suite runs at the resolution the pipeline ships at. It ran at 24, where the thumb is under two
  grid cells and the mesh welds — a parity test at a resolution nothing ships at can only prove the two
  implementations agree about a mesh nobody sees.

- **Each digit is measured, not assumed.** The four fingers were four equal cylinders spread evenly across
  one measured span; the plate carries each digit's own width, centre and tip, and the assumption was wrong in
  all three ways at once. On the real Slingshot plate the digits are 0.226, 0.228, 0.204 and 0.129 of the
  frame wide, their centres are 0.233, 0.226 and 0.168 apart, and their tips sit at 0.036, 0.000, 0.062 and
  0.147 of the height — which orders them middle, index, ring, little with no anthropometric prior consulted.
  The even spread also took 16% off every finger, solving `4 * diameter + 3 * gap = span` with the gap fixed
  in grid cells and leaving each digit 0.175 of the frame where the plate says 0.20 to 0.23.
- **The knuckle line was measuring the thumb.** It was the widest row of the whole outline, and on a plate
  with a thumb those are different rows: the real Slingshot outline peaks at 0.42 of the height, which is
  where the THUMB is widest, while the palm on its own peaks at 0.28 and narrows monotonically below. The
  finger band was 46% too long as a result. It is now the widest row of the palm with the thumb's band
  removed, which is the metacarpal heads.
- Each digit's web is measured too, so the digits merge one at a time as they do on the plate. The webs sit at
  0.28, 0.23, 0.18 and 0.18 of the height on the real plate — a staircase, not one height for all four — and
  the model now reproduces the plate's merge order exactly: four separate digits at 0.18, three at 0.22, two
  at 0.26, one at 0.30.
- **The digits taper, and that is what lets them separate.** Modelled as cylinders of their widest section
  the four fingers fused into a mitten, because the gap between two neighbours AT THEIR WIDEST is 0.1 to 0.9
  of a grid cell — sub-cell, and unrepresentable. A fifth of the way down from the tips the same gap is 2.1
  to 3.1 cells. Each digit is now two segments, a wide proximal one that merges with its neighbours at the
  web and a narrower distal one that stands clear, both measured from the plate. The digits now read as four
  separate fingers from 0.15 of the height down to the knuckle line, which is what the item's own 3D model
  shows.
- Adjacent digits are blended across their seam rather than held apart by an air gap. The plate measures
  0.0036 of the frame between neighbouring digits — a fifth of a grid cell, because on a sewn glove the
  digits touch and what shows is a seam. A fifth of a cell is the one width a grid extractor cannot carry:
  left as measured it welded seven edges on the fixture and broke the surface's genus, V − E + F coming out
  at 0 rather than 2.

### Documented
- Naive surface nets does not guarantee a manifold mesh, recorded in `forge/_shared/sdf_mesh.py` with the
  evidence, because six geometry changes were spent chasing a defect that was never in the geometry. One
  vertex per cell cannot represent two surface sheets in one cell; the count is 0–2 out of 10,000–20,000 edges
  and tracks the grid's phase, not any geometric margin. Every such mesh is still closed with V − E + F = 2.
  The fix is multi-vertex dual contouring in all three ports at once.

### Changed
- **BREAKING** — the SDF extractor is naive surface nets, not binary voxel occupancy. Every vertex is now
  the interpolated zero crossing of one cell's edges instead of an integer grid corner, which changes the
  mesh of every `geometryDescriptor.sdf` component. The old extractor could not represent a crease between
  two solids that touch without a gap — so two fingers pressed together came out as one mitten and had to
  be held apart artificially — it was faceted at cell scale at any resolution, and because every face was
  axis-aligned it left **35% of triangles with exactly zero uv area**, a third of the surface wearing one
  line of the texture. Measured after: 1.4-2.8%, and none of them on a face a plate faced. It also removes
  the diagonal-contact repair pass the old extractor needed to stay manifold.
- **BREAKING** — glove geometry is a hand armature fitted to the plate (`derivation.tier:
  sdf-armature-v1`), replacing the chamfer medial-axis inflation. The inflation stays available as the
  `silhouette-inflation` primitive but cannot produce a hand: its thickness is proportional to the 2D
  distance to the outline, so measured on the real Slingshot plates its digits were 0.13-0.18 as deep as
  wide where a finger is about 1.0, and its thumb sat in the plane of the fingers. The palm now sweeps the
  measured outline as a stack of slices rather than being one ellipsoid, which was a circle where the plate
  shows a trapezoid.
- `geometryDescriptor.sdf` gains a hard `union` operation and an opt-in `uvProjection`. `union` is what
  lets two touching digits keep a crease: `smooth-union` blends by proximity, so anything adjacent fuses
  regardless of whether it is the same body part, and the operations now form an anatomical tree — digits
  hard-unioned to each other, filleted to the palm — instead of one flat chain.
- Digit gaps and palm slice counts are derived from the polygonisation cell size instead of being chosen.
  A grid extractor has two representable states for nearby solids, a gap wider than a cell or a real
  overlap; a gap expressed as a fraction of a diameter silently fell under a cell and pinched the surface.
- `nonDegenerateExtrusion` for an implicit solid reports the smallest primitive cross-section, and says so.
  Two attempts to measure it off the distance field were instruments rather than measurements: 6-neighbour
  local maxima also fire on the saddle points a smooth union is full of (reported 0.008 for a solid whose
  slimmest part is 0.088), and walking inward from the surface is meaningless in a concave crease
  (reported 0.0008 for the same solid). Both failed the gate on a mesh that was never thin.
- **BREAKING** — `wearable-v1.0` glove review report is now `glove-review-report.v3`. The thirteen
  metrics carried nine aliases of one topology boolean while their `0.85`/`0.95` thresholds were
  unreachable (every value was `float(bool)`), and the evaluator never read the calibrated scene's
  thresholds at all, so calibration output was decorative. The report now publishes nine independent
  measurements, each named for what it measures — `crossSectionVariation` became
  `minimumThicknessMeasured` because it measured minimum thickness, and `handednessCorrect` now
  derives from the surface contract instead of from topology readiness.
- Thresholds are typed records (`{kind, threshold}`) read from the review scene. A boolean gate is
  compared by identity, the threshold key set must equal the metric set, and a scene with no
  thresholds fails `calibration:thresholds-absent` — there is no fallback to module constants,
  because a silent default is what made these gates inert. Calibration must bind
  `calibration.artifactDigests` to the artifacts the evaluator actually loaded, and the calibrator
  now emits `1.0` for boolean gates instead of the midpoint `0.5` that no boolean gate could satisfy.
- Scene threshold statuses reduced from four to two (`uncalibrated`,
  `verified-artifact-calibration-v2`); the misnamed `build_calibrated_scene` and two orphaned scene
  fixtures are removed.
- `validate_glove_surface_contract` is now a pipeline gate, and was strengthened first so promoting
  it means something: it **measures** per-hand separation instead of reading the geometry report's
  hardcoded `diagnosticOverlapSeparate`, and it requires an inspectable material set. Previously
  `validate_glove_surface_contract(geometry, {})` returned no errors — an empty spec passed clean.
- All metric derivation and threshold reading moved inside the evaluator's exception boundary. A
  missing artifact or malformed threshold is now a named failure with a written report and exit `1`,
  not a traceback and exit `2`.
- `activate_staged_adapter_after_review` verifies the report version, recomputes `reportDigest`, and
  requires empty `failedGates`; it previously accepted any two-key dict.

### Fixed
- `forge/tests/run_glove_e2e.py` ran no longer: both commands documented in
  `docs/CS2_GLOVE_WORKFLOW.md` tracebacked because spec readiness `quality:` warnings were promoted
  to fatal at spec-build time — the same deficiencies the review reports as `coverage:` gates, so the
  abort suppressed the run that would report them. No test imported the file, so nothing noticed.
  `forge/tests/test_glove_e2e_harness.py` now runs the golden invocation in the suite.

### Added
- `forge/tests/test_glove_gate_isolation.py` — function-level gate isolation with exact-set
  assertions for every review rule. Previously the verdict was `reject` for every possible input, so
  no assertion could distinguish a working gate from a deleted one.
- `capture_sanity` runs as a wearable-track precondition (`capture-sanity:<role>:<reason>`), never a
  scored metric. The `thumb-side-profile` capture is quarantined with its defect recorded: at
  azimuth 90 the flat panel slabs render edge-on and the foreground mask collapses to whole-frame.
- Concerns that cannot be measured are published under `unmeasured` with a reason rather than as a
  derived value — including `referenceResemblance`: the wearable track makes no claim about
  resemblance to the reference image, so its verdict says nothing about likeness.
- Add `runtime/scripts/export_mesh_geometry.mjs`, the mesh dumper `SKILL.md` already instructed
  callers to run. It did not exist and neither did `runtime/`, so `self_intersection.py` and
  `geometry_integrity.py` had no producer in this repo and their gates were never runnable while
  the surrounding checklist still read as complete. Emits world-space vertices (seam-overlap
  compares mesh PAIRS), expands `InstancedMesh` to one entry per instance, synthesises indices for
  non-indexed geometry, and fails closed rather than writing an empty `meshes.json` that every
  downstream gate would score as clean. The browser driver is resolved via `--driver`,
  `$IMG2THREEJS_PLAYWRIGHT`, or a bare `playwright` import — never a hardcoded absolute path.
- Port the compaction resume snapshot (`state.py compact`, `workflow_state`'s
  `build_resume_snapshot`/`write_resume_snapshot`/`resume_snapshot_path`) from the
  `~/.claude/skills` and `~/.codex/skills` host copies, which carried it while this repo never
  did — `git log -S "def cmd_compact"` returns 0 commits here, so it was developed outside git
  rather than deliberately dropped. Those copies were plain directories, not the symlinks
  SKILL.md prescribes, and had forked: they lacked this repo's versioned rifle adapter and this
  repo lacked their compaction work, so neither was a superset and symlinking either direction
  would have destroyed real work. Ported additively — `_has_external_versioned_ledger` is absent
  from those copies and stays — leaving the merged checkout a superset of all three. The feature
  arrived untested; `forge/tests/test_compaction_snapshot.py` is new and covers the snapshot's
  contract: it carries the resuming facts, names the state JSON as the authority rather than
  itself, stays bounded as history grows, and replaces rather than appends on rewrite.
- Add `forge/stage4_review/rank_lookdev_sweep.py`, which ranks a rendered look-dev parameter
  sweep against the reference so the choice is measured rather than reasoned. Motivation is a
  measured failure: three consecutive correction loops moved a finish in the WRONG direction
  (saturation error -24, -62, -79) because each reasoned about PBR physics and measured only
  afterwards, while the real culprit — the tone-mapping operator — had been fixed by assumption
  on a doc comment's authority and left outside the search. Enumerating 4 operators x 4 exposures
  settled it in one run, and the winner was the operator the doc had ruled out. Ranks on value +
  saturation delta over the subject foreground, because the failing candidates were washed out
  rather than off-hue and a lightness-weighted distance under-punishes that. Ranking is
  whole-foreground and reports that limitation: on the same data a ruby-region-only objective
  preferred a different exposure while agreeing on the operator.
- Add `forge/stage4_review/capture_sanity.py`, a pre-flight check on the CAPTURE that runs before
  any render is compared to a reference. Every other gate asks whether the model is right; this
  one settles whether the picture is usable evidence at all, because a wrong harness produces
  numbers that read as model defects. Measured motivation: on one reconstruction 5 of 12
  correction loops fixed the capture rather than the model — an oversized shadow catcher pushed
  the auto-framed camera to z=54.87 and rendered the subject at 8% of frame width, a contact
  shadow counted as foreground and inflated the bbox height 22% while width matched to 0.6%
  (IoU 0.686), and a pinned near/far pair clipped the model once orbited so frames came back
  empty and the degenerate-view gate read collapsed volume. Checks subject fraction, single
  connected foreground, empty/fallback frames, and framing match against the reference; exits
  0 usable / 1 capture defect / 2 error.
- Add `alignedIoU` to `diagnose_render.py`: the best silhouette IoU reachable by a pure
  translation, alongside the raw value. `grimoire/review/self_correction.md` already prescribed
  trusting IoU "only after scale+translation alignment" but nothing computed it, so a correctly
  shaped render that was merely mis-framed reported a low IoU — and a low IoU reads as "the shape
  is wrong", sending the fix onto geometry that was already correct. Observed at 0.736 raw vs
  0.965 after a 26px shift. Report-only by design: a genuine misplacement is also a translation,
  so alignment never rescues the hard gate; it only lets the failure message say whether this is a
  FRAMING error or a SHAPE error.

## [1.4.4-beta.2]

### Added
- Add a repository-local mandatory workflow checklist, resume gate, and evidence-backed step
  tracking under `.img2threejs/state.json`.
- Add per-pass and total correction ceilings derived from `reviewHistory`; `forge/next.py` now
  hard-stops when either limit is reached.
- Add an executable CS2 review CLI and profile-specific CS2/character checklist gates.
- Add explicit suitability, projection-route, and material-evidence decisions to every profile.

### Changed
- Keep progressive-disclosure references while making CS2 intake, deterministic review gates,
  self-correction, multi-angle review, part coverage, and action-ready validation explicit router
  requirements.
- Order each pass as build, render, Tier 1, multi-angle, deterministic pass check, profile review,
  AI review, and sync.
- Make regeneration action-aware so `refine-code` cannot overwrite the artifact it must repair,
  and reject spec paths that disagree with local state.

## [1.4.3] — 2026-07-30

The accepted current release line is `1.4.x`. GitHub Releases are the canonical changelog from
the governed `v1.4.3` tag onward.

### Changed
- Release publication now occurs only from an approved annotated version tag; merging a pull
  request never changes the version or creates a release.

## Invalid historical record: 1.5.0 — not released

The entry below was generated by the retired push-to-`main` release automation. It is retained as
historical context only and does not represent an accepted release or release-note baseline.

### Added
- add Python CI and automated releases
- update changelog and roadmap
- enhance skill and strict cs2 component render

### Fixed
- stabilize pHash brightness invariance
- align tests with review evidence gates
- sponsor donate link + weekly and all-language Trendshift badges (#42)
- use the logo mark for the README, at its real aspect ratio (#36)
- restore assets/logo.svg so the README logo stops 404-ing (#35)

## [1.4.1] — 2026-07-26

The hardening update for the CS2 reconstruction pipeline: explicit component coverage, a pistol
assembly contract, and review evidence that distinguishes real structure from a convincing texture.

### Added
- **Assembly coverage gate** — `stage4_review/check_part_coverage.py` verifies that every specified
  component is built, prevents multiple specified components from collapsing into one mesh, and
  reports unowned meshes and inventory details that never reached the spec.
- **Glock-18 adapter** — the CS2 route now supports a dedicated `pistol` / `glock-18` component tree
  with separate slide, frame, magazine, trigger-guard, control, barrel, and internal-mechanism
  contracts; it does not reuse the knife topology.
- **Structure-first guidance** — documented rules for named, explodable and selectable parts, plus
  correct layout scaling for exploded views in `SKILL.md` and
  `grimoire/build/geometry_patterns.md`.

### Changed
- **Strict review evidence** — the pipeline requires map-stripped blockout evidence, ordered pass
  credit, and thickness- and long-axis viewpoints before a visual pass can continue.
- **Geometry-integrity checks** — Tier 1 now surfaces open separate geometry, insufficient seams,
  constant blade grinds, and missing distal taper so projection cannot hide structural defects.

## [1.4.0] — 2026-07-25

**Theme: Weapon Pipeline.** Image-matched CS2 hard-surface reconstruction: evidence-backed identity,
projection-first finish matching, family-specific geometry, and gate-driven review.

### Added
- **CS2 intake and provenance contract** — reference admission, technical probing, identity routing,
  metadata lookup, VPK/texture discovery, and an atomic `cs2-intake.json` hand-off that preserves
  uncertainty instead of guessing.
- **CS2 knowledge base and local search** — bilingual BM25 search profiles, curated vocabulary and
  anatomy references, plus provenance-aware result handling for specification work.
- **Family-specific reconstruction** — knife adapters, supported subtype validation, component-tree
  contracts, projected-texture baking, and a strict-quality route for CS2 assets.
- **Evidence-backed CS2 review** — `cs2_review.py`, geometry-integrity measurements, fixed and orbit
  review views, family/finish/projection/critical-detail gates, and versioned review-scene metadata.
- **Reference preview and prompt assets** — a browser smoke-tested CS2 knife preview, reference
  fixture, and focused knife, pistol, and technical-analysis skill prompts.

### Changed
- **Projection-first finish workflow** — de-lit reference crops are the default path for matching
  skin patterns, decals, and painted surfaces; procedural finishes remain an explicitly disclosed
  fallback.
- **Divine Eye calibration** — scale and aspect signals are live, and the reconstruction rescue path
  now requires objectness, soft-fidelity, and proportion evidence rather than accepting an IoU-only
  result.

## [1.3.0] — 2026-07-22

The "quality & efficiency" line: a deterministic-first review harness (Divine Eye), stronger
input integrity, geometry-truth gates, and reference-grounded texture/material analysis.

### Added — Plan 1.3 (Phases 1–7)
- **Input integrity** — reference admission (`check_reference_admission.py`), intake-correctness
  cross-check (`check_intake_correctness.py`), property auto-binding, shared pHash.
- **Geometry truth** — curve-sweep (F.6), flatness gate (G.1), Blum lathe-profile derivation.
- **Divine Eye** — deterministic multi-signal ensemble (`divine_eye.py`): IoU/scale hard gates;
  proportion / symmetry-parity / pHash / SSIM / edge / blowout / flat / tonal-parity soft signals;
  self-uncertainty `probe` routing.
- **Multi-angle** — degenerate-view detection (`diagnose_render_multi_angle.py`) with reference-free
  self-consistency; auto-framing.
- **Eye judgment layers** — gated VLM gate (`vlm_gate.py`), per-feature verification (§3.8),
  bounded stop policy (§3.6), calibration harness (report-only + separation check).
- **Efficiency** — per-module codegen cache (§3.7 neighbor invalidation).
- **Presentation** — reference-conditional post-fx (DOF/bloom) strictly off the evaluation path.

### Added — session capability work (folded into 1.3)
- **Texture-finish analysis** — `stage1_intake/analyze_texture.py`: classifies finish
  (gem-metal / gemstone / painted-metal / worn-composite / brushed-steel / plastic) and writes
  doc-grounded MeshPhysicalMaterial scalars; `grimoire/build/threejs_texture_reference.md`.
- **Objectness (OSIM-lite)** — `stage4_review/objectness.py`: pure-stdlib HOG-like descriptor +
  cosine similarity; wired into Divine Eye as a soft signal + reconstruction-mode rescue.
- **`ground-blade` primitive** — lofted beveled cross-section (primary bevel + swedge/false edge)
  in the generator + validator whitelist.
- **Color-gate fix** — `diagnose_render.py` `color_is_gated(pass_id)` (color hard-fail only from
  the material pass onward, so clay blockouts don't false-fail).

### Added — reconstruction-fidelity upgrades (folded into 1.3)
- **Reference-grounded gradient stops** — `stage1_intake/extract_gradient_stops.py`: foreground-masked
  per-band median sampling extracts a material's true gradient from the reference (kills hand-guessed
  STOPS), names hue zones, and flags blue-leaning violet/blue stops (`B > R`) as `blue-collapse`
  (collapses to blue under tone-mapping) with a magenta-lean suggested correction.
- **`candy-coat` finish class** — `stage1_intake/analyze_texture.py`: an anodized/PVD/doppler
  dielectric-led recipe (metalness 0.35 / clearcoat 0.60 / envMapIntensity 0.70) so a saturated
  coloured coat keeps its hue instead of the environment stealing it; chrome-specular stays
  `gem-metal`, bright-clean stays `gemstone`. Plus a `paletteHueRisk` hue-survival annotation.
- **CIEDE2000 colour math** — `_shared/color_metrics.py`: sRGB→CIELAB + full ΔE00, verified against
  the canonical Sharma test pairs.
- **Colour-aware Divine Eye signals (report-only)** — `hue_zone_parity` (per-band CIEDE2000 along the
  axis; catches "purple rendered blue" that luma/structure signals miss) and `specular_wash`
  (saturation-decay + hue-drift-toward-cyan detector). Both ship report-only (no ensemble weight)
  until calibrated, so they never silently move a verdict.
- **InstancedMesh emission** — repetition systems now emit one `THREE.InstancedMesh` (single
  draw-call) instead of a per-instance `Mesh` clone loop; the `instanced-cluster` primitive resolves
  to its base geometry instead of failing.
- **`ground-blade` UV fix** — blade UVs now span the geometry's actual Y bounds instead of a
  hardcoded range, so an off-origin blade no longer clamps every face to the bright spine-rim row
  (the flat "one colour" / white-tip bug); the length gradient reads correctly.
- **Dep-free cutouts** — `extrude` supports `THREE.Shape.holes` + an `ovalLoop` helper (e.g. a
  wire-cutter oval hole) with no CSG dependency.

### Notes
- Pure Python 3.10+ stdlib in `forge/` (no pip installs). 20/20 forge test suites green.
- Grimoire lessons updated: shading realism (hue-survival under tone-mapping; reference beats prose),
  geometry patterns, self-correction.

## [1.2.0] - 2026-07-21

**Theme: Humanoid character generator.** Characters and hybrid subjects become
first-class citizens of the reconstruction pipeline, alongside a round of engine
and harness improvements to the underlying code generator.

### Added

- **Character / hybrid domain detection.** Assessment now recognizes character-like
  form language and routes the reconstruction through an anatomy-aware track instead
  of the hard-surface object path.
- **Humanoid component template.** A flattened humanoid template with measured
  head-unit proportions, facial landmark placement, and pose alignment is emitted
  from the assessment stage.
- **Proportion-lock build pass.** New gated pass that enforces anatomical proportion
  correctness before form/material work proceeds.
- **Feature-placement build pass.** New gated pass that places and validates facial
  and body landmarks against the reference.
- **Per-part character materials.** Skin, hair, cloth, and accessory materials
  integrate with the Track A detail machinery for stylized human figures with
  recognizable likeness.
- **Surface topology classification.** Parts are classified by surface topology to
  drive more accurate geometry choices.
- **Per-part color / RGBA recipes.** Explicit per-part color and RGBA material
  recipes for tighter reference matching.
- **Tier-1 diagnostics.** Diagnostic reporting layer for the generation harness.
- **Hash caching.** Content-hash caching to avoid redundant recompute across passes.
- **Real extrude / lathe / tube geometry.** Genuine extrude, lathe, and tube geometry
  generation replaces prior approximations.

### Changed

- Restructured the project layout ahead of the full harness rebuild, including
  stage-prefixed script names for clearer pipeline ordering.

### Docs

- Published a public ROADMAP (v1.0 → v1.5) and a token-cost document.
- README remake: 3D showcase, live-demo links, new logo, and animated GIF previews
  (shotgun, knife, war-hauler, Sony, Doraemon House, Crowned Loot Chest).
- Added LICENSE, CONTRIBUTING, and a community-outreach promotion playbook.
- Funding pointed to the VN donate page (MoMo / VietQR).

## [1.1.0] - 2026-07-15

**Theme: Detail-first analysis.**

### Added

- Required `detailInventory` artifact enumerating identity-defining micro-details
  (gloss zones, bevels, fasteners, engraved/painted linework, contours, stains, wear).
- Strict-quality gate that blocks code generation until every detail maps to a real
  component or material entry, preventing shallow specs from reaching the renderer.

## [1.0.0] - 2026-07-15

**Theme: Object pipeline.** Initial release.

### Added

- Staged sculpt pipeline: blockout → structure → form → material → lighting →
  interaction → optimization, with a visual gate on each pass.
- Image suitability validation and `ObjectSculptSpec` authoring (components + materials).
- Render-vs-reference review loop using side-by-side comparison sheets.
- Action-ready runtime hierarchy exposing pivots, sockets, and colliders.
- Token-efficient, code-only output (diffable TypeScript + JSON spec, no binaries).

[1.4.1]: https://github.com/hoainho/img2threejs/compare/v1.4.0...4e9fbecae0e63b370581737c89991d4dca84c287
[1.4.0]: https://github.com/hoainho/img2threejs/releases/tag/v1.4.0
[1.3.0]: https://github.com/hoainho/img2threejs/releases/tag/v1.3
[1.2.0]: https://github.com/hoainho/img2threejs/releases/tag/v1.2.0
[1.1.0]: https://github.com/hoainho/img2threejs/releases/tag/v1.1.0
[1.0.0]: https://github.com/hoainho/img2threejs/releases/tag/v1.0.0
[1.4.3]: https://github.com/img2threejs/img2threejs/releases/tag/v1.4.3
