# ★ Sport Gloves | Hedge Maze (Field-Tested)

The anatomical preview is implemented in [`runtime/cs2-preview`](../../runtime/cs2-preview). It uses the `cs2-glove-v1` adapter, validated paired dorsal/palmar references, a typed glove factory, and fixed/orbit inspection controls.

Run it locally:

```bash
cd runtime/cs2-preview
pnpm build
pnpm preview -- --port 4173
```

The preview is a non-production procedural approximation. It validates paired source metadata and resource limits, but deliberately reports unbaked projection coverage until the locked GLTF bake asset is supplied. Hidden glove geometry is inferred because the supplied references are 2D renders rather than a native mesh.
