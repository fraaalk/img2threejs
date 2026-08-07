#!/usr/bin/env python3
"""Tests for the `tapered-sweep` primitive.

Every other sweep this factory emits carries a CONSTANT cross-section: `buildTubeGeometry` takes one
radius, `buildCurveSweepGeometry` extrudes one Shape along a path. Nothing that comes to a point --
a hair lock, a horn, a tail, a finger, a blade tip -- could be expressed, so those subjects were
built from stacked constant-radius pieces and read as noodles.

The taper warning exists because of a measured failure, not a theory. A recovered build contained
eleven hair locks whose tip radius was 0.0327 on every single one, identical to four decimals, for
tip/root ratios of 0.58-0.79 against a reference that measures 0.087. The frame maths was correct;
the authored stations were not, and nothing objected.

Run: python3 forge/tests/test_tapered_sweep.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stage2_spec"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stage3_build"))

from generate_threejs_factory import _DEFAULT_TAPERED_SWEEP, geometry_for  # noqa: E402
from validate_sculpt_spec import TAPER_RATIO_MAX, VALID_PRIMITIVES, taper_risk  # noqa: E402


def component(stations: list[dict[str, object]]) -> dict[str, object]:
    return {"geometryDescriptor": {"taperedSweep": {"stations": stations}}}


def station(y: float, rx: float, rz: float, twist: float = 0.0) -> dict[str, object]:
    return {"position": [0.0, y, 0.0], "rx": rx, "rz": rz, "twist": twist}


class PrimitiveRegistration(unittest.TestCase):
    def test_primitive_is_accepted_by_the_schema(self) -> None:
        self.assertIn("tapered-sweep", VALID_PRIMITIVES)

    def test_geometry_for_emits_the_builder(self) -> None:
        call = geometry_for("tapered-sweep", {"taperedSweep": _DEFAULT_TAPERED_SWEEP}, {})
        self.assertTrue(call.startswith("buildTaperedSweepGeometry("))
        self.assertIn("stations", call)

    def test_a_missing_descriptor_falls_back_to_a_tapering_default(self) -> None:
        """The default must not itself trip the taper warning -- otherwise every spec that omits
        the descriptor inherits a warning it cannot act on."""
        stations = _DEFAULT_TAPERED_SWEEP["stations"]
        ratio = max(stations[-1]["rx"], stations[-1]["rz"]) / max(stations[0]["rx"], stations[0]["rz"])
        self.assertLess(ratio, TAPER_RATIO_MAX)

        call = geometry_for("tapered-sweep", {}, {})
        self.assertIn("buildTaperedSweepGeometry(", call)


class TaperWarning(unittest.TestCase):
    def test_a_lock_that_reaches_a_point_passes(self) -> None:
        severity, _ = taper_risk(
            "hair-lock",
            component([station(-0.5, 0.060, 0.040), station(0.0, 0.030, 0.020), station(0.5, 0.005, 0.003)]),
        )
        self.assertEqual(severity, "OK")

    def test_the_recovered_blunt_lock_is_caught(self) -> None:
        """The exact numbers from the recovered build: root 0.0538, tip 0.0323, ratio 0.60."""
        severity, message = taper_risk(
            "Hair_Fringe_L",
            component([station(-0.5, 0.0538, 0.0538), station(0.5, 0.0323, 0.0323)]),
        )
        self.assertEqual(severity, "HIGH")
        self.assertIn("0.60", message)
        self.assertIn("noodle", message)

    def test_a_constant_radius_sweep_is_caught(self) -> None:
        severity, _ = taper_risk(
            "cable", component([station(-0.5, 0.02, 0.02), station(0.5, 0.02, 0.02)])
        )
        self.assertEqual(severity, "HIGH")

    def test_components_without_the_descriptor_are_untouched(self) -> None:
        for candidate in ({}, {"geometryDescriptor": {}}, {"geometryDescriptor": {"tubePath": {}}}):
            with self.subTest(candidate=candidate):
                self.assertEqual(taper_risk("x", candidate)[0], "OK")

    def test_malformed_stations_do_not_raise(self) -> None:
        for stations in ([], [station(0, 0.1, 0.1)], ["not-a-dict", 7], [station(0, 0.0, 0.0), station(1, 0.0, 0.0)]):
            with self.subTest(stations=stations):
                self.assertEqual(taper_risk("x", component(stations))[0], "OK")


class EmittedSource(unittest.TestCase):
    """The emitted TypeScript is the deliverable; these assert the properties that make it correct.

    A full typecheck of the generated factory runs in test_showcase_tsc_smoke when a showcase
    checkout is configured; these checks hold with no browser and no Node.
    """

    _cached: str | None = None

    def source(self) -> str:
        """Generate a real factory from a spec that uses the primitive, and read what came out."""
        if EmittedSource._cached is None:
            from generate_threejs_factory import generate  # noqa: PLC0415

            spec = {
                "targetName": "TaperTest",
                "schemaVersion": "2.1",
                "suitability": "pass",
                "coordinateFrame": {},
                "silhouette": {},
                "proceduralStrategy": [],
                "materials": [{"id": "hair"}],
                "componentTree": [
                    {
                        "id": "lock",
                        "name": "Lock",
                        "primitive": "tapered-sweep",
                        "materialId": "hair",
                        "geometryDescriptor": {"taperedSweep": _DEFAULT_TAPERED_SWEEP},
                    }
                ],
            }
            EmittedSource._cached = generate(spec, "blockout")
        return EmittedSource._cached

    def test_the_builder_is_emitted_and_called(self) -> None:
        source = self.source()
        self.assertIn("function buildTaperedSweepGeometry(", source)
        self.assertIn("buildTaperedSweepGeometry({", source)

    def test_uses_parallel_transport_not_frenet(self) -> None:
        source = self.source()
        self.assertIn("buildTaperedSweepGeometry", source)
        self.assertNotIn("computeFrenetFrames", source)

    def test_guards_the_degenerate_seed_axis(self) -> None:
        """A reference axis parallel to the first tangent makes the first cross product zero and
        collapses the sweep to a line."""
        self.assertIn("> 0.9", self.source())

    def test_guards_coincident_stations(self) -> None:
        """Two stations at the same position normalise to NaN and poison every later vertex."""
        self.assertIn("1e-12", self.source())

    def test_recomputes_normals_after_building(self) -> None:
        self.assertIn("computeVertexNormals", self.source())


if __name__ == "__main__":
    unittest.main(verbosity=2)
