"""Unit checks on the geometry this pipeline is built out of, against analytic ground truth.

These run in a subprocess under the integration's own venv, same reason as test_cloud_seam.py: the
suite is invoked with the ambient stdlib interpreter and a test that needed numpy imported here would
skip on exactly the interpreter that actually runs it.

Each case is chosen so the right answer is known in closed form -- a sphere's normals are its radial
directions, a plane's are constant -- so a pass means the code agrees with mathematics, not with its
own previous output.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
VENV = PKG / ".venv/bin/python3"


class GeometryCase(unittest.TestCase):
    def setUp(self) -> None:
        self.python = str(VENV) if VENV.exists() else sys.executable
        probe = subprocess.run([self.python, "-c", "import numpy, scipy"], capture_output=True)
        if probe.returncode != 0:
            self.skipTest("numpy/scipy unavailable; run "
                          "uv sync --project integrations/photogrammetry_surface")

    def run_snippet(self, body: str) -> str:
        code = textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {str(PKG / 'python')!r})
            import numpy as np
            {textwrap.indent(textwrap.dedent(body), '            ').lstrip()}
        """)
        done = subprocess.run([self.python, "-c", code], capture_output=True, text=True,
                              env={**os.environ, "PYTHONWARNINGS": "ignore"})
        self.assertEqual(done.returncode, 0, f"snippet failed:\n{done.stdout}\n{done.stderr}")
        return done.stdout


class Cameras(GeometryCase):
    def test_project_backproject_round_trips_to_float_precision(self) -> None:
        out = self.run_snippet("""
            from cameras import Camera, intrinsics, look_at
            rng = np.random.default_rng(0)
            K = intrinsics(320, 240, 45.0)
            R, t = look_at([0.4, 0.3, 0.9], [0.0, 0.0, 0.0])
            cam = Camera(K, R, t, 320, 240)
            depth = np.full((240, 320), 0.9)
            world = cam.backproject(depth)
            uv, z = cam.project(world.reshape(-1, 3))
            uu, vv = np.meshgrid(np.arange(320) + 0.5, np.arange(240) + 0.5, indexing='xy')
            print('depth_err', np.abs(z - 0.9).max())
            print('uv_err', np.abs(uv.reshape(240, 320, 2) - np.stack([uu, vv], -1)).max())
            print('centre_err', np.abs(cam.centre - np.array([0.4, 0.3, 0.9])).max())
        """)
        values = dict(line.split() for line in out.strip().splitlines())
        self.assertLess(float(values["depth_err"]), 1e-12)
        self.assertLess(float(values["uv_err"]), 1e-9)
        self.assertLess(float(values["centre_err"]), 1e-12)

    def test_look_at_refuses_a_degenerate_up_vector(self) -> None:
        out = self.run_snippet("""
            from cameras import look_at
            try:
                look_at([0.0, 1.0, 0.0], [0.0, 0.0, 0.0], up=[0.0, 1.0, 0.0])
                print('raised', 'no')
            except ValueError:
                print('raised', 'yes')
        """)
        self.assertIn("raised yes", out)


