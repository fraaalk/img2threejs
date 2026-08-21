# Photogrammetry surface pipeline

How multi-view photographs become the same oriented point cloud a GLB baseline would produce, and
what that cloud is actually worth. Every number here was measured on a reproducible fixture, against
ground truth the pipeline never read.

`README.md` covers install and capture requirements. This document covers the method, the measured
quality, and the limits.

## The idea this rests on

`build_head_surface.py` needs exactly two arrays: oriented points `P` and unit normals `N`. Its GLB
reader is 16 lines at the top; the 120 lines below it — splat, field, Surface Nets, quad emission —
never knew where the points came from.

So the photo route does not reimplement reconstruction. It produces `(P, N)` and hands them to the
existing code through `CHARACTER_CLOUD_NPZ`.

**This equivalence is tested, not claimed.** `tests/test_cloud_seam.py` extracts the GLB's own cloud,
writes it to an `.npz`, feeds it back through the env var, and requires `np.array_equal` on both the
vertex and triangle arrays against the GLB route's output. It passes: 356,243 vertices and 713,012
triangles, byte for byte identical, at the shipped cell size. If that ever stops holding, the photo
route is running a different reconstruction and every comparison in this document is void.

## Stage 1 — Poses

`python/sfm_poses.py`, COLMAP incremental SfM: features, exhaustive matching, incremental mapping.
Recovers intrinsics, per-view poses and a sparse cloud from images alone.

Views COLMAP cannot register are **dropped and reported**, never given an invented pose. An
unregistered image is one the geometry could not explain; placing it anyway puts its pixels somewhere
wrong in every later stage, and the resulting surface defect looks like an MVS problem rather than a
pose problem.

### What registration actually depends on

This stage is where the fixture had to change to test anything, and the numbers are worth keeping
because they are the same numbers that decide whether a real capture works:

| Fixture | keypoints/view | verified pairs | registered | pose error vs truth |
|---|---|---|---|---|
| black background | 414 | 68 / 276 | 3 / 24 | — |
| + mask files wrongly indexed as views | 406 | 68 / 276 | 3 / 24 | — |
| + blocky-noise backdrop | 197 | 69 / 276 | 7 / 24 | — |
| + smooth but blurry backdrop | 175 | 68 / 276 | 3 / 24 | — |
| + sharp **tiled** backdrop | 861 | 276 / 276 | 24 / 24 | **34%** — see below |
| + unique high-res backdrop | 405 | 68 / 276 | 10 / 24 | **0.12%** |
| **+ retuned noise spectrum** | **4,411** | 77 / 276 | **24 / 24** | **0.01%** |

Read rows five and six together: the tiled fixture registered everything and got the geometry badly
wrong, while the unique one registered less than half and got it essentially exactly right. The
registration count and the accuracy moved in *opposite* directions, which is why the rightmost column
exists at all.

The last row gets both, and the difference is only the noise SPECTRUM. Unique texture is what makes the
poses correct; putting the contrast at the few-pixel scale is what makes them findable. Starting the
octaves high with a shallow falloff (base 128, 4 octaves, 0.9) rather than low with a steep one
(base 4, 9 octaves, 0.65) carries about ten times the fine-detail gradient energy at the same global
contrast, and took keypoints from 405 to 4,411 per view. All eleven consecutive view angles then read
exactly 30.0.

### "24/24 registered" is not the same as "the poses are right"

The single most deceptive result in this whole exercise. With a **tiled** backdrop texture, COLMAP
registered all 24 views, verified all 276 pairs, and found 33,500 inliers — every self-reported signal
said success. Compared against the fixture's known poses, the recovered camera centres sat a median
**526 mm off on a 1544 mm ring (34%)**, and the angle between consecutive views came out in a
repeating `28.0 / 56.2 / 28.2` pattern where every one should have been `30.0`.

Repeating texture is the cause: a tiled backdrop presents many identical-looking patches, matches
become ambiguous, and the reconstruction settles into a confidently wrong configuration whose error is
periodic with the tiling. Making the texture unique took the pose residual from 34% to **0.12%**
(1.23 mm), with consecutive angles at 29.9 / 29.8 / 30.1 / 29.8.

Two things follow, and the second is the general one:

