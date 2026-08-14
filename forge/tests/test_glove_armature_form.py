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
from forge._shared.sdf_mesh import _apply_quaternion, _quaternion_from_euler_xyz, sample_sdf
from forge.stage3_build.glove_armature_shell import measure_digit_protrusion

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

    def test_the_digits_separate_from_their_tips_downward(self):
        """The digits must part toward their tips and merge toward the palm, which is what the plate shows.

        This asserted eight consecutive heights crossing four separate solids, which suited digits placed
        evenly with an air gap between them and does not survive digits measured off the plate. The reference
        silhouette itself only resolves four separate runs across about one row in seventy-two: the little
        finger starts a seventh of the way down, and the others have merged again by a quarter. Demanding
        eight would demand a hand the reference is not.

        What must hold is the SHAPE of the sequence -- one run at the top where only the longest digit reaches,
        rising to four, then falling as they merge into the hand -- and that it never exceeds four, since a
        fifth run in the digit band would be a stray solid.
        """
        counts = [len(self._at_height(0.58 + 0.016 * step)) for step in range(SWEEP_SAMPLES)]
        self.assertEqual(max(counts), len(DIGITS), f"runs by height: {counts}")
        peak = max(range(len(counts)), key=lambda index: counts[index])
        self.assertTrue(all(counts[i] <= counts[i + 1] for i in range(peak)), f"runs by height: {counts}")
        self.assertTrue(all(counts[i] >= counts[i + 1] for i in range(peak, len(counts) - 1)), f"runs by height: {counts}")

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

    def test_the_seam_between_digits_is_a_crease_not_a_fusion(self):
        """Adjacent digits touch, so what separates them is a crease -- and the crease has to be there.

        This replaces a test that asserted three air gaps each wider than a grid cell. That was the right
        assertion for digits placed evenly with a gap solved in cells, and the wrong one for digits measured
        off the plate: the plate puts neighbouring digits 0.0036 of the frame apart, a fifth of a cell, because
        on a sewn glove they touch. Left as an air gap that width the extractor welded seven edges and broke
        the surface's genus; blended, it is one surface with a seam.

        The seam is measured as a dip in DEPTH: between two digit centres the solid is thinner than it is at
        either centre. A fusion has no such dip, which is the mitten this whole track has been avoiding.
        """
        centres = sorted(
            (item["transform"]["translation"][0], item["radius"])
            for item in self.body["primitives"] if item["id"].endswith("-digit") and item["id"] != "thumb-digit"
        )
        y = self.low[1] + (self.high[1] - self.low[1]) * self._height_with_all_digits()

        def thickness(x: float) -> float:
            runs = _solid_runs(self.sdf, (x, y, self.low[2]), (x, y, self.high[2]))
            return max(runs) if runs else 0.0

        for (left, _left_radius), (right, _right_radius) in zip(centres, centres[1:]):
            with self.subTest(seam=(round(left, 4), round(right, 4))):
                at_seam = thickness((left + right) / 2.0)
                self.assertGreater(thickness(left), at_seam, "no crease between two digits")
                self.assertGreater(thickness(right), at_seam, "no crease between two digits")

    def test_the_thumb_leaves_the_plane_of_the_fingers(self):
        """A thumb is opposed. An inflated silhouette cannot do this, and it is the single most visible
        thing missing when the model is viewed from anywhere but the camera the plate was taken from."""
        thumb = next(item for item in self.body["primitives"] if item["id"] == "thumb-digit")
        # Against the deepest palm slice, not one named primitive: the palm is a swept stack now, and the
        # thumb has to leave the plane of the whole of it.
        palm_half_depth = max(item["radii"][2] for item in self.body["primitives"]
                              if item["type"] == "ellipsoid")
        # Through the REALISED axis, and on the side the thumb actually leaves by. The earlier form read
        # `translation.z + height/2 + radius`, which assumed both that the thumb was centred on the palm's
        # own plane and that its whole length counted along z. Neither holds for a thumb posed as a segment:
        # its centre is offset to the palmar side, so adding a positive reach to a negative centre measured
        # the DORSAL end, and it reported 0.0858 against a palm 0.0927 deep for a thumb whose palmar surface
        # reaches 0.238 -- a fail on geometry that had never been more correct.
        axis = _apply_quaternion((0.0, 1.0, 0.0), _quaternion_from_euler_xyz(list(thumb["transform"]["rotation"])))
        reach = abs(axis[2]) * thumb["height"] / 2.0 + thumb["radius"]
        centre = thumb["transform"]["translation"][2]
        self.assertLess(centre - reach, -palm_half_depth, "the thumb stays inside the palm's depth")
        self.assertNotEqual(thumb["transform"]["rotation"][1], 0.0)

    def test_digits_are_round_in_cross_section(self):
        """Depth against width for each digit. The inflation measured 0.13-0.18 here, where a finger is 1.

        Measured through each digit's OWN centre, taken from the primitive, rather than through the centre of
        whatever the first solid run at that height happens to be. Once the digits are blended at their seams,
        the first run is no longer one digit, so that reading straddled a seam and reported a digit 1.63 times
        as deep as it was wide.
        """
        y = self.low[1] + (self.high[1] - self.low[1]) * self._height_with_all_digits()
        for item in self.body["primitives"]:
            if not item["id"].endswith("-digit") or item["id"] == "thumb-digit":
                continue
            x = item["transform"]["translation"][0]
            with self.subTest(digit=item["id"]):
                depth = _solid_runs(self.sdf, (x, y, self.low[2]), (x, y, self.high[2]))
                self.assertTrue(depth, f"{item['id']} has no solid at its own centre")
                ratio = max(depth) / (2.0 * item["radius"])
                self.assertGreater(ratio, 0.7, f"{item['id']} is {ratio:.2f} as deep as it is wide")
                self.assertLess(ratio, 1.5, f"{item['id']} is {ratio:.2f} as deep as it is wide")

    def test_all_five_digits_stand_clear_of_the_rest_of_the_hand(self):
        """A glove has five digits, and four of them being obvious does not make the fifth exist.

        The thumb is tucked against the palm, so it never crosses a line through the digit band and a
        band-sweep count cannot see it -- the count that shipped before this asked for five digits side by
        side, a pose the reference does not have. What makes a digit real is that some of its own surface is
        outside every other part, which is the condition for it being visible from any direction at all.

        This is the check that was missing when a thumb fused into the palm mass passed a dozen textured
        renders, with the palmar plate's painted thumb supplying the fifth digit the form did not have.
        """
        protrusion = measure_digit_protrusion(self.body)
        self.assertEqual(
            protrusion["value"], 5.0,
            f"only {protrusion['present']} stand clear; fractions {protrusion['protrudingFraction']}",
        )

    def test_consecutive_palm_slices_overlap_by_more_than_a_cell(self):
        """The palm is a stack of slices, and an overlap thinner than a cell welds rather than joins.

        Measured in the grid's own unit because that is where the constraint lives. Held as a dimensionless
        1.15 multiple of the slice spacing instead, the overlap came out at 0.0028 against a cell of 0.0179
        on the real plate -- six times too thin at every junction on the stack. The sweep was then manifold
        only by where the samples happened to land, and the tell was that changes to the THUMB flipped the
        mesh's non-manifold count: the thumb sets the bounds, the bounds set the cell, and the cell decided
        whether the palm's own seams welded.
        """
        cell = (self.high[0] - self.low[0]) / self.body["resolution"]
        slices = sorted(
            (item for item in self.body["primitives"] if item["id"].startswith("palm-slice")),
            key=lambda item: item["transform"]["translation"][1],
        )
        self.assertGreater(len(slices), 1)
        for lower, upper in zip(slices, slices[1:]):
            spacing = upper["transform"]["translation"][1] - lower["transform"]["translation"][1]
            overlap = lower["radii"][1] + upper["radii"][1] - spacing
            self.assertGreater(overlap, cell, f"slices overlap {overlap:.5f}, under one cell {cell:.5f}")


if __name__ == "__main__":
    unittest.main()
