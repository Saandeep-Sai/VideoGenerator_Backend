"""
VISUAL QUALITY VALIDATOR
========================

Simulation-first validator for the QUALITY PIPELINE.

This module enforces that the quality pipeline acts as a
**SIMULATION PRESERVER + ENHANCER** — not a redesign stage.

Called at THREE gates:
  1. PRE-SPEC:   reject spec-generation prompts lacking contract injection
  2. POST-SPEC:  reject scene specs that convert simulations into diagrams
  3. POST-SCRIPT: reject Manim scripts with insufficient simulation fidelity

Architecture position:
  Visual Contract
       ↓
  [PRE-SPEC GATE]  → scene_spec_generator prompt gets contract block
       ↓
  Scene Specification (JSON)
       ↓
  [POST-SPEC GATE]  → reject diagram-heavy specs when contract says simulation
       ↓
  Visual Director → Manim Code Generator
       ↓
  [POST-SCRIPT GATE] → reject static/text-heavy scripts
"""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ================================================================
# SIMULATION QUALITY METRICS
# ================================================================
# These replace the legacy "diagram neatness" metrics.
# Positive signal = entity interaction, visible motion, state evolution.
# Negative signal = symmetry dominance, label dominance, static layout.

class SimulationQualityMetrics:
    """
    Score a scene specification or script for simulation fidelity.

    Higher = better simulation.  Lower = more diagram-like.

    Fields after scoring:
        entity_interaction_score : 0.0–1.0
        motion_coverage_score   : 0.0–1.0
        transformation_score    : 0.0–1.0
        text_ratio_penalty      : 0.0–1.0  (0 = good, 1 = all text)
        diagram_penalty         : 0.0–1.0  (0 = good, 1 = full diagram)
        overall                 : 0.0–1.0
    """

    def __init__(self):
        self.entity_interaction_score: float = 0.0
        self.motion_coverage_score: float = 0.0
        self.transformation_score: float = 0.0
        self.text_ratio_penalty: float = 0.0
        self.diagram_penalty: float = 0.0
        self.overall: float = 0.0

    def to_dict(self) -> dict:
        return {
            "entity_interaction_score": round(self.entity_interaction_score, 3),
            "motion_coverage_score": round(self.motion_coverage_score, 3),
            "transformation_score": round(self.transformation_score, 3),
            "text_ratio_penalty": round(self.text_ratio_penalty, 3),
            "diagram_penalty": round(self.diagram_penalty, 3),
            "overall": round(self.overall, 3),
        }


# ================================================================
# CONSTANTS
# ================================================================

# Element types that are containers / diagram primitives
_CONTAINER_TYPES = frozenset([
    "glass_card", "boundary_box", "code_block", "text_block",
])

# Element types that indicate simulation entities
_SIMULATION_TYPES = frozenset([
    "node", "data_packet", "icon_badge", "arrow",
    "progress_bar", "checkpoint", "gate", "lock",
])

# Transformation actions that imply motion
_MOTION_ACTIONS = frozenset([
    "grow_from_center", "slide_in_from_left", "slide_in_from_right",
    "draw_arrow", "pulse", "circumscribe", "flash", "bounce",
    "draw_border_then_fill", "morph", "transform", "move",
    "scale", "flow", "connect",
])

# Static / reveal-only actions
_STATIC_ACTIONS = frozenset([
    "fade_in", "write",
])

# Manim patterns for motion detection in scripts
_SCRIPT_MOTION_PATTERN = re.compile(
    r'\b(?:MoveAlongPath|animate\.shift|animate\.move_to|'
    r'animate\.scale|Transform|ReplacementTransform|TransformFromCopy|'
    r'MoveToTarget|GrowFromCenter|Create|DrawBorderThenFill|'
    r'GrowArrow|Indicate|Circumscribe|'
    r'LaggedStart|AnimationGroup|Succession|'
    r'animate\.rotate|animate\.set_color|'
    r'FadeTransform|ClockwiseTransform|CounterclockwiseTransform)\s*[\(.]',
    re.IGNORECASE
)

_SCRIPT_TEXT_PATTERN = re.compile(
    r'\b(?:Text|MarkupText|MathTex|Tex|Paragraph|BulletedList)\s*\(',
    re.IGNORECASE
)

