/**
 * Polygonizes an SDF descriptor in the browser, from code, and gives it the two-plate atlas uvs.
 *
 * This is the review runtime's copy of `polygonizeSdf` / `projectSdfAtlasUv`, which ship as the
 * emitted TypeScript in `forge/stage3_build/generate_threejs_factory.py`.
 * `forge/_shared/sdf_mesh.py` is the authority and `forge/tests/test_glove_armature_parity.py` pins
 * all three to each other, position for position and uv for uv, because three implementations of one
 * algorithm drift silently otherwise.
 *
 * It takes THREE so the transform maths is the same objects the emitted factory uses: an Euler-XYZ
 * quaternion hand-rolled here would be a fourth implementation of the one thing that must not differ.
 */

const MIN_RESOLUTION = 4;
const MAX_RESOLUTION = 64;
const DEFAULT_BOUNDS = { min: [-2, -2, -2], max: [2, 2, 2] };

function sdfRadii(primitive) {
  if (primitive.radii) return primitive.radii;
  if (typeof primitive.radius === 'number') return [primitive.radius, primitive.radius, primitive.radius];
  return primitive.radius ?? [0.5, 0.5, 0.5];
}

function smin(left, right, radius) {
  const blend = Math.max(radius - Math.abs(left - right), 0) / radius;
  return Math.min(left, right) - blend * blend * radius * 0.25;
}

function localPoint(THREE, point, primitive) {
  const transform = primitive.transform;
  const translation = transform?.position ?? transform?.translation ?? primitive.center ?? [0, 0, 0];
  const rotation = transform?.rotation ?? [0, 0, 0];
  const scale = transform?.scale ?? [1, 1, 1];
  const local = point.clone().sub(new THREE.Vector3(translation[0], translation[1], translation[2]));
  const inverseRotation = new THREE.Quaternion()
    .setFromEuler(new THREE.Euler(rotation[0], rotation[1], rotation[2]))
    .invert();
  local.applyQuaternion(inverseRotation);
  local.set(local.x / scale[0], local.y / scale[1], local.z / scale[2]);
  return { point: local, scale: Math.min(scale[0], scale[1], scale[2]) };
}

function primitiveDistance(THREE, point, primitive) {
  const local = localPoint(THREE, point, primitive);
  const p = local.point;
  const numericRadius = typeof primitive.radius === 'number' ? primitive.radius : null;
  let distance;
  switch (primitive.type) {
    case 'sphere':
      distance = p.length() - (numericRadius ?? 0.5);
      break;
    case 'capsule': {
      const halfHeight = (primitive.height ?? 1) * 0.5;
      const y = Math.max(-halfHeight, Math.min(halfHeight, p.y));
      distance = p.distanceTo(new THREE.Vector3(0, y, 0)) - (numericRadius ?? 0.25);
      break;
    }
    case 'box': {
      const size = primitive.size ?? primitive.dimensions ?? [1, 1, 1];
      const q = new THREE.Vector3(Math.abs(p.x), Math.abs(p.y), Math.abs(p.z))
        .sub(new THREE.Vector3(size[0] * 0.5, size[1] * 0.5, size[2] * 0.5));
      distance = q.clone().max(new THREE.Vector3()).length() + Math.min(Math.max(q.x, q.y, q.z), 0);
      break;
    }
    case 'cone': {
      const radius = numericRadius ?? 0.5;
      const height = primitive.height ?? 1;
      const halfHeight = height * 0.5;
      const taper = radius * (1 - (p.y + halfHeight) / height);
      distance = Math.max(Math.hypot(p.x, p.z) - Math.max(0, taper), Math.abs(p.y) - halfHeight);
      break;
    }
    case 'ellipsoid': {
      const radii = sdfRadii(primitive);
      const scaled = new THREE.Vector3(p.x / radii[0], p.y / radii[1], p.z / radii[2]);
      distance = (scaled.length() - 1) * Math.min(radii[0], radii[1], radii[2]);
      break;
    }
    default:
      throw new Error(`unsupported sdf primitive type ${primitive.type}`);
  }
  return distance * local.scale;
}

function sampleSdf(THREE, descriptor) {
  const nodes = new Map();
  for (const primitive of descriptor.primitives) {
    nodes.set(primitive.id, (point) => primitiveDistance(THREE, point, primitive));
  }
  let result = descriptor.primitives.length > 0 ? nodes.get(descriptor.primitives[0].id) : undefined;
  const operations = descriptor.operations ?? [];
  for (let index = 0; index < operations.length; index += 1) {
    const operation = operations[index];
    const left = nodes.get(operation.left);
    const right = nodes.get(operation.right);
    if (!left || !right) continue;
    let combined;
    switch (operation.type) {
      case 'union':
        combined = (point) => Math.min(left(point), right(point));
        break;
      case 'smooth-union':
        combined = (point) => smin(left(point), right(point), operation.radius ?? 0.1);
        break;
      case 'subtract':
        combined = (point) => Math.max(left(point), -right(point));
        break;
      case 'intersect':
        combined = (point) => Math.max(left(point), right(point));
        break;
      default:
        throw new Error(`unsupported sdf operation type ${operation.type}`);
    }
    nodes.set(operation.id ?? operation.output ?? `operation-${index}`, combined);
    result = combined;
  }
  return result ?? (() => Infinity);
}

