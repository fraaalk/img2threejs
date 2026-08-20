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

    manifest = []
    for cam in cams:
        result = render(cam, mesh, texture)
        Image.fromarray(result["colour"]).save(out_dir / f"{cam.name}.png")
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
