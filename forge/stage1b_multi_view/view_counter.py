"""
View Counter Module

Detects and counts the number of provided views.
Supports named views (front, back, top) and unnamed views (auto-detected).
Handles duplicate views (multiple angles of same view).
"""

from pathlib import Path
from typing import List, Dict, Optional
import re


# Standard view names and their aliases
VIEW_NAMES = {
    "front": ["front", "forward", "anterior", "face"],
    "back": ["back", "rear", "posterior", "behind"],
    "top": ["top", "upper", "superior", "overhead"],
    "bottom": ["bottom", "lower", "inferior", "underside"],
    "left": ["left", "lateral", "side-left"],
    "right": ["right", "medial", "side-right"],
}

# Standard view angles (in degrees from front)
VIEW_ANGLES = {
    "front": 0,
    "back": 180,
    "top": 90,
    "bottom": 270,
    "left": 270,
    "right": 90,
}


def count_views(image_paths: List[Path]) -> int:
    """
    Count the number of provided views.

    Args:
        image_paths: List of paths to reference images

    Returns:
        Number of views
    """
    return len(image_paths)


def detect_named_views(image_paths: List[Path]) -> Dict[str, Path]:
    """
    Detect named views from image filenames.

    Args:
        image_paths: List of paths to reference images

    Returns:
        Dictionary mapping view names to paths
    """
    named_views = {}
    name_counts: Dict[str, int] = {}
    auto_labels = _auto_labels_for_unnamed_views(image_paths)

    for path in image_paths:
        filename = path.stem.lower()
        base_name = _extract_view_name(filename) or auto_labels.get(path) or filename
        occurrence = name_counts.get(base_name, 0) + 1
        name_counts[base_name] = occurrence
        view_name = base_name if occurrence == 1 else f"{base_name}-{occurrence}"
        named_views[view_name] = path

    return named_views


def cluster_unnamed_views(image_paths: List[Path]) -> Dict[str, List[Path]]:
    clusters: Dict[str, List[Path]] = {}
    representatives: Dict[str, tuple[float, ...]] = {}
    for path in image_paths:
        filename = path.stem.lower()
        if _extract_view_name(filename) is not None or _extract_angle_from_filename(filename) is not None:
            continue
        signature = _image_signature(path)
        if signature is None:
            continue
        matching_cluster = next(
            (
                name
                for name, representative in representatives.items()
                if _signature_distance(signature, representative) <= 12.0
            ),
            None,
        )
        if matching_cluster is None:
            matching_cluster = f"auto-{len(clusters) + 1}"
            clusters[matching_cluster] = []
            representatives[matching_cluster] = signature
        clusters[matching_cluster].append(path)
    return clusters


def _auto_labels_for_unnamed_views(image_paths: List[Path]) -> Dict[Path, str]:
    labels: Dict[Path, str] = {}
    for cluster_name, paths in cluster_unnamed_views(image_paths).items():
        for path in paths:
            labels[path] = cluster_name
    return labels


def _image_signature(path: Path) -> Optional[tuple[float, ...]]:
    try:
        from forge.stage4_review.make_comparison_sheet import read_png

        width, height, pixels = read_png(path)
    except (OSError, ValueError):
        return None
    samples: list[float] = []
    for row in range(4):
        for column in range(4):
            x = min(width - 1, int((column + 0.5) * width / 4))
            y = min(height - 1, int((row + 0.5) * height / 4))
            red, green, blue, _alpha = pixels[y * width + x]
            samples.append((299 * red + 587 * green + 114 * blue) / 1000)
    return tuple(samples)


def _signature_distance(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    return sum(abs(a - b) for a, b in zip(first, second)) / len(first)


def group_duplicate_views(
    image_paths: List[Path],
    named_views: Dict[str, Path],
) -> Dict[str, Path]:
    """
    Group duplicate views (multiple angles of same view).

    Args:
        image_paths: List of paths to reference images
        named_views: Dictionary mapping view names to paths

    Returns:
        Dictionary mapping view names to best quality path
    """
    grouped = {}

    # Group by view name
    for view_name, path in named_views.items():
        base_name = _get_base_view_name(view_name)
        if base_name in grouped:
            if _image_quality(path) <= _image_quality(grouped[base_name]):
                continue
        grouped[base_name] = path

    return grouped


def _image_quality(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (0, 0)
    return (stat.st_size, stat.st_mtime_ns)


def detect_view_angles(
    named_views: Dict[str, Path],
) -> Dict[str, float]:
    """
    Detect viewing angles from named views.

    Args:
        named_views: Dictionary mapping view names to paths

    Returns:
        Dictionary mapping view names to angles in degrees
    """
    angles = {}

    for view_name in named_views:
        base_name = _get_base_view_name(view_name)
        if base_name in VIEW_ANGLES:
            angles[view_name] = VIEW_ANGLES[base_name]
        else:
            # Try to extract angle from filename
            angle = _extract_angle_from_filename(view_name)
            if angle is not None:
                angles[view_name] = angle

    return angles


def _extract_view_name(filename: str) -> Optional[str]:
    """
    Extract view name from filename.

    Args:
        filename: Image filename (without extension)

    Returns:
        Standard view name or None
    """
    for view_name, aliases in VIEW_NAMES.items():
        for alias in aliases:
            # Match complete filename tokens. Substring matching incorrectly
            # classified names such as "frontier" and "leftover".
            if re.search(rf"(^|[^a-z0-9]){re.escape(alias)}([^a-z0-9]|$)", filename):
                return view_name
    return None


def _get_base_view_name(view_name: str) -> str:
    """
    Get base view name (remove numbering or suffixes).

    Args:
        view_name: View name potentially with suffix

    Returns:
        Base view name
    """
    # Remove common suffixes like "1", "2", "angle", etc.
    base = re.sub(r'[-_]\d+$', '', view_name)
    base = re.sub(r'[_-]angle$', '', base)
    base = re.sub(r'[_-]view$', '', base)
    return base.strip() or view_name


def _extract_angle_from_filename(filename: str) -> Optional[float]:
    """
    Extract angle from filename.

    Args:
        filename: Image filename

    Returns:
        Angle in degrees or None
    """
    # Look for angle patterns like "45deg", "angle45", etc.
    patterns = [
        r'(\d+)[-_]?deg',
        r'angle[_-]?(\d+)',
        r'(\d+)[-_]?degree',
    ]

    for pattern in patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            return float(match.group(1))

    return None
