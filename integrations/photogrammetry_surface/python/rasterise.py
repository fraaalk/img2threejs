"""Z-buffer triangle rasteriser, for manufacturing test views with ground-truth depth and normals.

Only used to build validation fixtures (see render_views.py). It is a real perspective rasteriser --
perspective-correct interpolation, per-pixel depth test -- because a fixture that cheats produces an
MVS accuracy number that means nothing.

Speed note: most triangles of a 130k-triangle head cover well under one pixel at 512², so the
per-triangle bounding boxes are tiny and a Python loop over them is dominated by numpy call overhead.
Triangles are therefore split into a vectorised path for the subpixel majority (one pixel each,
resolved by depth with `np.minimum.at`) and a looped path for the few that are genuinely large. That
split is what turns minutes per view into seconds; it changes no output, and `--no-fast-path` exists
to prove that on demand.
"""
from __future__ import annotations

import numpy as np


def _bilinear(texture: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Sample an (h, w, 3) uint8 texture at uv in [0,1], v measured DOWN from the top (glTF)."""
    h, w = texture.shape[:2]
    x = np.clip(u * w - 0.5, 0, w - 1)
    y = np.clip(v * h - 0.5, 0, h - 1)
    x0 = np.floor(x).astype(np.int64); x1 = np.minimum(x0 + 1, w - 1)
    y0 = np.floor(y).astype(np.int64); y1 = np.minimum(y0 + 1, h - 1)
    fx = (x - x0)[:, None]; fy = (y - y0)[:, None]
    tex = texture.astype(np.float64)
    top = tex[y0, x0] * (1 - fx) + tex[y0, x1] * fx
    bot = tex[y1, x0] * (1 - fx) + tex[y1, x1] * fx
    return top * (1 - fy) + bot * fy


def render(camera, mesh: dict, texture: np.ndarray | None = None,
           fast_path: bool = True) -> dict:
    """Rasterise `mesh` from `camera`.

    Returns `colour` (h,w,3 uint8), `depth` (h,w float64, camera-space z, inf where empty),
    `normal` (h,w,3 world-space, 0 where empty) and `mask` (h,w bool).
    """
    W, H = camera.width, camera.height
    P, N, UV, T = mesh["P"], mesh["N"], mesh["UV"], mesh["T"]

    uv_px, z = camera.project(P)
    # Reject triangles with any vertex behind or very near the camera plane: a near-zero z makes the
    # projected coordinate explode and would smear one triangle across the whole frame.
    tri_z = z[T]
    keep = (tri_z > 1e-6).all(axis=1)
    tris = T[keep]

    x = uv_px[:, 0]
    y = uv_px[:, 1]
    tx, ty, tz = x[tris], y[tris], tri_z[keep]

    # Cull anything wholly outside the frame.
    on = ((tx.min(axis=1) < W) & (tx.max(axis=1) >= 0)
          & (ty.min(axis=1) < H) & (ty.max(axis=1) >= 0))
    tris, tx, ty, tz = tris[on], tx[on], ty[on], tz[on]

    depth = np.full((H, W), np.inf)
    tri_id = np.full((H, W), -1, dtype=np.int64)
    bary = np.zeros((H, W, 3))

    x0 = np.floor(tx.min(axis=1)).astype(np.int64)
    x1 = np.floor(tx.max(axis=1)).astype(np.int64)
    y0 = np.floor(ty.min(axis=1)).astype(np.int64)
    y1 = np.floor(ty.max(axis=1)).astype(np.int64)
    subpixel = (x0 == x1) & (y0 == y1) if fast_path else np.zeros(len(tris), dtype=bool)

    # -- vectorised path: one pixel per triangle, depth-resolved together -------------------------
    if subpixel.any():
        idx = np.nonzero(subpixel)[0]
        px = np.clip(x0[idx], 0, W - 1)
        py = np.clip(y0[idx], 0, H - 1)
        inside = (x0[idx] >= 0) & (x0[idx] < W) & (y0[idx] >= 0) & (y0[idx] < H)
        idx, px, py = idx[inside], px[inside], py[inside]
        # A subpixel triangle's depth is taken at its centroid; the pixel centre is inside it to
        # within a pixel, and interpolating across a footprint smaller than a sample adds noise
        # rather than accuracy.
        zc = tz[idx].mean(axis=1)
        flat = py * W + px
        order = np.lexsort((-zc, flat))          # nearest last within each pixel
        flat_s, idx_s, zc_s = flat[order], idx[order], zc[order]
        last = np.ones(len(flat_s), dtype=bool)
        last[:-1] = flat_s[:-1] != flat_s[1:]
        win_flat, win_idx, win_z = flat_s[last], idx_s[last], zc_s[last]
        wy, wx = win_flat // W, win_flat % W
        depth[wy, wx] = win_z
        tri_id[wy, wx] = win_idx
        bary[wy, wx] = 1.0 / 3.0

    # -- looped path: the genuinely large triangles ------------------------------------------------
    for i in np.nonzero(~subpixel)[0]:
        ax, ay, az = tx[i, 0], ty[i, 0], tz[i, 0]
        bx, by, bz = tx[i, 1], ty[i, 1], tz[i, 1]
        cx, cy, cz = tx[i, 2], ty[i, 2], tz[i, 2]
        area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if abs(area) < 1e-12:
            continue
        lo_x = max(int(np.floor(min(ax, bx, cx))), 0)
        hi_x = min(int(np.floor(max(ax, bx, cx))), W - 1)
        lo_y = max(int(np.floor(min(ay, by, cy))), 0)
        hi_y = min(int(np.floor(max(ay, by, cy))), H - 1)
        if lo_x > hi_x or lo_y > hi_y:
            continue
        gx, gy = np.meshgrid(np.arange(lo_x, hi_x + 1) + 0.5,
                             np.arange(lo_y, hi_y + 1) + 0.5, indexing="xy")
        w0 = ((bx - gx) * (cy - gy) - (by - gy) * (cx - gx)) / area
        w1 = ((cx - gx) * (ay - gy) - (cy - gy) * (ax - gx)) / area
        w2 = 1.0 - w0 - w1
        hit = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        if not hit.any():
            continue
        # Perspective-correct depth: interpolate 1/z linearly in screen space, then invert.
        inv = w0 / az + w1 / bz + w2 / cz
        with np.errstate(divide="ignore", invalid="ignore"):
            zz = np.where(np.abs(inv) > 1e-12, 1.0 / inv, np.inf)
        sub_depth = depth[lo_y:hi_y + 1, lo_x:hi_x + 1]
        closer = hit & (zz < sub_depth)
        if not closer.any():
            continue
        sub_depth[closer] = zz[closer]
        tri_id[lo_y:hi_y + 1, lo_x:hi_x + 1][closer] = i
        # Perspective-correct barycentrics for attribute interpolation.
        pw = np.stack([w0 / az, w1 / bz, w2 / cz], axis=-1) * zz[..., None]
        bary[lo_y:hi_y + 1, lo_x:hi_x + 1][closer] = pw[closer]

    mask = tri_id >= 0
    colour = np.zeros((H, W, 3), dtype=np.uint8)
    normal = np.zeros((H, W, 3))
    if mask.any():
        sel = tri_id[mask]
        wts = bary[mask]
        verts = tris[sel]
        nrm = (N[verts] * wts[:, :, None]).sum(axis=1)
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
        normal[mask] = nrm
        if texture is not None:
            uvs = (UV[verts] * wts[:, :, None]).sum(axis=1)
            rgb = _bilinear(texture, uvs[:, 0], uvs[:, 1])
        else:
            rgb = np.full((len(sel), 3), 200.0)
        # Lambert shading against a fixed headlight, so a textureless region still carries the
        # shading gradient MVS actually matches on.
        lit = np.clip(np.abs(nrm @ camera.forward), 0.0, 1.0)[:, None]
        colour[mask] = np.clip(rgb * (0.35 + 0.65 * lit), 0, 255).astype(np.uint8)

    return {"colour": colour, "depth": depth, "normal": normal, "mask": mask}
