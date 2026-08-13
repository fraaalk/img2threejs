"""Python port of the runtime's SDF sampler and polygonizer, plus the glove's atlas UV projection.

Why this exists. An implicit surface has no mesh until something polygonizes it, and the only
polygonizer that ships is TypeScript (`_SDF_HELPER_SOURCE.polygonizeSdf` in
`forge/stage3_build/generate_threejs_factory.py`), which runs in the browser. Stage 4 measures
topology -- boundary edges, non-manifold edges, normal consistency, self-intersection -- from a mesh,
so without a Python mesh an SDF glove could only be reviewed by shipping it first. That is the wrong
order.

Why the port can be exact rather than approximate. The extractor is naive surface nets over an
axis-aligned grid: every vertex is the mean of the zero crossings on one cell's edges, and each crossing
is a single linear interpolation between two sampled corners. There is no iteration and no tolerance, so
both languages compute the same doubles in the same order and the two meshes agree vertex for vertex.
`forge/tests/test_glove_armature_parity.py` is what keeps that true.

The UV projection is deliberately here and not in the descriptor's geometry. The extractor emits
position and index only, so a textured SDF needs UVs assigned after the fact. For a glove the atlas
holds a dorsal plate in `u < 0.5` and a palmar plate in `u > 0.5`, so a triangle belongs to the half
that the plate facing it saw, judged by its smoothed normal's z sign. The equator band, whose normal has
no z, was seen by neither plate and is assigned to the dorsal half as a whole -- a triangle with uvs in
both halves would interpolate its texture straight through the middle of the atlas.
"""

from __future__ import annotations

import math
from typing import Any, Callable

MIN_RESOLUTION = 4
MAX_RESOLUTION = 64
DEFAULT_BOUNDS = {"min": [-2.0, -2.0, -2.0], "max": [2.0, 2.0, 2.0]}

Vector = tuple[float, float, float]
SdfFunction = Callable[[Vector], float]


def _length(point: Vector) -> float:
    return math.sqrt(point[0] * point[0] + point[1] * point[1] + point[2] * point[2])


def _sdf_sphere(point: Vector, radius: float) -> float:
    return _length(point) - radius


def _sdf_capsule(point: Vector, radius: float, height: float) -> float:
    half_height = height * 0.5
    y = max(-half_height, min(half_height, point[1]))
    return _length((point[0], point[1] - y, point[2])) - radius


def _sdf_box(point: Vector, size: list[float]) -> float:
    q = (abs(point[0]) - size[0] * 0.5, abs(point[1]) - size[1] * 0.5, abs(point[2]) - size[2] * 0.5)
    outside = _length((max(q[0], 0.0), max(q[1], 0.0), max(q[2], 0.0)))
    return outside + min(max(q[0], q[1], q[2]), 0.0)


def _sdf_cone(point: Vector, radius: float, height: float) -> float:
    half_height = height * 0.5
    taper = radius * (1.0 - (point[1] + half_height) / height)
    return max(math.hypot(point[0], point[2]) - max(0.0, taper), abs(point[1]) - half_height)


def _sdf_ellipsoid(point: Vector, radii: list[float]) -> float:
    scaled = (point[0] / radii[0], point[1] / radii[1], point[2] / radii[2])
    return (_length(scaled) - 1.0) * min(radii[0], radii[1], radii[2])


def _radii(primitive: dict[str, Any]) -> list[float]:
    if primitive.get("radii") is not None:
        return list(primitive["radii"])
    radius = primitive.get("radius")
    if isinstance(radius, (int, float)) and not isinstance(radius, bool):
        return [float(radius)] * 3
    return list(radius) if radius is not None else [0.5, 0.5, 0.5]


def _smin(left: float, right: float, radius: float) -> float:
    blend = max(radius - abs(left - right), 0.0) / radius
    return min(left, right) - blend * blend * radius * 0.25


def _quaternion_from_euler_xyz(rotation: list[float]) -> tuple[float, float, float, float]:
    """THREE.Quaternion.setFromEuler with the default 'XYZ' order, reproduced term for term."""
    c1, c2, c3 = (math.cos(rotation[axis] / 2.0) for axis in range(3))
    s1, s2, s3 = (math.sin(rotation[axis] / 2.0) for axis in range(3))
    return (
        s1 * c2 * c3 + c1 * s2 * s3,
        c1 * s2 * c3 - s1 * c2 * s3,
        c1 * c2 * s3 + s1 * s2 * c3,
        c1 * c2 * c3 - s1 * s2 * s3,
    )


