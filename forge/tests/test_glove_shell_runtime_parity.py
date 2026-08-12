"""The emitted runtime builder must rebuild the shell the intake measured.

A descriptor is only a substitute for the baked mesh if the runtime reproduces that mesh. This runs
the generated TypeScript against real three and compares it to the Python builder vertex for vertex,
so a drift between the two implementations fails rather than shipping a different glove to the
browser than the one the review gated.
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
# generate_threejs_factory reaches its siblings by flat import, as the rest of stage3 does.
sys.path.insert(0, str(ROOT / "forge" / "stage3_build"))

from forge.stage3_build.generate_threejs_factory import geometry_for
from forge.stage3_build.glove_shell import DESCRIPTOR_KIND, build_glove_shell_geometry

FIXTURE = Path(__file__).parent / "fixtures" / "glove_sport_v1" / "dorsal.png"
PALMAR_FIXTURE = Path(__file__).parent / "fixtures" / "glove_sport_v1" / "palmar.png"
GRID = 20
SHOWCASE = os.environ.get("IMG2THREEJS_SHOWCASE_ROOT")
REQUIRED = os.environ.get("IMG2THREEJS_REQUIRE_SHOWCASE") == "1"


def _three_module() -> Path | None:
    if not SHOWCASE:
        return None
    candidate = Path(SHOWCASE) / "node_modules" / "three" / "build" / "three.module.js"
    return candidate if candidate.is_file() else None


def _helper_source() -> str:
    """Pull the emitted builder out of the generator so the test runs the shipped code."""
    from forge.stage3_build import generate_threejs_factory as factory

    source = Path(factory.__file__).read_text(encoding="utf-8")
    lines: list[str] = []
    collecting = False
    for raw in source.splitlines():
        stripped = raw.strip()
        if stripped.startswith('"interface SilhouetteInflationDescriptor {"'):
            collecting = True
        if collecting:
            if stripped in {"]", "]", ")"} or stripped.startswith("if \"lathe\""):
                break
            if stripped.startswith('"') and stripped.endswith('",'):
                lines.append(json.loads(stripped[:-1]))
            elif stripped.startswith('"') and stripped.endswith('"'):
                lines.append(json.loads(stripped))
    if not any("function buildSilhouetteInflationGeometry" in line for line in lines):
        raise AssertionError("could not extract the emitted silhouette-inflation builder")
    return "\n".join(lines)


class GloveShellRuntimeParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.geometry = build_glove_shell_geometry(FIXTURE, source_view_id="glove-view-1-dorsal", grid=GRID)
        cls.descriptor = cls.geometry["geometryDescriptor"]

    def test_the_generator_dispatches_the_primitive(self):
        component = {"id": "glove-shell", "geometryDescriptor": self.descriptor}
        expression = geometry_for("silhouette-inflation", component)
        self.assertTrue(expression.startswith("buildSilhouetteInflationGeometry("))
        self.assertIn('"grid"', expression)

    def test_a_component_without_the_descriptor_is_refused(self):
        with self.assertRaises(ValueError):
            geometry_for("silhouette-inflation", {"id": "x", "geometryDescriptor": {}})

    def _parity(self, geometry, hand: str) -> None:
        three = _three_module()
        if three is None:
            if REQUIRED:
                self.fail("IMG2THREEJS_REQUIRE_SHOWCASE=1 but three was not found under IMG2THREEJS_SHOWCASE_ROOT")
            self.skipTest("set IMG2THREEJS_SHOWCASE_ROOT to a showcase checkout to run the runtime parity gate")
        body = dict(geometry["geometryDescriptor"][DESCRIPTOR_KIND])
        body["hand"] = hand
        harness = "\n".join(
            [
                f"import * as THREE from {json.dumps(three.as_posix())};",
                _helper_source(),
                f"const geometry = buildSilhouetteInflationGeometry({json.dumps(body)} as SilhouetteInflationDescriptor);",
                "const position = geometry.getAttribute('position');",
                "const index = geometry.getIndex();",
                "process.stdout.write(JSON.stringify({",
                "  vertexCount: position.count,",
                "  indexCount: index === null ? 0 : index.count,",
                "  positions: Array.from(position.array as Float32Array).map((value) => Math.round(value * 1e4) / 1e4),",
                "  uvs: Array.from((geometry.getAttribute('uv').array) as Float32Array).map((value) => Math.round(value * 1e4) / 1e4),",
                "}));",
            ]
        )
        with tempfile.TemporaryDirectory(prefix="img2-shell-parity-") as raw:
            script = Path(raw) / "parity.ts"
            script.write_text(harness, encoding="utf-8")
            completed = subprocess.run(
                ["node", "--experimental-strip-types", "--no-warnings", str(script)],
                capture_output=True, text=True, cwd=ROOT,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])
        runtime = json.loads(completed.stdout)
        mesh = next(item for item in geometry["meshes"] if item["hand"] == hand)
        self.assertEqual(runtime["vertexCount"], len(mesh["vertices"]))
        self.assertEqual(runtime["indexCount"], len(mesh["indices"]) * 3)
        expected = [round(value, 4) for vertex in mesh["vertices"] for value in vertex]
        self.assertEqual(len(runtime["positions"]), len(expected))
        worst = max(abs(a - b) for a, b in zip(runtime["positions"], expected))
        self.assertLess(worst, 1e-3, f"runtime and python vertices diverge by {worst}")
        # UVs decide which plate paints which side, so a drift there is a texturing bug the
        # position comparison cannot see.
        expected_uv = [round(value, 4) for pair in mesh["uv0"] for value in pair]
        self.assertEqual(len(runtime["uvs"]), len(expected_uv))
        worst_uv = max(abs(a - b) for a, b in zip(runtime["uvs"], expected_uv))
        self.assertLess(worst_uv, 1e-3, f"runtime and python uvs diverge by {worst_uv}")

    def test_runtime_matches_python_for_both_hands(self):
        for hand in ("left", "right"):
            with self.subTest(hand=hand):
                self._parity(self.geometry, hand)

    def test_runtime_matches_python_with_a_palmar_back_surface(self):
        """The asymmetric path is where the two implementations are easiest to drift apart."""
        asymmetric = build_glove_shell_geometry(
            FIXTURE, source_view_id="glove-view-1-dorsal", grid=GRID,
            palmar_reference=PALMAR_FIXTURE, palmar_source_view_id="glove-view-2-palmar",
        )
        body = asymmetric["geometryDescriptor"][DESCRIPTOR_KIND]
        self.assertIn("backMask", body)
        self.assertNotEqual(body["frontShare"], body["backShare"])
        self._parity(asymmetric, "left")


if __name__ == "__main__":
    unittest.main()
