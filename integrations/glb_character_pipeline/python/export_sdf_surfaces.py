"""Pack one or more Surface Nets node surfaces into a single binary the demo fetches.

Supersedes export_head_surface.py, which handled node 9 alone. Same construction throughout: a signed
distance field splatted from the node's own point cloud using the GLB's NORMAL attribute, contoured by
Surface Nets, coloured per vertex from the GLB diffuse (mean of the four nearest source vertices,
decoded sRGB -> linear because three.js treats a colour attribute as already being in the working
space). No UVs, so no UV seams.

WHY THIS EXISTS FOR MORE THAN THE HEAD. Five regions never moved across an entire pass of filtering and
material work -- pouches, boots, knee-pads, katana, canister -- and all five sit 1.3-1.8x the baseline's
surface noise. US-001 established that the residual is a SMOOTH error in the radial estimator, not
noise: a notch filter with zero gain at the ring frequency removed 100% of that component and moved the
figure by 6.8%. The head then showed what replacing the estimator is worth -- 17.40 -> 9.65, below the
baseline's own 11.76, with IoU 0.995.

Layout, little-endian:
    magic 'HEDS'  u32 version(3)  u32 jsonLength
    json bytes, padded to a 4-byte boundary
    then, per entry in json order: f32 position[3n], f32 normal[3n], u8 colour[3n] padded, u32 index[m]
"""
from __future__ import annotations
import json, os, struct, subprocess, sys
from collections import defaultdict
import os
from pathlib import Path
import numpy as np
from PIL import Image
Image.MAX_IMAGE_PIXELS = None

# ADAPTED FOR img2threejs (opt-in integration): this script's own location is no longer the
# showcase repo root -- it lives in integrations/glb_character_pipeline/python/ inside the
# img2threejs tool repo. Every showcase-side default path is resolved against
# IMG2THREEJS_SHOWCASE_ROOT instead (the same env var forge/tests already uses to reach a
# companion showcase checkout), falling back to the current directory only if unset.
ROOT = Path(os.environ.get('IMG2THREEJS_SHOWCASE_ROOT', '.')).resolve()

# PACKAGED (v1.5.1). Everything a new character has to supply is read from environment variables, with
# girl-character's own values as the default so this script reproduces the existing build unchanged when
# none are set. build-character.sh sets all of these from a per-character .env config file; see
# configs/example.env for what a new reference needs.
#
#   CHARACTER_GLB           path to the baseline GLB
#   CHARACTER_DIFFUSE       path to the extracted diffuse texture (run extract_glb_images.py first, or
#                           point this at whatever PNG holds the node's colour bake)
#   CHARACTER_REGIONS_JSON  path to a JSON object mapping node index (string) -> region label, e.g.
#                           {"0": "torso", "9": "head"}. A node missing from this map falls back to
#                           "region<N>" rather than crashing, so an incomplete map degrades gracefully.
#   CHARACTER_OUT_PREFIX    output .bin path prefix (default public/head/sdf-surfaces)
#   CHARACTER_WORKDIR       passed through to build_head_surface.py (default work/head)
GLB_PATH = Path(os.environ.get('CHARACTER_GLB', str(ROOT / 'public/mesh/girl-character-baseline.glb')))
DIFFUSE_PATH = Path(os.environ.get('CHARACTER_DIFFUSE', str(ROOT / 'work/baseline-textures/01-texture_diffuse.png')))
OUT_PREFIX = os.environ.get('CHARACTER_OUT_PREFIX', str(ROOT / 'public/head/sdf-surfaces'))
_regions_file = os.environ.get('CHARACTER_REGIONS_JSON')
if _regions_file:
    NODE_REGION = {int(k): v for k, v in json.loads(Path(_regions_file).read_text()).items()}
else:
    NODE_REGION = {0:'overalls',1:'skin',2:'boots',3:'skin',4:'boots',5:'pouches',6:'canister',7:'pouches',
                   8:'katana',9:'hair',10:'knee-pads',11:'boots',12:'knee-pads',13:'boots',14:'gloves',
                   15:'skin'}
# node -> cell size in metres. The head needs 1.5 mm because an eyelid's relief is 1.6 mm at an 8 mm
# scale; nothing else on the figure carries a feature that fine, and 2.0 mm keeps p95 near 1.17 mm.
# The head needs 1.5 mm because an eyelid's relief is 1.6 mm at an 8 mm scale. The trousers are the
# largest surface on the figure and carry nothing near that fine, so they take 2.5 mm to keep the file
# from doubling for no measured gain.
CELL = {9: 0.0015, 0: 0.0025}
DEFAULT_CELL = 0.0020

raw = GLB_PATH.read_bytes()
off, chunks = 12, {}
while off < len(raw):
    ln, ty = struct.unpack_from('<II', raw, off); chunks[ty] = raw[off+8:off+8+ln]; off += 8+ln
    off = off if off % 4 == 0 else off + (4 - off % 4)
