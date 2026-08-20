"""Read one GLB node's triangle mesh and its base-colour texture.

Used only to MANUFACTURE TEST VIEWS with known ground truth. The photogrammetry pipeline itself never
reads a GLB -- that is the whole point of it -- but validating an MVS reconstruction against a claim
is worthless, so the honest test is: render a real mesh from known cameras, run the pipeline on those
images alone, and compare the result against the mesh it never saw. This module supplies the mesh.
"""
from __future__ import annotations

import io
import json
import struct
from pathlib import Path

import numpy as np

_COMPONENT = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4", 5126: "f4"}
_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


class Glb:
    def __init__(self, path: Path):
        raw = Path(path).read_bytes()
        off, chunks = 12, {}
        while off < len(raw):
            length, kind = struct.unpack_from("<II", raw, off)
            chunks[kind] = raw[off + 8: off + 8 + length]
            off += 8 + length
            off = off if off % 4 == 0 else off + (4 - off % 4)
        self.gltf = json.loads(chunks[0x4E4F534A].decode())
        self.bin = chunks[0x004E4942]

    def accessor(self, index: int) -> np.ndarray:
        acc = self.gltf["accessors"][index]
        view = self.gltf["bufferViews"][acc["bufferView"]]
        dtype = np.dtype("<" + _COMPONENT[acc["componentType"]])
        per = _COUNT[acc["type"]]
        offset = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        flat = np.frombuffer(self.bin, dtype=dtype, count=acc["count"] * per, offset=offset)
        return flat.reshape(acc["count"], per) if per > 1 else flat

    def node_mesh(self, node_index: int) -> dict:
        """Positions, normals, UVs and a single concatenated triangle index buffer for one node.

        A node's primitives are concatenated with their index buffers offset, so the caller gets one
        mesh rather than a list it has to stitch. Node transforms are applied if present; girl-character
        happens to have none, and silently ignoring one on a character that does would misplace the
        entire reconstruction.
        """
        node = self.gltf["nodes"][node_index]
        prims = self.gltf["meshes"][node["mesh"]]["primitives"]

        positions, normals, uvs, tris, base = [], [], [], [], 0
        material = None
        for prim in prims:
            attrs = prim["attributes"]
            pos = self.accessor(attrs["POSITION"]).astype(np.float64)
            nrm = (self.accessor(attrs["NORMAL"]).astype(np.float64) if "NORMAL" in attrs
                   else np.zeros_like(pos))
            uv = (self.accessor(attrs["TEXCOORD_0"]).astype(np.float64) if "TEXCOORD_0" in attrs
                  else np.zeros((len(pos), 2)))
            if "indices" not in prim:
                raise SystemExit("primitive has no index buffer; non-indexed meshes are not supported")
            idx = self.accessor(prim["indices"]).astype(np.int64).reshape(-1, 3)
            positions.append(pos)
            normals.append(nrm)
            uvs.append(uv)
            tris.append(idx + base)
            base += len(pos)
            if material is None:
                material = prim.get("material")

        mesh = {
            "P": np.concatenate(positions),
            "N": np.concatenate(normals),
            "UV": np.concatenate(uvs),
            "T": np.concatenate(tris),
            "material": material,
        }

        matrix = node.get("matrix")
        if matrix is not None:
            M = np.array(matrix, dtype=np.float64).reshape(4, 4).T   # glTF stores column-major
            mesh["P"] = mesh["P"] @ M[:3, :3].T + M[:3, 3]
            mesh["N"] = mesh["N"] @ np.linalg.inv(M[:3, :3])         # inverse-transpose, transposed
        elif any(k in node for k in ("translation", "rotation", "scale")):
            raise SystemExit(f"node {node_index} has TRS components; only `matrix` is handled so far")

        norms = np.linalg.norm(mesh["N"], axis=1, keepdims=True)
        mesh["N"] = mesh["N"] / np.maximum(norms, 1e-12)
        return mesh

    def base_colour_image(self, material_index: int | None):
        """The material's baseColorTexture as an (h, w, 3) uint8 array, or None if it has none."""
        if material_index is None:
            return None
        try:
            from PIL import Image
        except ImportError:
            return None
        material = self.gltf["materials"][material_index]
        tex_index = material.get("pbrMetallicRoughness", {}).get("baseColorTexture", {}).get("index")
        if tex_index is None:
            return None
        source = self.gltf["textures"][tex_index].get("source")
        if source is None:
            return None
        image = self.gltf["images"][source]
        if "bufferView" not in image:
            return None
        view = self.gltf["bufferViews"][image["bufferView"]]
        start = view.get("byteOffset", 0)
        blob = self.bin[start: start + view["byteLength"]]
        with Image.open(io.BytesIO(blob)) as handle:
            return np.asarray(handle.convert("RGB"), dtype=np.uint8)
