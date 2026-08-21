"""Dense multi-view stereo on the CPU: plane-sweep ZNCC, then cross-view geometric consistency.

WHY THIS EXISTS RATHER THAN COLMAP'S OWN DENSE STAGE. COLMAP's `patch_match_stereo` refuses to run
without CUDA -- verified on this machine, it raises
`Dense stereo reconstruction requires CUDA, which is not available on your system` and reports
`has_cuda: False`. Sparse SfM runs fine on the CPU, so poses come from COLMAP (see sfm_poses.py) and
the dense stage is this module. It is real photometric stereo -- depth is triangulated from agreement
between actual pixels across calibrated views -- not a monocular depth network guessing a plausible
shape from one image.

METHOD, and why each choice is the way it is:

  INVERSE-DEPTH SWEEP, not uniform depth. Disparity is linear in 1/z, so uniform depth planes
  oversample the far field and undersample the near, spending the budget where precision is already
  free and starving it where it is not.

  ZNCC over a window, not SSD. ZNCC is invariant to per-view gain and offset, so a view that is a
  stop brighter still matches. SSD would rank it as a mismatch and quietly delete that surface.

  TOP-K NEIGHBOUR AGGREGATION, not the mean. A surface point is typically occluded in some views. The
  mean lets one occluded view veto a correct depth; taking the best K makes occlusion cost nothing as
  long as K views still see the point. K is deliberately small (2 by default) for that reason.

  GEOMETRIC CONSISTENCY as a separate, later filter. Photometric agreement alone accepts a wrong
  depth wherever texture repeats -- hair, cloth, any periodic weave. A depth survives only if other
  views, reconstructed independently, put the same surface in the same place: project the point into
  view n, read n's OWN depth there, back-project, and require the round trip to return within a
  tolerance. This is what turns a noisy cost-volume argmin into something a surface can be built on,
  and it is the single biggest quality lever in the module.

Pure numpy. Box filters are cumulative-sum integral images rather than scipy convolutions, which
keeps the dependency list at numpy + pillow and costs nothing in accuracy.
"""
from __future__ import annotations

import numpy as np


# -- small helpers ---------------------------------------------------------------------------------
def box_sum(a: np.ndarray, radius: int) -> np.ndarray:
    """Sum over a (2r+1)² window, edge-clamped, via an integral image."""
    if radius <= 0:
        return a.astype(np.float64, copy=True)
    pad = np.pad(a.astype(np.float64), radius + 1, mode="edge")
    integral = pad.cumsum(axis=0).cumsum(axis=1)
    h, w = a.shape
    size = 2 * radius + 1
    y0 = np.arange(h)
    x0 = np.arange(w)
    yy0, xx0 = np.meshgrid(y0, x0, indexing="ij")
    a1 = integral[yy0 + size, xx0 + size]
    a2 = integral[yy0, xx0 + size]
    a3 = integral[yy0 + size, xx0]
    a4 = integral[yy0, xx0]
    return a1 - a2 - a3 + a4


