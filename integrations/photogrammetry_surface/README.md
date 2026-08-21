# Photogrammetry surface (opt-in)

Reconstructs an oriented point cloud from **multi-view photographs**, so a subject with no GLB can
reach the same Surface Nets reconstruction a GLB baseline does. It is a front end, not a second
pipeline: its only output is a `cloud.npz` holding `P` and `N`, which is exactly what
`integrations/glb_character_pipeline/python/build_head_surface.py` already consumes.

**Read `PIPELINE.md`'s "Measured quality" section before using this on real work.** The plumbing is
verified and the pipeline runs end to end, but on the reference fixture the photo route lands well
short of the GLB route, and the limiting factor is the depth precision the input images can support.
That section carries the actual numbers and what moves them.

## Why it exists

`build_head_surface.py` splats a signed distance field from an oriented point cloud and contours it.
That code never depended on a GLB — a GLB was simply the only source that existed. Opening one env
var (`CHARACTER_CLOUD_NPZ`) lets any source feed the identical reconstruction, and
`tests/test_cloud_seam.py` proves the equivalence rather than assuming it: a GLB's own cloud pushed
back through the env var reproduces the GLB route's surface **byte for byte**, on both the vertex and
triangle arrays.

So the only new problem is producing `(P, N)` from images. That is what this integration does.

## How the geometry is obtained

Real photogrammetry, not monocular depth estimation:

1. **Poses** — COLMAP sparse SfM (`python/sfm_poses.py`) recovers intrinsics, poses and a sparse
   cloud from the images. This runs on the CPU.
2. **Dense depth** — plane-sweep ZNCC multi-view stereo (`python/dense_mvs.py`), one depth map per
   view, triangulated from photometric agreement between real pixels across calibrated views.
3. **Consistency** — a depth survives only where other views, reconstructed independently, put the
   same surface in the same place. This is the largest single quality lever in the module.
4. **Fusion** — back-project, estimate normals, voxel-average (`python/fuse_cloud.py`).

COLMAP's own dense stage is **not** used, and could not be: `pycolmap.patch_match_stereo` raises
`Dense stereo reconstruction requires CUDA, which is not available on your system` on any machine
without an NVIDIA GPU, and `pycolmap.has_cuda` is `False` here. Only its sparse half is used.

## Install

```bash
uv sync --project integrations/photogrammetry_surface --python 3.11
```

Pulls `pycolmap`, `numpy`, `pillow`, `scipy`. This is an opt-in integration precisely so the
stdlib-only `forge` core carries none of that.

## Use

```bash
export IMG2THREEJS_SHOWCASE_ROOT=/path/to/img2threejs-showcase

# poses unknown -- estimate them from the photos
integrations/photogrammetry_surface/photos-to-surface.sh \
  --images path/to/photos --out-dir work/photo-subject --sfm

# poses known (a calibrated rig, or a rendered fixture)
integrations/photogrammetry_surface/photos-to-surface.sh \
  --images work/views --cameras work/views/cameras.json --out-dir work/photo-subject
```

### Capture requirements, in order of how much they matter

1. **Angular spacing under 40°.** Consecutive views must be closer together than the neighbour
   window, or a view has nothing to triangulate against and is skipped outright. 12 views around a
   subject (30° apart) works; 8 views (45°) does not — the pipeline reports this rather than
   guessing.
2. **Fill the frame.** Depth error scales directly with millimetres-per-pixel. A subject occupying a
   quarter of a 512px frame is the difference between a recognisable reconstruction and a lumpy
   shell.
3. **Two elevations, not one.** A single orbit ring leaves the top and underside unconstrained.
4. **A background helps pose estimation and hurts nothing.** This is the one requirement that pulls in
   two directions, so it is worth stating plainly: MVS wants the subject cleanly separated, while SfM
   needs image features to recover pose from — and a featureless backdrop gives it none. Shoot against
   an ordinary textured background and supply a `<view>_mask.png` per view (from a segmentation model,
   or a lightbox shot of the same setup). Both halves then get what they need. Without a mask the
   subject is separated by a dark-backdrop threshold instead, and the run report says how many views
   relied on that.
5. **Enough texture for the detector.** Under `--sfm`, pose comes from matched SIFT features, and a
   smooth low-texture subject in a small frame does not produce them: a 512px synthetic fixture of a
   CG head yielded only ~400 keypoints per view where a real photograph yields five to twenty thousand.
   Resolution and surface texture are what move that number.
6. **Fixed focus and exposure.** ZNCC tolerates a gain difference; it does not tolerate the subject
   changing size between frames.

### Scale is arbitrary under `--sfm`

Structure from motion cannot recover absolute size — a doll photographed close and a statue
photographed far produce identical image evidence. So under `--sfm` you must supply one real
dimension:

```bash
--scale-longest 0.26      # the subject's longest real extent, in metres
```

That scales the **cameras**, not just the output cloud, so the depth range, the sweep, the fusion
voxel and `--cell` all end up in real millimetres. Omit it and the run still completes, but it is
**not metric**: `--cell 0.0015` then means 1.5 arbitrary units, and the orchestrator says so on every
run rather than letting a wrong figure reach a gate that trusts it.

For scoring an unscaled reconstruction, `verify_reconstruction.py --align-similarity` fits scale and
pose before measuring, so its numbers describe **shape only** and say nothing about size.

## What's here

- `python/cameras.py` — the single pinhole convention every other module imports. Round-trip verified
  to float64 epsilon.
- `python/sfm_poses.py` — COLMAP sparse SfM; drops unregistered views rather than inventing poses.
- `python/dense_mvs.py` — plane-sweep ZNCC and the cross-view consistency filter.
- `python/fuse_cloud.py` — depth maps → oriented, voxel-averaged cloud. See `pca_normals` for why
  normal *direction* and normal *sign* come from two different sources.
- `python/photos_to_cloud.py` — the whole front end as one command.
- `photos-to-surface.sh` — chains that onto `build_head_surface.py` via the seam.

Validation-only, never read by the pipeline:

- `python/glb_mesh.py`, `python/rasterise.py`, `python/render_views.py` — manufacture a multi-view
  fixture with known cameras and ground-truth depth from a real textured mesh, so accuracy can be
  measured against geometry the pipeline never saw.
- `python/verify_reconstruction.py` — scores accuracy **and** completeness. Reporting one without the
  other is the standard way an MVS result is made to look better than it is.

## Verify

```bash
IMG2THREEJS_SHOWCASE_ROOT=/path/to/showcase \
  python3 -m unittest discover -s integrations/photogrammetry_surface/tests -p 'test_*.py'
```

Runs on the ambient stdlib interpreter: every numpy-dependent step is executed in a subprocess under
the integration's own venv, so the test does not skip on the interpreter `forge/tests` actually uses.
