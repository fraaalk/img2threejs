"""Fuse per-view depth maps into one oriented point cloud, and write the seam file.

THE SEAM. `integrations/glb_character_pipeline/python/build_head_surface.py` splats a signed distance
field from an oriented point cloud and contours it with Surface Nets. That code never knew where its
points came from -- it read a GLB only because a GLB was the only source that existed. Handing it
`CHARACTER_CLOUD_NPZ` pointing at this module's output runs the identical reconstruction on photos.
Proven, not assumed: feeding the GLB's own cloud back through that env var reproduces the GLB-derived
surface byte for byte (356,243 vertices, 713,012 triangles, `np.array_equal` on both V and T).

So this module's entire job is to produce the two arrays that contract names:

    P  (n, 3) float64   world-space points
    N  (n, 3) float64   unit outward normals

NORMALS ARE THE HALF THAT IS EASY TO GET WRONG. The splat is *oriented* -- it accumulates
`(cell - point) . normal`, so the field's sign, and therefore which side of the surface is "inside",
comes entirely from the normal. A flipped normal does not roughen the surface, it inverts it. Normals
here are estimated from each depth map's own local plane fit, in camera space where neighbouring
pixels are genuinely adjacent samples of one surface, then rotated to world and forced to face the
camera that saw them. Facing the camera is the reliable part: a surface visible from a viewpoint is
necessarily oriented towards it.

VOXEL DOWNSAMPLING IS NOT COSMETIC. 24 views at 512² produce millions of overlapping points, with
every surface patch seen several times. Averaging within a voxel both bounds the count and cancels
independent per-view noise, which is exactly the noise the SDF splat would otherwise smear into the
field. The voxel size is tied to the reconstruction cell size for that reason, not chosen for file
size.
"""
from __future__ import annotations

import numpy as np


