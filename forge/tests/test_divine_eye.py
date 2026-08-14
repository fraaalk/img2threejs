#!/usr/bin/env python3
"""Tests for the Divine Eye deterministic ensemble (Plan 1.3 Phase 3 §3.1/§3.3)."""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "stage4_review"))

from divine_eye import (  # noqa: E402
    blowout_parity,
    edge_overlap,
    evaluate,
    flat_fraction,
    global_ssim,
    tonal_parity,
)
from diagnose_render import mask_is_unusable, silhouette_iou  # noqa: E402

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def write_rgb_png(path: Path, w: int, h: int, pixel_fn) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw += bytes(pixel_fn(x, y, w, h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    path.write_bytes(PNG_SIGNATURE + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def block(x0, y0, x1, y1, fg=(200, 40, 40), bg=(255, 255, 255)):
    return lambda x, y, w, h: fg if (x0 <= x < x1 and y0 <= y < y1) else bg


class SignalUnitTest(unittest.TestCase):
    def test_ssim_identical_is_one(self):
        a = [0.2, 0.8, 0.5, 0.1] * 16
        self.assertAlmostEqual(global_ssim(a, a), 1.0, places=5)

    def test_ssim_different_is_low(self):
        a = [0.0] * 64
        b = [1.0 if i % 2 else 0.0 for i in range(64)]
        self.assertLess(global_ssim(a, b), 0.5)

    def test_tonal_parity_identical_is_one(self):
        a = [i / 64 for i in range(64)]
        self.assertAlmostEqual(tonal_parity(a, a), 1.0, places=5)

    def test_tonal_parity_disjoint_is_low(self):
        dark = [0.02] * 64
        bright = [0.98] * 64
        self.assertLess(tonal_parity(dark, bright), 0.1)

    def test_blowout_parity_penalizes_extra_blown(self):
        ref = [0.5] * 64
        blown = [0.99] * 64
        self.assertLess(blowout_parity(ref, blown), 0.1)
        self.assertAlmostEqual(blowout_parity(ref, ref), 1.0, places=5)

    def test_flat_fraction_high_for_uniform(self):
        uniform = [0.5] * (16 * 16)
        self.assertGreater(flat_fraction(uniform, 16), 0.9)

    def test_edge_overlap_identical_is_one(self):
        # a vertical edge in the middle
        size = 32
        img = [0.0 if (i % size) < size // 2 else 1.0 for i in range(size * size)]
        self.assertAlmostEqual(edge_overlap(img, img, size), 1.0, places=5)


class DivineEyeIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.ref = self.dir / "ref.png"
        write_rgb_png(self.ref, 200, 200, block(50, 50, 150, 150))

    def test_identical_passes_with_full_fidelity(self):
        r = evaluate(self.ref, self.ref)
        self.assertEqual(r["verdict"], "pass")
        self.assertEqual(r["action"], "continue")
        self.assertEqual(r["fidelity"], 1.0)
        self.assertEqual(r["hardGateFailures"], [])

    def test_wrong_scale_trips_hard_gate(self):
        # a much smaller subject → scale/IoU hard gate → reject + refine-code
        ren = self.dir / "small.png"
        write_rgb_png(ren, 200, 200, block(90, 90, 110, 110))
        r = evaluate(self.ref, ren)
        self.assertEqual(r["verdict"], "reject")
        self.assertEqual(r["action"], "refine-code")
        self.assertTrue(r["hardGateFailures"])

    def test_shifted_same_shape_is_rescued_by_objectness(self):
        # SAME-SIZE square translated to a corner (100x100 → 100x100, area & aspect identical) →
        # only the IoU hard gate trips (scale/aspect pass), and objectness (bg/pose/scale-invariant)
        # recognises the same shape → reconstruction-mode rescue. Soft fidelity is well below target
        # (misaligned pixels tank ssim/edge), so it routes to probe, never an auto-pass.
        ren = self.dir / "shifted.png"
        write_rgb_png(ren, 200, 200, block(0, 0, 100, 100))
        r = evaluate(self.ref, ren)
        self.assertTrue(r["hardGateFailures"])          # IoU still trips
        self.assertTrue(r["reconstructionModeSuspected"])
        self.assertEqual(r["action"], "probe")          # rescued, NOT refine-code
        self.assertNotEqual(r["verdict"], "pass")       # never auto-passes

    def test_different_shape_iou_fail_is_not_rescued(self):
        # a genuinely different shape (thin bar vs square) → low objectness → NO rescue,
        # stays a hard reject. Guards the rescue from masking real geometric failures.
        ren = self.dir / "wrongshape.png"
        write_rgb_png(ren, 200, 200, block(10, 92, 190, 108))  # thin horizontal bar
        r = evaluate(self.ref, ren)
        self.assertTrue(r["hardGateFailures"])
        self.assertFalse(r["reconstructionModeSuspected"])
        self.assertEqual(r["action"], "refine-code")

    def test_asymmetric_subject_not_penalized_when_matched(self):
        # an asymmetric L-shape compared to itself must still score fidelity 1.0
        # (symmetry is a parity signal, not an absolute one).
        def lshape(x, y, w, h):
            if (20 <= x < 60 and 20 <= y < 160) or (20 <= x < 140 and 120 <= y < 160):
                return (30, 120, 90)
            return (255, 255, 255)
        aref = self.dir / "l.png"
        write_rgb_png(aref, 180, 180, lshape)
        r = evaluate(aref, aref)
        self.assertEqual(r["fidelity"], 1.0)
        self.assertEqual(r["verdict"], "pass")


class DegenerateEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_empty_union_is_not_a_perfect_match(self):
        self.assertEqual(silhouette_iou([False] * 16, [False] * 16), 0.0)

    def test_edge_overlap_no_edges_is_not_free_evidence(self):
        self.assertEqual(edge_overlap([0.5] * 64, [0.5] * 64, 8), 0.0)

    def test_tiny_disjoint_subjects_are_hard_rejected(self):
        ref = self.dir / "corner-a.png"
        render = self.dir / "corner-b.png"
        write_rgb_png(ref, 200, 200, block(10, 10, 40, 40))
        write_rgb_png(render, 200, 200, block(160, 160, 190, 190, fg=(30, 30, 220)))
        result = evaluate(ref, render)
        self.assertTrue(result["hardGateFailures"])
        self.assertTrue(result["maskWarnings"])
        self.assertNotEqual(result["verdict"], "pass")

    def test_both_whole_frame_fallbacks_are_caught(self):
        """`build_foreground_mask` gives up in two ways and both leave a mask covering the whole frame.

        This test used to assert the OPPOSITE for the second one -- that "not clearly isolated" is fine --
        which made the hard gate in `evaluate` unable to fire for the case that actually happens. An
        untextured normal-shaded render on a dark background reads as unisolated, its mask comes back at
        1.000 of the frame, and the silhouette IoU against a reference then equals the reference's own fill
        fraction: 0.729 measured on this repository's glove plate, which looks like a score and is not one.
        """
        self.assertTrue(mask_is_unusable(["foreground mask is tiny; material extraction is unreliable"]))
        self.assertTrue(mask_is_unusable(
            ["image is not clearly isolated from background; using most pixels as material evidence"]
        ))
        self.assertFalse(mask_is_unusable([]))
        self.assertFalse(mask_is_unusable(["colour profile assumed sRGB"]))

    def test_a_whole_frame_mask_cannot_score(self):
        """The point of the predicate: a degenerate mask must reject, not produce a plausible fidelity.

        A render that never separates from its background is compared against a reference that does. Every
        silhouette signal is then measuring the frame, so the verdict has to be a hard failure naming that --
        not a number a reader would act on.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference, render = root / "reference.png", root / "render.png"
            write_rgb_png(reference, 200, 200, block(60, 60, 140, 140))
            # A render whose "background" is the same mid-grey as its subject: nothing to separate.
            write_rgb_png(render, 200, 200, lambda x, y, w, h: (128, 128, 128))
            result = evaluate(reference, render)
            self.assertTrue(result["maskWarnings"], "the extractor did not warn about the flat render")
            self.assertTrue(
                any("whole-frame" in failure for failure in result["hardGateFailures"]),
                f"hard gates were {result['hardGateFailures']}",
            )
            self.assertNotEqual(result["verdict"], "pass")


if __name__ == "__main__":
    unittest.main(verbosity=2)