_SCRIPT_SHAPE_PATTERN = re.compile(
    r'\b(?:Circle|Square|Rectangle|Dot|Line|Arrow|Arc|Polygon|'
    r'Ellipse|Star|Triangle|RoundedRectangle|Annulus|'
    r'NumberLine|Axes|Graph|VGroup)\s*\(',
    re.IGNORECASE
)

_SCRIPT_STATIC_PLAY = re.compile(
    r'self\.play\s*\(\s*(?:FadeIn|Write)\s*\(',
    re.IGNORECASE
)

_SCRIPT_TRANSFORM = re.compile(
    r'\b(?:Transform|ReplacementTransform|TransformFromCopy|'
    r'FadeTransform|MoveAlongPath)\s*\(',
    re.IGNORECASE
)

_SCRIPT_CONTAINER_PATTERN = re.compile(
    r'\b(?:RoundedRectangle|Rectangle)\s*\([^)]*(?:fill_opacity|stroke_color)',
    re.IGNORECASE
)


# ================================================================
# POST-SPEC GATE
# ================================================================

def validate_spec_simulation(
    spec_dict: dict,
    visual_contract: dict,
) -> Tuple[bool, List[str], SimulationQualityMetrics]:
    """
    POST-SPEC GATE: Does this scene specification honour the visual contract?

    When ``visual_contract.depiction_mode == "simulation"``, the spec
    MUST NOT:
      - Have > 40% container/text elements (glass_card, boundary_box, …)
      - Lack entity state changes
      - Lack transformation animations
      - Have entities not derived from the contract

    Returns
    -------
    (passed, issues, metrics)
    """
    issues: List[str] = []
    metrics = SimulationQualityMetrics()
    mode = visual_contract.get("depiction_mode", "simulation")

    # No enforcement for explicit diagram mode
    if mode != "simulation":
        metrics.overall = 1.0
        return True, [], metrics

    # ── Extract spec elements ──
    metaphor = spec_dict.get("visual_metaphor", {})
    elements = metaphor.get("visual_elements", [])
    transform = spec_dict.get("transformation", {})
    sequence = transform.get("sequence", [])

    # ── 1. Container / text ratio ──
    if elements:
        container_count = sum(
            1 for e in elements
            if e.get("element_type", "") in _CONTAINER_TYPES
        )
        container_ratio = container_count / len(elements)
        metrics.diagram_penalty = container_ratio

        if container_ratio > 0.4:
            issues.append(
                f"Container-heavy spec: {container_count}/{len(elements)} elements "
                f"are containers ({container_ratio:.0%}) — simulation needs moving entities"
            )
    else:
        metrics.diagram_penalty = 0.5
        issues.append("No visual elements in spec")

    # ── 2. Entity origin check ──
    contract_entities = visual_contract.get("entities", [])
    contract_names = set()
    for e in contract_entities:
        if isinstance(e, dict):
            contract_names.add(e.get("type", "").lower())
            contract_names.add(e.get("semantic_role", "").lower())
            contract_names.add(e.get("label", "").lower())
        elif isinstance(e, str):
            contract_names.add(e.lower())
    contract_names.discard("")

    if elements and contract_names:
        foreign = 0
        for e in elements:
            label = e.get("label", "").lower()
            etype = e.get("element_type", "").lower()
            # Skip arrows/connections — they're structural
            if etype == "arrow":
                continue
            if label and not any(cn in label or label in cn for cn in contract_names):
                foreign += 1
        non_arrow = sum(1 for e in elements if e.get("element_type", "") != "arrow")
        if non_arrow > 0 and foreign / non_arrow > 0.5:
            issues.append(
                f"{foreign}/{non_arrow} non-arrow elements don't match contract entities"
            )

    # ── 3. Transformation presence ──
    motion_actions = [
        s for s in sequence
        if s.get("action", "") in _MOTION_ACTIONS
    ]
    static_actions = [
        s for s in sequence
        if s.get("action", "") in _STATIC_ACTIONS
    ]

    if not sequence:
        metrics.transformation_score = 0.0
        issues.append("No transformation sequence — simulation needs state changes")
    elif not motion_actions:
        metrics.transformation_score = 0.1
        issues.append(
            f"All {len(sequence)} actions are static ({[s.get('action') for s in sequence[:4]]}) "
            f"— simulation needs motion"
        )
    else:
        metrics.transformation_score = len(motion_actions) / max(len(sequence), 1)

    # ── 4. Entity interaction ──
    # At least 2 elements must be targeted in the transformation sequence
    targeted_elements = set()
    for s in sequence:
        t = s.get("target", "")
        if t:
            targeted_elements.add(t)
    if len(targeted_elements) < 2 and len(elements) >= 2:
        metrics.entity_interaction_score = 0.2
        issues.append(
            f"Only {len(targeted_elements)} element(s) targeted in transformation — "
            f"simulation needs entity interaction"
        )
    else:
        metrics.entity_interaction_score = min(1.0, len(targeted_elements) / max(len(elements), 1))

    # ── 5. Transformation chain coverage ──
    contract_chain = visual_contract.get("transformation_chain", [])
    if contract_chain and not sequence:
        issues.append(
            f"Contract has {len(contract_chain)} transformation steps but spec has none"
        )

    # ── 6. Motion coverage estimate ──
    total_actions = len(sequence)
    if total_actions > 0:
        metrics.motion_coverage_score = len(motion_actions) / total_actions
    else:
        metrics.motion_coverage_score = 0.0

    # ── 7. Text element ratio ──
    if elements:
        text_types = {"label", "text_block"}
        text_count = sum(1 for e in elements if e.get("element_type", "") in text_types)
        metrics.text_ratio_penalty = text_count / len(elements)
    else:
        metrics.text_ratio_penalty = 0.0

    # ── Overall score ──
    metrics.overall = (
        metrics.entity_interaction_score * 0.25
        + metrics.motion_coverage_score * 0.25
        + metrics.transformation_score * 0.25
        + (1.0 - metrics.diagram_penalty) * 0.15
        + (1.0 - metrics.text_ratio_penalty) * 0.10
    )

    passed = metrics.overall >= 0.40 and len(issues) <= 2
    return passed, issues, metrics


