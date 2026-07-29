"""
Unit tests for multi-view synthesis modules.
"""

import pytest
from pathlib import Path
from forge.stage1b_multi_view.view_counter import (
    count_views,
    detect_named_views,
    group_duplicate_views,
    detect_view_angles,
)
from forge.stage1b_multi_view.feature_detector import detect_features
from forge.stage1b_multi_view.feature_matcher import match_features, match_pair
from forge.stage1b_multi_view.pose_estimator import estimate_relative_poses
from forge.stage1b_multi_view.depth_estimator import estimate_depth
from forge.stage1b_multi_view.synthesize import synthesize_geometry_brief


class TestViewCounter:
    """Tests for view counter module."""

    def test_count_views_single(self):
        """Test counting single view."""
        paths = [Path("front.png")]
        assert count_views(paths) == 1

    def test_count_views_multiple(self):
        """Test counting multiple views."""
        paths = [Path("front.png"), Path("back.png"), Path("top.png")]
        assert count_views(paths) == 3

    def test_detect_named_views(self):
        """Test detecting named views from filenames."""
        paths = [
            Path("controller-front.png"),
            Path("controller-back.png"),
            Path("controller-top.png"),
        ]
        result = detect_named_views(paths)
        assert "front" in result
        assert "back" in result
        assert "top" in result

    def test_group_duplicate_views(self):
        """Test grouping duplicate views."""
        paths = [
            Path("front.png"),
            Path("front-angle.png"),
            Path("back.png"),
        ]
        named_views = detect_named_views(paths)
        grouped = group_duplicate_views(paths, named_views)
        # Should group front and front-angle together
        assert len(grouped) == 2

    def test_detect_view_angles(self):
        """Test detecting view angles."""
        named_views = {
            "front": Path("front.png"),
            "back": Path("back.png"),
            "top": Path("top.png"),
        }
        angles = detect_view_angles(named_views)
        assert angles.get("front") == 0
        assert angles.get("back") == 180
        assert angles.get("top") == 90


class TestFeatureDetector:
    """Tests for feature detector module."""

    def test_detect_features_edge(self):
        """Test edge feature detection (no OpenCV dependency)."""
        # Create a simple test image
        from PIL import Image, ImageDraw

        # Create test image with edges
        img = Image.new("L", (100, 100), 0)
        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, 90, 90], fill=255)

        # Save temporarily
        test_path = Path("/tmp/test_image.png")
        img.save(test_path)

        try:
            features = detect_features(test_path, method="edge")
            assert features.feature_count > 0
            assert features.detection_method == "edge"
        finally:
            test_path.unlink()


class TestFeatureMatcher:
    """Tests for feature matcher module."""

    def test_match_features_empty(self):
        """Test matching with no features."""
        from forge.stage1b_multi_view.feature_detector import FeatureSet

        features1 = FeatureSet(
            features=[],
            image_path=Path("test1.png"),
            feature_count=0,
            detection_method="none",
        )
        features2 = FeatureSet(
            features=[],
            image_path=Path("test2.png"),
            feature_count=0,
            detection_method="none",
        )

        all_features = {"view1": features1, "view2": features2}
        results = match_features(all_features)
        # Should have one result (for the pair) but with 0 matches
        assert len(results) == 1
        for key, result in results.items():
            assert result.match_count == 0


class TestPoseEstimator:
    """Tests for pose estimator module."""

    def test_estimate_relative_poses_empty(self):
        """Test pose estimation with no matches."""
        result = estimate_relative_poses({})
        assert len(result.poses) == 0
        assert len(result.relative_poses) == 0


class TestDepthEstimator:
    """Tests for depth estimator module."""

    def test_estimate_depth_empty(self):
        """Test depth estimation with no matches."""
        from forge.stage1b_multi_view.pose_estimator import PoseEstimationResult

        pose_result = PoseEstimationResult(
            poses={},
            relative_poses={},
            confidence=0.0,
        )
        result = estimate_depth({}, pose_result)
        assert len(result.depth_maps) == 0
        assert len(result.point_cloud) == 0


class TestSynthesize:
    """Tests for main synthesis module."""

    def test_synthesize_single_view(self):
        """Test synthesis with single view."""
        # Create a simple test image
        from PIL import Image

        test_path = Path("/tmp/test_single.png")
        img = Image.new("RGB", (100, 100), (255, 255, 255))
        img.save(test_path)

        try:
            brief = synthesize_geometry_brief([test_path])
            assert brief["viewCount"] == 1
            assert brief["synthesisMode"] == "single-view"
            assert brief["confidence"] == 0.3
        finally:
            test_path.unlink()

    def test_synthesize_multiple_views(self):
        """Test synthesis with multiple views."""
        from PIL import Image

        # Create test images
        test_paths = []
        for i in range(3):
            path = Path(f"/tmp/test_view_{i}.png")
            img = Image.new("RGB", (100, 100), (i * 80, i * 80, i * 80))
            img.save(path)
            test_paths.append(path)

        try:
            brief = synthesize_geometry_brief(test_paths)
            assert brief["viewCount"] == 3
            assert brief["synthesisMode"] == "standard"
            assert brief["confidence"] > 0.5
        finally:
            for path in test_paths:
                path.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
