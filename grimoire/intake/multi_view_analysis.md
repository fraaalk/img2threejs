# Multi-View Analysis Protocol

## Overview

This protocol defines how to analyze multiple reference images and synthesize 3D geometry information. It supports variable view counts (1 to N views) with adaptive processing.

## When To Use

Use this protocol when:
- Multiple reference images are provided (2+ views)
- The user wants to reconstruct an object from multiple angles
- High-fidelity reconstruction is required
- Single-view analysis is insufficient

## Protocol Steps

### Step 1: View Inventory

1. **Count views**: Determine how many images are provided
2. **Identify views**: Detect named views (front, back, top, etc.) or auto-detect angles
3. **Group duplicates**: If multiple angles of same view exist, group them
4. **Determine mode**: Based on view count, select synthesis mode:
   - 1 view: Skip synthesis, use code-written geometry
   - 2 views: Basic synthesis
   - 3-4 views: Standard synthesis
   - 5-6 views: Full synthesis
   - 7+ views: Optimal synthesis

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

1. **Triangulate points**: Compute 3D positions from matched features
2. **Generate depth maps**: Create depth information for each view
3. **Merge point clouds**: Combine depth data into unified 3D representation

### Step 6: Geometry Synthesis

1. **Extract dimensions**: Determine component sizes from 3D data
2. **Estimate curvature**: Compute surface curvature from point clouds
3. **Generate brief**: Create geometry brief with per-component confidence

## Output Format

The protocol produces a geometry brief with:

```json
{
  "viewCount": 6,
  "synthesisMode": "full",
  "confidence": 0.85,
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

### Partial Overlap
- Identify overlapping regions
- Only match features in overlap areas
- Mark non-overlapping components as low confidence

## Quality Gates

Before proceeding to spec generation:
- [ ] View count detected correctly
- [ ] Features detected in all views
- [ ] Matches found between view pairs
- [ ] Poses estimated with reasonable accuracy
- [ ] Depth data generated
- [ ] Geometry brief created with confidence scores

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

## References

- `forge/stage1b_multi_view/synthesize.py` - Main synthesis module
- `forge/stage1b_multi_view/view_counter.py` - View counting and detection
- `forge/stage1b_multi_view/feature_detector.py` - Feature detection
- `forge/stage1b_multi_view/feature_matcher.py` - Feature matching
- `forge/stage1b_multi_view/pose_estimator.py` - Pose estimation
- `forge/stage1b_multi_view/depth_estimator.py` - Depth estimation