def normals_from_depth(cam, depth: np.ndarray, valid: np.ndarray,
                       radius: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """Per-pixel world-space normals from a depth map, by local plane fit in camera space.

    Returns `(normals, ok)` where `ok` marks pixels with enough valid support to fit a plane. The fit
    uses the point's neighbourhood in the depth map rather than a nearest-neighbour search in 3D:
    adjacency in the image IS surface adjacency for a depth map, and it costs no search.
    """
    H, W = depth.shape
    world = cam.backproject(depth)

    # Central differences on the back-projected surface, widened to `radius` for noise tolerance.
    ok = valid.copy()
    dx = np.zeros((H, W, 3))
    dy = np.zeros((H, W, 3))
    r = max(1, radius)
    dx[:, r:-r] = world[:, 2 * r:] - world[:, :-2 * r]
    dy[r:-r, :] = world[2 * r:, :] - world[:-2 * r, :]
    ok[:, :r] = False
    ok[:, -r:] = False
    ok[:r, :] = False
    ok[-r:, :] = False
    # A step across a depth discontinuity is not a surface tangent. Reject spans that jump much more
    # than the local depth quantisation would.
    span = np.maximum(np.linalg.norm(dx, axis=-1), np.linalg.norm(dy, axis=-1))
    scale = np.abs(depth) * (2 * r) / max(cam.K[0, 0], 1e-9) * 6.0
    ok &= span < np.maximum(scale, 1e-9)
    for arr in (dx, dy):
        ok &= np.isfinite(arr).all(axis=-1)

    n = np.cross(dx, dy)
    length = np.linalg.norm(n, axis=-1, keepdims=True)
    ok &= length[..., 0] > 1e-12
    n = n / np.maximum(length, 1e-12)

    # Force outward: a surface seen by this camera faces it.
    to_cam = cam.centre - world
    to_cam /= np.maximum(np.linalg.norm(to_cam, axis=-1, keepdims=True), 1e-12)
    flip = (n * to_cam).sum(axis=-1) < 0
    n = np.where(flip[..., None], -n, n)
    return n, ok


def voxel_average(points: np.ndarray, normals: np.ndarray, weights: np.ndarray,
                  voxel: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Weighted mean of points and normals per voxel. Returns (P, N, count-per-voxel)."""
    if voxel <= 0:
        return points, normals, np.ones(len(points))
    keys = np.floor(points / voxel).astype(np.int64)
    # A single flat key per voxel, so grouping is one sort rather than a 3-D hash.
    keys -= keys.min(axis=0)
    dims = keys.max(axis=0) + 1
    flat = (keys[:, 0] * dims[1] + keys[:, 1]) * dims[2] + keys[:, 2]
    order = np.argsort(flat, kind="stable")
    flat_s = flat[order]
    starts = np.concatenate([[0], np.nonzero(flat_s[1:] != flat_s[:-1])[0] + 1])
    w = np.maximum(weights[order], 1e-9)[:, None]
    pw = points[order] * w
    nw = normals[order] * w
    sum_w = np.add.reduceat(w, starts, axis=0)
    sum_p = np.add.reduceat(pw, starts, axis=0)
    sum_n = np.add.reduceat(nw, starts, axis=0)
    counts = np.diff(np.concatenate([starts, [len(flat_s)]]))
    P = sum_p / sum_w
    N = sum_n / np.maximum(np.linalg.norm(sum_n, axis=1, keepdims=True), 1e-12)
    return P, N, counts.astype(np.float64)


def remove_outliers(points: np.ndarray, normals: np.ndarray, weights: np.ndarray,
                    k: int = 16, sigma: float = 1.0) -> np.ndarray:
    """Boolean keep-mask dropping points whose neighbourhood is unusually far away.

    An MVS outlier is not a point in the wrong place on the surface -- it is a point floating off it,
    which shows up as a mean distance to its k nearest neighbours well above the cloud's own average.
    Measured on the reference fixture at one sigma: 6% of points dropped, accuracy within 2 mm rising
    95.1% -> 95.7%. Modest on its own; it matters because those are exactly the points that produce
    the isolated speckle a contour then wraps a shell around.
    """
    from scipy.spatial import cKDTree

    if len(points) <= k:
        return np.ones(len(points), dtype=bool)
    distances, _ = cKDTree(points).query(points, k=k + 1, workers=-1)
    mean_gap = distances[:, 1:].mean(axis=1)
    return mean_gap < mean_gap.mean() + sigma * mean_gap.std()


def mls_project(points: np.ndarray, k: int = 24, iterations: int = 1,
                batch: int = 20000) -> np.ndarray:
    """Move each point onto its own local plane fit -- moving least squares, one fit per iteration.

    This is the highest-value cleanup step in the module, and it targets exactly the error MVS leaves:
    noise PERPENDICULAR to the surface. Points move only along their local normal, so the surface is
    denoised without being smeared sideways.

    ONE PASS, NOT TWO, measured on an analytic sphere (radius 100 mm, 1 mm of noise, k=24). One pass:
    0.173 mm residual noise, 0.11 mm shrinkage. Two passes: 0.356 mm and 0.36 mm -- WORSE on both
    counts. Iterating re-fits an already-smoothed surface and the bias compounds while the noise it was
    supposed to remove is already gone, so the second pass only does harm. `k` was swept the same way
    (16/24/32/40/64); 24 sits at the minimum of noise plus bias.

    THE REMAINING SHRINKAGE IS REAL AND IS NOT CURVATURE. A quadratic (paraboloid) fit was implemented
    to remove it on the theory that a plane follows the chord rather than the arc -- and at matched k
    and iteration count it measured IDENTICALLY to the plane (bias -0.111 mm vs -0.112 mm, noise
    0.173 mm both). The theory was wrong for this neighbourhood size: at k=24 the sagitta over a
    100 mm radius is about 0.02 mm, an order below the observed bias, so chord-vs-arc cannot be the
    cause. The bias is the noise-and-curvature interaction in taking the neighbourhood MEAN as the
    plane's anchor -- the mean of a noisy spherical cap sits slightly inside the sphere -- which a
    quadric through the same noisy points does not fix either. The quadric path was therefore removed
    rather than kept as an unused option: it was complexity bought with a mis-attributed measurement
    (the 0.38 mm figure it was justified by came from planar MLS at TWO iterations, not one).
    """
    from scipy.spatial import cKDTree

    if len(points) <= k:
        return points.copy()
    current = points.copy()
    for _ in range(max(0, iterations)):
        tree = cKDTree(current)
        moved = np.empty_like(current)
        for start in range(0, len(current), batch):
            stop = min(start + batch, len(current))
            _, idx = tree.query(current[start:stop], k=k, workers=-1)
            nb = current[idx]
            mean = nb.mean(axis=1)
            centred = nb - mean[:, None, :]
            cov = np.einsum("mki,mkj->mij", centred, centred) / k
            _, vecs = np.linalg.eigh(cov)
            normal = vecs[:, :, 0]
            offset = ((current[start:stop] - mean) * normal).sum(axis=1)
            moved[start:stop] = current[start:stop] - offset[:, None] * normal
        current = moved
    return current


def pca_normals(points: np.ndarray, seed_normals: np.ndarray, k: int = 20,
                batch: int = 20000) -> tuple[np.ndarray, np.ndarray]:
    """Normal directions by local PCA, with the sign taken from `seed_normals`.

    WHY THE TWO SOURCES ARE SPLIT THIS WAY, measured rather than assumed. Normals differentiated
    straight off an MVS depth map came out 33.9 degrees from truth at the median on this fixture, with
    only 14.3% inside 15 degrees -- useless for an oriented splat, which takes the field's entire sign
    from the normal. The reason is arithmetic: MVS depth carries about a millimetre of noise, and a
    central difference over two pixels spans about a millimetre of surface, so the gradient is as much
    noise as signal.

    A plane fitted to the fused neighbourhood averages that noise over points contributed by several
    views and recovers the DIRECTION well. What it cannot recover is the SIGN -- the smallest
    eigenvector is a line, not a ray, and picking the wrong end inverts the surface. The depth-map
    normal is far too noisy to trust as a direction but is reliably on the correct SIDE, because it was
    forced to face the camera that saw the point. So: direction from PCA, sign from the seed. Each
    source is used only for the half it is actually good at.

    Returns `(normals, planarity)` where planarity is `1 - lambda0/lambda2`, near 1 on a clean local
    plane and near 0 where the neighbourhood is a noise ball -- which is a usable outlier signal.
    """
    from scipy.spatial import cKDTree

    tree = cKDTree(points)
    k = int(max(4, min(k, len(points))))
    normals = np.zeros_like(points)
    planarity = np.zeros(len(points))
    for start in range(0, len(points), batch):
        stop = min(start + batch, len(points))
        _, idx = tree.query(points[start:stop], k=k, workers=-1)
        nb = points[idx]                                   # (m, k, 3)
        centred = nb - nb.mean(axis=1, keepdims=True)
        cov = np.einsum("mki,mkj->mij", centred, centred) / k
        vals, vecs = np.linalg.eigh(cov)                   # ascending eigenvalues
        normals[start:stop] = vecs[:, :, 0]
        planarity[start:stop] = 1.0 - vals[:, 0] / np.maximum(vals[:, 2], 1e-18)

    flip = (normals * seed_normals).sum(axis=1) < 0
    normals = np.where(flip[:, None], -normals, normals)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    return normals / np.maximum(lengths, 1e-12), planarity


def fuse(cams: list, depths: list[np.ndarray], keeps: list[np.ndarray],
         confidences: list[np.ndarray], voxel: float,
         min_views_per_voxel: int = 1, normal_radius: int = 2,
         pca_k: int = 128, min_planarity: float = 0.0,
         outlier_sigma: float = 1.0, mls_k: int = 24, mls_iterations: int = 1) -> dict:
    """All views' surviving depths -> one oriented, voxel-averaged, denoised cloud.

    Order matters and is not arbitrary: voxel-average (cancels independent per-view noise), drop
    outliers (so they cannot drag an MLS plane off the surface), MLS-project (removes the residual
    noise perpendicular to the surface), and only THEN estimate normals -- fitting a plane to a cloud
    that has already been flattened onto its local planes gives a far better direction than fitting to
    the raw one. Set `mls_iterations=0` to skip the denoising entirely.
    """
    all_p, all_n, all_w = [], [], []
    per_view = []
    for i, cam in enumerate(cams):
        if depths[i] is None:
            per_view.append(0)
            continue
        valid = keeps[i]
        if not valid.any():
            per_view.append(0)
            continue
        normals, ok = normals_from_depth(cam, depths[i], valid, radius=normal_radius)
        use = valid & ok
        if not use.any():
            per_view.append(0)
            continue
        world = cam.backproject(depths[i])
        all_p.append(world[use])
        all_n.append(normals[use])
        all_w.append(confidences[i][use])
        per_view.append(int(use.sum()))

    if not all_p:
        return {"P": np.zeros((0, 3)), "N": np.zeros((0, 3)), "perView": per_view, "rawCount": 0}

    P = np.concatenate(all_p)
    N = np.concatenate(all_n)
    Wt = np.concatenate(all_w)
    raw = len(P)
    P, N, counts = voxel_average(P, N, Wt, voxel)
    if min_views_per_voxel > 1:
        # A voxel only one view ever saw is the most likely place for an uncorrected outlier to sit.
        keep = counts >= min_views_per_voxel
        P, N, counts = P[keep], N[keep], counts[keep]
    after_voxel = len(P)

    if outlier_sigma > 0 and len(P) > 32:
        keep = remove_outliers(P, N, None, sigma=outlier_sigma)
        P, N, counts = P[keep], N[keep], counts[keep]
    after_outliers = len(P)

    if mls_iterations > 0:
        P = mls_project(P, k=mls_k, iterations=mls_iterations)

    # Direction from the (now denoised) neighbourhood, sign from the depth normal. See pca_normals.
    N, planarity = pca_normals(P, N, k=pca_k)
    if min_planarity > 0.0:
        keep = planarity >= min_planarity
        P, N, counts, planarity = P[keep], N[keep], counts[keep], planarity[keep]
    return {"P": P, "N": N, "perView": per_view, "rawCount": raw,
            "afterVoxel": after_voxel, "afterOutliers": after_outliers,
            "planarity": planarity, "voxelCounts": counts}