- **Never tile a photogrammetry target's texture.** Random-dot and speckle patterns are used in
  practice precisely because they are unique.
- **Registration counts, inlier counts and reprojection error cannot detect this.** They are all
  measures of internal consistency, and an ambiguous-match reconstruction is internally consistent.
  Only a comparison against independently known geometry exposes it — which is the entire argument for
  keeping a fixture with ground-truth poses rather than trusting the solver's own report.

An intermediate hypothesis is worth recording as *disproved*: the wrong poses came with a focal length
36% low (567.7 against a true 892.8) and a fitted `k1 = -0.088` on distortion-free renders, which
looked like classic focal/depth ambiguity. Pinning the intrinsics changed the pose residual from
526 mm to 532 mm — nothing. The distortion was a symptom of the bad matches, not the cause.

### Three further lessons, each of which cost a run to learn:

- **A featureless background makes SfM impossible, not merely harder.** MVS wants the subject cleanly
  separated and a black backdrop gives that for free; SfM recovers pose from image features and a black
  backdrop gives it none. The two halves of the pipeline want opposite things from the background, and
  the resolution is a textured background plus explicit masks.
- **Texture has to be the right kind.** Blocky noise is worse than useless: its only structure is
  axis-aligned straight edges, and SIFT deliberately rejects edge responses in favour of blob-like
  extrema. Blurry noise fails for the opposite reason — no structure at any scale the detector keys on.
  Only sharp, multi-scale, blob-rich texture moved the count.
- **`extract_features` globs the directory unless told otherwise.** The fixture writes
  `<view>_mask.png` next to each view, and COLMAP indexed all 48 files, tried to register 24
  silhouettes, and reported nothing unusual. Passing `image_names` explicitly is the fix; filtering
  only the list used for the printed count is not.

**Scale is arbitrary here and that has consequences.** SfM from images cannot recover absolute size.
Until the scale is set from one known real dimension, a `--cell 0.0015` is not 1.5 mm of subject — it
is 1.5 units of an arbitrary reconstruction. Every millimetre figure downstream inherits that.

## Stage 2 — Dense depth

`python/dense_mvs.py`, plane-sweep ZNCC. Real photometric stereo: depth comes from agreement between
actual pixels across calibrated views.

COLMAP's own dense stage is unavailable rather than unchosen. `pycolmap.patch_match_stereo` raises
`Dense stereo reconstruction requires CUDA, which is not available on your system`, and
`pycolmap.has_cuda` is `False` on Apple Silicon. Sparse SfM is CPU-fine, dense is not, so the dense
half is this module.

Four choices carry the quality, each for a stated reason:

- **Inverse-depth planes.** Disparity is linear in `1/z`, so uniform depth planes oversample the far
  field and starve the near.
- **ZNCC, not SSD.** ZNCC is invariant to per-view gain and offset, so a frame a stop brighter still
  matches instead of being scored as a mismatch and deleted.
- **Top-k neighbour aggregation, not the mean.** A surface point is occluded in some views; the mean
  lets one occluded view veto a depth the others agree on. `k=2` by default.
- **Neighbour angle bounded at both ends.** Below ~4° triangulation is ill-conditioned; above ~40°
  the two windows no longer describe the same patch and ZNCC collapses. Views spaced wider than the
  upper bound leave a reference view with nothing to match against, and it is skipped with an
  actionable message rather than silently producing noise. This is a real capture constraint: 8 views
  around a subject (45° apart) fails; 12 (30°) works.

### Measured: the full SfM route, end to end

24 views at 512px with a textured backdrop and supplied masks, poses from COLMAP (validated at 0.01%
against known poses), scale from `--scale-longest 0.2596`:

| | SfM route | known-pose route |
|---|---|---|
| points | 168,409 | 180,333 |
| accuracy median (after alignment) | 5.40 mm | 1.24 mm |
| completeness median | 9.01 mm | 2.40 mm |
| normal error median | 30.1° | 14.3° |

**Do not read that gap as the cost of estimating poses.** The two runs differ in the *background* as
well as the pose source — the SfM fixture needs a textured backdrop, the known-pose one used black —
and there is a known defect that makes exactly that difference matter:

