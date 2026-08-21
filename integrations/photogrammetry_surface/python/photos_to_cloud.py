"""Multi-view images -> one oriented point cloud, ready for the existing Surface Nets reconstruction.

This is the whole pipeline in one command. It reads images and camera poses and writes `cloud.npz`
holding `P` and `N` -- the exact contract `build_head_surface.py` already consumes via
CHARACTER_CLOUD_NPZ, so nothing downstream (encode, emit, verify, capture) changes at all.

Poses come from one of two places:
  --cameras cameras.json   poses already known (a rendered fixture, or a calibrated rig)
  --sfm                    estimate them from the images with COLMAP (see sfm_poses.py)

Stages, and what each is for:
  1. masks       separate subject from background, so the sweep never matches backdrop
  2. depth range derived from the poses' own convergence, not guessed
  3. sweep       plane-sweep ZNCC per view (dense_mvs.sweep_depth)
  4. consistency cross-view agreement filter -- the step that makes the cloud usable
  5. fuse        back-project, estimate normals, voxel-average (fuse_cloud.fuse)

Usage:
  photos_to_cloud.py --images work/views --cameras work/views/cameras.json --out work/cloud.npz
                     [--cell 0.0015] [--planes 96] [--window 4] [--neighbours 4]
                     [--min-confidence 0.35] [--min-agreeing 2] [--max-views 0]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cameras import Camera, load_cameras  # noqa: E402
from dense_mvs import geometric_consistency, sweep_depth  # noqa: E402
from fuse_cloud import fuse  # noqa: E402

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def load_images(image_dir: Path, cams: list[Camera]) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Greyscale image + subject mask per camera, matched to cameras by name."""
    greys, masks = [], []
    for cam in cams:
        found = None
        for suffix in IMAGE_SUFFIXES:
            candidate = image_dir / f"{cam.name}{suffix}"
            if candidate.exists():
                found = candidate
                break
        if found is None:
            raise SystemExit(f"no image for camera {cam.name!r} in {image_dir} "
                             f"(looked for {cam.name}{{{','.join(IMAGE_SUFFIXES)}}})")
        with Image.open(found) as handle:
            rgb = handle.convert("RGB")
            if rgb.size != (cam.width, cam.height):
                raise SystemExit(f"{found.name} is {rgb.size} but its camera says "
                                 f"{(cam.width, cam.height)}; a mismatched intrinsic silently "
                                 f"misplaces every depth")
            grey = np.asarray(rgb.convert("L"), dtype=np.float64)

        mask_path = image_dir / f"{cam.name}_mask.png"
        if mask_path.exists():
            with Image.open(mask_path) as handle:
                mask = np.asarray(handle.convert("L")) > 127
        else:
            # No supplied mask: assume a dark, uniform backdrop, which is what a rendered fixture and
            # a lightbox photo both give. Said out loud in the report rather than assumed silently.
            mask = grey > 8.0
        greys.append(grey)
        masks.append(mask)
    return greys, masks


