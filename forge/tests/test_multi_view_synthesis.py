"""Regression tests for the fail-closed multi-view synthesis pipeline."""

from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from forge.stage1b_multi_view.brief_enhancer import enhance_spec_with_brief
from forge.stage1b_multi_view.build_enhancer import enhance_build_with_brief
from forge.stage1b_multi_view.depth_estimator import estimate_depth
from forge.stage1b_multi_view.feature_detector import Feature
from forge.stage1b_multi_view.feature_matcher import FeatureMatch, MatchResult
from forge.stage1b_multi_view.integrate import (
    enhance_intake_record_with_synthesis,
    run_synthesis_for_intake,
)
from forge.stage1b_multi_view.pose_estimator import CameraPose, PoseEstimationResult
from forge.stage1b_multi_view.review_enhancer import (
    aggregate_multi_view_scores,
    compare_multi_view,
)
from forge.stage1b_multi_view.synthesize import synthesize_geometry_brief
from forge.stage1b_multi_view.view_counter import detect_named_views


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def write_rgb_png(path: Path, width: int, height: int, pixel_fn) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind)
        checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    scanlines = bytearray()
    for y in range(height):
        scanlines.append(0)
        for x in range(width):
            scanlines.extend(pixel_fn(x, y))
    path.write_bytes(
        PNG_SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(scanlines), 9))
        + chunk(b"IEND", b"")
    )


def block_image(path: Path, offset: int = 0) -> None:
    write_rgb_png(
        path,
        64,
        64,
        lambda x, y: (200, 40, 40)
        if 12 + offset <= x < 52 + offset and 12 <= y < 52
        else (255, 255, 255),
    )


class ViewCounterTests(unittest.TestCase):
    def test_token_boundaries_prevent_false_view_names(self) -> None:
        result = detect_named_views([Path("frontier.png"), Path("leftover.png")])
        self.assertEqual(set(result), {"frontier", "leftover"})

    def test_repeated_named_views_are_preserved(self) -> None:
        result = detect_named_views(
            [Path("dragon-front.png"), Path("dragon-front-detail.png")]
        )
        self.assertEqual(set(result), {"front", "front-2"})


class SynthesisTests(unittest.TestCase):
    def test_multiple_views_report_evidence_not_metric_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / f"view-{index}.png" for index in range(3)]
            for index, path in enumerate(paths):
                block_image(path, index)

            brief = synthesize_geometry_brief(paths)

        self.assertEqual(brief["status"], "evidence-only")
        self.assertLess(brief["confidence"], 0.5)
        self.assertEqual(brief["components"], {})
        self.assertFalse(brief["evidence"]["calibratedDepthAvailable"])

    def test_intake_status_is_not_false_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / f"view-{index}.png" for index in range(2)]
            for index, path in enumerate(paths):
                block_image(path, index)
            result = run_synthesis_for_intake(paths, "Test Item")

        self.assertEqual(result["status"], "evidence-only")


class ReviewTests(unittest.TestCase):
    def test_identical_images_use_real_evaluator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.png"
            render = root / "render.png"
            block_image(reference)
            block_image(render)

            result = compare_multi_view(
                {"front-primary": render},
                {"front-primary": reference},
            )

        self.assertTrue(result["complete"])
        self.assertTrue(result["passed"])
        self.assertGreater(result["aggregatedScore"], 0.9)
        self.assertEqual(
            result["perViewResults"]["front-primary"]["status"],
            "compared",
        )

    def test_missing_view_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "front.png"
            render = root / "front-render.png"
            rear = root / "rear.png"
            block_image(reference)
            block_image(render)
            block_image(rear)

            result = compare_multi_view(
                {"front-primary": render},
                {"front-primary": reference, "rear": rear},
            )

        self.assertFalse(result["complete"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["missingViews"], ["rear"])
        self.assertEqual(result["worstView"], "rear")
        self.assertEqual(result["worstScore"], 0.0)
        self.assertLessEqual(result["aggregatedScore"], 0.5)

    def test_aggregation_counts_missing_or_error_views(self) -> None:
        score = aggregate_multi_view_scores(
            {
                "front-primary": {"status": "compared", "score": 0.9},
                "rear": {"status": "missing", "score": 0.0},
            }
        )
        self.assertAlmostEqual(score, 0.45)


class CalibrationTests(unittest.TestCase):
    def test_uncalibrated_pose_does_not_generate_depth(self) -> None:
        match = FeatureMatch(Feature(10, 10), Feature(15, 10), 5, 0.9)
        match_result = MatchResult("front", "side", [match], 3, 0.9)
        pose = CameraPose(
            rotation=(0, 0, 0),
            translation=(0.1, 0, 0),
            confidence=0.9,
            view_name="side",
            calibrated=False,
        )
        poses = PoseEstimationResult(
            poses={},
            relative_poses={("front", "side"): pose},
            confidence=0.9,
        )

        result = estimate_depth(
            {("front", "side"): match_result},
            poses,
            focal_length_px=1000,
            baseline_units=0.1,
        )

        self.assertEqual(result.point_cloud, [])
        self.assertEqual(result.confidence, 0.0)


class MutationTests(unittest.TestCase):
    def test_enhancers_do_not_mutate_callers(self) -> None:
        brief = {
            "viewCount": 3,
            "components": {"body": {"dimensions": {"width": 150}}},
        }
        spec = {"components": {"body": {"dimensions": {"width": 100}}}}
        build = {"components": {}}
        intake = {"itemName": "Test"}

        enhanced_spec = enhance_spec_with_brief(spec, brief)
        enhanced_build = enhance_build_with_brief(build, brief)
        enhanced_intake = enhance_intake_record_with_synthesis(
            intake,
            {"status": "evidence-only", "brief": brief},
        )

        self.assertEqual(spec["components"]["body"]["dimensions"]["width"], 100)
        self.assertEqual(build, {"components": {}})
        self.assertEqual(intake, {"itemName": "Test"})
        self.assertEqual(
            enhanced_spec["components"]["body"]["dimensions"]["width"],
            150,
        )
        self.assertIn("body", enhanced_build["components"])
        self.assertIn("synthesis", enhanced_intake)


if __name__ == "__main__":
    unittest.main()
