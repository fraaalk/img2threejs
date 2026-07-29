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
    try:
        from PIL import Image, ImageFilter
        import numpy as np

        # Load image
        img = Image.open(image_path).convert("L")

        # Apply edge detection
        edges = img.filter(ImageFilter.FIND_EDGES)

        # Convert to numpy array
        edge_array = np.array(edges)

        # Find edge points (pixels with high edge strength)
        threshold = np.percentile(edge_array, 90)  # Top 10% strongest edges
        edge_points = np.where(edge_array > threshold)

        # Sample features from edge points
        features = []
        if len(edge_points[0]) > 0:
            # Sample evenly across edge points
            indices = np.linspace(0, len(edge_points[0]) - 1, min(max_features, len(edge_points[0])), dtype=int)
            for i in indices:
                y, x = edge_points[0][i], edge_points[1][i]
                strength = float(edge_array[y, x]) / 255.0
                feature = Feature(
                    x=float(x),
                    y=float(y),
                    strength=strength,
                )
                features.append(feature)

        return FeatureSet(
            features=features,
            image_path=image_path,
            feature_count=len(features),
            detection_method="edge",
        )

    except ImportError:
        # If PIL not available, return empty feature set
        return FeatureSet(
            features=[],
            image_path=image_path,
            feature_count=0,
            detection_method="none",
        )