g = json.loads(chunks[0x4E4F534A].decode()); BIN = chunks[0x004E4942]
def acc(i):
    a=g['accessors'][i]; bv=g['bufferViews'][a['bufferView']]
    dt={5120:'i1',5121:'u1',5122:'i2',5123:'u2',5125:'u4',5126:'f4'}[a['componentType']]
    nc={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[a['type']]
    o=bv.get('byteOffset',0)+a.get('byteOffset',0)
    return np.frombuffer(BIN,dtype=np.dtype('<'+dt),count=a['count']*nc,offset=o).reshape(a['count'],nc)

diffuse = np.asarray(Image.open(DIFFUSE_PATH).convert('RGB'))
TH, TW = diffuse.shape[:2]

# Optional trailing "xN" argument scales every cell size, for measuring what triangle budget actually
# costs in fidelity rather than assuming it.
scale = 1.0
keep_head = False
argv = list(sys.argv[1:])
if argv and argv[-1] == 'keephead':
    keep_head = True
    argv.pop()
if argv and argv[-1].startswith('x'):
    scale = float(argv.pop()[1:])
nodes = [int(a) for a in argv] or [9]
entries, blocks = [], []
for node in nodes:
    # The head is exempt from coarsening. It is the only part whose detail the eye tracks -- the
    # measured comparison across detail levels shows the nose and eyes softening first, while boots,
    # trousers and armour hold up -- so scaling it with everything else spends the budget in the one
    # place it is worst spent.
    cell = CELL.get(node, DEFAULT_CELL) * (1.0 if node == 9 and keep_head else scale)
    workdir = Path(os.environ.get('CHARACTER_WORKDIR', str(ROOT / 'work/head')))
    subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'build_head_surface.py'),
                     str(node), str(cell)],
                   check=True, cwd=ROOT, stdout=subprocess.DEVNULL, env={**os.environ, 'CHARACTER_GLB': str(GLB_PATH)})
    V = np.load(workdir/'V.npy').astype(np.float64)
    T = np.load(workdir/'T.npy').astype(np.int64)
    prims = g['meshes'][g['nodes'][node]['mesh']]['primitives']
    P = np.concatenate([acc(p['attributes']['POSITION']) for p in prims]).astype(np.float64)
    UV = np.concatenate([acc(p['attributes']['TEXCOORD_0']) for p in prims]).astype(np.float64)
    col = diffuse[np.clip((UV[:,1] % 1.0 * TH).astype(int), 0, TH-1),
                  np.clip((UV[:,0] % 1.0 * TW).astype(int), 0, TW-1)].astype(np.float64)
    hash_cell = 0.005
    lo = np.minimum(V.min(0), P.min(0)) - hash_cell
    buck = defaultdict(list)
    for i, k in enumerate(map(tuple, np.floor((P - lo)/hash_cell).astype(np.int64))): buck[k].append(i)
    vk = np.floor((V - lo)/hash_cell).astype(np.int64)
    srgb = np.zeros((len(V), 3))
    for n in range(len(V)):
        k = tuple(vk[n]); cand = []
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for dz in (-1,0,1): cand += buck.get((k[0]+dx,k[1]+dy,k[2]+dz), [])
        if not cand: continue
        cand = np.asarray(cand)
        srgb[n] = col[cand[np.argsort(np.linalg.norm(P[cand]-V[n], axis=1))[:4]]].mean(axis=0)
    lin = np.where(srgb/255 <= 0.04045, (srgb/255)/12.92, (((srgb/255)+0.055)/1.055)**2.4)
    COL = np.clip(np.round(lin*255), 0, 255).astype(np.uint8)
    fn = np.cross(V[T[:,1]]-V[T[:,0]], V[T[:,2]]-V[T[:,0]])
    N = np.zeros_like(V)
    for c in range(3): np.add.at(N, T[:,c], fn)
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    entries.append({'node': node, 'region': NODE_REGION.get(node, f'region{node}'), 'cellMillimetres': round(cell*1000, 2),
                    'vertexCount': int(len(V)), 'indexCount': int(T.size)})
    body = bytearray()
    body += V.astype('<f4').tobytes()
    body += N.astype('<f4').tobytes()
    body += COL.tobytes()
    while len(body) % 4: body += b'\x00'
    body += T.ravel().astype('<u4').tobytes()
    blocks.append(bytes(body))
    print(f"node {node:2d} {NODE_REGION.get(node, f'region{node}'):10s} cell {cell*1000:.1f} mm  "
          f"{len(V):,} verts  {T.shape[0]:,} tris  {len(body)/1e6:.2f} MB")

hdr = json.dumps(entries, separators=(',', ':')).encode()
out = bytearray(b'HEDS') + struct.pack('<II', 3, len(hdr)) + hdr
while len(out) % 4: out += b'\x00'
for b in blocks: out += b
suffix = '' if scale == 1.0 else f'-x{scale:g}'
if keep_head:
    suffix += '-sharpface'
dest = Path(f'{OUT_PREFIX}{suffix}.bin')
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_bytes(out)
_shown = dest.relative_to(ROOT) if str(dest.resolve()).startswith(str(ROOT.resolve())) else dest
print(f"\nwrote {_shown}  {len(out)/1e6:.2f} MB  ({len(entries)} node(s))")
