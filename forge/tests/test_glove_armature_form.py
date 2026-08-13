"""The armature must be shaped like a hand, asserted against the model rather than a picture.

These are the properties the silhouette inflation could not have, and they are the ones a reviewer
looking at a render actually complains about: four separate digits, a thumb that leaves the plane of
the fingers, and digits with a round cross-section rather than a flat one.

Every check queries the signed-distance field directly instead of the polygonised mesh, because a mesh
measurement at this scale reports the grid rather than the form: an inter-digit groove and one voxel
are the same size, so counting clusters of mesh vertices with a distance threshold measures the cell
size. Asking the field is resolution-independent.

Each of these has already failed on real code in this repository:
  * `test_four_digits_are_separate` -- deriving the digit radius as a quarter of the measured row width
    left adjacent surfaces zero apart, and the smooth union fused them into one mitten.
  * `test_the_thumb_leaves_the_plane_of_the_fingers` -- the inflation's thumb z range sat inside the
    palm's, which is what made every angle read as a puffed sticker.
  * `test_digits_are_round_in_cross_section` -- the inflation's digits measured 0.13-0.18 deep per unit
    wide, where a finger is about 1.0.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from forge._shared.glove_armature import DIGITS, build_glove_sdf_descriptor
from forge._shared.glove_silhouette import measure_silhouette
from forge._shared.sdf_mesh import sample_sdf

FIXTURE = Path(__file__).parent / "fixtures" / "glove_sport_v1" / "dorsal.png"
# Fine enough that a groove several hundredths of a unit wide cannot be stepped over.
LINE_SAMPLES = 1200
# Heights swept across the digit band, and how many consecutive ones must show four separate digits.
SWEEP_SAMPLES = 21
MIN_SEPARATED_SWEEP = 8


def _solid_runs(sdf, start, end, samples: int = LINE_SAMPLES) -> list[float]:
    """Widths of the solid intervals a straight line crosses, in model units."""
    step = [(end[axis] - start[axis]) / (samples - 1) for axis in range(3)]
    length = sum(value * value for value in step) ** 0.5
    runs: list[float] = []
    current = 0
    for index in range(samples):
        point = tuple(start[axis] + step[axis] * index for axis in range(3))
        if sdf(point) < 0.0:
            current += 1
        elif current:
            runs.append(current * length)
            current = 0
    if current:
        runs.append(current * length)
    return runs


class GloveArmatureFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _mask, cls.measured = measure_silhouette(FIXTURE)
        cls.body = build_glove_sdf_descriptor(cls.measured, hand="left", source_view_id="glove-view-1-dorsal")["sdf"]
        # staticmethod, or attribute access turns the field into a bound method and the point
        # lands in the first default argument.
        cls.sdf = staticmethod(sample_sdf(cls.body))
        cls.low = cls.body["bounds"]["min"]
        cls.high = cls.body["bounds"]["max"]

    def _at_height(self, fraction: float) -> list[float]:
        y = self.low[1] + (self.high[1] - self.low[1]) * fraction
        return _solid_runs(self.sdf, (self.low[0], y, 0.0), (self.high[0], y, 0.0))

    def test_four_digits_are_separate(self):
        """The digits must read as four across a contiguous stretch of the band, not at odd heights.

        Swept rather than checked at fixed heights, because the digits have different lengths: above the
        pinky's tip a line legitimately crosses three, and a plate with a different band fraction puts
        that boundary somewhere else.

        The assertion is the length of the longest *contiguous* stretch, and that is deliberate. A test
        that only asked whether four ever appears would be vacuous: the fused build still produces an
        isolated four wherever the mitten's own outline happens to dip. Measured across both plates in
        this repository, a fused build reaches 2-3 consecutive samples and a separated one reaches
        14-16, so eight has wide margin either side.
        """
        counts = [len(self._at_height(0.58 + 0.016 * step)) for step in range(SWEEP_SAMPLES)]
        longest = current = 0
        for count in counts:
            current = current + 1 if count == len(DIGITS) else 0
            longest = max(longest, current)
        self.assertGreaterEqual(longest, MIN_SEPARATED_SWEEP, f"runs by height: {counts}")
        self.assertLessEqual(max(counts), len(DIGITS), f"runs by height: {counts}")

    def test_the_digits_join_the_palm_below_the_knuckles(self):
        """Separate all the way down would be four detached rods, which is the opposite defect.

        Sampled in the bottom quarter rather than at a fixed fraction tuned to one plate: how far down
        the digits reach is measured per plate, so a height that sits in the palm for one sits among the
        digits for another. The bottom quarter is palm or cuff for any hand.
        """
        for fraction in (0.10, 0.18, 0.25):
            with self.subTest(height=fraction):
                self.assertEqual(len(self._at_height(fraction)), 1)

    def _height_with_all_digits(self) -> float:
        """A height where the line crosses all four digits, found rather than assumed.

        A fixed fraction is wrong per plate: the digits have different lengths, so above the pinky's tip
        only three are there, and how far up that is depends on the measured finger band. Two tests here
        used a hardcoded 0.78 and both failed the moment the band changed.
        """
        for step in range(SWEEP_SAMPLES):
            fraction = 0.58 + 0.016 * step
            if len(self._at_height(fraction)) == len(DIGITS):
                return fraction
        raise AssertionError("no sampled height crosses all four digits")

    def test_the_grooves_are_wide_enough_to_survive_polygonisation(self):
        """A groove thinner than a grid cell cannot be extracted, so the render would fuse the digits
        even though the field separates them. The gate is the cell size the descriptor itself declares."""
        cell = (self.high[0] - self.low[0]) / self.body["resolution"]
        y = self.low[1] + (self.high[1] - self.low[1]) * self._height_with_all_digits()
        samples = LINE_SAMPLES
        step = (self.high[0] - self.low[0]) / (samples - 1)
        gaps: list[float] = []
        current = 0
        started = False
        for index in range(samples):
            solid = self.sdf((self.low[0] + step * index, y, 0.0)) < 0.0
            if solid:
                if started and current:
                    gaps.append(current * step)
                started = True
                current = 0
            elif started:
                current += 1
        self.assertEqual(len(gaps), len(DIGITS) - 1, f"gaps {gaps}")
        for gap in gaps:
            self.assertGreater(gap, cell, f"groove {gap:.4f} is under one grid cell {cell:.4f}")

    def test_the_thumb_leaves_the_plane_of_the_fingers(self):
        """A thumb is opposed. An inflated silhouette cannot do this, and it is the single most visible
        thing missing when the model is viewed from anywhere but the camera the plate was taken from."""
        thumb = next(item for item in self.body["primitives"] if item["id"] == "thumb-digit")
        # Against the deepest palm slice, not one named primitive: the palm is a swept stack now, and the
        # thumb has to leave the plane of the whole of it.
        thumb_z = thumb["transform"]["translation"][2]
        reach = thumb["height"] / 2.0 + thumb["radius"]
        palm_half_depth = max(item["radii"][2] for item in self.body["primitives"]
                              if item["type"] == "ellipsoid")
        self.assertGreater(thumb_z + reach, palm_half_depth, "the thumb stays inside the palm's depth")
        self.assertNotEqual(thumb["transform"]["rotation"][1], 0.0)

    def test_digits_are_round_in_cross_section(self):
        """Depth against width for one digit. The inflation measured 0.13-0.18 here."""
        fraction = self._height_with_all_digits()
        y = self.low[1] + (self.high[1] - self.low[1]) * fraction
        runs = self._at_height(fraction)
        self.assertEqual(len(runs), len(DIGITS))
        # Walk in from the outside to find the middle of the first digit, then measure through it in z.
        step = (self.high[0] - self.low[0]) / (LINE_SAMPLES - 1)
        first_start = None
        for index in range(LINE_SAMPLES):
            if self.sdf((self.low[0] + step * index, y, 0.0)) < 0.0:
                first_start = index
                break
        self.assertIsNotNone(first_start)
        centre_x = self.low[0] + step * (first_start + runs[0] / (2.0 * step))
        depth_runs = _solid_runs(self.sdf, (centre_x, y, self.low[2]), (centre_x, y, self.high[2]))
        self.assertTrue(depth_runs)
        ratio = max(depth_runs) / runs[0]
        self.assertGreater(ratio, 0.7, f"digit is {ratio:.2f} as deep as it is wide; a finger is about 1")
        self.assertLess(ratio, 1.5, f"digit is {ratio:.2f} as deep as it is wide; a finger is about 1")


if __name__ == "__main__":
    unittest.main()