# ================================================================
# POST-SCRIPT GATE  (Execution Safety Rules)
# ================================================================

def validate_script_simulation_quality(
    script: str,
    visual_contract: dict,
) -> Tuple[bool, List[str], SimulationQualityMetrics]:
    """
    POST-SCRIPT GATE: Does the generated Manim script implement simulation?

    When ``visual_contract.depiction_mode == "simulation"``, the script
    MUST satisfy:
      - Motion runtime ≥ 50% (estimated by motion-animation count vs total play calls)
      - At least one moving entity path (MoveAlongPath or animate.shift/move_to)
      - At least one ReplacementTransform / Transform
      - Text objects ≤ 20% of all scene objects
      - Container-style RoundedRectangle with fill ≤ 30% of shapes

    Returns (passed, issues, metrics).
    """
    issues: List[str] = []
    metrics = SimulationQualityMetrics()
    mode = visual_contract.get("depiction_mode", "simulation")

    if mode != "simulation":
        metrics.overall = 1.0
        return True, [], metrics

    # ── Count objects ──
    text_count = len(_SCRIPT_TEXT_PATTERN.findall(script))
    shape_count = len(_SCRIPT_SHAPE_PATTERN.findall(script))
    total_objs = text_count + shape_count

    # ── 1. Text ratio ≤ 20% ──
    if total_objs > 0:
        text_ratio = text_count / total_objs
        metrics.text_ratio_penalty = text_ratio
        if text_ratio > 0.20:
            issues.append(
                f"Text-heavy: {text_count}/{total_objs} objects are text "
                f"({text_ratio:.0%}) — simulation limit is 20%"
            )
    else:
        metrics.text_ratio_penalty = 0.0

    # ── 2. Motion animations ──
    motion_hits = len(_SCRIPT_MOTION_PATTERN.findall(script))
    play_count = script.count("self.play")

    if play_count > 0:
        motion_ratio = motion_hits / play_count
        metrics.motion_coverage_score = min(1.0, motion_ratio)
        if motion_ratio < 0.50:
            issues.append(
                f"Motion coverage {motion_ratio:.0%} < 50% minimum "
                f"({motion_hits} motion animations / {play_count} play calls)"
            )
    elif motion_hits > 0:
        metrics.motion_coverage_score = 0.8
    else:
        metrics.motion_coverage_score = 0.0
        issues.append("No motion animations found — simulation must have movement")

    # ── 3. Transform presence ──
    transform_hits = len(_SCRIPT_TRANSFORM.findall(script))
    if transform_hits == 0:
        metrics.transformation_score = 0.0
        issues.append("No Transform/ReplacementTransform — simulation must morph elements")
    elif transform_hits < 2:
        metrics.transformation_score = 0.4
        issues.append(f"Only {transform_hits} transform(s) — simulation needs evolving visuals")
    else:
        metrics.transformation_score = min(1.0, transform_hits / 4)

    # ── 4. Moving entity paths ──
    has_move_path = bool(re.search(
        r'\b(?:MoveAlongPath|animate\.shift|animate\.move_to|'
        r'animate\.rotate|animate\.scale)\s*[\(.]', script, re.IGNORECASE
    ))
    if not has_move_path:
        issues.append("No moving entity paths — simulation needs at least one")

    # ── 5. Container penalty (RoundedRectangle with fill = diagram box) ──
    container_hits = len(_SCRIPT_CONTAINER_PATTERN.findall(script))
    if shape_count > 0:
        container_ratio = container_hits / shape_count
        metrics.diagram_penalty = container_ratio
        if container_ratio > 0.30:
            issues.append(
                f"Container-heavy: {container_hits}/{shape_count} shapes are filled "
                f"rectangles ({container_ratio:.0%}) — looks like a diagram"
            )
    else:
        metrics.diagram_penalty = 0.0

    # ── 6. Static play dominance ──
    static_count = len(_SCRIPT_STATIC_PLAY.findall(script))
    if play_count > 0 and static_count / play_count > 0.60:
        issues.append(
            f"Static-dominated: {static_count}/{play_count} play() calls are FadeIn/Write"
        )

    # ── 7. Entity interaction estimate ──
    # Count unique mobject names in self.play() calls
    play_calls = re.findall(r'self\.play\((.*?)\)', script, re.DOTALL)
    unique_targets = set()
    for call in play_calls:
        # Extract variable names (self.xxx or bare xxx)
        targets = re.findall(r'\b(?:self\.)?([a-z_][a-z0-9_]*)', call)
        unique_targets.update(targets)
    # Remove common non-entity names
    non_entities = {"play", "self", "animate", "run_time", "rate_func", "lag_ratio"}
    unique_targets -= non_entities
    if len(unique_targets) >= 3:
        metrics.entity_interaction_score = min(1.0, len(unique_targets) / 6)
    elif len(unique_targets) >= 1:
        metrics.entity_interaction_score = 0.3
    else:
        metrics.entity_interaction_score = 0.0

    # ── Overall score ──
    metrics.overall = (
        metrics.entity_interaction_score * 0.20
        + metrics.motion_coverage_score * 0.30
        + metrics.transformation_score * 0.25
        + (1.0 - metrics.diagram_penalty) * 0.15
        + (1.0 - metrics.text_ratio_penalty) * 0.10
    )

    # Hard-fail conditions (regardless of overall score)
    hard_fail = False
    if motion_hits == 0:
        hard_fail = True
    if total_objs > 0 and text_count / total_objs > 0.40:
        hard_fail = True

    passed = metrics.overall >= 0.40 and not hard_fail
    return passed, issues, metrics


