"""Pinhole cameras, and the one convention every other module in this integration reads.

WHY THIS IS ITS OWN FILE. Multi-view geometry breaks silently when two modules disagree about a sign
or a multiplication order -- the reconstruction still runs and produces a plausible, wrong surface.
So the convention lives in exactly one place and everything imports it:

    x_cam = R @ x_world + t          (R world-to-camera, t the camera's translation in that frame)
    u = K @ x_cam, then divide by z  (pinhole, z forward, +x right, +y DOWN in image space)

Camera centre in world space is therefore `C = -R.T @ t`, and the viewing ray through pixel (u, v) is
`R.T @ (K^-1 @ [u, v, 1])`. The +y-down image convention matches how PIL, COLMAP and every raster
format index rows, so no module has to flip anything.

Pure numpy. No OpenCV: the three operations this needs are eight lines each, and a dependency whose
wheels differ per platform is not worth it for that.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class Camera:
    """One pinhole view: intrinsics, world-to-camera rotation/translation, image size."""

    __slots__ = ("K", "R", "t", "width", "height", "name")

    def __init__(self, K: np.ndarray, R: np.ndarray, t: np.ndarray,
                 width: int, height: int, name: str = ""):
        self.K = np.asarray(K, dtype=np.float64).reshape(3, 3)
        self.R = np.asarray(R, dtype=np.float64).reshape(3, 3)
        self.t = np.asarray(t, dtype=np.float64).reshape(3)
        self.width = int(width)
        self.height = int(height)
        self.name = name

    # -- derived quantities ------------------------------------------------------------------------
    @property
    def centre(self) -> np.ndarray:
        """Camera position in world space."""
        return -self.R.T @ self.t

    @property
    def forward(self) -> np.ndarray:
        """Unit viewing direction in world space (camera +z)."""
        return self.R.T @ np.array([0.0, 0.0, 1.0])

    def project(self, points_world: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """World points -> (pixel uv, camera-space depth z). Depth <= 0 means behind the camera."""
        pts = np.asarray(points_world, dtype=np.float64).reshape(-1, 3)
        cam = pts @ self.R.T + self.t
        z = cam[:, 2]
        safe = np.where(np.abs(z) > 1e-12, z, 1e-12)
        uv = (cam / safe[:, None]) @ self.K.T
        return uv[:, :2], z

    def rays(self) -> np.ndarray:
        """Unit world-space ray direction per pixel, shaped (height, width, 3)."""
        us, vs = np.meshgrid(np.arange(self.width) + 0.5,
                             np.arange(self.height) + 0.5, indexing="xy")
        homo = np.stack([us, vs, np.ones_like(us)], axis=-1)
        dirs_cam = homo @ np.linalg.inv(self.K).T
        dirs_world = dirs_cam @ self.R
        norm = np.linalg.norm(dirs_world, axis=-1, keepdims=True)
        return dirs_world / np.maximum(norm, 1e-12)

    def backproject(self, depth: np.ndarray) -> np.ndarray:
        """Per-pixel camera-space z (height, width) -> world points (height, width, 3).

        `depth` is z along the camera axis, not distance along the ray -- the same quantity
        `project()` returns, so a project/backproject round trip is exact rather than nearly exact.
        """
        depth = np.asarray(depth, dtype=np.float64)
        us, vs = np.meshgrid(np.arange(self.width) + 0.5,
                             np.arange(self.height) + 0.5, indexing="xy")
        homo = np.stack([us, vs, np.ones_like(us)], axis=-1)
        dirs_cam = homo @ np.linalg.inv(self.K).T           # z-component is exactly 1
        cam = dirs_cam * depth[..., None]
        return (cam - self.t) @ self.R

    # -- serialisation -----------------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "K": self.K.tolist(),
            "R": self.R.tolist(),
            "t": self.t.tolist(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Camera":
        return cls(np.array(data["K"]), np.array(data["R"]), np.array(data["t"]),
                   data["width"], data["height"], data.get("name", ""))


def look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray = (0.0, 1.0, 0.0)) -> tuple[np.ndarray, np.ndarray]:
    """World-to-camera (R, t) for a camera at `eye` looking at `target`.

    Returns the +y-DOWN image convention this module documents, so the result feeds `Camera`
    directly. Getting this wrong flips every reconstruction upside down while leaving every
    projection self-consistent, which is exactly the class of bug the single-convention rule exists
    to prevent.
    """
    eye = np.asarray(eye, dtype=np.float64).reshape(3)
    target = np.asarray(target, dtype=np.float64).reshape(3)
    up = np.asarray(up, dtype=np.float64).reshape(3)

    forward = target - eye
    forward /= np.maximum(np.linalg.norm(forward), 1e-12)
    if abs(float(forward @ (up / np.maximum(np.linalg.norm(up), 1e-12)))) > 0.999:
        raise ValueError("up vector is parallel to the viewing direction; pick another up")
    right = np.cross(forward, up)
    right /= np.maximum(np.linalg.norm(right), 1e-12)
    down = np.cross(forward, right)                     # +y down, completing a right-handed frame
    R = np.stack([right, down, forward], axis=0)        # rows map world -> camera axes
    t = -R @ eye
    return R, t


def intrinsics(width: int, height: int, fov_y_degrees: float) -> np.ndarray:
    """Square-pixel pinhole K from a vertical field of view."""
    f = (height / 2.0) / np.tan(np.radians(fov_y_degrees) / 2.0)
    return np.array([[f, 0.0, width / 2.0],
                     [0.0, f, height / 2.0],
                     [0.0, 0.0, 1.0]])


def save_cameras(path: Path, cams: list[Camera]) -> None:
    Path(path).write_text(json.dumps([c.to_dict() for c in cams], indent=1))


def load_cameras(path: Path) -> list[Camera]:
    return [Camera.from_dict(d) for d in json.loads(Path(path).read_text())]