def _apply_quaternion(point: Vector, quaternion: tuple[float, float, float, float]) -> Vector:
    qx, qy, qz, qw = quaternion
    vx, vy, vz = point
    ix = qw * vx + qy * vz - qz * vy
    iy = qw * vy + qz * vx - qx * vz
    iz = qw * vz + qx * vy - qy * vx
    iw = -qx * vx - qy * vy - qz * vz
    return (
        ix * qw + iw * -qx + iy * -qz - iz * -qy,
        iy * qw + iw * -qy + iz * -qx - ix * -qz,
        iz * qw + iw * -qz + ix * -qy - iy * -qx,
    )


def _local_point(point: Vector, primitive: dict[str, Any]) -> tuple[Vector, float]:
    transform = primitive.get("transform") or {}
    translation = transform.get("position") or transform.get("translation") or primitive.get("center") or [0.0, 0.0, 0.0]
    rotation = transform.get("rotation") or [0.0, 0.0, 0.0]
    scale = transform.get("scale") or [1.0, 1.0, 1.0]
    local: Vector = (point[0] - translation[0], point[1] - translation[1], point[2] - translation[2])
    inverse = _quaternion_from_euler_xyz(list(rotation))
    local = _apply_quaternion(local, (-inverse[0], -inverse[1], -inverse[2], inverse[3]))
    return (local[0] / scale[0], local[1] / scale[1], local[2] / scale[2]), min(scale[0], scale[1], scale[2])


def _primitive_distance(point: Vector, primitive: dict[str, Any]) -> float:
    local, scale = _local_point(point, primitive)
    radius = primitive.get("radius")
    numeric_radius = float(radius) if isinstance(radius, (int, float)) and not isinstance(radius, bool) else None
    kind = primitive["type"]
    if kind == "sphere":
        distance = _sdf_sphere(local, numeric_radius if numeric_radius is not None else 0.5)
    elif kind == "capsule":
        distance = _sdf_capsule(local, numeric_radius if numeric_radius is not None else 0.25, float(primitive.get("height", 1.0)))
    elif kind == "box":
        distance = _sdf_box(local, list(primitive.get("size") or primitive.get("dimensions") or [1.0, 1.0, 1.0]))
    elif kind == "cone":
        distance = _sdf_cone(local, numeric_radius if numeric_radius is not None else 0.5, float(primitive.get("height", 1.0)))
    elif kind == "ellipsoid":
        distance = _sdf_ellipsoid(local, _radii(primitive))
    else:
        raise ValueError(f"unsupported sdf primitive type {kind!r}")
    return distance * scale


def sample_sdf(descriptor: dict[str, Any]) -> SdfFunction:
    """Compose the descriptor into one distance function, matching `sdfSample`."""
    nodes: dict[str, SdfFunction] = {}
    for primitive in descriptor["primitives"]:
        nodes[primitive["id"]] = lambda point, primitive=primitive: _primitive_distance(point, primitive)
    result = nodes[descriptor["primitives"][0]["id"]] if descriptor["primitives"] else None
    for index, operation in enumerate(descriptor.get("operations") or []):
        left = nodes.get(operation["left"])
        right = nodes.get(operation["right"])
        if left is None or right is None:
            continue
        kind = operation["type"]
        if kind == "union":
            combined: SdfFunction = lambda point, left=left, right=right: min(left(point), right(point))
        elif kind == "smooth-union":
            radius = float(operation.get("radius", 0.1))
            combined = lambda point, left=left, right=right, radius=radius: _smin(left(point), right(point), radius)
        elif kind == "subtract":
            combined = lambda point, left=left, right=right: max(left(point), -right(point))
        elif kind == "intersect":
            combined = lambda point, left=left, right=right: max(left(point), right(point))
        else:
            raise ValueError(f"unsupported sdf operation type {kind!r}")
        nodes[operation.get("id") or operation.get("output") or f"operation-{index}"] = combined
        result = combined
    return result if result is not None else (lambda point: math.inf)


# The twelve edges of a cell, as pairs of corner offsets in (dx, dy, dz).
_CELL_CORNERS = tuple((dx, dy, dz) for dz in (0, 1) for dy in (0, 1) for dx in (0, 1))
_CELL_EDGES = tuple(
    (first, second)
    for first in range(8)
    for second in range(first + 1, 8)
    if sum(1 for axis in range(3) if _CELL_CORNERS[first][axis] != _CELL_CORNERS[second][axis]) == 1
)


