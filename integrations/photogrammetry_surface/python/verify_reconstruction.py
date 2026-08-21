"""Score a photogrammetry cloud against the mesh it was never shown.

THE ONLY HONEST TEST OF THIS PIPELINE. Everything else it prints -- pixel counts, survival rates,
confidence -- is self-reported. This compares the reconstruction against ground truth the pipeline
had no access to, and reports the two errors that actually matter, in both directions, because one
direction alone is easy to look good on:

  ACCURACY   distance from each reconstructed point to the true surface. Low accuracy error with a
             cloud covering 5% of the subject is a pipeline that reconstructed an ear very well.
  COMPLETENESS distance from each true surface point to the nearest reconstructed point. Low
             completeness error with points everywhere including empty space is a pipeline that
             filled the volume with noise.

Reporting one without the other is the standard way an MVS result is made to look better than it is,
so this refuses to print either alone.

Distances are computed against the mesh's VERTICES, not its faces -- a point-to-point distance on a
130k-vertex head is an upper bound on point-to-surface, so every number here is pessimistic rather
than flattering. Said out loud because the difference matters when the mesh is coarse.

Usage:
  verify_reconstruction.py --cloud work/cloud.npz --glb model.glb --node 9 [--json report.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glb_mesh import Glb  # noqa: E402


def nearest_distances(query: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Exact distance from each `query` point to the nearest `target` point.

    Exact, not approximate: an approximate nearest neighbour would report a LARGER distance than the
    truth for accuracy and a larger one for completeness too, so it would flatter neither -- but it
    would make the two numbers incomparable between runs. A KD-tree keeps them exact and is fast
    enough that there is no reason to trade that away.
    """
    tree = cKDTree(target)
    distances, _ = tree.query(query, k=1, workers=-1)
    return np.asarray(distances, dtype=np.float64)


def summarise(name: str, distances: np.ndarray) -> dict:
    finite = distances[np.isfinite(distances)]
    if len(finite) == 0:
        return {"name": name, "count": 0}
    return {
        "name": name,
        "count": int(len(finite)),
        "medianMm": float(np.median(finite) * 1000),
        "meanMm": float(finite.mean() * 1000),
        "p90Mm": float(np.percentile(finite, 90) * 1000),
        "p99Mm": float(np.percentile(finite, 99) * 1000),
        "under1mm": float((finite < 0.001).mean()),
        "under2mm": float((finite < 0.002).mean()),
        "under5mm": float((finite < 0.005).mean()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cloud", required=True)
    ap.add_argument("--glb", required=True)
    ap.add_argument("--node", type=int, required=True)
    ap.add_argument("--sample", type=int, default=120000,
                    help="cap on points scored per direction, sampled deterministically")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    with np.load(args.cloud) as data:
        P = np.asarray(data["P"], dtype=np.float64)
        N = np.asarray(data["N"], dtype=np.float64)
    truth = Glb(Path(args.glb)).node_mesh(args.node)
    G = truth["P"]
    GN = truth["N"]

    print(f"reconstruction: {len(P):,} points | ground truth: {len(G):,} vertices")
    ext_p = P.max(axis=0) - P.min(axis=0)
    ext_g = G.max(axis=0) - G.min(axis=0)
    print(f"  extent recon {np.round(ext_p, 4).tolist()}")
    print(f"  extent truth {np.round(ext_g, 4).tolist()}")
    print(f"  extent ratio {np.round(ext_p / np.maximum(ext_g, 1e-9), 3).tolist()}")

    rng = np.random.default_rng(0)
    pi = rng.choice(len(P), min(args.sample, len(P)), replace=False)
    gi = rng.choice(len(G), min(args.sample, len(G)), replace=False)

    acc = nearest_distances(P[pi], G)
    comp = nearest_distances(G[gi], P)
    accuracy = summarise("accuracy (recon -> truth)", acc)
    completeness = summarise("completeness (truth -> recon)", comp)

    for block in (accuracy, completeness):
        print(f"\n{block['name']}  ({block['count']:,} points)")
        print(f"  median {block['medianMm']:.2f} mm | mean {block['meanMm']:.2f} mm | "
              f"p90 {block['p90Mm']:.2f} mm | p99 {block['p99Mm']:.2f} mm")
        print(f"  under 1 mm {block['under1mm']:.1%} | under 2 mm {block['under2mm']:.1%} | "
              f"under 5 mm {block['under5mm']:.1%}")

    # Normal agreement, on the points that landed close enough for the comparison to mean anything.
    close = acc < 0.002
    normal_report = {"comparedPoints": int(close.sum())}
    if close.sum() > 0:
        subset = P[pi][close]
        _, near_idx = cKDTree(G).query(subset, k=1, workers=-1)
        dots = np.abs((N[pi][close] * GN[near_idx]).sum(axis=1))
        angles = np.degrees(np.arccos(np.clip(dots, -1, 1)))
        normal_report.update({
            "medianAngleDeg": float(np.median(angles)),
            "p90AngleDeg": float(np.percentile(angles, 90)),
            "within15deg": float((angles < 15).mean()),
            "within30deg": float((angles < 30).mean()),
        })
        print(f"\nnormal agreement, on the {close.sum():,} points within 2 mm of truth")
        print(f"  median {normal_report['medianAngleDeg']:.1f}deg | "
              f"p90 {normal_report['p90AngleDeg']:.1f}deg | "
              f"within 15deg {normal_report['within15deg']:.1%} | "
              f"within 30deg {normal_report['within30deg']:.1%}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "cloud": str(Path(args.cloud).resolve()),
            "groundTruth": {"glb": str(Path(args.glb).resolve()), "node": args.node,
                            "vertices": int(len(G))},
            "points": int(len(P)),
            "extentRecon": ext_p.tolist(),
            "extentTruth": ext_g.tolist(),
            "accuracy": accuracy,
            "completeness": completeness,
            "normals": normal_report,
        }, indent=1))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
