"""
Hybrid Synthesis Mode

Combines deterministic and agent-driven synthesis for robust multi-view analysis.
"""

from typing import Dict, Any, Optional, List
from pathlib import Path
import logging

from .synthesize import synthesize_geometry_brief
from .view_counter import count_views

logger = logging.getLogger(__name__)


def hybrid_synthesis(
    image_paths: List[Path],
    agent_analysis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run hybrid synthesis combining deterministic and agent-driven analysis.

    Args:
        image_paths: List of paths to reference images
        agent_analysis: Optional agent-driven analysis results

    Returns:
        Combined synthesis results
    """
    view_count = count_views(image_paths)

    # Run deterministic synthesis
    deterministic_result = synthesize_geometry_brief(image_paths)

    # If no agent analysis provided, return deterministic result
    if agent_analysis is None:
        return deterministic_result

    # Combine results
    combined = combine_results(deterministic_result, agent_analysis)

    return combined


def combine_results(
    deterministic: Dict[str, Any],
    agent: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Combine deterministic and agent-driven results.

    Args:
        deterministic: Deterministic synthesis results
        agent: Agent-driven analysis results

    Returns:
        Combined results
    """
    combined = deterministic.copy()

    # Merge confidence scores
    det_confidence = deterministic.get("confidence", 0.0)
    agent_confidence = agent.get("confidence", 0.0)

    # Weighted average (deterministic 0.6, agent 0.4)
    combined_confidence = (det_confidence * 0.6) + (agent_confidence * 0.4)
    combined["confidence"] = combined_confidence

    # Merge components
    if "components" in agent:
        combined["components"] = merge_components(
            deterministic.get("components", {}),
            agent.get("components", {}),
        )

    # Add agent notes
    if "notes" in agent:
        combined["agentNotes"] = agent["notes"]

    combined["synthesisMode"] = "hybrid"

    return combined


def merge_components(
    deterministic_components: Dict[str, Any],
    agent_components: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Merge components from deterministic and agent analysis.

    Args:
        deterministic_components: Components from deterministic synthesis
        agent_components: Components from agent analysis

    Returns:
        Merged components
    """
    merged = deterministic_components.copy()

    for component_name, agent_data in agent_components.items():
        if component_name in merged:
            # Merge existing component
            merged[component_name] = merge_single_component(
                merged[component_name],
                agent_data,
            )
        else:
            # Add new component from agent
            merged[component_name] = agent_data

    return merged


def merge_single_component(
    deterministic: Dict[str, Any],
    agent: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Merge a single component from deterministic and agent analysis.

    Args:
        deterministic: Component from deterministic synthesis
        agent: Component from agent analysis

    Returns:
        Merged component
    """
    merged = deterministic.copy()

    # Use agent dimensions if available (higher confidence)
    if "dimensions" in agent:
        merged["dimensions"] = agent["dimensions"]

    # Use agent curvature if available
    if "curvature" in agent:
        merged["curvature"] = agent["curvature"]

    # Merge confidence scores
    det_conf = deterministic.get("confidence", 0.0)
    agent_conf = agent.get("confidence", 0.0)
    merged["confidence"] = (det_conf * 0.6) + (agent_conf * 0.4)

    # Add agent notes
    if "notes" in agent:
        merged["agentNotes"] = agent["notes"]

    return merged


def create_agent_analysis_template() -> Dict[str, Any]:
    """
    Create a template for agent-driven analysis.

    Returns:
        Template dictionary
    """
    return {
        "viewCount": 0,
        "confidence": 0.0,
        "components": {},
        "notes": "",
        "observations": [],
        "inferences": [],
    }
