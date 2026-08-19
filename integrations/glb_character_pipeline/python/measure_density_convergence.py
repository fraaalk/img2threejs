"""Does raising slice/spoke density recover REAL form, or only smooth through the same samples?

This is the question that decides whether matching the baseline's triangle count buys anything.
Triangle count is a COST metric; it becomes a FIDELITY metric only if the extra triangles carry
outline that the coarser sampling missed. There is no way to tell by inspection which it is -- hence
this measurement rather than an assumption.

METHOD. Build the radial outline of one band at rising spoke counts and compare each against the
finest, resampled onto a common dense set of rays so the comparison is like-for-like. Sampling that
has CONVERGED shows error collapsing toward zero: the extra spokes are re-describing a curve already
captured. Sampling still SHORT of the form shows error that keeps falling as density rises. The same
test along the height axis answers it for slice count.

Interpretation is the whole point: a converged axis means triangles spent there are cosmetic.

THIS SCRIPT ONLY PRINTS TABLES. Reading them and deciding the final per-node spoke count for
CHARACTER_SPOKES_JSON (min(convergence, density), raised only where a material-patch boundary needs
finer cutting) is a human/agent judgment call -- see PIPELINE.md Stage 1 -- not something this script
resolves for you.

Usage:  python3 measure_density_convergence.py <glb> [nodeIndex]
"""
from __future__ import annotations

import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from slice_node import cluster_slice, radial_outline, read_node_positions  # noqa: E402

RAYS = 360


def outline_on_rays(points, spokes):
    """Outline at `spokes` resolution, re-read on a fixed dense ray set so densities are comparable."""
    ring = radial_outline(points, spokes)
    if len(ring) < 3:
        return None
    cx = sum(p[0] for p in ring) / len(ring)
    cy = sum(p[1] for p in ring) / len(ring)
    polar = sorted((math.atan2(p[1] - cy, p[0] - cx) % (2 * math.pi),
                    math.hypot(p[0] - cx, p[1] - cy)) for p in ring)
    angles = [t[0] for t in polar]
    out = []
    for i in range(RAYS):
        a = 2 * math.pi * i / RAYS
        j = 0
        while j < len(angles) and angles[j] <= a:
            j += 1
        lo = polar[j - 1] if j else (polar[-1][0] - 2 * math.pi, polar[-1][1])
        hi = polar[j] if j < len(polar) else (polar[0][0] + 2 * math.pi, polar[0][1])
        gap = hi[0] - lo[0]
        out.append(lo[1] if gap <= 0 else lo[1] + (hi[1] - lo[1]) * (a - lo[0]) / gap)
    return out


def biggest_cluster(band):
    groups = cluster_slice(band)
    return max(groups, key=len) if groups else []


def main() -> int:
    glb, node = Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 0
    positions, count = read_node_positions(glb, node)
    xs, ys, zs = positions[0::3], positions[1::3], positions[2::3]
    low, high = min(ys), max(ys)
    span = high - low
    print(f"node {node}: {count} vertices, height span {span:.4f}")

    def band_at(y, half):
        return [(round(xs[i], 4), round(zs[i], 4))
                for i in range(count) if abs(ys[i] - y) <= half]

    SPOKES = (16, 32, 64, 96, 128)
    print("\nSPOKE CONVERGENCE   mean |radius error| vs a 320-spoke outline, as % of mean radius")
    print(f"{'band y':>9}{'pts':>8}  " + "".join(f"{s:>8}" for s in SPOKES))
    for frac in (0.12, 0.32, 0.52, 0.72, 0.92):
        y = low + span * frac
        group = biggest_cluster(band_at(y, span / 80))
        if len(group) < 400:
            continue
        ref = outline_on_rays(group, 320)
        if ref is None:
            continue
        mean_r = statistics.fmean(ref)
        row = ""
        for spokes in SPOKES:
            test = outline_on_rays(group, spokes)
            err = statistics.fmean(abs(a - b) for a, b in zip(test, ref)) / mean_r * 100
            row += f"{err:7.2f}%"
        print(f"{y:9.3f}{len(group):8d}  {row}")

    print("\nSLICE CONVERGENCE   coarse band vs a 320-slice-thin band at the same height, 96 spokes")
    print(f"{'slices':>8}{'bands':>8}{'error':>9}")
    fine_half = span / 640
    for slices in (20, 40, 80, 160):
        half = span / (2 * slices)
        errs = []
        for i in range(2, slices - 2, max(1, slices // 12)):
            yc = low + span * (i + 0.5) / slices
            coarse = biggest_cluster(band_at(yc, half))
            fine = biggest_cluster(band_at(yc, fine_half))
            if len(coarse) < 400 or len(fine) < 400:
                continue
            a, b = outline_on_rays(coarse, 96), outline_on_rays(fine, 96)
            if a is None or b is None:
                continue
            errs.append(statistics.fmean(abs(x - y) for x, y in zip(a, b))
                        / statistics.fmean(b) * 100)
        if errs:
            print(f"{slices:8d}{len(errs):8d}{statistics.fmean(errs):8.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
