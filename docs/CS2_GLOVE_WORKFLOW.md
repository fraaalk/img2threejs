# CS2 Sport Gloves workflow

This checkout implements a diagnostic v2 path for one narrow target: static, full-finger
`sport-gloves`, normalized scale, canonical-left geometry plus a derived right hand. It now emits
canonical triangle meshes with measured non-zero thickness and a portable content-addressed bundle.
The current normalized fixture remains diagnostic-only: its panel seams are not physically welded,
its source controls are not evidence-derived, and it cannot return `ready`.

## Reproducible commands

From `img2/`:

```bash
python3 forge/tests/fixtures/glove_sport_v1/build_fixture.py
python3 forge/tests/run_glove_e2e.py --fixture golden --expect reject --out-dir /tmp/img2-glove-diagnostic
python3 forge/tests/run_glove_e2e.py --suite seeded-negative --expect reject --out-dir /tmp/img2-glove-negative
```

The four required intake roles are `dorsal`, `palmar`, `thumb-side-profile`, and
`three-quarter`. A missing or unreadable required view remains `request-input` and is intake-only;
it must not create a spec, geometry, runtime capture, or ready verdict. Without verified camera
calibration, the output is normalized/evidence-only.

The diagnostic run writes `cs2-intake.v1.json`, `pre-spec-assessment.v1.json`,
`object-sculpt-spec.json`, `glove-model-bundle.v2.json`, `geometry-report.v2.json`, a pending
`capture-plan.v2.json`, and `glove-review-report.v2.json`. The runtime loads the verified factory
and payloads, but a browser bridge must still attach real PNG evidence before a v2 capture manifest
can be finalized. Calibration likewise requires a separately admitted evidence-backed positive
artifact plus named artifact-level negatives; the v1 measurement JSON is deliberately rejected.
