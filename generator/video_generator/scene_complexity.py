"""
Scene Complexity Scorer
========================

Scores scene complexity to route to appropriate Gemini models.

Complexity dimensions:
  - Animation density (animations per second)
  - Object count
  - Interaction depth (transforms, updaters, camera moves)
  - Choreography complexity

Routing:
  LOW    → gemini-2.5-flash-lite  (simple scenes)
  MEDIUM → gemini-2.5-flash       (standard scenes)
  HIGH   → gemini-3-flash-preview (cinematic scenes)

Usage:
  score = score_scene_complexity(scene_spec, narration, duration)
  model = route_to_model(score, available_models)
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional, List

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# COMPLEXITY LEVELS
# ═══════════════════════════════════════════════════════════════════

class ComplexityLevel:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ComplexityScore:
    """Scored complexity of a scene."""
    total: float          # 0.0 – 1.0
    level: str            # ComplexityLevel.LOW/MEDIUM/HIGH
    animation_density: float
    object_count: float
    interaction_depth: float
    choreography: float
    reasons: list         # Human-readable reasons for the score

    @property
    def prompt_tier(self) -> str:
        """Map complexity level to prompt tier name."""
        if self.level == ComplexityLevel.HIGH:
            return "HIGH_INTELLIGENCE"
        elif self.level == ComplexityLevel.MEDIUM:
            return "STANDARD"
        else:
            return "LIGHTWEIGHT"


# ═══════════════════════════════════════════════════════════════════
# MODEL CAPABILITY REGISTRY
# ═══════════════════════════════════════════════════════════════════

MODEL_CAPABILITIES = {
    # model_name: (capability_tier, max_complexity)
    "gemini-3.6-flash":          ("HIGH_INTELLIGENCE", 1.0),
    "gemini-3.1-pro-preview":    ("HIGH_INTELLIGENCE", 1.0),
    "gemini-3-flash-preview":    ("HIGH_INTELLIGENCE", 1.0),
    "gemini-2.5-flash":          ("STANDARD", 0.65),
    "gemini-3.5-flash-lite":     ("LIGHTWEIGHT", 0.40),
    "gemini-2.5-flash-lite":     ("LIGHTWEIGHT", 0.40),
}

# Complexity thresholds for level assignment
COMPLEXITY_THRESHOLDS = {
    "low": 0.35,
    "medium": 0.65,
    # Anything above 0.65 is HIGH
}


def get_model_tier(model_name: str) -> str:
    """Get the prompt tier for a given model name."""
    for name, (tier, _) in MODEL_CAPABILITIES.items():
        if name in model_name:
            return tier
    return "STANDARD"  # Default


def get_model_max_complexity(model_name: str) -> float:
    """Get the maximum complexity a model can handle."""
    for name, (_, max_c) in MODEL_CAPABILITIES.items():
        if name in model_name:
            return max_c
    return 0.65  # Default


# ═══════════════════════════════════════════════════════════════════
# COMPLEXITY SCORING
# ═══════════════════════════════════════════════════════════════════

# Keywords that indicate high-complexity scenes
_HIGH_COMPLEXITY_SIGNALS = [
    "parallel", "simultaneous", "concurrent", "choreograph",
    "transform", "morph", "evolve", "cascade", "chain",
    "real-time", "dynamic", "interactive", "simulation",
    "particle", "swarm", "network", "graph", "tree",
    "recursion", "fractal", "wave", "oscillat",
]

_MEDIUM_COMPLEXITY_SIGNALS = [
    "compare", "timeline", "sequence", "flow", "process",
    "step-by-step", "before/after", "diagram", "chart",
    "cycle", "loop", "architecture", "system",
]

_LOW_COMPLEXITY_SIGNALS = [
    "title", "intro", "outro", "subscribe", "summary",
    "recap", "conclusion", "simple", "basic",
]


def score_scene_complexity(
    scene_spec=None,
    narration: str = "",
    duration: float = 10.0,
    visual_contract: dict = None,
) -> ComplexityScore:
    """
    Score the complexity of a scene to determine model routing.
    
    Args:
        scene_spec: SceneSpecification with concept, visual_metaphor, etc.
        narration: The narration text.
        duration: Scene duration in seconds.
        visual_contract: Optional visual contract dict.
    
    Returns:
        ComplexityScore with total score, level, and reasons.
    """
    scores = {
        "animation_density": 0.0,
        "object_count": 0.0,
        "interaction_depth": 0.0,
        "choreography": 0.0,
    }
    reasons = []

    # ── 1. Animation density (from narration content analysis) ──
    narration_lower = narration.lower()
    word_count = len(narration.split())
    
    # Longer narrations need more visual content
    if duration > 15:
        scores["animation_density"] += 0.2
        reasons.append(f"Long duration ({duration:.0f}s)")
    
    if word_count > 60:
        scores["animation_density"] += 0.15
        reasons.append(f"Dense narration ({word_count} words)")

    # ── 2. Content complexity signals ──
    high_signals = sum(1 for s in _HIGH_COMPLEXITY_SIGNALS if s in narration_lower)
    medium_signals = sum(1 for s in _MEDIUM_COMPLEXITY_SIGNALS if s in narration_lower)
    low_signals = sum(1 for s in _LOW_COMPLEXITY_SIGNALS if s in narration_lower)
    
    if high_signals >= 2:
        scores["choreography"] += 0.3
        reasons.append(f"High-complexity keywords: {high_signals}")
    elif medium_signals >= 2:
        scores["choreography"] += 0.15
        reasons.append(f"Medium-complexity keywords: {medium_signals}")
    
    if low_signals >= 2:
        scores["choreography"] -= 0.15
        reasons.append(f"Low-complexity scene (intro/outro)")

    # ── 3. Scene spec analysis (if available) ──
    if scene_spec:
        # Visual metaphor complexity
        if hasattr(scene_spec, 'visual_metaphor') and scene_spec.visual_metaphor:
            vm = scene_spec.visual_metaphor
            
            # Count visual elements
            if hasattr(vm, 'visual_elements') and vm.visual_elements:
                elem_count = len(vm.visual_elements)
                if elem_count > 6:
                    scores["object_count"] += 0.3
                    reasons.append(f"Many visual elements ({elem_count})")
                elif elem_count > 3:
                    scores["object_count"] += 0.15
            
            # Count transition chains
            if hasattr(vm, 'transformation_chain') and vm.transformation_chain:
                chain_len = len(vm.transformation_chain)
                if chain_len > 4:
                    scores["interaction_depth"] += 0.3
                    reasons.append(f"Complex transformation chain ({chain_len})")
                elif chain_len > 2:
                    scores["interaction_depth"] += 0.15

        # Concept complexity
        if hasattr(scene_spec, 'concept') and scene_spec.concept:
            concept = scene_spec.concept
            if hasattr(concept, 'emotional_arc') and concept.emotional_arc:
                arc = concept.emotional_arc.lower()
                if any(word in arc for word in ["complex", "intricate", "layered"]):
                    scores["choreography"] += 0.15
                    reasons.append("Complex emotional arc")

    # ── 4. Visual contract complexity ──
    if visual_contract:
        depiction_mode = visual_contract.get("depiction_mode", "")
        if depiction_mode == "simulation":
            scores["interaction_depth"] += 0.2
            reasons.append("Simulation depiction mode")
        elif depiction_mode == "abstract":
            scores["interaction_depth"] += 0.1

    # ── Compute total ──
    total = sum(scores.values()) / 4.0  # Average of 4 dimensions
    total = max(0.0, min(1.0, total * 2))  # Scale to 0-1 range
    
    # Determine level
    if total <= COMPLEXITY_THRESHOLDS["low"]:
        level = ComplexityLevel.LOW
    elif total <= COMPLEXITY_THRESHOLDS["medium"]:
        level = ComplexityLevel.MEDIUM
    else:
        level = ComplexityLevel.HIGH

    result = ComplexityScore(
        total=round(total, 2),
        level=level,
        animation_density=round(scores["animation_density"], 2),
        object_count=round(scores["object_count"], 2),
        interaction_depth=round(scores["interaction_depth"], 2),
        choreography=round(scores["choreography"], 2),
        reasons=reasons,
    )

    logger.info(
        f"📊 Scene complexity: {result.total:.2f} ({result.level}) "
        f"→ prompt tier: {result.prompt_tier} "
        f"[{', '.join(reasons[:3])}]"
    )

    return result


def route_to_model(
    score: ComplexityScore,
    available_models: List[str],
) -> str:
    """
    Route a scene to the best available model based on complexity.
    
    Args:
        score: ComplexityScore from score_scene_complexity()
        available_models: List of available model names.
    
    Returns:
        Best model name for this scene's complexity.
    """
    if not available_models:
        return "gemini-2.5-flash"  # Fallback
    
    # Find the best model that can handle this complexity
    target_complexity = score.total
    
    # Sort models by capability (highest first)
    ranked = []
    for model in available_models:
        max_c = get_model_max_complexity(model)
        ranked.append((model, max_c))
    ranked.sort(key=lambda x: x[1], reverse=True)
    
    # Pick the least powerful model that can handle the complexity
    for model, max_c in reversed(ranked):
        if max_c >= target_complexity:
            logger.info(
                f"🎯 Routed complexity={score.total:.2f} ({score.level}) "
                f"→ {model} (max={max_c:.2f})"
            )
            return model
    
    # If no model can handle it, use the most powerful available
    best = ranked[0][0]
    logger.info(
        f"🎯 Routed complexity={score.total:.2f} ({score.level}) "
        f"→ {best} (most powerful available)"
    )
    return best
