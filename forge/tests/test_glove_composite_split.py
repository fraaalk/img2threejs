"""The composite splitter: what it separates, what it rejects, and what it records.

Nothing tested this when it landed, and it is the step every marketplace image has to pass through, with
three ways to be quietly wrong: a caption band admitted as a view, a watermark tile admitted as a view, and
a backdrop carried into the crop so the plate is refused downstream as not isolable.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from forge.stage1_intake.check_reference_admission import check_admission
from forge.stage1_intake.extract_pbr_evidence import load_image
from forge.stage1_intake.split_composite_plate import (
    NEUTRAL_BACKDROP,
    find_view_regions,
    split_composite,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "glove_hydra_v1"
COMPOSITE = FIXTURE / "composite.png"


class CompositeSplitTests(unittest.TestCase):
    def test_the_caption_band_and_the_watermark_are_not_views(self):
        """Two views, and the band and the tiles are rejected for their own stated reasons.

        The band is rejected by SHAPE -- wide and short -- rather than by position, so a listing that puts
        its caption somewhere else still splits. The watermark tiles are rejected by area.
        """
        regions, meta = find_view_regions(COMPOSITE, 2)
        self.assertEqual(len(regions), 2)
        reasons = sorted({item["rejectedAs"] for item in meta["rejected"]})
        self.assertIn("caption band", reasons)
        self.assertIn("speckle or watermark tile", reasons)
        # Top-to-bottom, so `--roles dorsal palmar` means what a reader of the image would expect.
        self.assertLess(regions[0]["y0"], regions[1]["y0"])

    def test_asking_for_the_wrong_number_of_views_is_a_named_failure(self):
        with self.assertRaises(ValueError) as raised:
            find_view_regions(COMPOSITE, 3)
        self.assertIn("expected 3", str(raised.exception))

    def test_each_plate_is_distinct_and_admissible(self):
        """Distinct content, because one path submitted twice sets `duplicateOfHash` and is refused.

        And admissible, which is the whole reason the backdrop is replaced: a crop keeping a saturated navy
        backdrop reports `foregroundCoverage 1.000` and `check_reference_admission` rejects it as having no
        background to segment against.
        """
        with self.subTest("written"):
            records = split_composite(COMPOSITE, FIXTURE / "plates", ["dorsal", "palmar"])
        self.assertEqual([record["role"] for record in records], ["dorsal", "palmar"])
        self.assertNotEqual(records[0]["cropSha256"], records[1]["cropSha256"])
        for record in records:
            with self.subTest(role=record["role"]):
                admission = check_admission(Path(record["path"]))
                self.assertTrue(admission["admitted"], admission.get("reasons"))
                self.assertLess(admission["provenance"]["foregroundCoverage"], 0.97)

    def test_the_backdrop_replacement_is_recorded_and_actually_applied(self):
        """A pixel change nobody can reconstruct from the record is the defect this exists to avoid."""
        records = split_composite(COMPOSITE, FIXTURE / "plates", ["dorsal", "palmar"])
        replaced = records[0]["backdropReplaced"]
        self.assertEqual(tuple(replaced["to"]), NEUTRAL_BACKDROP)
        self.assertNotEqual(tuple(replaced["from"]), NEUTRAL_BACKDROP)
        self.assertIsInstance(replaced["subjectThreshold"], float)
        self.assertTrue(replaced["rule"].strip())
        # The corner of the emitted plate is the neutral value, not the listing's backdrop.
        _width, _height, pixels, _warnings = load_image(Path(records[0]["path"]))
        self.assertEqual(pixels[0][:3], NEUTRAL_BACKDROP)

    def test_the_crop_rectangle_locates_the_plate_inside_its_source(self):
        records = split_composite(COMPOSITE, FIXTURE / "plates", ["dorsal", "palmar"])
        source_width, source_height, _pixels, _warnings = load_image(COMPOSITE)
        for record in records:
            with self.subTest(role=record["role"]):
                rect = record["cropRect"]
                self.assertGreaterEqual(rect["x"], 0)
                self.assertGreaterEqual(rect["y"], 0)
                self.assertLessEqual(rect["x"] + rect["width"], source_width)
                self.assertLessEqual(rect["y"] + rect["height"], source_height)
                emitted_width, emitted_height, _px, _w = load_image(Path(record["path"]))
                self.assertEqual((emitted_width, emitted_height), (rect["width"], rect["height"]))
                self.assertEqual(record["sourceImage"], COMPOSITE.resolve().as_posix())


if __name__ == "__main__":
    unittest.main()