def polygonize_sdf(descriptor: dict[str, Any]) -> dict[str, Any]:
    """Extract the zero level set with naive surface nets: one interpolated vertex per crossing cell.

    Why this and not the binary-occupancy extractor it replaces. That one placed every vertex on an
    integer grid corner and emitted axis-aligned quads on the boundary between inside and outside cells.
    Three consequences, all of them visible: the surface was faceted at cell scale no matter how fine
    the grid, because sub-cell position information was thrown away; a crease where two solids touch
    without a gap between them could not be represented AT ALL, since every cell either side of it is
    solid, which is why two fingers pressed together came out as one mitten and had to be held apart by
    an artificial gap; and every face being axis-aligned made half the surface degenerate under a planar
    uv projection -- 35% of triangles had exactly zero uv area, so a whole face sampled one line of
    texels.

    Surface nets fixes all three by interpolating. Each cell whose eight corners are not all on the same
    side of the surface contributes ONE vertex, placed at the mean of the zero crossings along its
    edges, and each grid edge that changes sign contributes ONE quad joining the four cells around it.
    That makes the result closed and manifold by construction: every interior edge of the mesh is used
    by exactly two quads, so the diagonal-contact pinch the previous extractor needed a repair pass for
    cannot arise.

    The field is sampled at cell CORNERS, (resolution + 1) cubed of them, not at cell centres.
    """
    resolution = max(MIN_RESOLUTION, min(MAX_RESOLUTION, int(math.floor(descriptor["resolution"]))))
    bounds = descriptor.get("bounds") or DEFAULT_BOUNDS
    minimum = [float(value) for value in bounds["min"]]
    step = [(float(bounds["max"][axis]) - minimum[axis]) / resolution for axis in range(3)]
    sample = sample_sdf(descriptor)

    side = resolution + 1
    field = [0.0] * (side ** 3)
    for z in range(side):
        for y in range(side):
            row = (z * side + y) * side
            for x in range(side):
                field[row + x] = sample((
                    minimum[0] + x * step[0],
                    minimum[1] + y * step[1],
                    minimum[2] + z * step[2],
                ))

    def corner(x: int, y: int, z: int) -> int:
        return (z * side + y) * side + x

    positions: list[Vector] = []
    cell_vertex: dict[tuple[int, int, int], int] = {}
    for z in range(resolution):
        for y in range(resolution):
            for x in range(resolution):
                values = [field[corner(x + dx, y + dy, z + dz)] for dx, dy, dz in _CELL_CORNERS]
                inside = [value < 0.0 for value in values]
                if all(inside) or not any(inside):
                    continue
                total = [0.0, 0.0, 0.0]
                crossings = 0
                for first, second in _CELL_EDGES:
                    if inside[first] == inside[second]:
                        continue
                    a, b = values[first], values[second]
                    # Where along the edge the field passes through zero. The denominator cannot be zero
                    # because the two ends are strictly on opposite sides.
                    t = a / (a - b)
                    for axis in range(3):
                        low = _CELL_CORNERS[first][axis]
                        high = _CELL_CORNERS[second][axis]
                        total[axis] += low + (high - low) * t
                    crossings += 1
                cell_vertex[(x, y, z)] = len(positions)
                positions.append((
                    minimum[0] + (x + total[0] / crossings) * step[0],
                    minimum[1] + (y + total[1] / crossings) * step[1],
                    minimum[2] + (z + total[2] / crossings) * step[2],
                ))

    triangles: list[tuple[int, int, int]] = []
    # One quad per sign-changing grid edge, from the four cells that share it. The winding follows the
    # direction the field increases in, so every face points out of the solid; `test_glove_armature_form`
    # checks that against the field's own gradient rather than trusting this comment.
    neighbours = (
        (0, (0, -1, -1), (0, 0, -1), (0, 0, 0), (0, -1, 0)),
        (1, (-1, 0, -1), (-1, 0, 0), (0, 0, 0), (0, 0, -1)),
        (2, (-1, -1, 0), (0, -1, 0), (0, 0, 0), (-1, 0, 0)),
    )
    for axis, *offsets in neighbours:
        for z in range(side):
            for y in range(side):
                for x in range(side):
                    head = [x, y, z]
                    head[axis] += 1
                    if head[axis] > resolution:
                        continue
                    low = field[corner(x, y, z)] < 0.0
                    high = field[corner(head[0], head[1], head[2])] < 0.0
                    if low == high:
                        continue
                    cells = [(x + dx, y + dy, z + dz) for dx, dy, dz in offsets]
                    if any(cell not in cell_vertex for cell in cells):
                        continue
                    quad = [cell_vertex[cell] for cell in cells]
                    if not low:
                        quad.reverse()
                    triangles.append((quad[0], quad[1], quad[2]))
                    triangles.append((quad[0], quad[2], quad[3]))

    if not triangles:
        raise ValueError("sdf polygonisation produced no geometry; the surface never crosses zero inside its bounds")
    return {"positions": positions, "indices": triangles, "resolution": resolution}