// The eight corners of a cell and its twelve edges, as corner-index pairs.
const CELL_CORNERS = [
  [0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1],
];
const CELL_EDGES = [
  [0, 1], [0, 2], [0, 4], [1, 3], [1, 5], [2, 3], [2, 6], [3, 7], [4, 5], [4, 6], [5, 7], [6, 7],
];
// One quad per sign-changing grid edge, from the four cells that share it, per edge direction.
const EDGE_CELLS = [
  [0, [[0, -1, -1], [0, 0, -1], [0, 0, 0], [0, -1, 0]]],
  [1, [[-1, 0, -1], [-1, 0, 0], [0, 0, 0], [0, 0, -1]]],
  [2, [[-1, -1, 0], [0, -1, 0], [0, 0, 0], [-1, 0, 0]]],
];

/**
 * Extracts the zero level set with naive surface nets: one interpolated vertex per crossing cell.
 *
 * It replaces a binary-occupancy extractor that placed every vertex on an integer grid corner. That
 * threw away all sub-cell position, so the surface was faceted at cell scale however fine the grid; it
 * could not represent a crease where two solids touch without a gap; and every face being axis-aligned
 * left 35% of triangles with exactly zero uv area under a planar projection.
 *
 * The field is sampled at cell CORNERS, (resolution + 1) cubed of them.
 */
export function polygonizeSdfAttributes(THREE, descriptor) {
  const resolution = Math.max(MIN_RESOLUTION, Math.min(MAX_RESOLUTION, Math.floor(descriptor.resolution)));
  const bounds = descriptor.bounds ?? DEFAULT_BOUNDS;
  const min = [bounds.min[0], bounds.min[1], bounds.min[2]];
  const step = [0, 1, 2].map((axis) => (bounds.max[axis] - min[axis]) / resolution);
  const sample = sampleSdf(THREE, descriptor);

  const side = resolution + 1;
  const field = new Float64Array(side * side * side);
  const at = (x, y, z) => (z * side + y) * side + x;
  for (let z = 0; z < side; z += 1) {
    for (let y = 0; y < side; y += 1) {
      for (let x = 0; x < side; x += 1) {
        field[at(x, y, z)] = sample(new THREE.Vector3(
          min[0] + x * step[0],
          min[1] + y * step[1],
          min[2] + z * step[2],
        ));
      }
    }
  }

  const positions = [];
  const cellVertex = new Map();
  const cellKey = (x, y, z) => (z * resolution + y) * resolution + x;
  const values = new Float64Array(8);
  const inside = new Array(8);
  for (let z = 0; z < resolution; z += 1) {
    for (let y = 0; y < resolution; y += 1) {
      for (let x = 0; x < resolution; x += 1) {
        let insideCount = 0;
        for (let corner = 0; corner < 8; corner += 1) {
          const offset = CELL_CORNERS[corner];
          values[corner] = field[at(x + offset[0], y + offset[1], z + offset[2])];
          inside[corner] = values[corner] < 0;
          if (inside[corner]) insideCount += 1;
        }
        if (insideCount === 0 || insideCount === 8) continue;
        const total = [0, 0, 0];
        let crossings = 0;
        for (const [first, second] of CELL_EDGES) {
          if (inside[first] === inside[second]) continue;
          const a = values[first];
          const b = values[second];
          const t = a / (a - b);
          for (let axis = 0; axis < 3; axis += 1) {
            const low = CELL_CORNERS[first][axis];
            const high = CELL_CORNERS[second][axis];
            total[axis] += low + (high - low) * t;
          }
          crossings += 1;
        }
        cellVertex.set(cellKey(x, y, z), positions.length / 3);
        positions.push(
          min[0] + (x + total[0] / crossings) * step[0],
          min[1] + (y + total[1] / crossings) * step[1],
          min[2] + (z + total[2] / crossings) * step[2],
        );
      }
    }
  }

  const triangles = [];
  for (const [axis, offsets] of EDGE_CELLS) {
    for (let z = 0; z < side; z += 1) {
      for (let y = 0; y < side; y += 1) {
        for (let x = 0; x < side; x += 1) {
          const head = [x, y, z];
          head[axis] += 1;
          if (head[axis] > resolution) continue;
          const low = field[at(x, y, z)] < 0;
          const high = field[at(head[0], head[1], head[2])] < 0;
          if (low === high) continue;
          const quad = [];
          let complete = true;
          for (const offset of offsets) {
            const cx = x + offset[0];
            const cy = y + offset[1];
            const cz = z + offset[2];
            if (cx < 0 || cy < 0 || cz < 0 || cx >= resolution || cy >= resolution || cz >= resolution) {
              complete = false;
              break;
            }
            const vertex = cellVertex.get(cellKey(cx, cy, cz));
            if (vertex === undefined) { complete = false; break; }
            quad.push(vertex);
          }
          if (!complete) continue;
          if (!low) quad.reverse();
          triangles.push([quad[0], quad[1], quad[2]], [quad[0], quad[2], quad[3]]);
        }
      }
    }
  }
  if (!triangles.length) throw new Error('sdf polygonisation produced no geometry');
  return { positions, triangles };
}