**The subject mask restricts the OUTPUT but not the correlation window.** `sweep_depth` zeroes depth
and confidence outside `masks[ref]`, but the ZNCC window itself is computed over raw pixels. Within
half a window of the silhouette, that window straddles subject and backdrop, and the backdrop sits at a
completely different depth — so those windows cannot match consistently in any view. On a black
backdrop this was harmless (no variance to inject, and the `support` test absorbed it); against a
textured backdrop it actively feeds in wrong signal. Making the window mask-aware is the obvious next
step and is **not implemented**.

So the honest statement is: the SfM route is measured at 5.40 mm on a fixture that also carries this
defect, and how much of the gap is pose estimation versus the unmasked window is **not yet separated**.
Running the known-pose route on the *same* textured-backdrop fixture would separate them, and has not
been done.

**Also note the scale bias.** `--scale-longest` measures the extent of the *sparse* subject points, and
sparse features cluster where texture is (hair, edges) rather than spanning the whole subject. Here the
sparse subject spanned 1.588 units where the true extent implied more, so the factor came out high and
the reconstruction ended ~19% too large — visible as the similarity alignment fitting 0.8366 rather
than 1.000. A run scored without `--align-similarity` therefore reports metres of error (1446 mm here)
purely because SfM's world frame is arbitrary; the raw comparison is meaningless for an SfM run, which
is what the alignment flag exists for.

## Stage 3 — Cross-view consistency

The single largest quality lever. Photometric agreement alone accepts a wrong depth wherever texture
repeats — hair, weave, any periodic pattern. A depth survives only if other views, reconstructed
independently, place the same surface in the same spot: project into view *n*, read *n*'s **own**
depth there, back-project, and require the round trip to land within a tolerance scaled to distance.

Measured on the 512px fixture: this discards **45–58% of the depths that passed the confidence
threshold**, per view. That is the filter doing its job, not a defect.

## Stage 4 — Fusion, denoising and normals

`python/fuse_cloud.py`, in this order, and the order is load-bearing:

1. **Back-project and voxel-average** at half the reconstruction cell. Every surface patch is seen by
   several views, so averaging within a voxel cancels independent per-view noise — noise the splat
   would otherwise smear straight into the field.
2. **Drop outliers** (`--outlier-sigma`, default 1.0): points whose mean gap to their 16 nearest
   neighbours exceeds the cloud's own mean + σ. An MVS outlier is not a point misplaced *on* the
   surface, it is one floating off it, and those are precisely the points a contour then wraps an
   isolated speck of shell around. Before MLS, so an outlier cannot drag a plane fit off the surface.
3. **MLS projection** (`--mls-iterations`, default 1): move each point onto its own local plane fit.
   This is the highest-value cleanup in the module because it targets exactly the error MVS leaves —
   noise *perpendicular* to the surface. Points move only along their local normal, so the surface is
   denoised without being smeared sideways.

   **One pass, not two.** On an analytic sphere (100 mm radius, 1 mm noise, k=24) one pass leaves
   0.173 mm of noise and 0.11 mm of shrinkage; two passes give 0.356 mm and 0.36 mm — worse on both.
   The second pass re-fits an already-smoothed surface, so it compounds the bias while the noise it
   was meant to remove is already gone.

   A quadratic fit was implemented to remove the residual shrinkage and **measured identically to the
   plane** (bias −0.111 vs −0.112 mm, noise 0.173 mm both), so it was removed rather than kept. The
   theory behind it was wrong at this neighbourhood size: the chord-versus-arc sagitta at k=24 over a
   100 mm radius is about 0.02 mm, an order below the observed bias. The bias comes from anchoring the
   fit at the neighbourhood mean, which on a noisy curved patch sits slightly inside the surface — and
   a quadric through the same noisy points inherits it. Recorded here because the figure that
   originally justified the quadric (0.38 mm) was planar MLS at *two* iterations, not one; comparing
   against the wrong baseline is what made a pointless option look like a fix.
4. **Estimate normals** last, on the already-flattened cloud, which gives a markedly better direction
   than fitting to the raw one.

Measured contribution of steps 2–3 on the 1024px fixture:

