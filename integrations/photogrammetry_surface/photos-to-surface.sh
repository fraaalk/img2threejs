#!/usr/bin/env bash
# Multi-view photographs -> a Surface Nets surface, with no GLB anywhere in the chain.
#
# This chains the photogrammetry front end onto the reconstruction that already exists:
#
#   photos ──► [this integration] ──► cloud.npz (P, N) ──► glb_character_pipeline's
#                                                          build_head_surface.py ──► V/T
#
# The seam is `CHARACTER_CLOUD_NPZ`, and it is the same code path a GLB takes. That equivalence is
# tested, not assumed: tests/test_cloud_seam.py feeds a GLB's own cloud through the env var and
# requires the surface to come out byte-identical to the GLB route's.
#
# Usage:
#   IMG2THREEJS_SHOWCASE_ROOT=/path/to/showcase \
#     photos-to-surface.sh --images DIR --out-dir DIR [--cameras FILE | --sfm]
#                          [--cell 0.0015] [--splat-radius 6] [--planes 96] [--verify-glb FILE --verify-node N]
#
#   --cameras FILE   poses are already known (a rendered fixture, or a calibrated rig)
#   --sfm            estimate poses from the images with COLMAP; scale is then arbitrary (see below)
#   --splat-radius   splat radius in cells. The GLB route's 2.5 assumes a clean mesh-sampled cloud;
#                    a photogrammetry cloud carries real per-point error and needs more averaging.
#   --verify-glb     score the result against a GLB the pipeline never read (validation only)
set -euo pipefail

PKG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GLB_PIPELINE="$(cd "$PKG_DIR/../glb_character_pipeline" && pwd)"

IMAGES=""; OUT_DIR=""; CAMERAS=""; USE_SFM=0
CELL="0.0015"; SPLAT_RADIUS="6"; PLANES="96"; VERIFY_GLB=""; VERIFY_NODE=""
EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    --images) IMAGES="$2"; shift 2 ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    --cameras) CAMERAS="$2"; shift 2 ;;
    --sfm) USE_SFM=1; shift ;;
    --cell) CELL="$2"; shift 2 ;;
    --splat-radius) SPLAT_RADIUS="$2"; shift 2 ;;
    --planes) PLANES="$2"; shift 2 ;;
    --verify-glb) VERIFY_GLB="$2"; shift 2 ;;
    --verify-node) VERIFY_NODE="$2"; shift 2 ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

if [ -z "$IMAGES" ] || [ -z "$OUT_DIR" ]; then
  echo "usage: photos-to-surface.sh --images DIR --out-dir DIR [--cameras FILE | --sfm]" >&2
  exit 1
fi
if [ -z "$CAMERAS" ] && [ "$USE_SFM" -eq 0 ]; then
  echo "pass --cameras FILE (known poses) or --sfm (estimate them from the images)" >&2
  exit 1
fi

PY="${IMG2THREEJS_PHOTOGRAMMETRY_PYTHON:-uv run --project $PKG_DIR python3}"
GLB_PY="${IMG2THREEJS_GLB_PIPELINE_PYTHON:-uv run --project $GLB_PIPELINE python3}"
mkdir -p "$OUT_DIR"

echo "== Stage A: images -> oriented point cloud =="
POSE_ARGS=()
if [ "$USE_SFM" -eq 1 ]; then
  POSE_ARGS+=(--sfm --sfm-work "$OUT_DIR/sfm")
  echo "  poses: COLMAP SfM. NOTE: scale from images alone is ARBITRARY -- a --cell in millimetres"
  echo "  means nothing against an unscaled reconstruction. Set the scale from a known dimension"
  echo "  before trusting any millimetre figure downstream."
else
  POSE_ARGS+=(--cameras "$CAMERAS")
fi
# shellcheck disable=SC2086
$PY "$PKG_DIR/python/photos_to_cloud.py" \
  --images "$IMAGES" "${POSE_ARGS[@]}" \
  --out "$OUT_DIR/cloud.npz" --cell "$CELL" --planes "$PLANES" \
  --report "$OUT_DIR/cloud-report.json" "${EXTRA[@]+"${EXTRA[@]}"}"

echo
echo "== Stage B: cloud -> surface, through the EXISTING Surface Nets reconstruction =="
echo "  (build_head_surface.py, splat radius ${SPLAT_RADIUS} cells)"
# shellcheck disable=SC2086
CHARACTER_CLOUD_NPZ="$OUT_DIR/cloud.npz" \
CHARACTER_SPLAT_RADIUS_CELLS="$SPLAT_RADIUS" \
CHARACTER_WORKDIR="$OUT_DIR/surface" \
  $GLB_PY "$GLB_PIPELINE/python/build_head_surface.py" 0 "$CELL"

if [ -n "$VERIFY_GLB" ]; then
  if [ -z "$VERIFY_NODE" ]; then
    echo "--verify-glb needs --verify-node" >&2
    exit 1
  fi
  echo
  echo "== Validation: score against a GLB the pipeline never read =="
  # shellcheck disable=SC2086
  $PY "$PKG_DIR/python/verify_reconstruction.py" \
    --cloud "$OUT_DIR/cloud.npz" --glb "$VERIFY_GLB" --node "$VERIFY_NODE" \
    --json "$OUT_DIR/accuracy.json"
fi

echo
echo "Done."
echo "  cloud   $OUT_DIR/cloud.npz"
echo "  surface $OUT_DIR/surface/{V,T,cloud}.npy"
echo
echo "READ PIPELINE.md's 'Measured quality' section before treating this surface as finished: on the"
echo "reference fixture the photo route lands well short of the GLB route, and the limit is the depth"
echo "precision the input images can support, not the plumbing."