def compute_vertex_normals(positions: list[Vector], triangles: list[tuple[int, int, int]]) -> list[Vector]:
    """Area-weighted vertex normals, matching `THREE.BufferGeometry.computeVertexNormals`.

    They are averaged across the shared grid corners on purpose. The mesh is blocky because the grid
    is finite, not because the surface is; averaging shades it as the smooth surface it approximates.
    """
    accumulated = [[0.0, 0.0, 0.0] for _ in positions]
    for a, b, c in triangles:
        pa, pb, pc = positions[a], positions[b], positions[c]
        edge1 = (pc[0] - pb[0], pc[1] - pb[1], pc[2] - pb[2])
        edge2 = (pa[0] - pb[0], pa[1] - pb[1], pa[2] - pb[2])
        cross = (
            edge1[1] * edge2[2] - edge1[2] * edge2[1],
            edge1[2] * edge2[0] - edge1[0] * edge2[2],
            edge1[0] * edge2[1] - edge1[1] * edge2[0],
        )
        for index in (a, b, c):
            for axis in range(3):
                accumulated[index][axis] += cross[axis]
    normals: list[Vector] = []
    for vector in accumulated:
        length = _length((vector[0], vector[1], vector[2]))
        if length == 0.0:
            normals.append((0.0, 0.0, 1.0))
        else:
            normals.append((vector[0] / length, vector[1] / length, vector[2] / length))
    return normals