def sample_bilinear(image: np.ndarray, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sample a 2D image at float pixel coords. Returns (values, valid) with valid=False off-frame."""
    h, w = image.shape[:2]
    valid = (u >= 0.5) & (u <= w - 0.5) & (v >= 0.5) & (v <= h - 0.5)
    x = np.clip(u - 0.5, 0, w - 1)
    y = np.clip(v - 0.5, 0, h - 1)
    x0 = np.floor(x).astype(np.int32); x1 = np.minimum(x0 + 1, w - 1)
    y0 = np.floor(y).astype(np.int32); y1 = np.minimum(y0 + 1, h - 1)
    fx = x - x0
    fy = y - y0
    top = image[y0, x0] * (1 - fx) + image[y0, x1] * fx
    bot = image[y1, x0] * (1 - fx) + image[y1, x1] * fx
    return top * (1 - fy) + bot * fy, valid


def pick_neighbours(cams: list, ref: int, count: int,
                    min_angle_deg: float = 4.0, max_angle_deg: float = 40.0) -> list[int]:
    """Views whose baseline to `ref` is wide enough to triangulate and narrow enough to still match.

    Both bounds matter. Below `min_angle` the triangulation is ill-conditioned -- a pixel of matching
    error becomes centimetres of depth error. Above `max_angle` the surface is foreshortened
    differently in the two views and the window stops describing the same patch, so ZNCC falls apart
    on exactly the oblique surfaces that need it most.
    """
    fwd_ref = cams[ref].forward
    scored = []
    for i, cam in enumerate(cams):
        if i == ref:
            continue
        # Angle between the two viewing directions is the usable proxy for baseline on an orbit.
        cos = float(np.clip(fwd_ref @ cam.forward, -1.0, 1.0))
        angle = np.degrees(np.arccos(cos))
        if angle < min_angle_deg or angle > max_angle_deg:
            continue
        scored.append((abs(angle - 15.0), i))       # prefer ~15 degrees
    scored.sort()
    return [i for _, i in scored[:count]]


# -- the sweep -------------------------------------------------------------------------------------
def sweep_depth(cams: list, greys: list[np.ndarray], masks: list[np.ndarray], ref: int,
                depth_min: float, depth_max: float, planes: int = 96, window: int = 4,
                neighbours: int = 4, top_k: int = 2,
                min_neighbour_angle: float = 4.0, max_neighbour_angle: float = 40.0) -> dict:
    """Plane-sweep ZNCC for one reference view. Returns depth, confidence and the neighbours used."""
    cam = cams[ref]
    H, W = cam.height, cam.width
    nb = pick_neighbours(cams, ref, neighbours, min_neighbour_angle, max_neighbour_angle)
    if len(nb) < max(2, top_k):
        return {"depth": np.zeros((H, W)), "confidence": np.zeros((H, W)), "neighbours": nb,
                "reason": (f"only {len(nb)} neighbour(s) within "
                           f"{min_neighbour_angle:.0f}-{max_neighbour_angle:.0f} deg of this view; "
                           f"add views so consecutive angles are under {max_neighbour_angle:.0f} deg "
                           f"apart, or widen --max-neighbour-angle (wider baselines foreshorten the "
                           f"patch and ZNCC degrades)")}

    ref_grey = greys[ref].astype(np.float64)
    n_win = (2 * window + 1) ** 2
    ref_sum = box_sum(ref_grey, window)
    ref_sq = box_sum(ref_grey * ref_grey, window)
    ref_mean = ref_sum / n_win
    ref_var = np.maximum(ref_sq / n_win - ref_mean * ref_mean, 0.0)
    ref_std = np.sqrt(ref_var)

    # Inverse-depth planes: uniform in 1/z, which is uniform in disparity.
    inv = np.linspace(1.0 / depth_max, 1.0 / depth_min, planes)
    depths = 1.0 / inv

    best = np.full((H, W), -np.inf)
    second = np.full((H, W), -np.inf)
    best_idx = np.zeros((H, W), dtype=np.int32)
    scores = np.empty((planes, H, W), dtype=np.float32)

    inv_K = np.linalg.inv(cam.K)
    us, vs = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5, indexing="xy")
    dirs_cam = np.stack([us, vs, np.ones_like(us)], axis=-1) @ inv_K.T   # z == 1

    for pi, d in enumerate(depths):
        world = (dirs_cam * d - cam.t) @ cam.R
        per_nb = []
        for j in nb:
            other = cams[j]
            cam_pts = world @ other.R.T + other.t
            z = cam_pts[..., 2]
            front = z > 1e-6
            safe = np.where(front, z, 1.0)
            uv = (cam_pts / safe[..., None]) @ other.K.T
            vals, inside = sample_bilinear(greys[j].astype(np.float64), uv[..., 0], uv[..., 1])
            ok = front & inside
            vals = np.where(ok, vals, 0.0)

            # ZNCC over the window, computed from box sums so it is one pass regardless of window size.
            o_sum = box_sum(vals, window)
            o_sq = box_sum(vals * vals, window)
            cross = box_sum(ref_grey * vals, window)
            o_mean = o_sum / n_win
            o_var = np.maximum(o_sq / n_win - o_mean * o_mean, 0.0)
            denom = ref_std * np.sqrt(o_var)
            cov = cross / n_win - ref_mean * o_mean
            zncc = np.where(denom > 1e-8, cov / np.maximum(denom, 1e-12), -1.0)
            # A window that is mostly off-frame or behind the camera cannot vote.
            support = box_sum(ok.astype(np.float64), window) / n_win
            zncc = np.where(support > 0.6, zncc, -1.0)
            per_nb.append(zncc)

        stack = np.stack(per_nb, axis=0)
        k = min(top_k, stack.shape[0])
        # Top-k mean: occlusion in some views must not veto a depth the others agree on.
        part = np.partition(stack, stack.shape[0] - k, axis=0)[stack.shape[0] - k:]
        score = part.mean(axis=0)
        scores[pi] = score.astype(np.float32)

        improved = score > best
        second = np.where(improved, best, np.maximum(second, score))
        best_idx = np.where(improved, pi, best_idx)
        best = np.where(improved, score, best)

    # Sub-plane refinement: fit a parabola through the winner and its two neighbours in inverse depth,
    # so the result is not quantised to the plane spacing.
    inv_best = inv[best_idx]
    step = inv[1] - inv[0]
    lo_idx = np.clip(best_idx - 1, 0, planes - 1)
    hi_idx = np.clip(best_idx + 1, 0, planes - 1)
    yy, xx = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")
    c0 = scores[lo_idx, yy, xx].astype(np.float64)
    c1 = scores[best_idx, yy, xx].astype(np.float64)
    c2 = scores[hi_idx, yy, xx].astype(np.float64)
    denom = (c0 - 2 * c1 + c2)
    # Guard the divisor before dividing, not after: `np.where` still evaluates both branches, so a
    # near-zero denominator raises and poisons the array with nan even though the result is discarded.
    safe_denom = np.where(np.abs(denom) > 1e-9, denom, 1.0)
    shift = np.where(np.abs(denom) > 1e-9, 0.5 * (c0 - c2) / safe_denom, 0.0)
    shift = np.clip(shift, -0.5, 0.5)
    interior = (best_idx > 0) & (best_idx < planes - 1)
    inv_ref = inv_best + np.where(interior, shift * step, 0.0)
    depth = 1.0 / np.maximum(inv_ref, 1e-9)

    # Confidence: how much better the winner is than the best rival elsewhere in the volume. A flat
    # cost profile (untextured wall, repeating weave) scores near zero here even when ZNCC is high.
    margin = np.clip(best - second, 0.0, 2.0)
    confidence = np.clip(best, 0.0, 1.0) * np.clip(margin / 0.1, 0.0, 1.0)
    confidence = np.where(masks[ref], confidence, 0.0)
    depth = np.where(masks[ref], depth, 0.0)
    return {"depth": depth, "confidence": confidence, "neighbours": nb, "reason": ""}


def geometric_consistency(cams: list, depths: list[np.ndarray], confidences: list[np.ndarray],
                          ref: int, tolerance_ratio: float = 0.01,
                          min_agreeing: int = 2) -> np.ndarray:
    """Keep only depths that other views, reconstructed independently, agree with.

    For each pixel: back-project with this view's depth, project into view n, read n's own depth at
    that pixel, back-project THAT, and measure how far the two world points are apart. Agreement is
    scaled by the point's distance from the camera (`tolerance_ratio`), because a fixed metric
    tolerance is too tight up close and meaningless far away.
    """
    cam = cams[ref]
    depth = depths[ref]
    H, W = depth.shape
    valid = (depth > 0) & (confidences[ref] > 0)
    world = cam.backproject(depth)
    agree = np.zeros((H, W), dtype=np.int32)

    for j, other in enumerate(cams):
        if j == ref or depths[j] is None:
            continue
        uv, z = other.project(world.reshape(-1, 3))
        uv = uv.reshape(H, W, 2)
        z = z.reshape(H, W)
        other_depth, inside = sample_bilinear(depths[j], uv[..., 0], uv[..., 1])
        other_conf, _ = sample_bilinear(confidences[j], uv[..., 0], uv[..., 1])
        usable = inside & (z > 1e-6) & (other_depth > 0) & (other_conf > 0)
        if not usable.any():
            continue
        # Where does view j think that surface is?
        u = np.clip(uv[..., 0], 0.5, other.width - 0.5)
        v = np.clip(uv[..., 1], 0.5, other.height - 0.5)
        homo = np.stack([u, v, np.ones_like(u)], axis=-1)
        dirs = homo @ np.linalg.inv(other.K).T
        other_world = (dirs * other_depth[..., None] - other.t) @ other.R
        distance = np.linalg.norm(other_world - world, axis=-1)
        agree += (usable & (distance < tolerance_ratio * np.abs(depth))).astype(np.int32)

    return valid & (agree >= min_agreeing)
