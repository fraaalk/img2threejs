"""The silhouette-derived shell must close, separate, and stay honest about its depth axis.

The panel route could not satisfy the first two by construction and hid the third in a constant.
Each test here fails if that regresses.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from forge.stage3_build.glove_geometry import validate_geometry_report
from forge.stage3_build.glove_shell import DESCRIPTOR_KIND, build_glove_shell_geometry, validate_shell_descriptor
from forge.stage4_review.glove_surface_gates import measure_hand_separation, validate_glove_surface_contract

FIXTURE = Path(__file__).parent / "fixtures" / "glove_sport_v1" / "dorsal.png"
SPEC = {"materials": [{"id": "glove-leather", "qualityTier": "reference"}]}


class GloveShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.geometry = build_glove_shell_geometry(FIXTURE, source_view_id="glove-view-1-dorsal", grid=48)

    def test_one_closed_shell_per_hand(self):
        meshes = self.geometry["meshes"]
        self.assertEqual({mesh["hand"] for mesh in meshes}, {"left", "right"})
        self.assertEqual(len(meshes), 2)
        for mesh in meshes:
            with self.subTest(hand=mesh["hand"]):
                self.assertEqual(mesh["measurements"]["boundaryEdges"], 0)
                self.assertEqual(mesh["measurements"]["nonManifoldEdges"], 0)

    def test_manifoldness_is_measured_not_promised(self):
        integrity = self.geometry["integrity"]
        self.assertEqual(integrity["productionManifold"]["status"], "measured")
        self.assertEqual(integrity["productionManifold"]["value"], 1.0)
        self.assertEqual(integrity["seamBoundaryCorrespondence"]["status"], "measured")

    def test_hands_are_separated_in_space(self):
        separation = measure_hand_separation(self.geometry)
        self.assertTrue(separation["separated"])
        self.assertGreater(separation["minimumSeparation"], 0.0)

    def test_surface_contract_passes_on_a_real_shell(self):
        self.assertEqual(validate_glove_surface_contract(self.geometry, SPEC), [])

    def test_depth_is_declared_inferred_without_a_side_view(self):
        axes = self.geometry["derivation"]["axes"]
        self.assertEqual(axes["x"]["state"], "observed")
        self.assertEqual(axes["y"]["state"], "observed")
        self.assertEqual(axes["z"]["state"], "inferred")
        self.assertEqual(self.geometry["evidenceTier"], "diagnostic")
        self.assertTrue(any("prior" in note for note in self.geometry["limitations"]))

    def test_a_side_view_upgrades_the_depth_axis(self):
        observed = build_glove_shell_geometry(FIXTURE, source_view_id="glove-view-1-dorsal", grid=48, depth_source="glove-view-3-thumb-side-profile")
        self.assertEqual(observed["derivation"]["axes"]["z"]["state"], "observed")
        self.assertEqual(observed["evidenceTier"], "evidence-backed")

    def test_derivation_names_the_source_view(self):
        derivation = self.geometry["derivation"]
        self.assertEqual(derivation["sourceViewIds"], ["glove-view-1-dorsal"])
        self.assertGreater(derivation["confidence"], 0.0)
        self.assertIn("thumbSide", derivation["measured"])

    def test_geometry_report_schema_still_validates(self):
        self.assertEqual(validate_geometry_report(self.geometry, require_production=False), [])

    def test_the_report_carries_a_descriptor_the_runtime_can_rebuild_from(self):
        """SKILL.md promises procedural Three.js, not extracted meshes. The descriptor is what makes
        that possible: the object track already builds `visualHull` and `sdf` geometry at runtime."""
        descriptor = self.geometry["geometryDescriptor"]
        self.assertEqual(validate_shell_descriptor(descriptor), [])
        body = descriptor[DESCRIPTOR_KIND]
        self.assertEqual(len(body["mask"]), body["grid"])
        self.assertEqual(body["sourceViewIds"], ["glove-view-1-dorsal"])
        self.assertEqual(body["depthAxis"]["state"], "inferred")

    def test_the_descriptor_is_far_smaller_than_the_baked_mesh(self):
        descriptor_size = len(json.dumps(self.geometry["geometryDescriptor"]))
        mesh_size = sum(len(json.dumps({key: mesh[key] for key in ("vertices", "indices", "normals", "uv0")})) for mesh in self.geometry["meshes"])
        self.assertLess(descriptor_size * 20, mesh_size)

    def test_a_descriptor_the_runtime_could_not_rebuild_from_is_refused(self):
        body = self.geometry["geometryDescriptor"][DESCRIPTOR_KIND]
        for name, broken in (
            ("grid below the floor", {**body, "grid": 4}),
            ("mask row count", {**body, "mask": ["00", "00"]}),
            ("ragged mask", {**body, "mask": ["1" * body["grid"]] * (body["grid"] - 1) + ["1"]}),
            ("empty mask", {**body, "mask": ["0" * body["grid"]] * body["grid"]}),
            ("unstated depth axis", {**body, "depthAxis": {"state": "guessed", "source": "x"}}),
            ("no source view", {**body, "sourceViewIds": []}),
            ("non-positive thickness", {**body, "palmThicknessRatio": 0}),
        ):
            with self.subTest(case=name):
                self.assertTrue(validate_shell_descriptor({DESCRIPTOR_KIND: broken}))
        self.assertTrue(validate_shell_descriptor({}))

    def test_each_side_is_painted_by_the_view_that_saw_it(self):
        """Panels become surface regions projected onto one shell, which is what
        surfaceRegionEvidence already models. The rim is seen by neither front-axis plate."""
        projection = self.geometry["surfaceProjection"]
        self.assertEqual(projection["mode"], "orthographic-front-projection")
        sides = {side["side"]: side for side in projection["sides"]}
        self.assertEqual(sides["front"]["orientation"], "dorsal")
        self.assertEqual(sides["back"]["orientation"], "palmar")
        self.assertEqual(sides["front"]["uvRect"], [0.0, 0.0, 0.5, 1.0])
        self.assertEqual(sides["back"]["uvRect"], [0.5, 0.0, 0.5, 1.0])
        # Without a palmar plate the back cannot claim to be observed.
        self.assertEqual(sides["back"]["unseenStrategy"], "mirror-symmetry")
        self.assertEqual([entry["region"] for entry in projection["unseen"]], ["silhouette-rim"])

    def test_no_triangle_straddles_the_atlas_seam(self):
        """A triangle with uvs in both halves interpolates its texture across the seam, which is the
        fringing that made the rim visible. Surface quads sit in the half of the view that saw them;
        the rim is pinned to the dorsal half as a whole, because a rim quad joins a front vertex to a
        back one and only a single-half assignment keeps it off the seam."""
        for mesh in self.geometry["meshes"]:
            uv = mesh["uv0"]
            for triangle in mesh["indices"]:
                us = [uv[index][0] for index in triangle]
                with self.subTest(mesh=mesh["id"], triangle=triangle):
                    self.assertTrue(max(us) <= 0.5 or min(us) >= 0.5)

    def test_surface_sides_take_the_view_that_saw_them(self):
        mesh = next(item for item in self.geometry["meshes"] if item["hand"] == "left")
        # Rim vertices duplicate a surface position, so identify surface vertices by the sides that
        # are not shared with a rim quad.
        rim_indices = {index for triangle in mesh["indices"] for index in triangle}
        front = [index for index, vertex in enumerate(mesh["vertices"]) if vertex[2] > 0 and index in rim_indices]
        back = [index for index, vertex in enumerate(mesh["vertices"]) if vertex[2] < 0 and index in rim_indices]
        self.assertTrue(front and back)
        self.assertTrue(all(mesh["uv0"][index][0] <= 0.5 for index in front))
        self.assertTrue(any(mesh["uv0"][index][0] >= 0.5 for index in back))

    def test_a_palmar_plate_makes_the_back_observed(self):
        observed = build_glove_shell_geometry(
            FIXTURE, source_view_id="glove-view-1-dorsal", grid=48,
            palmar_reference=FIXTURE.parent / "palmar.png", palmar_source_view_id="glove-view-2-palmar",
        )
        back = next(side for side in observed["surfaceProjection"]["sides"] if side["side"] == "back")
        self.assertEqual(back["sourceViewId"], "glove-view-2-palmar")
        self.assertNotIn("unseenStrategy", back)
        self.assertEqual(observed["derivation"]["backSurfaceSource"], "glove-view-2-palmar")

    def test_a_coarser_grid_that_erases_the_subject_is_refused(self):
        with self.assertRaises(ValueError):
            build_glove_shell_geometry(FIXTURE, source_view_id="glove-view-1-dorsal", grid=3)


if __name__ == "__main__":
    unittest.main()
