"""The seam contract: any oriented point cloud reaches the same reconstruction a GLB does.

This is the test that makes the photogrammetry front end worth having. If feeding a GLB's own cloud
through CHARACTER_CLOUD_NPZ did not reproduce the GLB route exactly, the photo route would be running
a DIFFERENT reconstruction and every comparison between the two would be meaningless.

Every numpy-dependent step runs in a SUBPROCESS under the integration's own venv, never in the test
process. `forge/tests` runs on the ambient stdlib-only interpreter, and a test that needed numpy
imported here would skip on exactly the interpreter the suite actually uses -- which is the same as
not having the test. Skips only when the showcase checkout or the venv is genuinely absent.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BUILD = REPO / "integrations/glb_character_pipeline/python/build_head_surface.py"
VENV = REPO / "integrations/glb_character_pipeline/.venv/bin/python3"
NODE = 9
CELL = "0.004"          # coarse on purpose: this asserts equivalence, not fidelity, so keep it quick


class CloudSeam(unittest.TestCase):
    def setUp(self) -> None:
        root = os.environ.get("IMG2THREEJS_SHOWCASE_ROOT")
        if not root:
            self.skipTest("IMG2THREEJS_SHOWCASE_ROOT is unset")
        self.showcase = Path(root)
        self.glb = self.showcase / "public/mesh/girl-character-baseline.glb"
        if not self.glb.exists():
            self.skipTest(f"{self.glb} is missing")
        self.python = str(VENV) if VENV.exists() else sys.executable
        if subprocess.run([self.python, "-c", "import numpy"], capture_output=True).returncode != 0:
            self.skipTest("numpy unavailable; run uv sync --project integrations/glb_character_pipeline")

    def _build(self, workdir: Path, cloud: Path | None) -> None:
        env = dict(os.environ)
        env["IMG2THREEJS_SHOWCASE_ROOT"] = str(self.showcase)
        env["CHARACTER_WORKDIR"] = str(workdir)
        env.pop("CHARACTER_CLOUD_NPZ", None)
        if cloud is not None:
            env["CHARACTER_CLOUD_NPZ"] = str(cloud)
        done = subprocess.run([self.python, str(BUILD), str(NODE), CELL],
                              env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, f"build failed:\n{done.stdout}\n{done.stderr}")

    def _py(self, code: str) -> subprocess.CompletedProcess:
        return subprocess.run([self.python, "-c", code], capture_output=True, text=True)

    def test_glb_cloud_through_the_seam_reproduces_the_glb_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            via_glb, via_npz = tmp / "via-glb", tmp / "via-npz"
            cloud = tmp / "cloud.npz"

            self._build(via_glb, None)

            extract = f"""
import json, struct, numpy as np
from pathlib import Path
raw = Path({str(self.glb)!r}).read_bytes()
off, chunks = 12, {{}}
while off < len(raw):
    ln, ty = struct.unpack_from('<II', raw, off); chunks[ty] = raw[off+8:off+8+ln]; off += 8+ln
    off = off if off % 4 == 0 else off + (4 - off % 4)
g = json.loads(chunks[0x4E4F534A].decode()); BIN = chunks[0x004E4942]
def acc(i):
    a=g['accessors'][i]; bv=g['bufferViews'][a['bufferView']]
    dt={{5120:'i1',5121:'u1',5122:'i2',5123:'u2',5125:'u4',5126:'f4'}}[a['componentType']]
    nc={{'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}}[a['type']]
    o=bv.get('byteOffset',0)+a.get('byteOffset',0)
    return np.frombuffer(BIN,dtype=np.dtype('<'+dt),count=a['count']*nc,offset=o).reshape(a['count'],nc)
prims = g['meshes'][g['nodes'][{NODE}]['mesh']]['primitives']
P = np.concatenate([acc(p['attributes']['POSITION']) for p in prims]).astype(np.float64)
N = np.concatenate([acc(p['attributes']['NORMAL']) for p in prims]).astype(np.float64)
np.savez({str(cloud)!r}, P=P, N=N)
"""
            done = self._py(extract)
            self.assertEqual(done.returncode, 0, done.stderr)

            self._build(via_npz, cloud)

            compare = f"""
import numpy as np, sys
a_v = np.load({str(via_glb / 'V.npy')!r}); b_v = np.load({str(via_npz / 'V.npy')!r})
a_t = np.load({str(via_glb / 'T.npy')!r}); b_t = np.load({str(via_npz / 'T.npy')!r})
problems = []
if a_v.shape != b_v.shape: problems.append(f"vertex shape {{a_v.shape}} != {{b_v.shape}}")
if a_t.shape != b_t.shape: problems.append(f"triangle shape {{a_t.shape}} != {{b_t.shape}}")
if not problems:
    if not np.array_equal(a_v, b_v): problems.append("vertices differ")
    if not np.array_equal(a_t, b_t): problems.append("triangles differ")
if problems:
    print("; ".join(problems)); sys.exit(1)
print(f"identical: {{len(a_v)}} vertices, {{len(a_t)}} triangles")
"""
            done = self._py(compare)
            self.assertEqual(done.returncode, 0,
                             f"the seam is not source-agnostic: {done.stdout}{done.stderr}")
            self.assertIn("identical:", done.stdout)

    def test_seam_rejects_a_cloud_with_no_normals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.npz"
            done = self._py(f"import numpy as np; np.savez({str(bad)!r}, P=np.zeros((10,3)))")
            self.assertEqual(done.returncode, 0, done.stderr)

            env = dict(os.environ)
            env["IMG2THREEJS_SHOWCASE_ROOT"] = str(self.showcase)
            env["CHARACTER_WORKDIR"] = str(Path(tmp) / "out")
            env["CHARACTER_CLOUD_NPZ"] = str(bad)
            done = subprocess.run([self.python, str(BUILD), str(NODE), CELL],
                                  env=env, capture_output=True, text=True)
            self.assertNotEqual(done.returncode, 0,
                                "an unoriented cloud must be refused, not splatted with zero normals")
            self.assertIn("'P' and 'N'", done.stdout + done.stderr)

    def test_seam_rejects_a_mis_shaped_cloud(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.npz"
            done = self._py(
                f"import numpy as np; np.savez({str(bad)!r}, P=np.zeros((10,3)), N=np.zeros((7,3)))")
            self.assertEqual(done.returncode, 0, done.stderr)

            env = dict(os.environ)
            env["IMG2THREEJS_SHOWCASE_ROOT"] = str(self.showcase)
            env["CHARACTER_WORKDIR"] = str(Path(tmp) / "out")
            env["CHARACTER_CLOUD_NPZ"] = str(bad)
            done = subprocess.run([self.python, str(BUILD), str(NODE), CELL],
                                  env=env, capture_output=True, text=True)
            self.assertNotEqual(done.returncode, 0, "mismatched P/N lengths must be refused")


if __name__ == "__main__":
    unittest.main()
