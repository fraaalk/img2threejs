"""The Python SDF mesh must be the mesh the browser polygonizes, vertex for vertex and uv for uv.

Why this gate has to exist. An implicit surface has no mesh until something extracts one, and stage 4
measures topology from a mesh. If Python extracted its own approximation, the review would be gating a
mesh nobody ships. `forge/_shared/sdf_mesh.py` is therefore a port of `polygonizeSdf` rather than an
equivalent, and this is what keeps the port honest: it runs the *emitted* TypeScript against real three
and compares.

The comparison can be exact because the extractor is naive surface nets with no iteration and no
tolerance: each vertex is the mean of linear interpolations between two sampled corners, so all three
implementations compute the same doubles in the same order.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "forge" / "stage3_build"))

from forge._shared.glove_armature import build_glove_sdf_descriptor
from forge._shared.glove_silhouette import measure_silhouette
from forge._shared.sdf_mesh import polygonize_sdf, project_atlas_uv
from forge.stage3_build.generate_threejs_factory import _SDF_HELPER_SOURCE
from forge.stage4_review.geometry_integrity import mesh_edge_counts

FIXTURE = Path(__file__).parent / "fixtures" / "glove_sport_v1" / "dorsal.png"
# Small enough for a pure-Python sampler in a test suite, large enough that the digits separate.
PARITY_RESOLUTION = 24


def _three_module() -> Path | None:
    """Either checkout with three will do; the review runtime's copy is present in this repo."""
    candidates = [ROOT / "runtime" / "glove-review" / "node_modules" / "three" / "build" / "three.module.js"]
    showcase = os.environ.get("IMG2THREEJS_SHOWCASE_ROOT")
    if showcase:
        candidates.append(Path(showcase) / "node_modules" / "three" / "build" / "three.module.js")
    return next((candidate for candidate in candidates if candidate.is_file()), None)


class GloveArmatureParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _mask, cls.measured = measure_silhouette(FIXTURE)
        cls.descriptor = build_glove_sdf_descriptor(
            cls.measured, hand="left", source_view_id="glove-view-1-dorsal", resolution=PARITY_RESOLUTION
        )
        cls.raw = polygonize_sdf(cls.descriptor["sdf"])
        cls.mesh = project_atlas_uv(cls.raw, flip_u=False)

    def test_the_shell_closes(self):
        counts = mesh_edge_counts(
            [list(position) for position in self.mesh["positions"]],
            [list(triangle) for triangle in self.mesh["indices"]],
        )
        self.assertEqual(counts["boundaryEdges"], 0)
        self.assertEqual(counts["nonManifoldEdges"], 0)

    def test_the_surface_is_a_single_closed_sphere(self):
        """V - E + F = 2 for a closed genus-0 surface. A digit left floating or a tunnel through the
        palm changes the characteristic, which the edge counts alone would not notice."""
        counts = mesh_edge_counts(
            [list(position) for position in self.mesh["positions"]],
            [list(triangle) for triangle in self.mesh["indices"]],
        )
        self.assertEqual(len(self.raw["positions"]) - counts["edgeCount"] + len(self.mesh["indices"]), 2)

    def test_vertices_are_interpolated_not_snapped_to_the_grid(self):
        """The property the whole extractor change rests on.

        The extractor this replaced put every vertex on an integer grid corner, `min + i * step`. That is
        what made the surface faceted at cell scale at any resolution, what made a crease between two
        touching solids unrepresentable, and what left a third of the triangles with zero uv area. If a
        regression put vertices back on the grid, these three would come back together and this is the
        cheapest way to notice.
        """
        body = self.descriptor["sdf"]
        minimum = body["bounds"]["min"]
        step = [(body["bounds"]["max"][axis] - minimum[axis]) / self.raw["resolution"] for axis in range(3)]
        snapped = 0
        for position in self.raw["positions"]:
            offsets = [(position[axis] - minimum[axis]) / step[axis] for axis in range(3)]
            if all(abs(offset - round(offset)) < 1e-9 for offset in offsets):
                snapped += 1
        self.assertLess(snapped, len(self.raw["positions"]) * 0.02, f"{snapped} vertices sit exactly on grid corners")

    def test_every_triangle_a_plate_faced_carries_real_texture(self):
        """A triangle with zero uv area samples a single line of texels across its whole face.

        For a face the plates never saw -- the band around the equator, whose normal points around the
        form rather than at either plate -- that is the intended answer: it takes the plate's colour at
        the silhouette edge at its own height, flat, because no plate observed its depth. Roughly half of
        those come out flat and should.

        For a face a plate DID see, flat means the observation was thrown away, and that is the defect.
        The previous extractor put every vertex on a grid corner and made 35% of ALL triangles flat,
        including plate-facing ones. Measured after interpolating: zero plate-facing triangles are flat, at
        resolution 24 and 48 alike, which is why this asserts none rather than a fraction.
        """
        flat_facing = 0
        facing = 0
        for triangle in self.mesh["indices"]:
            normal = [sum(self.mesh["normals"][corner][axis] for corner in triangle) / 3.0 for axis in range(3)]
            if abs(normal[2]) < max(abs(normal[0]), abs(normal[1])):
                continue
            facing += 1
            a, b, c = (self.mesh["uv0"][corner] for corner in triangle)
            if abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) == 0.0:
                flat_facing += 1
        self.assertGreater(facing, 0, "no triangle faces either plate")
        self.assertEqual(flat_facing, 0, f"{flat_facing} of {facing} plate-facing triangles have zero uv area")

    def test_the_texture_is_not_upside_down(self):
        """The model's fingertips must wear the plate's fingertips.

        The atlas is uploaded with `flipY = false`, so texture v=0 is the image's FIRST row, and the atlas's
        first row is the plate's first row -- the fingertips, since the bake crops the plate to its own
        silhouette and preserves orientation. So v has to run downward from the frame's top.

        It ran the other way for the whole life of this track, in the inflation route before the armature and
        in the armature after it: the model's fingertips took v=1 and therefore the atlas's LAST row, so every
        glove wore its cuff on its fingertips. A dozen renders went by without it being spotted, because a
        glove is nearly symmetric in its colour blocking end to end -- the aggregate luma of the atlas's top
        and bottom eighths differs by 4 out of 255. It was settled by comparing the atlas's rows against the
        plate's crop row for row.
        """
        heights = [position[1] for position in self.mesh["positions"]]
        top, bottom = max(heights), min(heights)
        near_top = [uv[1] for position, uv in zip(self.mesh["positions"], self.mesh["uv0"]) if position[1] > top - 0.02]
        near_bottom = [uv[1] for position, uv in zip(self.mesh["positions"], self.mesh["uv0"]) if position[1] < bottom + 0.02]
        self.assertTrue(near_top and near_bottom)
        self.assertLess(max(near_top), 0.1, "the model's fingertips are sampling the bottom of the plate")
        self.assertGreater(min(near_bottom), 0.9, "the model's cuff is sampling the top of the plate")

    def test_no_triangle_straddles_the_atlas_seam(self):
        for triangle in self.mesh["indices"]:
            us = [self.mesh["uv0"][corner][0] for corner in triangle]
            with self.subTest(triangle=triangle):
                self.assertTrue(max(us) <= 0.5 or min(us) >= 0.5)

    def test_both_plates_paint_a_real_share_of_the_surface(self):
        """A projection that sent almost everything to one half would texture the glove with one plate
        while reporting two. Judged by facet normal rather than smoothed normal it did exactly that."""
        dorsal = sum(1 for triangle in self.mesh["indices"] if self.mesh["uv0"][triangle[0]][0] <= 0.5)
        share = dorsal / len(self.mesh["indices"])
        self.assertGreater(share, 0.25)
        self.assertLess(share, 0.75)

    def test_the_right_hand_mirrors_its_texture(self):
        mirrored = project_atlas_uv(self.raw, flip_u=True)
        # A mirrored u reflects within its own atlas half, so the pair sums to that half's span: 0.5
        # across the dorsal half, 1.5 across the palmar one. Classifying by `u <= 0.5` instead would be
        # meaningless at exactly 0.5, which both halves share.
        for triangle in self.mesh["indices"]:
            sums = {round(self.mesh["uv0"][corner][0] + mirrored["uv0"][corner][0], 6) for corner in triangle}
            with self.subTest(triangle=triangle):
                self.assertEqual(len(sums), 1, "a triangle landed in two atlas halves at once")
                self.assertIn(sums.pop(), {0.5, 1.5})

    def test_the_descriptor_declares_its_projection(self):
        from forge._shared.sdf_primitives import validate_sdf_descriptor

        errors: list[str] = []
        body = {**self.descriptor["sdf"], "uvProjection": {"mode": "atlas-front-back", "flipU": True}}
        validate_sdf_descriptor("glove-armature", body, errors)
        self.assertEqual(errors, [])
        for name, broken in (
            ("unknown mode", {"mode": "spherical"}),
            ("no mode", {"flipU": True}),
            ("unsupported field", {"mode": "atlas-front-back", "scale": 2}),
            ("non-boolean flip", {"mode": "atlas-front-back", "flipU": 1}),
        ):
            with self.subTest(case=name):
                errors = []
                validate_sdf_descriptor("glove-armature", {**self.descriptor["sdf"], "uvProjection": broken}, errors)
                self.assertTrue(errors)

    def test_the_review_runtime_polygonizes_the_same_mesh(self):
        """The review runtime carries its own copy, so it needs its own pin. It imports three from this
        repo's own node_modules rather than a showcase checkout, so it is never the leg left unchecked."""
        three = _three_module()
        if three is None:
            self.skipTest("no three build found; run `npm ci --prefix runtime/glove-review`")
        body = {**self.descriptor["sdf"], "uvProjection": {"mode": "atlas-front-back", "flipU": False}}
        module = (ROOT / "runtime" / "glove-review" / "src" / "sdf.mjs").as_posix()
        harness = "\n".join([
            f"import * as THREE from {json.dumps(three.as_posix())};",
            f"import {{ buildSdfAtlasAttributes }} from {json.dumps(module)};",
            f"const built = buildSdfAtlasAttributes(THREE, {json.dumps(body)});",
            "process.stdout.write(JSON.stringify({",
            "  triangleCount: built.triangleCount,",
            "  positions: built.positions.map((value) => Math.round(value * 1e5) / 1e5),",
            "  uvs: built.uvs.map((value) => Math.round(value * 1e5) / 1e5),",
            "}));",
        ])
        with tempfile.TemporaryDirectory(prefix="img2-armature-review-parity-") as raw:
            script = Path(raw) / "parity.mjs"
            script.write_text(harness, encoding="utf-8")
            completed = subprocess.run(["node", str(script)], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(completed.returncode, 0, completed.stderr[-3000:])
        runtime = json.loads(completed.stdout)
        self.assertEqual(runtime["triangleCount"], len(self.mesh["indices"]))
        expected = [round(value, 5) for position in self.mesh["positions"] for value in position]
        self.assertEqual(len(runtime["positions"]), len(expected))
        self.assertLess(max(abs(left - right) for left, right in zip(runtime["positions"], expected)), 1e-4)
        expected_uv = [round(value, 5) for pair in self.mesh["uv0"] for value in pair]
        self.assertEqual(len(runtime["uvs"]), len(expected_uv))
        self.assertLess(max(abs(left - right) for left, right in zip(runtime["uvs"], expected_uv)), 1e-4)

    def test_the_runtime_polygonizes_the_same_mesh(self):
        three = _three_module()
        if three is None:
            self.skipTest("no three build found; run `npm ci --prefix runtime/glove-review`")
        body = {**self.descriptor["sdf"], "uvProjection": {"mode": "atlas-front-back", "flipU": False}}
        body.pop("derivation", None)
        harness = "\n".join([
            f"import * as THREE from {json.dumps(three.as_posix())};",
            _SDF_HELPER_SOURCE,
            f"const geometry = polygonizeSdf({json.dumps(body)} as unknown as SdfDescriptor);",
            "const position = geometry.getAttribute('position');",
            "const uv = geometry.getAttribute('uv');",
            "process.stdout.write(JSON.stringify({",
            "  indexed: geometry.getIndex() === null,",
            "  vertexCount: position.count,",
            "  positions: Array.from(position.array as Float32Array).map((value) => Math.round(value * 1e5) / 1e5),",
            "  uvs: Array.from(uv.array as Float32Array).map((value) => Math.round(value * 1e5) / 1e5),",
            "}));",
        ])
        with tempfile.TemporaryDirectory(prefix="img2-armature-parity-") as raw:
            script = Path(raw) / "parity.ts"
            script.write_text(harness, encoding="utf-8")
            completed = subprocess.run(
                ["node", "--experimental-strip-types", "--no-warnings", str(script)],
                capture_output=True, text=True, cwd=ROOT,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr[-3000:])
        runtime = json.loads(completed.stdout)
        self.assertTrue(runtime["indexed"], "an atlas projection must unindex, so the index is dropped")
        self.assertEqual(runtime["vertexCount"], len(self.mesh["positions"]))
        expected = [round(value, 5) for position in self.mesh["positions"] for value in position]
        self.assertEqual(len(runtime["positions"]), len(expected))
        self.assertLess(
            max(abs(left - right) for left, right in zip(runtime["positions"], expected)), 1e-4,
            "the runtime polygonised a different surface than the review measured",
        )
        expected_uv = [round(value, 5) for pair in self.mesh["uv0"] for value in pair]
        self.assertEqual(len(runtime["uvs"]), len(expected_uv))
        self.assertLess(
            max(abs(left - right) for left, right in zip(runtime["uvs"], expected_uv)), 1e-4,
            "the runtime assigned different plates to the surface than the review measured",
        )


if __name__ == "__main__":
    unittest.main()
