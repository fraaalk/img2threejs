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

    def _plate_peak_separation(self) -> int:
        """How many digits the PLATE itself shows apart at once, from its own measured tips and webs.

        Asserting a flat four was wrong, and the plate is what says so: each digit is separate only between
        its own tip and its own web, those intervals are staggered, and on the fixture no single height falls
        inside all four. The real Slingshot plate resolves four separate runs across about one row in
        seventy-two. So the model is held to the plate's own maximum rather than to a number.
        """
        edges = sorted({value for run in self.measured["digitRuns"]
                        for value in (run["tipFraction"], run["mergeFraction"])})
        best = 0
        for low, high in zip(edges, edges[1:]):
            middle = (low + high) / 2.0
            best = max(best, sum(1 for run in self.measured["digitRuns"]
                                 if run["tipFraction"] <= middle <= run["mergeFraction"]))
        return best

    def _sweep(self) -> list[int]:
        """Runs crossed at each height across the whole digit band, in fractions of the plate's frame."""
        band = float(self.measured["fingerBandFraction"])
        return [len(self._at_top_fraction(band * (step + 0.5) / SWEEP_SAMPLES)) for step in range(SWEEP_SAMPLES)]

    def _at_top_fraction(self, top: float) -> list[float]:
        """`top` is measured DOWN FROM THE PLATE'S OWN TOP, not up from the descriptor's bounds.

        The bounds pad the content by a margin that changes with the digits' radii, so a fraction of the
        bounds is a different height on every plate -- these tests swept 0.58 to 0.90 of the bounds, tuned
        when the knuckle line sat at 0.41 of the height, and looked straight past the digit band once the
        knuckle was measured from the palm instead of from the thumb and moved to 0.27.
        """
        y = 0.5 - top
        return _solid_runs(self.sdf, (self.low[0], y, 0.0), (self.high[0], y, 0.0))

    def test_the_digits_separate_from_their_tips_downward(self):
        """The digits must part toward their tips and merge toward the palm, as the plate shows.

        The shape of the sequence is the assertion -- one run at the top where only the longest digit
        reaches, rising as each shorter digit starts, falling as each reaches its web -- together with the
        peak matching what the plate itself resolves.
        """
        counts = self._sweep()
        # At LEAST what the plate resolves, and never more digits than there are. Equality would be too
        # strict at the grid's own scale: the model's separation runs from each digit's measured tip to its
        # measured web, the same interval the plate gives, but the sweep samples 21 heights and a pair whose
        # intervals barely fail to overlap on the plate can overlap at one of them.
        self.assertGreaterEqual(max(counts), self._plate_peak_separation(), f"runs by height: {counts}")
        self.assertLessEqual(max(counts), len(DIGITS), f"runs by height: {counts}")
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

    def _height_of_peak_separation(self) -> float:
        """The height, down from the plate's top, at which the model shows the most digits apart."""
        band = float(self.measured["fingerBandFraction"])
        heights = [band * (step + 0.5) / SWEEP_SAMPLES for step in range(SWEEP_SAMPLES)]
        return max(heights, key=lambda top: len(self._at_top_fraction(top)))

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
            for item in self.body["primitives"]
            if item["id"].endswith("-digit-tip") and item["id"] != "thumb-digit"
        )
        y = 0.5 - self._height_of_peak_separation()

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

        Both numbers come from the FIELD at the same point, not from a declared radius. Comparing the solid's
        depth against the radius of the primitive whose centre the line passes through reported the ring digit
        at 1.62: the line was crossing the wider knuckle segment while the radius came from the narrower tip
        segment above it. Measuring both from the field cannot make that mistake.
        """
        top = self._height_of_peak_separation()
        y = 0.5 - top
        runs = self._at_top_fraction(top)
        self.assertTrue(runs, "no solid at the height of peak separation")
        step = (self.high[0] - self.low[0]) / (LINE_SAMPLES - 1)
        # Walk the row, and for each separate run measure through its own middle.
        inside = [self.sdf((self.low[0] + step * index, y, 0.0)) < 0.0 for index in range(LINE_SAMPLES)]
        spans: list[tuple[int, int]] = []
        for index, solid in enumerate(inside):
            if solid and (not spans or not inside[index - 1] or index == 0):
                spans.append((index, index))
            elif solid:
                spans[-1] = (spans[-1][0], index)
        for low, high in spans:
            width = (high - low + 1) * step
            centre = self.low[0] + step * (low + high) / 2.0
            with self.subTest(centre=round(centre, 4)):
                depth = _solid_runs(self.sdf, (centre, y, self.low[2]), (centre, y, self.high[2]))
                self.assertTrue(depth, "a solid run with no depth under it")
                ratio = max(depth) / width
                self.assertGreater(ratio, 0.7, f"a digit {ratio:.2f} as deep as it is wide; a finger is about 1")
                self.assertLess(ratio, 1.5, f"a digit {ratio:.2f} as deep as it is wide; a finger is about 1")

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

    def test_an_open_cut_digit_ends_flat_and_a_closed_one_does_not(self):
        """The predicate for "half-finger", measured from the FIELD rather than declared.

        Nothing asserted this before. `open-cut` had been a legal value in
        `glove_contracts.VALID_OPENING_KINDS` since before any builder could produce one, and the only
        references to it anywhere in the suite were intake-contract assertions on a hand-built record that
        never reach geometry -- so a builder that quietly capped every digit would have passed.

        What separates the two is not the digit's LENGTH, which the plate sets either way. It is the
        cross-section on the way to the end: a capsule's cap tapers to nothing, a cut ends at full width.
        """
        openings = {digit: "open-cut" for digit in ("index", "middle", "ring", "pinky")}
        cut = build_glove_sdf_descriptor(
            self.measured, hand="left", source_view_id="glove-view-1-dorsal", digit_openings=openings
        )["sdf"]
        cut_sdf = sample_sdf(cut)
        tip = next(item for item in cut["primitives"] if item["id"] == "middle-digit-tip")
        x = tip["transform"]["translation"][0]
        probe = float(tip["radius"]) * 0.2

        def profile(field, body):
            """(top of the digit, widths at three depths below it) along the middle digit's own column."""
            step = (body["bounds"]["max"][1] - body["bounds"]["min"][1]) / 400.0
            column = [body["bounds"]["min"][1] + step * index for index in range(401)]
            solid = [y for y in column if field((x, y, 0.0)) < 0.0]
            top = max(solid)
            widths = []
            for depth in (probe * 0.25, probe, probe * 2.0):
                span = [k for k in range(-40, 41) if field((x + k * probe / 8.0, top - depth, 0.0)) < 0.0]
                widths.append((max(span) - min(span)) * probe / 8.0 if span else 0.0)
            return top, widths

        cut_top, cut_widths = profile(cut_sdf, cut)
        capped_top, capped_widths = profile(self.sdf, self.body)
        self.assertLess(min(cut_widths), max(cut_widths) * 1.02, f"an open cut should not taper: {cut_widths}")
        self.assertGreater(max(capped_widths), min(capped_widths) * 1.15, f"a cap should taper: {capped_widths}")
        self.assertLess(cut_top, capped_top, "the cut removes the cap, so the digit ends lower")

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
