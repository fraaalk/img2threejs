"""Camera poses from unordered photographs, via COLMAP's sparse SfM (CPU).

WHAT THIS DOES AND DOES NOT PROVIDE. COLMAP's incremental mapper gives intrinsics, poses and a sparse
point cloud from images alone. That is the hard, well-solved half of photogrammetry and it runs fine
on the CPU. Its DENSE half does not: `pycolmap.patch_match_stereo` raises
`Dense stereo reconstruction requires CUDA, which is not available on your system` on any machine
without an NVIDIA GPU, and `pycolmap.has_cuda` is False here. Dense reconstruction is therefore
dense_mvs.py's job, and this module stops at poses.

SCALE IS ARBITRARY, AND THAT MATTERS DOWNSTREAM. SfM from images alone cannot know absolute size --
a doll photographed close and a statue photographed far give identical image evidence. The
reconstruction comes out in an arbitrary unit, so a cell size in millimetres means nothing against it
until the scale is fixed.

`photos_to_cloud.py --scale-longest <metres>` fixes it, via `rescale()` below. It scales the CAMERAS
rather than the output cloud, so every downstream quantity derived from camera geometry -- the depth
range, the sweep, the fusion voxel, `--cell` itself -- lands in real units too; scaling only the final
cloud would leave every intermediate in SfM units and the millimetre-denominated parameters
meaningless. Without the flag a run still completes and is self-consistent, but is NOT metric, and
`photos_to_cloud` says so on every such run.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cameras import Camera  # noqa: E402

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


MAX_IGNORED_DISTORTION = 0.005


def _intrinsics_from_colmap(camera) -> np.ndarray:
    """K from a COLMAP camera, REFUSING any model whose distortion this pipeline cannot honour.

    THE WHOLE PIPELINE IS AN UNDISTORTED PINHOLE. `cameras.py` projects with K alone, so any radial or
    tangential coefficient COLMAP fitted is simply discarded -- and a discarded distortion term is not a
    small error. It means the sweep reprojects every pixel to a slightly wrong place in every neighbour
    view, ZNCC stops agreeing, and the depth maps come back nearly empty. Measured on the reference
    fixture: COLMAP fitted `k1 = -0.088` on renders that carry no distortion at all, and the sweep
    produced 2,107 points where the known-pose route produced 292,640.

    So the extra parameters are checked rather than dropped. A fitted distortion is a signal the
    intrinsics are badly constrained (COLMAP absorbs focal-length error into k1), which is worth
    stopping for on its own.
    """
    model = camera.model.name if hasattr(camera.model, "name") else str(camera.model)
    p = list(camera.params)
    if model == "SIMPLE_PINHOLE":
        fx = fy = p[0]
        cx, cy = p[1], p[2]
        extra: list[float] = []
    elif model in ("SIMPLE_RADIAL", "RADIAL"):
        fx = fy = p[0]
        cx, cy = p[1], p[2]
        extra = p[3:]
    elif model == "PINHOLE":
        fx, fy, cx, cy = p[0], p[1], p[2], p[3]
        extra = []
    elif model in ("OPENCV", "FULL_OPENCV", "OPENCV_FISHEYE"):
        fx, fy, cx, cy = p[0], p[1], p[2], p[3]
        extra = p[4:]
    else:
        raise SystemExit(f"unhandled COLMAP camera model {model!r}; re-run with a pinhole model")

    worst = max((abs(v) for v in extra), default=0.0)
    if worst > MAX_IGNORED_DISTORTION:
        raise SystemExit(
            f"COLMAP fitted camera model {model!r} with distortion coefficients {extra}, the largest "
            f"|{worst:.4f}| exceeding the {MAX_IGNORED_DISTORTION} this pipeline can ignore. Every "
            f"stage downstream projects through K alone, so honouring only K would reproject every "
            f"pixel slightly wrong and the depth sweep would return almost nothing.\n"
            f"Fix by constraining the intrinsics instead of letting them absorb error: pass "
            f"--intrinsics 'f,cx,cy' (from EXIF, or the lens spec) so the focal length is not free.")
    return np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]])


def estimate_poses(image_dir: Path, work_dir: Path, camera_model: str = "PINHOLE",
                   reuse: bool = True, intrinsics: tuple[float, float, float] | None = None
                   ) -> list[Camera]:
    """Run COLMAP feature extraction, matching and incremental mapping. Returns registered cameras.

    Views COLMAP fails to register are DROPPED and reported, never silently given a made-up pose: an
    unregistered image is one the geometry could not explain, and inventing a pose for it would put
    its pixels somewhere wrong in every later stage.

    THE DEFAULT MODEL IS PINHOLE, deliberately, not COLMAP's own SIMPLE_RADIAL default. This pipeline
    projects through K alone, so a model with a distortion term can only ever fit a coefficient that
    then has to be discarded -- and `_intrinsics_from_colmap` now refuses to discard one, which would
    turn every default run into an error. Asking for the model the pipeline can actually honour is the
    coherent fix. On real photographs with genuine lens distortion this trades a little pose accuracy
    for consistency; undistorting the images up front would be the better answer and is not implemented.

    `intrinsics=(f, cx, cy)` pins the camera instead of letting bundle adjustment solve for it, and on a
    weakly-constrained scene that is the difference between a usable reconstruction and a warped one.
    Left free on the reference fixture, COLMAP settled on a focal length of 567.7 against a true 892.8
    -- 36% low -- and absorbed the mismatch into radial distortion. All 24 views still "registered",
    but their recovered centres sat a median 526 mm off the truth on a 1544 mm ring. Registration
    succeeding is not the same as the geometry being right, and only a comparison against known poses
    shows the difference. Supply the focal length from EXIF or the lens spec whenever it is known.
    """
    try:
        import pycolmap
    except ImportError as exc:
        raise SystemExit("pycolmap is required for --sfm; run "
                         "`uv sync --project integrations/photogrammetry_surface`") from exc

    images = sorted(p for p in Path(image_dir).iterdir()
                    if p.suffix.lower() in IMAGE_SUFFIXES and not p.stem.endswith("_mask"))
    if len(images) < 3:
        raise SystemExit(f"found {len(images)} images in {image_dir}; SfM needs at least 3")

    work_dir = Path(work_dir)
    database = work_dir / "database.db"
    sparse = work_dir / "sparse"
    if not reuse and work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    if not database.exists():
        print(f"  COLMAP: extracting features from {len(images)} images")
        # The camera model belongs to ImageReaderOptions, not to a keyword on extract_features, and
        # there is no `sift_options=` parameter in pycolmap 4.x. Both were assumed once and neither
        # exists -- which is why this path is exercised by an actual run rather than only read.
        reader = pycolmap.ImageReaderOptions()
        reader.camera_model = "PINHOLE" if intrinsics else camera_model
        if intrinsics:
            f, cx, cy = intrinsics
            # PINHOLE takes fx, fy, cx, cy and carries no distortion term -- so nothing can be fitted
            # that this pipeline would then have to discard.
            reader.camera_params = f"{f},{f},{cx},{cy}"
            print(f"  intrinsics pinned: f={f:.2f} cx={cx:.1f} cy={cy:.1f} (PINHOLE, no distortion)")
        # PASS THE FILE LIST, NOT JUST THE DIRECTORY. extract_features globs the directory when
        # image_names is empty, which silently swept up the 24 `<view>_mask.png` files a fixture writes
        # alongside its views: COLMAP indexed 48 images, half of them black-and-white silhouettes
        # yielding 7-56 keypoints, and the mapper then tried to register them. Filtering the list used
        # for the printed count is not enough -- COLMAP has to be told.
        pycolmap.extract_features(database, image_dir, image_names=[p.name for p in images],
                                  reader_options=reader)
        print("  COLMAP: exhaustive matching")
        pycolmap.match_exhaustive(database)
    else:
        print(f"  COLMAP: reusing {database}")

    sparse.mkdir(parents=True, exist_ok=True)
    existing = [d for d in sorted(sparse.iterdir()) if d.is_dir()] if sparse.exists() else []
    if not existing:
        print("  COLMAP: incremental mapping")
        options = pycolmap.IncrementalPipelineOptions()
        if intrinsics:
            # Pinning the intrinsics is pointless if bundle adjustment is then free to move them.
            options.ba_refine_focal_length = False
            options.ba_refine_principal_point = False
            options.ba_refine_extra_params = False
        maps = pycolmap.incremental_mapping(database, image_dir, sparse, options=options)
        if not maps:
            raise SystemExit("COLMAP registered no reconstruction; the views may not overlap enough")
        reconstruction = maps[0] if isinstance(maps, list) else maps[0]
    else:
        reconstruction = pycolmap.Reconstruction(existing[0])

    if hasattr(reconstruction, "num_reg_images"):
        registered = reconstruction.num_reg_images()
    else:
        registered = len(reconstruction.images)
    print(f"  COLMAP: {registered}/{len(images)} images registered, "
          f"{len(reconstruction.points3D):,} sparse points")
    if registered < len(images):
        print(f"  NOTE: {len(images) - registered} image(s) could not be registered and are dropped; "
              f"they are not given invented poses")

    cams: list[Camera] = []
    for image in reconstruction.images.values():
        has_pose = image.has_pose
        if callable(has_pose):
            has_pose = has_pose()
        if not has_pose:
            continue
        colmap_cam = reconstruction.cameras[image.camera_id]
        K = _intrinsics_from_colmap(colmap_cam)
        # `cam_from_world` is a METHOD on pycolmap 4.x, not a property. Reading it as an attribute
        # yields the bound method and fails on `.rotation` -- one of three API details in this file
        # that were assumed correct and were not, all three found by running it rather than reading it.
        rigid = image.cam_from_world() if callable(image.cam_from_world) else image.cam_from_world
        R = np.array(rigid.rotation.matrix(), dtype=np.float64)
        t = np.array(rigid.translation, dtype=np.float64)
        cams.append(Camera(K, R, t, colmap_cam.width, colmap_cam.height, Path(image.name).stem))

    cams.sort(key=lambda c: c.name)
    if len(cams) < 3:
        raise SystemExit(f"only {len(cams)} views carry a pose; not enough to reconstruct")
    return cams


def sparse_points(work_dir: Path) -> np.ndarray:
    """The sparse cloud, for depth-range bounds and scale checks. Empty array if unavailable."""
    try:
        import pycolmap
    except ImportError:
        return np.zeros((0, 3))
    sparse = Path(work_dir) / "sparse"
    dirs = [d for d in sorted(sparse.iterdir()) if d.is_dir()] if sparse.exists() else []
    if not dirs:
        return np.zeros((0, 3))
    reconstruction = pycolmap.Reconstruction(dirs[0])
    if not reconstruction.points3D:
        return np.zeros((0, 3))
    return np.array([p.xyz for p in reconstruction.points3D.values()], dtype=np.float64)


def rescale(cams: list[Camera], points: np.ndarray, longest_edge_metres: float,
            masks: list[np.ndarray] | None = None, min_consistency: float = 0.7,
            min_seen: int = 3) -> float:
    """Scale factor putting the reconstruction into metres, from the SUBJECT's known real dimension.

    MEASURING THE WHOLE SPARSE CLOUD IS WRONG, and wrong by an order of magnitude in the capture setup
    this pipeline recommends. SfM reconstructs everything it can see, and a textured background -- the
    thing that makes pose estimation work at all -- dominates the point count and the extent. Measured
    on the reference fixture: the full sparse cloud spanned 39.9 units against a subject of about 4, so
    dividing the subject's real size by the full extent produced a factor ten times too small and
    scaled the entire reconstruction to a tenth of life size. Everything downstream stayed
    self-consistent and every millimetre figure was silently a tenth of its true value.

    So the subject has to be isolated first, and MASK MEMBERSHIP ALONE DOES NOT DO IT. A background
    point directly behind the subject projects inside the subject's silhouette, so "inside the mask in
    a couple of views" keeps it: filtering that way kept 867 of 1195 points and left the extent at
    40.2 units, essentially unfiltered.

    What separates them is CONSISTENCY. A real subject point is inside the silhouette in nearly every
    view that sees it; a background point only lands inside by coincidence, from a few directions. So
    the test is the FRACTION of observing views that place the point inside the mask, and the measured
    behaviour is a cliff rather than a gradient:

        fraction >= 0.30  ->  678 points, extent 40.5     (still the backdrop)
        fraction >= 0.50  ->  595 points, extent 37.6     (still the backdrop)
        fraction >= 0.70  ->  514 points, extent  3.99    <- the subject
        fraction >= 0.85  ->  435 points, extent  3.95
        fraction >= 1.00  ->  203 points, extent  4.00

    The plateau from 0.70 upward is why 0.7 is a safe default: the answer does not depend delicately on
    the threshold. Without masks there is no way to tell subject from background at all, and this
    refuses rather than guessing -- a silent order-of-magnitude scale error is worse than a stop.
    """
    if len(points) == 0:
        raise SystemExit("no sparse points to measure; cannot set scale")

    if masks is None:
        raise SystemExit(
            "--scale-longest needs per-view subject masks to tell the subject apart from the "
            "background. SfM reconstructs the background too, and on the reference fixture it "
            "dominated the extent by 10x, which would scale the whole reconstruction to a tenth of "
            "life size. Supply <view>_mask.png files, or drop --scale-longest and accept a "
            "non-metric reconstruction.")

    inside = np.zeros(len(points), dtype=np.int32)
    seen = np.zeros(len(points), dtype=np.int32)
    for cam, mask in zip(cams, masks):
        uv, z = cam.project(points)
        u = np.round(uv[:, 0] - 0.5).astype(np.int64)
        v = np.round(uv[:, 1] - 0.5).astype(np.int64)
        visible = (z > 1e-9) & (u >= 0) & (u < cam.width) & (v >= 0) & (v < cam.height)
        seen += visible
        if visible.any():
            hit = np.zeros(len(points), dtype=bool)
            idx = np.nonzero(visible)[0]
            hit[idx] = mask[v[idx], u[idx]]
            inside += hit

    with np.errstate(invalid="ignore", divide="ignore"):
        consistency = inside / np.maximum(seen, 1)
    subject = (consistency >= min_consistency) & (seen >= min_seen)
    if subject.sum() < 8:
        raise SystemExit(
            f"only {int(subject.sum())} sparse point(s) sit inside the subject masks in "
            f"{min_consistency:.0%}+ of the views that see them; cannot measure the subject's extent. "
            f"Check that the masks correspond to the images and actually mark the subject.")

    lo = np.percentile(points[subject], 1, axis=0)
    hi = np.percentile(points[subject], 99, axis=0)
    longest = float(np.max(hi - lo))
    if longest <= 0:
        raise SystemExit("degenerate subject point set; cannot set scale")

    # Report the alternative so a wrong answer is visible rather than silent: if these two are close,
    # the masks are not separating anything and the scale is probably measuring the background.
    all_lo = np.percentile(points, 1, axis=0)
    all_hi = np.percentile(points, 99, axis=0)
    all_longest = float(np.max(all_hi - all_lo))
    print(f"  scale from {int(subject.sum())}/{len(points)} sparse points that are inside the subject "
          f"mask in >={min_consistency:.0%} of views")
    print(f"    subject extent {longest:.3f} SfM units vs whole-scene {all_longest:.3f}")
    if all_longest > 0 and longest / all_longest > 0.8:
        print(f"    WARNING: the subject spans {longest / all_longest:.0%} of the whole reconstruction. "
              f"Either the subject really does fill the scene, or the masks are not isolating it and "
              f"this scale is measuring the background.")
    return longest_edge_metres / longest