| | points | accuracy median | accuracy <2 mm |
|---|---|---|---|
| voxel-averaged only | 216,210 | 1.04 mm | 95.1% |
| + outlier removal | 202,259 | 1.03 mm | 95.7% |
| **+ MLS ×1** | 202,259 | **0.90 mm** | **98.0%** |
| + MLS ×2 | 202,259 | 0.86 mm | 98.3% |

Note the tension in the last two rows: on this fixture two passes score slightly *better* on
accuracy-to-truth, while on the analytic sphere two passes are clearly worse on both noise and
shrinkage. The sphere is the controlled measurement — it separates noise from bias, which a
distance-to-truth median cannot — so the default follows it. A 0.04 mm accuracy gain is not worth an
uncontrolled shrinkage that lands on exactly the millimetre-scale features the reconstruction exists
to recover.

**Normals are where this pipeline nearly failed, and the fix was measured.** The splat is *oriented*:
it accumulates `(cell − point) · normal`, so the field's sign comes entirely from the normal. A wrong
normal does not roughen the surface, it inverts it.

On the 512px fixture, where the effect is largest:

| Normal source | median error | within 15° | within 30° |
|---|---|---|---|
| depth-map gradient | 34.0° | 14.4% | 42.8% |
| local PCA, k=20 | 33.2° | 16.2% | 44.5% |
| local PCA, k=48 | 23.6° | 28.6% | 62.5% |
| local PCA, k=96 | 16.1° | 46.4% | 79.5% |
| **local PCA, k=128** | **13.5°** | **55.5%** | **85.5%** |

Note what `k` is really buying: with fixed point noise, a wider neighbourhood averages more of it
away, so this column is a noise-vs-feature-size trade, not a free improvement. It is also why the
same estimator reaches 6.2° on the 1024px fixture at a *smaller* k — less input noise to average.

The depth-gradient estimate is arithmetically doomed: MVS depth carries about a millimetre of noise,
and a central difference over two pixels spans about a millimetre of surface, so the gradient is as
much noise as signal. A plane fitted to the fused neighbourhood averages that noise across views and
recovers direction — but the smallest eigenvector is a **line**, not a ray, so it cannot supply the
sign. The depth-map normal, useless as a direction, is reliably on the correct *side*, because it was
forced to face the camera that saw it.

So: **direction from PCA, sign from the depth normal.** Each source used only for the half it is good
at. `--pca-k` defaults to 128 because that is what the table above measured, not because it is round.

## Measured quality

Fixture: node 9 of `girl-character-baseline.glb` (a textured head, 83,930 vertices, 129,634
triangles), rendered to 24 views at 512² across two elevation rings by `python/render_views.py`. The
pipeline received the PNGs and camera poses and nothing else.

### Cloud, against the mesh it never saw

Two fixtures, differing only in image resolution and framing. This is the single most important table
in the document, because the difference between the rows is not a tuning choice — it is how much
information the input images carry.

| | 512px, subject ~25% of frame | 1024px, subject ~50% of frame |
|---|---|---|
| accuracy median | 1.36 mm | **1.04 mm** |
| accuracy p90 | 2.52 mm | **1.75 mm** |
| accuracy under 2 mm | 78.5% | **95.2%** |
| completeness median | 1.76 mm | **1.29 mm** |
| completeness p90 | 10.40 mm | 8.45 mm |
| **normal error median** | 13.5° | **6.2°** |
| **normals within 15°** | 55.5% | **85.6%** |

Extent came out within 1% on all three axes at 512px (`[1.007, 0.989, 1.002]` of truth) and within 5%
at 1024px, so scale and framing are right in both. Completeness p90 stays high in both because it is
measuring occlusion, not precision: the tail is true surface no pair of views ever saw, and no amount
of resolution fixes that.

Adding the Stage 4 denoising to the 1024px run takes accuracy to **0.90 mm median, 98.0% within
2 mm** (table above).

### Surface, through the shared reconstruction

| Route | accuracy median | completeness median | completeness <2 mm |
|---|---|---|---|
| GLB (cell 1.2 mm) — the ceiling | 1.68 mm | 0.43 mm | 100% |
| photo (cell 1.5 mm) | 2.49 mm | 1.14 mm | 75.8% |
| photo (cell 2.5 mm) | 3.71 mm | 1.42 mm | 70.7% |

