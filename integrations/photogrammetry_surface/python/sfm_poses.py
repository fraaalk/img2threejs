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

There is currently NO command-line flag that fixes it. `rescale()` below computes the factor from one
known real dimension, and nothing calls it yet: a caller has to apply it to the cloud itself. Said
plainly rather than implied, because a docstring that advertises a `--scale-longest` option which does
not exist is worse than one that admits the gap -- and this docstring did exactly that until the flag
was looked for and found missing. Until a caller wires it up, treat every millimetre figure derived
from an `--sfm` run as being in arbitrary units.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cameras import Camera  # noqa: E402

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def _intrinsics_from_colmap(camera) -> np.ndarray:
    """K from any of COLMAP's pinhole-family models; anything else is refused rather than guessed."""
    model = camera.model.name if hasattr(camera.model, "name") else str(camera.model)
    p = list(camera.params)
    if model in ("SIMPLE_PINHOLE", "SIMPLE_RADIAL", "RADIAL"):
        f, cx, cy = p[0], p[1], p[2]
        fx = fy = f
    elif model in ("PINHOLE", "OPENCV", "FULL_OPENCV", "OPENCV_FISHEYE"):
        fx, fy, cx, cy = p[0], p[1], p[2], p[3]
    else:
        raise SystemExit(f"unhandled COLMAP camera model {model!r}; re-run with a pinhole model")
    return np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]])


def estimate_poses(image_dir: Path, work_dir: Path, camera_model: str = "SIMPLE_RADIAL",
                   reuse: bool = True) -> list[Camera]:
    """Run COLMAP feature extraction, matching and incremental mapping. Returns registered cameras.

    Views COLMAP fails to register are DROPPED and reported, never silently given a made-up pose: an
    unregistered image is one the geometry could not explain, and inventing a pose for it would put
    its pixels somewhere wrong in every later stage.
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
        reader.camera_model = camera_model
        pycolmap.extract_features(database, image_dir, reader_options=reader)
        print("  COLMAP: exhaustive matching")
        pycolmap.match_exhaustive(database)
    else:
        print(f"  COLMAP: reusing {database}")

    sparse.mkdir(parents=True, exist_ok=True)
    existing = [d for d in sorted(sparse.iterdir()) if d.is_dir()] if sparse.exists() else []
    if not existing:
        print("  COLMAP: incremental mapping")
        maps = pycolmap.incremental_mapping(database, image_dir, sparse)
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


def rescale(cams: list[Camera], points: np.ndarray, longest_edge_metres: float) -> float:
    """Scale factor putting the reconstruction into metres, from one known real dimension.

    Applied to the CLOUD, not the cameras, by the caller -- and returned rather than applied here so
    the number appears in the run report. A reconstruction whose scale nobody set is not metric, and
    every millimetre figure computed from it is decoration.
    """
    if len(points) == 0:
        raise SystemExit("no sparse points to measure; cannot set scale")
    lo = np.percentile(points, 1, axis=0)
    hi = np.percentile(points, 99, axis=0)
    longest = float(np.max(hi - lo))
    if longest <= 0:
        raise SystemExit("degenerate sparse cloud; cannot set scale")
    return longest_edge_metres / longest