# ================================================================
# SIMULATION-AWARE QUALITY SCORING
# ================================================================
# Replaces legacy diagram-neatness scoring.

def score_simulation_quality(
    spec_dict: dict,
    script: str,
    visual_contract: dict,
) -> SimulationQualityMetrics:
    """
    Unified quality score that rewards simulation fidelity.

    Positive signals:
      - Entity interaction (multiple objects in same play() call)
      - Propagation behavior (MoveAlongPath, animate.shift chains)
      - Transformation (ReplacementTransform, morphing)
      - Evolving structures (state changes over time)
      - Visible cause-and-effect motion

    Negative signals:
      - Symmetry dominance (all elements equidistant)
      - Text clarity dominance (mostly Text objects)
      - Diagram neatness (filled containers, static layout)
    """
    mode = visual_contract.get("depiction_mode", "simulation")
    if mode != "simulation":
        m = SimulationQualityMetrics()
        m.overall = 1.0
        return m

    # Run both spec-level and script-level checks
    _, _, spec_metrics = validate_spec_simulation(spec_dict, visual_contract)
    _, _, script_metrics = validate_script_simulation_quality(script, visual_contract)

    # Merge: weight script metrics more (it's the actual output)
    merged = SimulationQualityMetrics()
    merged.entity_interaction_score = (
        spec_metrics.entity_interaction_score * 0.3
        + script_metrics.entity_interaction_score * 0.7
    )
    merged.motion_coverage_score = (
        spec_metrics.motion_coverage_score * 0.2
        + script_metrics.motion_coverage_score * 0.8
    )
    merged.transformation_score = (
        spec_metrics.transformation_score * 0.3
        + script_metrics.transformation_score * 0.7
    )
    merged.text_ratio_penalty = (
        spec_metrics.text_ratio_penalty * 0.3
        + script_metrics.text_ratio_penalty * 0.7
    )
    merged.diagram_penalty = (
        spec_metrics.diagram_penalty * 0.3
        + script_metrics.diagram_penalty * 0.7
    )
    merged.overall = (
        merged.entity_interaction_score * 0.20
        + merged.motion_coverage_score * 0.30
        + merged.transformation_score * 0.25
        + (1.0 - merged.diagram_penalty) * 0.15
        + (1.0 - merged.text_ratio_penalty) * 0.10
    )
    return merged


