"""
View Counter Module

Detects and counts the number of provided views.
Supports named views (front, back, top) and unnamed views (auto-detected).
Handles duplicate views (multiple angles of same view).
"""

from pathlib import Path
from typing import List, Dict, Optional, Tuple
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

    for path in image_paths:
        filename = path.stem.lower()
        view_name = _extract_view_name(filename)
        if view_name:
            named_views[view_name] = path
        else:
            # Use filename as view name if no standard name detected
            named_views[filename] = path

    return named_views


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
            # Keep the first one (could be enhanced to select best quality)
            continue
        grouped[base_name] = path

    return grouped


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
            if alias in filename:
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
    base = re.sub(r'[\d\-_]$', '', view_name)
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
