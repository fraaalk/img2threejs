"""Manufacture a multi-view fixture from a GLB node: images, known cameras, and ground truth.

THIS IS THE TEST HARNESS, NOT PART OF THE PIPELINE. The photogrammetry pipeline reads images only.
This script exists so the pipeline's accuracy can be MEASURED against geometry it never saw, instead
of asserted -- render a real textured mesh from known viewpoints, hand the pipeline nothing but the
PNGs, then compare the surface it produces against the mesh.

The ground-truth depth and normal maps are written alongside each image and are for scoring only;
no pipeline stage may read a `*_depth.npy` or `*_normal.npy`, and `verify_reconstruction.py` is the
only consumer.

Usage:
  render_views.py --glb model.glb --node 9 --out work/views [--views 12] [--size 512]
                  [--fov 40] [--elevations 0,20] [--seed 0] [--jitter 0]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cameras import Camera, intrinsics, look_at, save_cameras  # noqa: E402
from glb_mesh import Glb  # noqa: E402
from rasterise import render  # noqa: E402


def backdrop_mesh(centre: np.ndarray, radius: float, seed: int = 0,
                  rings: int = 48, segments: int = 96) -> tuple[dict, np.ndarray]:
    """An inward-facing textured sphere enclosing the subject, plus its texture.

    WHY A FIXTURE NEEDS THIS AT ALL, measured rather than assumed. A subject on a pure black
    background is the *easy* case for MVS -- the mask is free -- and an impossible case for structure
    from motion, which has to recover pose from image features alone. On the black-background fixture
    COLMAP found 201-670 SIFT keypoints per image where a real photograph yields five to twenty
    thousand, verified 68 of 276 pairs, and registered 3 of 24 images. The SfM path could not be
    validated on it at all.

    Real photographs have backgrounds, and a background is what makes pose estimation tractable: it is
    static geometry at a different depth from the subject, so it carries strong parallax. This sphere
    supplies that. Because it is real geometry rather than a pasted 2-D pattern, its parallax is
    consistent across views, which is exactly the property SfM needs and a flat backdrop image would
    not provide.

    The subject mask is written separately, so MVS still gets a clean subject the way a real capture
    would from a lightbox or a segmentation model.
    """
    rng = np.random.default_rng(seed)
    # SMOOTH multi-octave value noise, interpolated rather than block-replicated. This distinction is
    # not cosmetic: a nearest-neighbour upsample makes large flat squares whose only structure is
    # axis-aligned straight edges, and SIFT deliberately REJECTS edge responses -- it keeps blob-like
    # extrema. Measured on the blocky first attempt, the backdrop barely moved feature counts (median
    # 197 keypoints per image, one view as low as 7) and COLMAP still registered only 7 of 24 views.
    # Bilinear octaves give blobs at several scales, which is what a real textured surface presents and
    # what the detector is built to find.
    size = 1024
    texture = np.zeros((size, size), dtype=np.float64)
    amplitude = 1.0
    for octave in range(7):
        n = 4 * 2 ** octave
        coarse = rng.random((n, n)) * 255.0
        with Image.fromarray(coarse.astype(np.uint8)) as handle:
            octave_image = handle.resize((size, size), Image.BILINEAR)
        texture += amplitude * (np.asarray(octave_image, dtype=np.float64) / 255.0)
        amplitude *= 0.65
    texture -= texture.min()
    texture /= max(texture.max(), 1e-12)
    rgb = np.stack([texture * 215 + 20] * 3, axis=-1).astype(np.uint8)

    us = np.linspace(0.0, 1.0, segments + 1)[:-1]
    vs = np.linspace(0.0, 1.0, rings)
    uu, vv = np.meshgrid(us, vs, indexing="xy")
    theta = uu * 2 * np.pi
    phi = vv * np.pi
    points = np.stack([
        centre[0] + radius * np.sin(phi) * np.cos(theta),
        centre[1] + radius * np.cos(phi),
        centre[2] + radius * np.sin(phi) * np.sin(theta),
    ], axis=-1).reshape(-1, 3)
    normals = centre - points
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    # NOT tiled. `rasterise._bilinear` clamps uv to [0,1] rather than wrapping -- correct for a glTF
    # mesh whose UVs are already in range -- so a tiling factor here collapses the whole backdrop onto
    # one edge texel and renders as flat grey. Detail comes from the 1024-square noise instead, which
    # covers the visible part of the sphere at several hundred texels across the frame.
    uvs = np.stack([uu, vv], axis=-1).reshape(-1, 2)

    tris = []
    for r in range(rings - 1):
        for s in range(segments):
            a = r * segments + s
            b = r * segments + (s + 1) % segments
            c = (r + 1) * segments + s
            d = (r + 1) * segments + (s + 1) % segments
            tris.append([a, c, b])
            tris.append([b, c, d])
    mesh = {"P": points, "N": normals, "UV": uvs,
            "T": np.array(tris, dtype=np.int64), "material": None}
    return mesh, rgb


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True)
    ap.add_argument("--node", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--views", type=int, default=12, help="azimuth samples per elevation ring")
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--fov", type=float, default=40.0)
    ap.add_argument("--elevations", default="0,20", help="comma-separated degrees")
    ap.add_argument("--distance-scale", type=float, default=1.3,
                    help="camera distance as a multiple of the node's bounding-box diagonal")
    ap.add_argument("--jitter", type=float, default=0.0,
                    help="random pose jitter in degrees, to stop views being exactly regular")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--backdrop", action="store_true",
                    help="enclose the subject in a textured sphere, so the fixture can exercise the "
                         "SfM path. Without it the black background starves feature detection and only "
                         "the known-pose path is testable -- see backdrop_mesh for the measured numbers")
    ap.add_argument("--masks", action="store_true",
                    help="write <view>_mask.png marking the subject, as a real capture would supply "
                         "from a lightbox or a segmentation model")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)

    glb = Glb(Path(args.glb))
    mesh = glb.node_mesh(args.node)
    texture = glb.base_colour_image(mesh["material"])
    lo, hi = mesh["P"].min(axis=0), mesh["P"].max(axis=0)
    centre = (lo + hi) / 2.0
    diagonal = float(np.linalg.norm(hi - lo))
    distance = diagonal * args.distance_scale
    print(f"node {args.node}: {len(mesh['P']):,} verts, {len(mesh['T']):,} tris, "
          f"bbox diagonal {diagonal:.4f}, camera distance {distance:.4f}")
    if texture is None:
        print("  WARNING: no base-colour texture; views will carry shading gradient only, which is a "
              "harder and less representative test than a real photograph")

    K = intrinsics(args.size, args.size, args.fov)
    elevations = [float(v) for v in args.elevations.split(",") if v.strip()]

    cams: list[Camera] = []
    for elevation in elevations:
        for i in range(args.views):
            az = 360.0 * i / args.views
            if args.jitter:
                az += float(rng.normal(scale=args.jitter))
                elev = elevation + float(rng.normal(scale=args.jitter))
            else:
                elev = elevation
            a, e = np.radians(az), np.radians(elev)
            eye = centre + distance * np.array([np.cos(e) * np.sin(a),
                                                np.sin(e),
                                                np.cos(e) * np.cos(a)])
            R, t = look_at(eye, centre)
            name = f"view_e{int(round(elevation)):+03d}_a{int(round(az)) % 360:03d}"
            cams.append(Camera(K, R, t, args.size, args.size, name))

    back_mesh = back_texture = None
    if args.backdrop:
        back_mesh, back_texture = backdrop_mesh(centre, distance * 2.6, seed=args.seed)
        print(f"  backdrop: textured sphere at radius {distance * 2.6:.3f} "
              f"({len(back_mesh['T']):,} triangles)")

    manifest = []
    for cam in cams:
        result = render(cam, mesh, texture)
        colour = result["colour"]
        if back_mesh is not None:
            back = render(cam, back_mesh, back_texture)
            # Composite: the subject always wins where it exists. The backdrop sits far enough out that
            # a depth test would say the same thing, so this is a shortcut, not a different answer.
            colour = np.where(result["mask"][..., None], colour, back["colour"])
        Image.fromarray(colour).save(out_dir / f"{cam.name}.png")
        if args.masks:
            Image.fromarray((result["mask"] * 255).astype(np.uint8)).save(
                out_dir / f"{cam.name}_mask.png")
        np.save(out_dir / f"{cam.name}_depth.npy", result["depth"].astype(np.float32))
        np.save(out_dir / f"{cam.name}_normal.npy", result["normal"].astype(np.float32))
        coverage = float(result["mask"].mean())
        manifest.append({"name": cam.name, "image": f"{cam.name}.png", "coverage": coverage})
        print(f"  {cam.name}  coverage {coverage:6.2%}")

    save_cameras(out_dir / "cameras.json", cams)
    (out_dir / "fixture.json").write_text(json.dumps({
        "source": str(Path(args.glb).resolve()),
        "node": args.node,
        "views": manifest,
        "centre": centre.tolist(),
        "bboxDiagonal": diagonal,
        "note": "ground-truth *_depth.npy / *_normal.npy are for scoring only; no pipeline stage reads them",
    }, indent=1))
    print(f"\nwrote {len(cams)} views + cameras.json + fixture.json to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
