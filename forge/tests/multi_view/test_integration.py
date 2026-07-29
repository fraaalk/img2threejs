"""
Integration tests for multi-view synthesis pipeline.
"""

import pytest
from pathlib import Path
from forge.stage1b_multi_view.synthesize import synthesize_geometry_brief
from forge.stage1b_multi_view.integrate import (
    run_synthesis_for_intake,
    enhance_intake_record_with_synthesis,
    get_synthesis_summary,
)
from forge.stage1b_multi_view.brief_enhancer import (
    enhance_spec_with_brief,
    load_brief_from_file,
    get_brief_summary,
)
from forge.stage1b_multi_view.build_enhancer import (
    enhance_build_with_brief,
    generate_geometry_from_brief,
)
from forge.stage1b_multi_view.review_enhancer import (
    enhance_review_with_multi_view,
    compare_multi_view,
    aggregate_multi_view_scores,
)
from forge.stage1b_multi_view.hybrid_synthesis import (
    hybrid_synthesis,
    combine_results,
)


class TestIntegrate:
    """Tests for integration module."""

    def test_run_synthesis_for_intake_single_view(self):
        """Test synthesis for single view (should skip)."""
        from PIL import Image

        test_path = Path("/tmp/test_single_view.png")
        img = Image.new("RGB", (100, 100), (255, 255, 255))
        img.save(test_path)

        try:
            result = run_synthesis_for_intake([test_path], "Test Item")
            assert result["status"] == "skipped"
            assert result["viewCount"] == 1
        finally:
            test_path.unlink()

    def test_run_synthesis_for_intake_multiple_views(self):
        """Test synthesis for multiple views."""
        from PIL import Image

        test_paths = []
        for i in range(3):
            path = Path(f"/tmp/test_view_{i}.png")
            img = Image.new("RGB", (100, 100), (i * 80, i * 80, i * 80))
            img.save(path)
            test_paths.append(path)

        try:
            result = run_synthesis_for_intake(test_paths, "Test Item")
            assert result["status"] == "complete"
            assert result["viewCount"] == 3
        finally:
            for path in test_paths:
                path.unlink()

    def test_enhance_intake_record(self):
        """Test enhancing intake record with synthesis results."""
        intake_record = {"itemName": "Test Item"}
        synthesis_result = {
            "status": "complete",
            "viewCount": 3,
            "synthesisMode": "standard",
            "confidence": 0.7,
        }

        enhanced = enhance_intake_record_with_synthesis(intake_record, synthesis_result)
        assert "synthesis" in enhanced
        assert enhanced["synthesis"]["viewCount"] == 3

    def test_get_synthesis_summary(self):
        """Test getting synthesis summary."""
        result = {
            "status": "complete",
            "viewCount": 3,
            "synthesisMode": "standard",
            "confidence": 0.7,
        }

        summary = get_synthesis_summary(result)
        assert "3 views" in summary
        assert "standard" in summary


class TestBriefEnhancer:
    """Tests for brief enhancer module."""

    def test_enhance_spec_with_brief(self):
        """Test enhancing spec with brief."""
        spec = {"components": {"body": {"dimensions": {"width": 100}}}}
        brief = {
            "components": {
                "body": {
                    "dimensions": {"width": 150, "height": 50},
                    "curvature": "rounded",
                    "confidence": 0.9,
                }
            }
        }

        enhanced = enhance_spec_with_brief(spec, brief)
        assert "multiViewBrief" in enhanced
        assert enhanced["components"]["body"]["dimensions"]["width"] == 150

    def test_get_brief_summary(self):
        """Test getting brief summary."""
        brief = {
            "viewCount": 3,
            "synthesisMode": "standard",
            "confidence": 0.7,
            "components": {"body": {}, "handle": {}},
        }

        summary = get_brief_summary(brief)
        assert "3 views" in summary
        assert "2 components" in summary


class TestBuildEnhancer:
    """Tests for build enhancer module."""

    def test_enhance_build_with_brief(self):
        """Test enhancing build with brief."""
        build_config = {"components": {}}
        brief = {
            "components": {
                "body": {
                    "dimensions": {"width": 150, "height": 50},
                    "curvature": "rounded",
                    "confidence": 0.9,
                }
            }
        }

        enhanced = enhance_build_with_brief(build_config, brief)
        assert "multiViewBrief" in enhanced
        assert "body" in enhanced["components"]

    def test_generate_geometry_from_brief(self):
        """Test generating geometry from brief."""
        brief_data = {
            "dimensions": {"width": 100, "height": 50, "depth": 30},
            "curvature": "rounded",
        }

        code = generate_geometry_from_brief("testComponent", brief_data)
        assert "BoxGeometry" in code
        assert "testComponent" in code


class TestReviewEnhancer:
    """Tests for review enhancer module."""

    def test_enhance_review_with_multi_view(self):
        """Test enhancing review with multi-view data."""
        review_config = {}
        brief = {
            "viewCount": 3,
            "namedViews": {"front": "front.png", "back": "back.png", "top": "top.png"},
        }

        enhanced = enhance_review_with_multi_view(review_config, brief)
        assert "multiViewBrief" in enhanced
        assert "viewCoverage" in enhanced

    def test_aggregate_multi_view_scores(self):
        """Test aggregating multi-view scores."""
        per_view_results = {
            "front": {"status": "compared", "score": 0.8},
            "back": {"status": "compared", "score": 0.7},
            "top": {"status": "compared", "score": 0.6},
        }

        aggregated = aggregate_multi_view_scores(per_view_results)
        assert 0.6 <= aggregated <= 0.8


class TestHybridSynthesis:
    """Tests for hybrid synthesis module."""

    def test_hybrid_synthesis_single_view(self):
        """Test hybrid synthesis with single view."""
        from PIL import Image

        test_path = Path("/tmp/test_hybrid_single.png")
        img = Image.new("RGB", (100, 100), (255, 255, 255))
        img.save(test_path)

        try:
            result = hybrid_synthesis([test_path])
            assert result["viewCount"] == 1
        finally:
            test_path.unlink()

    def test_combine_results(self):
        """Test combining deterministic and agent results."""
        deterministic = {
            "viewCount": 3,
            "confidence": 0.6,
            "components": {"body": {"dimensions": {"width": 100}}},
        }
        agent = {
            "confidence": 0.8,
            "components": {"body": {"dimensions": {"width": 120}, "notes": "agent says wider"}},
        }

        combined = combine_results(deterministic, agent)
        assert combined["confidence"] > 0.6
        assert combined["components"]["body"]["dimensions"]["width"] == 120


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
