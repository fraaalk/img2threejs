/**
 * Builds the glove shell from its descriptor, in the browser, from code.
 *
 * This is the review runtime's copy of the inflation. `forge/stage3_build/glove_shell.py` is the
 * authority and `forge/tests/test_glove_shell_runtime_parity.py` pins this file to it vertex for
 * vertex and uv for uv, because three implementations of one algorithm (Python, the emitted
 * TypeScript factory, and this) drift silently otherwise.
 */

export function buildShellAttributes(descriptor) {
  const size = descriptor.grid;
  const hand = descriptor.hand ?? 'left';
  const offset = hand === 'right' ? descriptor.handSeparation : -descriptor.handSeparation;
  const occupied = (mask, row, col) => (
    row >= 0 && col >= 0 && row < size && col < size && mask[row][col] === '1'
  );
  const inside = (row, col) => occupied(descriptor.mask, row, col);
  const chamfer = (mask) => {
    const field = [];
    for (let row = 0; row < size; row += 1) {
      field.push(new Array(size).fill(0));
      for (let col = 0; col < size; col += 1) field[row][col] = occupied(mask, row, col) ? size * size : 0;
    }
    for (let row = 0; row < size; row += 1) {
      for (let col = 0; col < size; col += 1) {
        if (!field[row][col]) continue;
        let best = field[row][col];
        if (row > 0) best = Math.min(best, field[row - 1][col] + 1);
        if (col > 0) best = Math.min(best, field[row][col - 1] + 1);
        field[row][col] = best;
      }
    }
    for (let row = size - 1; row >= 0; row -= 1) {
      for (let col = size - 1; col >= 0; col -= 1) {
        if (!field[row][col]) continue;
        let best = field[row][col];
        if (row < size - 1) best = Math.min(best, field[row + 1][col] + 1);
        if (col < size - 1) best = Math.min(best, field[row][col + 1] + 1);
        field[row][col] = best;
      }
    }
    let peak = 0;
    for (const row of field) for (const value of row) peak = Math.max(peak, value);
    return { field, peak: Math.max(1, peak) };
  };
  const front = chamfer(descriptor.mask);
  // The palmar plate gives the back its own profile; without it both halves mirror the dorsal.
  const back = descriptor.backMask ? chamfer(descriptor.backMask) : front;
  const palmThickness = descriptor.palmThicknessRatio * descriptor.aspect;
  const halfThickness = (row, col, isFront) => {
    const side = isFront ? front : back;
    const share = isFront ? descriptor.frontShare : descriptor.backShare;
    return palmThickness * share * Math.sqrt(Math.min(1, side.field[row][col] / side.peak));
  };
  const solid = new Set();
  for (let row = 0; row < size - 1; row += 1) {
    for (let col = 0; col < size - 1; col += 1) {
      if (inside(row, col) && inside(row, col + 1) && inside(row + 1, col + 1) && inside(row + 1, col)) {
        solid.add(`${row},${col}`);
      }
    }
  }
  const positions = [];
  const uvs = [];
  const indices = [];
  const lookup = new Map();
  const vertex = (row, col, isFront) => {
    const key = `${row},${col},${isFront ? 1 : 0}`;
    const existing = lookup.get(key);
    if (existing !== undefined) return existing;
    const id = positions.length / 3;
    lookup.set(key, id);
    const x = (col + 0.5) / size - 0.5;
    const y = 0.5 - (row + 0.5) / size;
    const half = halfThickness(row, col, isFront);
    positions.push(hand === 'right' ? -x + offset : x + offset, y, isFront ? half : -half);
    const u = (col + 0.5) / size;
    uvs.push(isFront ? u * 0.5 : 0.5 + u * 0.5, 1 - (row + 0.5) / size);
    return id;
  };
  const outwardFront = hand === 'right';
  const cells = Array.from(solid).map((key) => key.split(',').map(Number));
  cells.sort((left, right) => (left[0] - right[0]) || (left[1] - right[1]));
  for (const [row, col] of cells) {
    const corners = [[row, col], [row, col + 1], [row + 1, col + 1], [row + 1, col]];
    for (const isFront of [true, false]) {
      const [a, b, c, d] = corners.map(([r, cc]) => vertex(r, cc, isFront));
      if (isFront === outwardFront) indices.push(a, b, c, a, c, d);
      else indices.push(a, c, b, a, d, c);
    }
    const rim = [
      [[row - 1, col], [row, col], [row, col + 1]],
      [[row, col + 1], [row, col + 1], [row + 1, col + 1]],
      [[row + 1, col], [row + 1, col + 1], [row + 1, col]],
      [[row, col - 1], [row + 1, col], [row, col]],
    ];
    for (const [neighbour, cornerA, cornerB] of rim) {
      if (solid.has(`${neighbour[0]},${neighbour[1]}`)) continue;
      const a = vertex(cornerA[0], cornerA[1], true);
      const b = vertex(cornerB[0], cornerB[1], true);
      const c = vertex(cornerB[0], cornerB[1], false);
      const d = vertex(cornerA[0], cornerA[1], false);
      if (!outwardFront) indices.push(a, b, c, a, c, d);
      else indices.push(a, c, b, a, d, c);
    }
  }
  if (!indices.length) throw new Error('silhouette inflation produced no geometry');
  return { positions, uvs, indices };
}
