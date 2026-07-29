"""
Multi-View Synthesis Module

Synthesizes 3D geometry information from multiple reference images.
Supports variable view counts (1 to N views) with adaptive processing.

Usage:
    python synthesize.py <image_paths> [--output <output_path>]

Example:
    python synthesize.py front.png back.png top.png --output geometry_brief.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any

from .view_counter import count_views, detect_named_views, group_duplicate_views
from .feature_detector import detect_features
from .feature_matcher import match_features
from .pose_estimator import estimate_relative_poses
from .depth_estimator import estimate_depth


def synthesize_geometry_brief(
    image_paths: List[Path],
    output_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Synthesize geometry brief from multiple reference images.

    Args:
        image_paths: List of paths to reference images
        output_path: Optional path to save the geometry brief

    Returns:
        Geometry brief dictionary with per-component dimensions and confidence
    """
    # Step 1: Count and analyze views
    input_view_count = len(image_paths)
    named_views = detect_named_views(image_paths)
    grouped_views = group_duplicate_views(image_paths, named_views)
    view_count = len(grouped_views)

    # Step 2: Handle single-view fallback
    if input_view_count == 1:
        return _generate_minimal_brief(image_paths[0])

    # Step 3: Detect features in each view
    all_features = {}
    for view_name, path in grouped_views.items():
        features = detect_features(path)
        all_features[view_name] = features

    # Step 4: Match features across views
    match_results = match_features(all_features)

    # Step 5: Estimate relative poses
    poses = estimate_relative_poses(match_results)

    # Step 6: Estimate depth from parallax
    depth_data = estimate_depth(match_results, poses)

    # Step 7: Generate geometry brief
    brief = _generate_geometry_brief(
        view_count=view_count,
        input_view_count=input_view_count,
        named_views=named_views,
        grouped_views=grouped_views,
        features=all_features,
        matches=match_results,
        poses=poses,
        depth=depth_data,
    )

    # Step 8: Save if output path provided
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(brief, f, indent=2)

    return brief


def _generate_minimal_brief(image_path: Path) -> Dict[str, Any]:
    """Generate minimal geometry brief for single-view input."""
    return {
        "viewCount": 1,
        "synthesisMode": "single-view",
        "confidence": 0.3,
        "components": {},
        "notes": "Single view provided - using code-written geometry"
    }


def _generate_geometry_brief(
    view_count: int,
    input_view_count: int,
    named_views: Dict[str, Path],
    grouped_views: Dict[str, Path],
    features: Dict[str, List],
    matches: Dict,
    poses: Dict,
    depth: Dict,
) -> Dict[str, Any]:
    """Generate comprehensive geometry brief from synthesis results."""
    # View count determines processing capacity, not confidence. Confidence
    # must be earned by observable feature, match, pose and depth evidence.
    if view_count <= 2:
        mode = "basic"
    elif view_count <= 4:
        mode = "standard"
    elif view_count <= 6:
        mode = "full"
    else:
        mode = "optimal"
    pair_count = max(1, len(matches))
    matched_pairs = [match for match in matches.values() if match.match_count > 0]
    feature_coverage = (
        sum(1 for feature_set in features.values() if feature_set.feature_count > 0)
        / max(1, len(grouped_views))
    )
    match_coverage = len(matched_pairs) / pair_count
    match_confidence = (
        sum(match.confidence for match in matched_pairs) / len(matched_pairs)
        if matched_pairs else 0.0
    )
    pose_confidence = poses.confidence
    depth_confidence = depth.confidence
    evidence_confidence = (
        0.20 * feature_coverage
        + 0.30 * match_coverage
        + 0.25 * match_confidence
        + 0.15 * pose_confidence
        + 0.10 * depth_confidence
    )
    # No calibrated depth or component reconstruction is emitted yet. Cap the
    # result so downstream stages cannot mistake feature evidence for a
    # metric geometry solution.
    confidence = min(0.49, evidence_confidence)

    return {
        "viewCount": view_count,
        "inputViewCount": input_view_count,
        "duplicateViewCount": max(0, input_view_count - view_count),
        "synthesisMode": mode,
        "confidence": round(confidence, 4),
        "status": "evidence-only",
        "namedViews": {k: str(v) for k, v in named_views.items()},
        "featureCount": {k: v.feature_count for k, v in features.items()},
        "matchCount": sum(m.match_count for m in matches.values()) if matches else 0,
        "evidence": {
            "featureCoverage": round(feature_coverage, 4),
            "matchCoverage": round(match_coverage, 4),
            "matchConfidence": round(match_confidence, 4),
            "poseConfidence": round(pose_confidence, 4),
            "depthConfidence": round(depth_confidence, 4),
            "calibratedDepthAvailable": bool(depth.point_cloud),
        },
        "components": {},
        "notes": (
            f"Multi-view evidence extraction with {view_count} unique views. "
            "No metric component geometry has been synthesized."
        ),
    }


def main():
    """CLI entry point for multi-view synthesis."""
    parser = argparse.ArgumentParser(
        description="Synthesize 3D geometry from multiple reference images"
    )
    parser.add_argument(
        "images",
        nargs="+",
        help="Paths to reference images"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output path for geometry brief JSON"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )

    args = parser.parse_args()

    # Convert to Path objects
    image_paths = [Path(p) for p in args.images]

    # Validate images exist
    for path in image_paths:
        if not path.exists():
            print(f"Error: Image not found: {path}", file=sys.stderr)
            sys.exit(1)

    # Run synthesis
    try:
        brief = synthesize_geometry_brief(image_paths, args.output)
        if args.verbose:
            print(json.dumps(brief, indent=2))
        else:
            print(f"Synthesis complete: {brief['viewCount']} views, "
                  f"mode={brief['synthesisMode']}, "
                  f"confidence={brief['confidence']:.2f}")
    except Exception as e:
        print(f"Error during synthesis: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