class CloudCleanup(GeometryCase):
    def test_mls_denoises_a_known_sphere_without_shrinking_it(self) -> None:
        """Noise must fall, the radius must survive, and one pass must beat two."""
        out = self.run_snippet("""
            from fuse_cloud import mls_project
            rng = np.random.default_rng(1)
            n = 20000
            v = rng.normal(size=(n, 3))
            v /= np.linalg.norm(v, axis=1, keepdims=True)
            radius = 0.10
            noisy = v * radius + rng.normal(scale=0.0010, size=(n, 3))

            def stats(points):
                r = np.linalg.norm(points, axis=1)
                return np.median(np.abs(r - radius)), np.median(r) - radius

            noise_in, _ = stats(noisy)
            noise_1, bias_1 = stats(mls_project(noisy, k=24, iterations=1))
            noise_2, bias_2 = stats(mls_project(noisy, k=24, iterations=2))
            print('noise_in', noise_in)
            print('noise_1', noise_1)
            print('bias_1', abs(bias_1))
            print('noise_2', noise_2)
            print('bias_2', abs(bias_2))
        """)
        v = dict(line.split() for line in out.strip().splitlines())
        noise_in, noise_1, bias_1 = float(v["noise_in"]), float(v["noise_1"]), float(v["bias_1"])
        noise_2, bias_2 = float(v["noise_2"]), float(v["bias_2"])

        # Denoising must actually work: measured 0.660 mm -> 0.173 mm.
        self.assertLess(noise_1, noise_in * 0.4,
                        f"MLS barely helped: {noise_in * 1000:.3f} mm -> {noise_1 * 1000:.3f} mm")
        # Shrinkage is the classic MLS failure -- a sphere smoothed toward its own centre scores well
        # on noise and is the wrong size. This bounds the real measured residual (0.11 mm) rather than
        # asserting a zero the method does not achieve.
        self.assertLess(bias_1, 0.00015,
                        f"shrinkage {bias_1 * 1000:.3f} mm exceeds the measured 0.11 mm")
        # The one-pass default exists because two passes measured worse on BOTH counts. If that ever
        # stops holding, the default should be revisited rather than this test relaxed.
        self.assertLess(noise_1, noise_2, "two passes denoised better than one; revisit the default")
        self.assertLess(bias_1, bias_2, "two passes shrank less than one; revisit the default")

    def test_outlier_removal_drops_planted_floaters_and_keeps_the_surface(self) -> None:
        out = self.run_snippet("""
            from fuse_cloud import remove_outliers
            rng = np.random.default_rng(2)
            n = 8000
            v = rng.normal(size=(n, 3))
            v /= np.linalg.norm(v, axis=1, keepdims=True)
            surface = v * 0.10
            # Floaters well off the surface, sparse enough to have no near neighbours.
            floaters = rng.normal(size=(200, 3))
            floaters /= np.linalg.norm(floaters, axis=1, keepdims=True)
            floaters = floaters * 0.16
            points = np.vstack([surface, floaters])
            keep = remove_outliers(points, np.zeros_like(points), None, sigma=1.0)
            print('surface_kept', keep[:n].mean())
            print('floaters_kept', keep[n:].mean())
        """)
        values = dict(line.split() for line in out.strip().splitlines())
        self.assertGreater(float(values["surface_kept"]), 0.95, "too much real surface discarded")
        self.assertLess(float(values["floaters_kept"]), 0.25, "planted floaters survived")

    def test_pca_normals_recover_a_spheres_radial_directions(self) -> None:
        out = self.run_snippet("""
            from fuse_cloud import pca_normals
            rng = np.random.default_rng(3)
            n = 20000
            v = rng.normal(size=(n, 3))
            v /= np.linalg.norm(v, axis=1, keepdims=True)
            points = v * 0.10
            # Seed normals deliberately crude: correct side, 40 degrees of random error. PCA must
            # supply the direction and take only the sign from these.
            noise = rng.normal(scale=0.7, size=(n, 3))
            seed = v + noise
            seed /= np.linalg.norm(seed, axis=1, keepdims=True)
            seed = np.where(((seed * v).sum(1) < 0)[:, None], -seed, seed)
            N, planarity = pca_normals(points, seed, k=32)
            ang = np.degrees(np.arccos(np.clip(np.abs((N * v).sum(1)), -1, 1)))
            outward = (N * v).sum(1) > 0
            print('median_angle', np.median(ang))
            print('outward_fraction', outward.mean())
            print('median_planarity', np.median(planarity))
        """)
        values = dict(line.split() for line in out.strip().splitlines())
        self.assertLess(float(values["median_angle"]), 6.0,
                        "PCA failed to recover direction from a clean sphere")
        self.assertGreater(float(values["outward_fraction"]), 0.99,
                           "signs were not taken from the seed; the surface would be inverted")
        self.assertGreater(float(values["median_planarity"]), 0.9,
                           "a locally flat patch should score near-planar")


class DenseStereo(GeometryCase):
    def test_box_sum_matches_a_direct_window_sum(self) -> None:
        out = self.run_snippet("""
            from dense_mvs import box_sum
            rng = np.random.default_rng(4)
            a = rng.normal(size=(40, 37))
            r = 3
            got = box_sum(a, r)
            pad = np.pad(a, r, mode='edge')
            want = np.empty_like(got)
            for y in range(a.shape[0]):
                for x in range(a.shape[1]):
                    want[y, x] = pad[y:y + 2 * r + 1, x:x + 2 * r + 1].sum()
            print('max_err', np.abs(got - want).max())
        """)
        self.assertLess(float(out.split()[1]), 1e-9)

    def test_neighbour_choice_respects_both_angle_bounds(self) -> None:
        out = self.run_snippet("""
            from cameras import Camera, intrinsics, look_at
            from dense_mvs import pick_neighbours
            K = intrinsics(64, 64, 40.0)
            cams = []
            for az in range(0, 360, 15):
                a = np.radians(az)
                eye = np.array([np.sin(a), 0.0, np.cos(a)])
                R, t = look_at(eye, [0.0, 0.0, 0.0])
                cams.append(Camera(K, R, t, 64, 64, f'v{az}'))
            nb = pick_neighbours(cams, 0, count=4, min_angle_deg=4.0, max_angle_deg=40.0)
            fwd0 = cams[0].forward
            angles = sorted(round(float(np.degrees(np.arccos(np.clip(fwd0 @ cams[i].forward, -1, 1)))))
                            for i in nb)
            print('angles', ','.join(str(a) for a in angles))
        """)
        angles = [int(v) for v in out.strip().split()[1].split(",")]
        self.assertTrue(angles, "no neighbours chosen on a dense 15-degree orbit")
        for angle in angles:
            self.assertGreaterEqual(angle, 4)
            self.assertLessEqual(angle, 40)


if __name__ == "__main__":
    unittest.main()