def project_atlas_uv(mesh: dict[str, Any], *, flip_u: bool = False, frame: dict[str, Any] | None = None) -> dict[str, Any]:
    """Split the surface into the atlas's dorsal and palmar halves and unindex it.

    The result is unindexed because the atlas half is a property of a *triangle* -- which plate faced
    it -- while `polygonizeSdf` shares one grid corner between faces pointing different ways, so a
    single uv per position cannot express the split. Unindexing costs nothing that is measured here:
    `geometry_integrity.mesh_edge_counts` welds edges by rounded position, so a duplicated position
    still closes the surface.
    """
    positions: list[Vector] = mesh["positions"]
    triangles: list[tuple[int, int, int]] = mesh["indices"]
    normals = compute_vertex_normals(positions, triangles)
    lows = [min(position[axis] for position in positions) for axis in range(3)]
    highs = [max(position[axis] for position in positions) for axis in range(3)]
    if frame is not None:
        # The caller states the rectangle the plate covers. The mesh's own bounding box is not that
        # rectangle: it also contains the thumb's sideways reach and anything else that extends past the
        # measured silhouette, and mapping the plate onto it puts the print off the form.
        lows = [float(frame["min"][0]), float(frame["min"][1]), lows[2]]
        highs = [float(frame["max"][0]), float(frame["max"][1]), highs[2]]
    spans = [highs[axis] - lows[axis] or 1.0 for axis in range(3)]

    # The silhouette's own left and right edge at each height, read off the mesh.
    #
    # A face whose normal lies in the xy plane was seen by NEITHER plate: it is the band around the
    # equator of the form. Giving it u from its own x smears the plate across it -- the face spans many
    # plate columns over a few pixels of screen, which rendered as vertical stripes down both outer edges
    # of the glove. The honest colour for an unobserved side face is the nearest observed one, which is
    # the plate at the silhouette's edge at that height, so that is what it gets: u follows the boundary
    # and varies with height, and does not vary across the face's depth, because no plate saw that depth.
    # Plain planar projection: u from x, v from y, for every face.
    #
    # Three schemes for the faces no plate saw were built and measured against this one, and none beat it.
    # Sourcing their u from the silhouette's hull edge per row, then per row AND column by dominant axis,
    # then stepping the sample two cells inside that edge -- the last moved 3,771 uvs by up to 8% of a plate
    # and changed the render not at all. Rendered side by side, the hull-boundary scheme and this are
    # indistinguishable.
    #
    # What that means: the striping along the silhouette edge is not a scheme's mistake. At the edge the
    # surface turns away from the camera, so a projection along that camera's own axis compresses its last
    # texels into a grazing band however u is chosen. It is foreshortening. The cures are real side data or
    # a flatter form, not a cleverer lookup, and this is the simplest thing that is exactly as good.
    out_positions: list[Vector] = []
    out_normals: list[Vector] = []
    out_uv: list[tuple[float, float]] = []
    out_indices: list[tuple[int, int, int]] = []
    for a, b, c in triangles:
        # The side that saw a triangle comes from the *smoothed* normal, not the facet's own. Every
        # face of a voxel mesh is axis-aligned, so on a rounded form most facets point along x or y
        # and have no z at all: judged by facet, four fifths of the armature landed in the dorsal
        # half. The averaged normal is the normal of the surface being approximated, which is what the
        # camera that took the plate actually faced.
        # The plate that saw a triangle comes from the *smoothed* normal, not the facet's own: the facet is
        # one cell of an extraction grid, the smoothed normal is the surface being approximated, and that is
        # what the camera faced.
        dorsal = normals[a][2] + normals[b][2] + normals[c][2] >= 0.0

        base = len(out_positions)
        for index in (a, b, c):
            position = positions[index]
            # Clamped here rather than left to the texture's own wrap mode: the atlas holds both plates
            # in one image, so a u past 1.0 in the dorsal half would sample the palmar half rather than
            # the dorsal plate's edge. Parts of the form that reach outside the measured silhouette --
            # the thumb, the fingertips -- take the plate's edge colour, which the atlas dilates.
            # v runs DOWNWARD from the frame's top, because the atlas is uploaded with `flipY = false`:
            # texture v=0 is the first row in memory, that row is the image's top, and the atlas's top row is
            # the plate's top row -- the fingertips. Measuring v upward from the frame's bottom put the
            # model's fingertips at v=1 and so on the atlas's LAST row, and every glove wore its cuff on its
            # fingertips and its fingertips at its wrist. It survived a dozen renders unnoticed because a
            # glove is nearly symmetric in its colour blocking end to end; it was settled by comparing the
            # atlas's rows against the plate's crop row for row, not by looking at either.
            u = min(1.0, max(0.0, (position[0] - lows[0]) / spans[0]))
            v = min(1.0, max(0.0, (highs[1] - position[1]) / spans[1]))
            if flip_u:
                u = 1.0 - u
            out_positions.append(position)
            out_normals.append(normals[index])
            out_uv.append((u * 0.5 if dorsal else 0.5 + u * 0.5, v))
        out_indices.append((base, base + 1, base + 2))
    return {
        "positions": out_positions,
        "normals": out_normals,
        "uv0": out_uv,
        "indices": out_indices,
        "projection": {
            "mode": "orthographic-front-projection",
            "dorsalHalf": [0.0, 0.0, 0.5, 1.0],
            "palmarHalf": [0.5, 0.0, 0.5, 1.0],
            "flipU": flip_u,
            "frame": {"min": lows[:2], "max": highs[:2]},
            "frameSource": "declared" if frame is not None else "polygonised-bounds",
            "limitations": [
                "the grazing band along the silhouette edge, where the surface turns away from the plate's own camera, wears that plate's last texels stretched along it; no projection along the camera axis can avoid that, and no plate observed what is there.",
                "anything reaching outside the measured silhouette -- the thumb, the fingertips -- takes the plate's clamped edge colour rather than an observed one.",
            ] + ([] if frame is not None else [
                "no frame was declared, so u and v span the polygonised bounds including the thumb's reach; the plate is aligned to a few percent, not exactly.",
            ]),
        },
    }


def build_sdf_mesh(descriptor: dict[str, Any], *, flip_u: bool = False) -> dict[str, Any]:
    """Polygonize an SDF descriptor and give it atlas UVs, as the runtime will."""
    return project_atlas_uv(polygonize_sdf(descriptor["sdf"] if "sdf" in descriptor else descriptor), flip_u=flip_u)
