# CS2 family review gates

The review contract is owned by `forge/stage4_review/cs2_review.py`. It consumes a
validated manifest, render metrics, painted-region results, projection coverage,
critical-feature scores, and two orbit results. It emits a machine-readable report
with family, route, exactness tier, scene metadata, per-region confidence,
approximation notes, and failed gates.

The versioned fixture is family-owned; the current knife fixture is `forge/tests/fixtures/knife_review_scene.json`. It records
the camera, object transform, environment hash, exposure, tone mapping, resolution, background,
renderer version, visible regions, critical features, and frozen initial thresholds:

- silhouette IoU: at least `0.85`
- aspect-ratio delta: at most `0.05`
- scale delta: at most `0.08`
- projection coverage: at least `0.85` when projection is required
- finish/material response and identity detail: at least `0.80`
- painted-region score: at least `0.80`
- orbit collapse ratio: `0.15` maximum

These thresholds are fixture data, not caller-supplied prose. They are blocking for
each calibrated production family. A wrong family, missing adapter, missing projection evidence,
insufficient coverage, critical-feature failure, or degenerate orbit cannot be
overridden by a global visual score.

The fixture records calibration status and positive/negative render references. A family cannot
return `pass` or `continue` while calibration is incomplete. `calibrate_eye.py` must be run on
both classes before new family thresholds are treated as empirically calibrated.

Attach a report to the normal review record with:

```sh
python3 forge/stage4_review/append_review.py object-sculpt-spec.json \
  --pass-id material-pass --fidelity 0.9 --action continue --summary "knife review passed" \
  --cs2-review-json cs2-review.json \
  --review-scene-json forge/tests/fixtures/knife_review_scene.json --in-place
```

`append_review.py` rejects `action=continue` when the attached report is not a
passing family review or when its scene fixture does not match. The report retains
single-view limitations: hidden-region confidence and approximation notes are
required evidence, not an exactness claim.

The fixture metadata labels the image as `user-supplied-review-required`. Do not
mark it rights-safe or commit extracted Valve pixels until provenance is verified.
Local extraction remains outside the repository under the existing `cs2_textures/`
IP boundary. Browser capture remains the responsibility of `runtime/cs2-preview`;
the Python review gate accepts its metrics and screenshots but does not pretend to
render them.
