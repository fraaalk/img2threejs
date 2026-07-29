"""
Feature Detector Module

Detects visual features in reference images.
Supports SIFT/ORB feature detection with fallback to edge detection.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import math


@dataclass
class Feature:
    """Represents a detected feature in an image."""
    x: float
    y: float
    descriptor: Optional[List[float]] = None
    strength: float = 1.0
    angle: float = 0.0


@dataclass
class FeatureSet:
    """Collection of features detected in an image."""
    features: List[Feature]
    image_path: Path
    feature_count: int
    detection_method: str


def detect_features(
    image_path: Path,
    method: str = "auto",
    max_features: int = 1000,
) -> FeatureSet:
    """
    Detect features in an image.

    Args:
        image_path: Path to the image
        method: Detection method ("sift", "orb", "edge", "auto")
        max_features: Maximum number of features to detect

    Returns:
        FeatureSet with detected features
    """
    if method == "auto":
        method = _select_detection_method(image_path)

    if method == "sift":
        return _detect_sift(image_path, max_features)
    elif method == "orb":
        return _detect_orb(image_path, max_features)
    elif method == "edge":
        return _detect_edge_features(image_path, max_features)
    else:
        raise ValueError(f"Unknown detection method: {method}")


def _select_detection_method(image_path: Path) -> str:
    """
    Automatically select detection method based on image characteristics.

    Args:
        image_path: Path to the image

    Returns:
        Detection method name
    """
    # For now, default to edge detection (no OpenCV dependency)
    # In future, could analyze image complexity to choose
    return "edge"


def _detect_sift(image_path: Path, max_features: int) -> FeatureSet:
    """
    Detect SIFT features (requires OpenCV).

    Args:
        image_path: Path to the image
        max_features: Maximum number of features

    Returns:
        FeatureSet with SIFT features
    """
    try:
        import cv2
        import numpy as np

        # Load image
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError(f"Could not load image: {image_path}")

        # Create SIFT detector
        sift = cv2.SIFT_create(nfeatures=max_features)

        # Detect features
        keypoints, descriptors = sift.detectAndCompute(img, None)

        # Convert to Feature objects
        features = []
        for kp, desc in zip(keypoints, descriptors):
            feature = Feature(
                x=kp.pt[0],
                y=kp.pt[1],
                descriptor=desc.tolist(),
                strength=kp.response,
                angle=kp.angle,
            )
            features.append(feature)

        return FeatureSet(
            features=features,
            image_path=image_path,
            feature_count=len(features),
            detection_method="sift",
        )

    except ImportError:
        # Fallback to edge detection if OpenCV not available
        return _detect_edge_features(image_path, max_features)


def _detect_orb(image_path: Path, max_features: int) -> FeatureSet:
    """
    Detect ORB features (requires OpenCV).

    Args:
        image_path: Path to the image
        max_features: Maximum number of features

    Returns:
        FeatureSet with ORB features
    """
    try:
        import cv2
        import numpy as np

        # Load image
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError(f"Could not load image: {image_path}")

        # Create ORB detector
        orb = cv2.ORB_create(nfeatures=max_features)

        # Detect features
        keypoints, descriptors = orb.detectAndCompute(img, None)

        # Convert to Feature objects
        features = []
        for kp, desc in zip(keypoints, descriptors):
            feature = Feature(
                x=kp.pt[0],
                y=kp.pt[1],
                descriptor=desc.tolist() if desc is not None else None,
                strength=kp.response,
                angle=kp.angle,
            )
            features.append(feature)

        return FeatureSet(
            features=features,
            image_path=image_path,
            feature_count=len(features),
            detection_method="orb",
        )

    except ImportError:
        # Fallback to edge detection if OpenCV not available
        return _detect_edge_features(image_path, max_features)


def _detect_edge_features(image_path: Path, max_features: int) -> FeatureSet:
    """
    Detect edge features using PIL (no OpenCV dependency).

    Args:
        image_path: Path to the image
        max_features: Maximum number of features

    Returns:
        FeatureSet with edge features
    """
    from forge.stage4_review.make_comparison_sheet import read_png

    width, height, pixels = read_png(image_path)
    luminance = [
        (299 * red + 587 * green + 114 * blue) // 1000
        for red, green, blue, _alpha in pixels
    ]
    candidates = []
    for y in range(1, height - 1):
        row = y * width
        for x in range(1, width - 1):
            index = row + x
            gradient_x = abs(luminance[index + 1] - luminance[index - 1])
            gradient_y = abs(luminance[index + width] - luminance[index - width])
            strength = gradient_x + gradient_y
            if strength >= 48:
                candidates.append((strength, x, y))

    # Keep the strongest points while distributing the final sample across the
    # sorted candidate set. Pure stdlib, deterministic, and bounded.
    candidates.sort(reverse=True)
    strongest = candidates[: max(max_features * 4, max_features)]
    strongest.sort(key=lambda item: (item[2], item[1]))
    if len(strongest) > max_features:
        step = len(strongest) / max_features
        strongest = [strongest[int(index * step)] for index in range(max_features)]

    features = [
        Feature(x=float(x), y=float(y), strength=min(1.0, strength / 510.0))
        for strength, x, y in strongest
    ]
    return FeatureSet(
        features=features,
        image_path=image_path,
        feature_count=len(features),
        detection_method="edge",
    )
