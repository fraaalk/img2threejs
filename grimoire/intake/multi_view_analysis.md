# Multi-View Analysis Protocol

## Overview

This protocol defines how to analyze multiple reference images and preserve evidence for procedural 3D authoring. It supports variable view counts (1 to N views) with adaptive processing.

## Current Bounded Behavior

`forge/stage1b_multi_view/synthesize.py` is deliberately fail-closed. With ordinary uncalibrated photos it returns an `evidence-only` brief, not metric component dimensions or an automatic mesh. With verified `cameraMatrix`, `focalLengthPx`, and `baselineUnits`, it can emit a bounded calibrated depth envelope. `new_pre_spec_assessment.py` accepts repeatable `--image` arguments, stores every path in `sourceImages`, and carries the brief through `new_sculpt_spec.py`. Do not describe uncalibrated evidence extraction as photogrammetry.

## When To Use

Use this protocol when:
- Multiple reference images are provided (2+ views)
- The user wants to reconstruct an object from multiple angles
- High-fidelity reconstruction is required
- Single-view analysis is insufficient

## Protocol Steps

### Step 1: View Inventory

1. **Count views**: Determine how many images are provided
2. **Identify views**: Detect named views (front, back, top, etc.) first. Preserve `three-quarter`/`iso`/`oblique` observations and their visible direction tokens rather than collapsing them into a front view. A bare `side` is valid evidence but carries no inferred left/right angle. For readable unnamed PNGs, group simple luminance signatures into `auto-*` view clusters; those labels are not semantic front/back claims.
3. **Group duplicate candidates**: If multiple captures have the same semantic view label, retain the higher-quality file. This is not pixel-level duplicate detection; reference admission owns the stricter image-duplicate check.
4. **Determine evidence coverage**: Preserve every distinct view and record what each reveals.
   - 1 view: skip synthesis and mark hidden surfaces as unknown
   - 2+ views: run evidence-only synthesis and keep named/duplicate view provenance
   - calibrated capture: only then promote pose/depth estimates into dimensions

### Step 2: Feature Detection

For each view:
1. **Detect features**: Find distinctive visual features (edges, corners, blobs)
2. **Extract descriptors**: Create feature descriptors for matching
3. **Quality assessment**: Rate feature quality and coverage

### Step 3: Cross-View Matching

1. **Match features**: Find corresponding features between view pairs
2. **Filter matches**: Remove outlier matches using ratio test
3. **Calculate confidence**: Rate match quality based on count and quality

### Step 4: Pose Estimation

1. **Estimate relative poses**: Compute camera positions relative to each other
2. **Calculate baseline**: Determine distance between camera positions
3. **Assess accuracy**: Rate pose estimation confidence

### Step 5: Depth Estimation

1. **Check calibration first**: require known intrinsics/baseline or an explicit calibrated solver result
2. **Triangulate points only when calibrated**: otherwise retain match evidence without depth claims
3. **Keep confidence bounded**: uncalibrated cues cannot become metric dimensions

### Step 6: Geometry Synthesis

1. **Extract dimensions only from calibrated 3D data or agent-authored measurements**
2. **Attach curvature only when its evidence is explicit**
3. **Generate an evidence brief**: include per-component confidence and unknowns

## Output Format

The protocol produces a geometry brief with:

```json
{
  "viewCount": 6,
  "synthesisMode": "full",
  "confidence": 0.49,
  "status": "evidence-only",
  "namedViews": {
    "front": "path/to/front.png",
    "back": "path/to/back.png"
  },
  "components": {
    "componentName": {
      "visibleIn": ["front", "top"],
      "dimensions": {"width": 100, "height": 50},
      "curvature": "description",
      "confidence": 0.9
    }
  }
}
```

## Edge Cases

### Single View
- Skip synthesis
- Use code-written geometry
- Return minimal brief with low confidence

### Low-Texture Surfaces
- Use edge detection instead of feature matching
- Rely on contour matching
- Reduce confidence scores

### Misaligned Views
- Use robust matching with RANSAC
- Filter outlier matches
- Report reduced confidence

### Contradictory Views
- Do not average incompatible dimensions into a fictional object.
- Select and record a metric authority: a calibrated view or an independently measured real-world prior.
- Record each conflicting observation as an explicit assumption, including the affected component and confidence.
- Return `request-input` when no authority can reconcile the disagreement at the requested fidelity.

### Partial Overlap
- Identify overlapping regions
- Only match features in overlap areas
- Mark non-overlapping components as low confidence

## Quality Gates

### Evidence-only (default)

Before proceeding to spec generation:
- [ ] View count detected correctly
- [ ] Features detected in all views
- [ ] Matches found between view pairs
- [ ] Geometry brief created with bounded confidence scores and unknown surfaces recorded
- [ ] No metric dimensions or calibrated-depth claim was made

### Calibrated metric envelope (additional)

- [ ] Verified intrinsics and baseline were supplied
- [ ] Metric solver support is available in the runtime environment
- [ ] Poses estimated with reasonable accuracy
- [ ] Depth data generated and its confidence recorded

## Integration Points

### With Intake
- Call `run_synthesis_for_intake()` during intake processing
- Add synthesis result to intake record
- Use synthesis mode to guide further processing

### With Spec
- Pass geometry brief to spec generation
- Use brief dimensions for component definitions
- Incorporate confidence scores into spec

### With Build
- Use brief dimensions for geometry generation
- Apply curvature data to surface profiles
- Generate brief-aware Three.js code

### With Review
- Compare against all provided views
- Aggregate scores across views
- Report per-view breakdown
- For the PS5 iteration target, record baseline and multi-view review artifacts in a release-evidence JSON and validate it with `validate_release_evidence.py`; do not claim the target from synthetic tests.

## References

- `forge/stage1b_multi_view/synthesize.py` - Main synthesis module
- `forge/stage1b_multi_view/view_counter.py` - View counting and detection
- `forge/stage1b_multi_view/feature_detector.py` - Feature detection
- `forge/stage1b_multi_view/feature_matcher.py` - Feature matching
- `forge/stage1b_multi_view/pose_estimator.py` - Pose estimation
- `forge/stage1b_multi_view/depth_estimator.py` - Depth estimation