def depth_range(cams: list[Camera]) -> tuple[float, float, np.ndarray, float, float]:
    """Depth bounds from where the cameras' own optical axes converge.

    The subject sits near the point the views look at, and its extent is bounded by how far the
    cameras are from it. Deriving the range costs nothing and removes a magic number that would
    silently clip a larger subject.

    Returns `(near, far, convergence_point, mean_radius, radius_spread)`.
    """
    centres = np.array([c.centre for c in cams])
    forwards = np.array([c.forward for c in cams])
    # Least-squares intersection of all viewing axes.
    A = np.zeros((3, 3))
    b = np.zeros(3)
    for centre, forward in zip(centres, forwards):
        proj = np.eye(3) - np.outer(forward, forward)
        A += proj
        b += proj @ centre
    target = np.linalg.lstsq(A, b, rcond=None)[0]
    distances = np.linalg.norm(centres - target, axis=1)
    radius = float(distances.mean())
    spread = float(np.linalg.norm(centres - target, axis=1).std())
    # A subject is assumed to sit within 65% of the camera distance either side of the convergence
    # point. Wider than any sane framing, and the sweep spends planes rather than missing surface.
    near = radius * 0.35
    far = radius * 1.75
    return near, far, target, radius, spread


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True)
    ap.add_argument("--cameras", help="cameras.json with known poses")
    ap.add_argument("--sfm", action="store_true", help="estimate poses from the images with COLMAP")
    ap.add_argument("--sfm-work", default=None, help="scratch dir for COLMAP (default: <images>/_sfm)")
    ap.add_argument("--out", required=True, help="destination .npz holding P and N")
    ap.add_argument("--cell", type=float, default=0.0015,
                    help="reconstruction cell size the cloud will be splatted at; the fusion voxel is "
                         "tied to it, since a cloud finer than the grid cannot be represented")
    ap.add_argument("--planes", type=int, default=96)
    ap.add_argument("--window", type=int, default=4)
    ap.add_argument("--neighbours", type=int, default=4)
    ap.add_argument("--top-k", type=int, default=2)
    ap.add_argument("--min-confidence", type=float, default=0.35)
    ap.add_argument("--min-agreeing", type=int, default=2)
    ap.add_argument("--tolerance-ratio", type=float, default=0.01)
    ap.add_argument("--min-views-per-voxel", type=int, default=1)
    ap.add_argument("--pca-k", type=int, default=128,
                    help="neighbours in the local plane fit that sets normal direction")
    ap.add_argument("--min-planarity", type=float, default=0.0,
                    help="drop points whose neighbourhood is a noise ball rather than a plane")
    ap.add_argument("--outlier-sigma", type=float, default=1.0,
                    help="drop points whose mean neighbour gap exceeds mean + sigma*std; 0 disables")
    ap.add_argument("--mls-k", type=int, default=24,
                    help="neighbours in the MLS plane fit that denoises the cloud")
    ap.add_argument("--mls-iterations", type=int, default=1,
                    help="MLS passes; 0 disables. One quadric pass beats two on both noise and "
                         "curvature bias -- see fuse_cloud.mls_project")
    ap.add_argument("--max-views", type=int, default=0, help="0 = all; otherwise cap for a quick run")
    ap.add_argument("--report", default=None, help="write a JSON run report here")
    args = ap.parse_args()

    image_dir = Path(args.images)
    if args.sfm:
        from sfm_poses import estimate_poses
        work = Path(args.sfm_work) if args.sfm_work else image_dir / "_sfm"
        cams = estimate_poses(image_dir, work)
    else:
        if not args.cameras:
            raise SystemExit("pass --cameras cameras.json, or --sfm to estimate poses from the images")
        cams = load_cameras(Path(args.cameras))

    if args.max_views and len(cams) > args.max_views:
        step = len(cams) / args.max_views
        cams = [cams[int(i * step)] for i in range(args.max_views)]
        print(f"--max-views {args.max_views}: using a {len(cams)}-view subset")

    greys, masks = load_images(image_dir, cams)
    near, far, target, radius, spread = depth_range(cams)
    print(f"{len(cams)} views at {cams[0].width}x{cams[0].height}")
    print(f"  axes converge at {np.round(target, 4).tolist()}, mean camera distance {radius:.4f} "
          f"(spread {spread:.4f})")
    print(f"  sweeping depth {near:.4f}..{far:.4f} over {args.planes} inverse-depth planes")
    supplied_masks = sum(1 for c in cams if (image_dir / f"{c.name}_mask.png").exists())
    print(f"  subject masks: {supplied_masks} supplied, {len(cams) - supplied_masks} from a "
          f"dark-backdrop threshold")

    depths: list[np.ndarray | None] = [None] * len(cams)
    confs: list[np.ndarray | None] = [None] * len(cams)
    started = time.time()
    for i, cam in enumerate(cams):
        t0 = time.time()
        result = sweep_depth(cams, greys, masks, i, near, far, planes=args.planes,
                             window=args.window, neighbours=args.neighbours, top_k=args.top_k)
        if result["reason"]:
            print(f"  [{i + 1}/{len(cams)}] {cam.name}: SKIPPED -- {result['reason']}")
            continue
        conf = result["confidence"]
        keep = conf >= args.min_confidence
        depths[i] = np.where(keep, result["depth"], 0.0)
        confs[i] = np.where(keep, conf, 0.0)
        print(f"  [{i + 1}/{len(cams)}] {cam.name}: {keep.sum():,} px above confidence "
              f"({keep.mean():.1%} of frame) in {time.time() - t0:.1f}s")

    usable = [i for i, d in enumerate(depths) if d is not None]
    if len(usable) < 2:
        raise SystemExit("fewer than two views produced usable depth; cannot cross-check anything")

    print(f"\ncross-view consistency (>= {args.min_agreeing} views agreeing, "
          f"tolerance {args.tolerance_ratio:.1%} of depth)")
    keeps: list[np.ndarray | None] = [None] * len(cams)
    for i in usable:
        keeps[i] = geometric_consistency(cams, depths, confs, i,
                                          tolerance_ratio=args.tolerance_ratio,
                                          min_agreeing=args.min_agreeing)
        before = int((depths[i] > 0).sum())
        after = int(keeps[i].sum())
        pct = (after / before) if before else 0.0
        print(f"  {cams[i].name}: {before:,} -> {after:,} px survive ({pct:.1%})")

    voxel = args.cell * 0.5
    print(f"\nfusing (voxel {voxel * 1000:.2f} mm = half the {args.cell * 1000:.2f} mm cell)")
    fused = fuse(cams, depths, [k if k is not None else None for k in keeps], confs,
                 voxel=voxel, min_views_per_voxel=args.min_views_per_voxel,
                 pca_k=args.pca_k, min_planarity=args.min_planarity,
                 outlier_sigma=args.outlier_sigma, mls_k=args.mls_k,
                 mls_iterations=args.mls_iterations)
    P, N = fused["P"], fused["N"]
    if len(P) == 0:
        raise SystemExit("fusion produced no points; loosen --min-confidence or --min-agreeing")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, P=P.astype(np.float64), N=N.astype(np.float64))
    extent = P.max(axis=0) - P.min(axis=0)
    print(f"  {fused['rawCount']:,} raw -> {fused['afterVoxel']:,} voxel-averaged -> "
          f"{fused['afterOutliers']:,} after outlier removal -> {len(P):,} final")
    if args.mls_iterations:
        print(f"  MLS: {args.mls_iterations} pass(es) at k={args.mls_k}")
    print(f"  extent {np.round(extent, 4).tolist()} m")
    print(f"\nwrote {out}")
    print(f"total {time.time() - started:.1f}s")

    if args.report:
        Path(args.report).write_text(json.dumps({
            "views": len(cams),
            "usableViews": len(usable),
            "rawPoints": int(fused["rawCount"]),
            "points": int(len(P)),
            "voxel": voxel,
            "cell": args.cell,
            "depthRange": [near, far],
            "convergence": target.tolist(),
            "cameraRadius": radius,
            "perViewKeptPixels": fused["perView"],
            "settings": {k: v for k, v in vars(args).items()},
        }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