/** Area-weighted vertex normals, matching THREE.BufferGeometry.computeVertexNormals. */
function computeVertexNormals(positions, triangles) {
  const accumulated = new Float64Array(positions.length);
  for (const [a, b, c] of triangles) {
    const pa = a * 3; const pb = b * 3; const pc = c * 3;
    const e1 = [positions[pc] - positions[pb], positions[pc + 1] - positions[pb + 1], positions[pc + 2] - positions[pb + 2]];
    const e2 = [positions[pa] - positions[pb], positions[pa + 1] - positions[pb + 1], positions[pa + 2] - positions[pb + 2]];
    const cross = [
      e1[1] * e2[2] - e1[2] * e2[1],
      e1[2] * e2[0] - e1[0] * e2[2],
      e1[0] * e2[1] - e1[1] * e2[0],
    ];
    for (const base of [pa, pb, pc]) for (let axis = 0; axis < 3; axis += 1) accumulated[base + axis] += cross[axis];
  }
  const normals = new Float64Array(positions.length);
  for (let base = 0; base < positions.length; base += 3) {
    const length = Math.hypot(accumulated[base], accumulated[base + 1], accumulated[base + 2]);
    if (length === 0) { normals[base + 2] = 1; continue; }
    for (let axis = 0; axis < 3; axis += 1) normals[base + axis] = accumulated[base + axis] / length;
  }
  return normals;
}

/**
 * Splits the surface into the atlas's dorsal and palmar halves and unindexes it.
 *
 * The side comes from the smoothed normal, not the facet's own: every face of a voxel mesh is
 * axis-aligned, so on a rounded form most facets point along x or y and carry no z at all. Judged by
 * facet, four fifths of the glove armature fell into the dorsal half. Unindexing is what lets the
 * choice be per triangle -- one uv per shared grid corner cannot express which plate saw a face, and a
 * triangle with uvs either side of 0.5 would interpolate its texture through the middle of the atlas.
 */
export function buildSdfAtlasAttributes(THREE, descriptor) {
  const { positions, triangles } = polygonizeSdfAttributes(THREE, descriptor);
  const normals = computeVertexNormals(positions, triangles);
  const flipU = descriptor.uvProjection?.flipU === true;
  const frame = descriptor.uvProjection?.frame ?? null;
  let lowX = Infinity; let highX = -Infinity; let lowY = Infinity; let highY = -Infinity;
  if (frame) {
    // The declared rectangle the plate covers. The mesh's own bounding box is not it: that also holds
    // the thumb's sideways reach, and mapping the plate onto it puts the print off the form.
    [lowX, lowY] = frame.min;
    [highX, highY] = frame.max;
  } else {
    for (let base = 0; base < positions.length; base += 3) {
      lowX = Math.min(lowX, positions[base]); highX = Math.max(highX, positions[base]);
      lowY = Math.min(lowY, positions[base + 1]); highY = Math.max(highY, positions[base + 1]);
    }
  }
  const spanX = highX - lowX || 1;
  const spanY = highY - lowY || 1;
  // Plain planar projection: u from x, v from y, for every face. Three schemes for the faces no plate saw
  // were measured against this one and none beat it. The striping along the silhouette edge is
  // foreshortening, not a lookup mistake.
  const outPositions = [];
  const outNormals = [];
  const outUvs = [];
  for (const triangle of triangles) {
    const dorsal = triangle.reduce((total, corner) => total + normals[corner * 3 + 2], 0) >= 0;
    for (const corner of triangle) {
      const base = corner * 3;
      const x = positions[base];
      const y = positions[base + 1];
      outPositions.push(x, y, positions[base + 2]);
      outNormals.push(normals[base], normals[base + 1], normals[base + 2]);
      // Clamped here rather than left to the texture's wrap mode: the atlas holds both plates in one
      // image, so a u past 1.0 in the dorsal half would sample the palmar half instead of the dorsal
      // plate's dilated edge.
      let u = Math.min(1, Math.max(0, (x - lowX) / spanX));
      // v downward from the frame's top: `flipY = false` makes v=0 the image's first row, which is the
      // plate's top. Measured upward, the model wore its cuff on its fingertips.
      const v = Math.min(1, Math.max(0, (highY - y) / spanY));
      if (flipU) u = 1 - u;
      outUvs.push(dorsal ? u * 0.5 : 0.5 + u * 0.5, v);
    }
  }
  return { positions: outPositions, normals: outNormals, uvs: outUvs, triangleCount: triangles.length };
}