# ================================================================
# AUTHORITY RESTRICTION
# ================================================================

def restrict_quality_pipeline_authority(
    spec_dict: dict,
    visual_contract: dict,
) -> Tuple[dict, List[str]]:
    """
    When ``depiction_mode == "simulation"``, the quality pipeline
    MUST NOT redesign the scene.  This function detects and patches
    spec-level violations.

    Patches applied:
      - Replace glass_card / boundary_box elements with node / icon_badge
      - Ensure at least one motion action in transformation sequence
      - Inject missing contract entities

    Returns
    -------
    (patched_spec_dict, applied_patches)
    """
    mode = visual_contract.get("depiction_mode", "simulation")
    patches: List[str] = []

    if mode != "simulation":
        return spec_dict, patches

    metaphor = spec_dict.get("visual_metaphor", {})
    elements = metaphor.get("visual_elements", [])

    # ── Patch 1: Replace container elements ──
    replacement_map = {
        "glass_card": "node",
        "boundary_box": "icon_badge",
        "text_block": "tag_pill",
    }
    for elem in elements:
        etype = elem.get("element_type", "")
        if etype in replacement_map:
            old_type = etype
            elem["element_type"] = replacement_map[etype]
            patches.append(
                f"Replaced {old_type} → {elem['element_type']} "
                f"(label='{elem.get('label', '?')}')"
            )

    # ── Patch 2: Ensure motion actions ──
    transform = spec_dict.get("transformation", {})
    sequence = transform.get("sequence", [])
    has_motion = any(s.get("action", "") in _MOTION_ACTIONS for s in sequence)
    if not has_motion and sequence:
        # Upgrade first fade_in to grow_from_center
        for step in sequence:
            if step.get("action") == "fade_in":
                step["action"] = "grow_from_center"
                patches.append(f"Upgraded fade_in → grow_from_center for '{step.get('target', '?')}'")
                break

    # ── Patch 3: Inject missing contract entities ──
    contract_entities = visual_contract.get("entities", [])
    existing_labels = {e.get("label", "").lower() for e in elements}
    existing_labels.discard("")

    for ce in contract_entities[:4]:
        ce_name = ""
        if isinstance(ce, dict):
            ce_name = ce.get("type", ce.get("label", ""))
        elif isinstance(ce, str):
            ce_name = ce
        if ce_name and ce_name.lower() not in existing_labels:
            elements.append({
                "id": f"contract_{ce_name.replace(' ', '_').lower()}",
                "element_type": "node",
                "label": ce_name[:20],
                "position": "center",
                "size": "medium",
                "color": "TEAL",
            })
            patches.append(f"Injected missing contract entity: {ce_name}")

    if patches:
        logger.info(
            f"🔒 Quality pipeline authority restricted: {len(patches)} patches applied"
        )
        for p in patches:
            logger.info(f"   → {p}")

    return spec_dict, patches
