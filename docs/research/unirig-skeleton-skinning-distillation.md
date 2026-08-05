# UniRig → img2threejs 1.5-alpha: skeleton and skinning distillation

Status: distilled 2026-08-02 with NotebookLM research, then cross-checked against the
official repository and paper.

## Executive conclusion

UniRig is valuable to alpha as a representation and validation reference, not as a
browser dependency. Its useful boundary is the separation between a skeleton tree and
per-vertex skin weights, plus explicit parent ordering, semantic names, local bone axes,
and deformation-aware evaluation. The neural checkpoint, dataset, CUDA stack, and
downloaded asset pipeline do not belong in the code-only procedural Three.js route.

The alpha adoption is therefore:

```text
procedural geometry + authored rig payload
        -> deterministic Python structural gate
        -> Three.js Bone/Skeleton/SkinnedMesh binding
        -> pose stress tests + dynamic bounds
        -> readable browser screenshots + reference loop
```

## Verified UniRig facts

The official README documents world-space mesh data (`vertices`, `faces`, normals), joint
positions (`joints`), dense per-vertex weights (`skin`), parent indices (`parents`), joint
names (`names`), and local bone axes (`matrix_local`). It specifies `parents[0]` as the
root with no parent and requires later parent indices to refer to an earlier joint. The
official `raw_data.py` implements the same invariant. The README also says that generated
skinning can degrade when the predicted skeleton is inaccurate, so skeleton review comes
before skinning review.

The paper describes two related stages: skeleton-tree prediction and skin-weight
prediction. It also uses skeleton-tree tokenization and bone-aware training/evaluation;
those are research-model details, not a requirement to copy its neural architecture.

The paper discusses DFS during skeleton-tree tokenization, while the serialized runtime
contract only needs a topologically valid parent-before-child array. Alpha deliberately
does not claim that its authored procedural payload must use BFS or DFS: traversal order is
an internal authoring choice, and the stable runtime invariant is `parentIndex < childIndex`.

Sources:

- Official dataset format and usage: <https://github.com/VAST-AI-Research/UniRig/blob/main/README.md>
- Official payload/export implementation: <https://github.com/VAST-AI-Research/UniRig/blob/main/src/data/raw_data.py>
- Official ordering helper: <https://github.com/VAST-AI-Research/UniRig/blob/main/src/data/order.py>
- Primary paper: <https://arxiv.org/abs/2504.12451>
- Project page: <https://zjp-shadow.github.io/works/UniRig/>

## Alpha contract

The validator accepts a JSON payload with this shape:

```json
{
  "schemaVersion": 1,
  "coordinateSystem": {"up": "Y", "handedness": "right", "unit": "normalized"},
  "joints": [[0, 1, 0], [0, 1.4, 0]],
  "parents": [null, 0],
  "names": ["root", "spine"],
  "matrix_local": [
    [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0.4, 0, 1]
  ],
  "skinIndex": [[0, 1, 0, 0]],
  "skinWeight": [[0.75, 0.25, 0, 0]]
}
```

The first five arrays mirror UniRig's data boundary. `skinIndex` and `skinWeight` are
alpha's packed WebGL representation: exactly four slots per vertex, non-negative finite
weights, valid joint indices, and a row sum of 1 within tolerance. The fixed four-slot
limit is an alpha/Three.js engineering decision; UniRig's raw `skin` matrix is dense and
its exporter exposes influence/normalization options.

## Gates

The dependency-free `forge/stage5_rig/validate_rig_payload.py` blocks malformed payloads
before browser binding:

1. schema and Y-up/right-handed coordinate declaration;
2. finite joint coordinates and unique non-empty names;
3. exactly one root at index 0 and `parentIndex < childIndex` for every other joint;
4. non-zero parent-child bone length;
5. one finite affine `matrix_local` per joint;
6. four skin index/weight slots for every geometry vertex;
7. valid indices, non-negative finite weights, and normalized rows;
8. active-weight coverage report per joint, with unweighted auxiliary joints surfaced as a
   warning rather than silently discarded.

Passing these gates proves payload integrity only. It does not prove that elbows, knees,
shoulders, hands, feet, hair, or clothing deform acceptably.

## What is not transferred

- no UniRig checkpoint, model weights, Articulation-XL/Rig-XL data, or downloaded mesh;
- no PyTorch/CUDA/`spconv`/`torch_scatter` runtime in the browser or stdlib forge;
- no claim that a procedural heuristic is equivalent to UniRig's learned skeleton or skin;
- no physics/spring-bone implementation in this alpha gate;
- no automatic remeshing or topology rewrite;
- no visual likeness pass before runtime pose/deformation evidence exists.

The next runtime phase must bind the validated payload to `THREE.Bone`,
`THREE.Skeleton`, and `THREE.SkinnedMesh`, then capture neutral, elbow, shoulder, knee,
hand/foot, and multi-angle views through the existing Python↔Three.js render bridge.