Note the ceiling is not zero: the GLB route scores 1.68 mm on accuracy because a voxel contour at
1.2 mm quantises to about that. The photo route is roughly 1.5× looser and misses about a quarter of
the surface.

### The honest part: it does not yet look like a face

**The metrics above are not the whole story, and a visual check contradicted them.** Rendered side by
side against the GLB route, the photo-derived surface reads as a lumpy, hole-riddled shell with the
correct silhouette and volume but no recoverable facial features. Median accuracy of 2.49 mm was
consistent with that and did not reveal it. This is exactly the failure mode the project's own visual
gate exists to catch, and it caught it.

Raising the splat radius (`CHARACTER_SPLAT_RADIUS_CELLS`, default 2.5, which suits a clean
mesh-sampled cloud) to 5–8 cells closes most of the holes and smooths the speckle, at the cost of
detail — the shell becomes solid but the features do not return. Coarsening the cell does not help
either; the noise is at the same scale as the features.

**The limit is depth precision, and it is resolution-bound.** At 512² with the head filling about a
quarter of the frame, one pixel is roughly a millimetre of subject, so a one-pixel matching error is
a one-millimetre depth error — which is exactly the 1.36 mm accuracy measured. Facial relief on this
subject is 1–2 mm (the eyelid margin the GLB pipeline sizes its 1.5 mm cell around), so the signal and
the noise are the same size. No amount of filtering separates them; the input has to carry more
information.

What that implies for capture, in order of leverage: **fill the frame** and **shoot at higher
resolution**, then add planes (`--planes`) to match the finer disparity, then more views. The
`--fov` used when framing matters as much as the megapixel count.

## Limits that are structural, not tuning

- **Occluded surface is not reconstructed.** MVS reports what at least two views saw. The inside of a
  mouth, the scalp under hair, a deep concavity — no view, no surface. The completeness p90 is where
  this shows up.
- **Untextured regions carry no signal.** ZNCC needs local variation. A uniform matte surface gives a
  flat cost profile at every depth, which the confidence measure correctly scores near zero and the
  consistency filter then discards.
- **Scale is not metric without an external dimension** (see Stage 1).
- **The subject must be rigid and unchanged across views.** Anything that moves between frames
  triangulates to a wrong depth with high photometric confidence, which is the worst combination.

## Reproducing every number above

Write fixtures somewhere durable, **not `/tmp`**. A 24-view 1024px run costs about 1h45m of CPU and
the whole set was lost once to a `/tmp` sweep at a date rollover, which meant re-measuring rather than
re-reading. Use a work directory inside the repo's own ignored scratch space, or anywhere you would be
willing to keep a build artifact.

```bash
cd integrations/photogrammetry_surface
WORK=work/mvs-fixture       # anywhere durable; NOT /tmp

# 1. manufacture the fixture (validation only; the pipeline never reads its ground truth)
uv run --project . python3 python/render_views.py \
  --glb $IMG2THREEJS_SHOWCASE_ROOT/public/mesh/girl-character-baseline.glb \
  --node 9 --out "$WORK" --views 12 --size 512 --elevations 0,20

# 2. images -> cloud
uv run --project . python3 python/photos_to_cloud.py \
  --images "$WORK" --cameras "$WORK/cameras.json" \
  --out "$WORK/cloud.npz" --cell 0.0015 --planes 96 --report "$WORK/report.json"

# 3. score the cloud against the mesh it never saw
uv run --project . python3 python/verify_reconstruction.py \
  --cloud "$WORK/cloud.npz" \
  --glb $IMG2THREEJS_SHOWCASE_ROOT/public/mesh/girl-character-baseline.glb --node 9

# 4. cloud -> surface, through the shared reconstruction
CHARACTER_CLOUD_NPZ="$WORK/cloud.npz" CHARACTER_SPLAT_RADIUS_CELLS=6 \
CHARACTER_WORKDIR="$WORK/surface" \
  uv run --project ../glb_character_pipeline python3 \
  ../glb_character_pipeline/python/build_head_surface.py 9 0.0015
```

Step 3's two numbers must always be read together. Accuracy alone rewards a pipeline that
reconstructed one ear very well; completeness alone rewards one that filled the volume with noise.
