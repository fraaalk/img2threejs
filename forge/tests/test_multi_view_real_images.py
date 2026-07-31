#!/usr/bin/env python3
"""Test multi-view synthesis with real M9 Bayonet images.

This test verifies the pipeline works with actual reference images,
not just mock data. Run with: python -m pytest forge/tests/test_multi_view_real_images.py -v
"""

import sys
from pathlib import Path

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from forge.stage1b_multi_view.synthesize import synthesize_geometry_brief
from forge.stage1b_multi_view.view_counter import detect_named_views


# Fixture images
FIXTURES_DIR = Path(__file__).parent / "fixtures"
FRONT_IMAGE = FIXTURES_DIR / "m9-front.webp"
BACK_IMAGE = FIXTURES_DIR / "m9-back.webp"


@pytest.fixture(scope="module")
def real_images_exist():
    """Check if real fixture images exist."""
    if not FRONT_IMAGE.exists() or not BACK_IMAGE.exists():
        pytest.skip("Real fixture images not found")
    return True


@pytest.fixture(scope="module")
def synthesis_result(real_images_exist):
    """Run synthesis with real images."""
    return synthesize_geometry_brief(
        image_paths=[FRONT_IMAGE, BACK_IMAGE]
    )


class TestRealImageSynthesis:
    """Test synthesis with real M9 Bayonet images."""

    def test_view_detection(self, real_images_exist):
        """Test that front/back views are detected from real filenames."""
        views = detect_named_views([FRONT_IMAGE, BACK_IMAGE])
        assert "front" in views, "Front view not detected"
        assert "back" in views, "Back view not detected"

    def test_opposing_views_detected(self, synthesis_result):
        """Test that real images are identified as opposing views."""
        assert synthesis_result["synthesisMode"] == "opposing-views"

    def test_confidence_is_silhouette_based(self, synthesis_result):
        """Test that confidence uses silhouette-based scoring (not feature matching)."""
        confidence = synthesis_result["confidence"]
        # Silhouette-based confidence should be > 0.8
        # Feature matching would fail (confidence ~0.02)
        assert confidence > 0.8, f"Confidence {confidence} too low for silhouette-based"

    def test_status_is_complete(self, synthesis_result):
        """Test that status is 'complete' (not 'evidence-only')."""
        assert synthesis_result["status"] == "complete"

    def test_two_views_recognized(self, synthesis_result):
        """Test that exactly 2 views are recognized."""
        assert synthesis_result["viewCount"] == 2
        assert len(synthesis_result["namedViews"]) == 2

    def test_named_views_correct(self, synthesis_result):
        """Test that named views are front and back."""
        named_views = set(synthesis_result["namedViews"].keys())
        assert named_views == {"front", "back"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
