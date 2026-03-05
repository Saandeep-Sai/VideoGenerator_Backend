"""
SIMULATION INTEGRITY GATE
==========================

Hard architectural gate that BLOCKS progression when the quality pipeline
produces diagram-like output for a simulation-mode contract.

Unlike visual_quality_validator.py (which scores and warns), this module
returns PASS / FAIL with NO ambiguity.  Callers MUST act on the result:
    - On FAIL → regenerate the segment (up to N retries)
    - On continued failure → fall back to the LEGACY pipeline

Architecture position:
    ┌──────────────────────────────────────────────────────────────┐
    │  Visual Contract (frozen, highest authority)                  │
    │        ↓                                                     │
    │  SceneSpecGenerator → SceneSpecification (JSON)              │
    │        ↓                                                     │
    │  ★ INTEGRITY GATE: validate_spec_integrity()                 │
    │        ↓  PASS → continue    FAIL → regenerate / fallback    │
    │  VisualDirector → VisualTimeline                             │
    │        ↓                                                     │
    │  ManimCodeGenerator → Manim script                           │
    │        ↓                                                     │
    │  ★ INTEGRITY GATE: validate_script_integrity()               │
    │        ↓  PASS → render      FAIL → regenerate / fallback    │
    │  Manim render                                                │
    └──────────────────────────────────────────────────────────────┘

This module is the SINGLE enforcement point.  It replaces all warning-only
checks with hard pass/fail decisions.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# CONSTANTS
# ════════════════════════════════════════════════════════════════════

# Element types that are containers / diagram primitives
# When depiction_mode == "simulation", these MUST NOT dominate.
CONTAINER_ELEMENT_TYPES = frozenset([
    "glass_card", "boundary_box", "code_block", "text_block",
    "rounded_rectangle",
])

# Element types that indicate simulation entities
SIMULATION_ELEMENT_TYPES = frozenset([
    "node", "data_packet", "icon_badge", "arrow", "circle",
    "progress_bar", "checkpoint", "star_badge", "annulus_ring",
    "curved_arrow", "dashed_line", "tag_pill",
])

# Transformation actions that imply real motion
MOTION_ACTIONS = frozenset([
    "grow_from_center", "slide_in_from_left", "slide_in_from_right",
    "draw_arrow", "pulse", "circumscribe", "flash", "bounce",
    "draw_border_then_fill", "morph", "transform", "move",
    "scale", "flow", "connect", "grow", "create",
])

# Regex: motion-heavy Manim calls
_RE_MOTION = re.compile(
    r'\b(?:MoveAlongPath|animate\.shift|animate\.move_to|'
    r'animate\.scale|animate\.rotate|animate\.set_color|'
    r'Transform|ReplacementTransform|TransformFromCopy|FadeTransform|'
    r'MoveToTarget|GrowFromCenter|Create|DrawBorderThenFill|'
    r'GrowArrow|Indicate|Circumscribe|Flash|Wiggle|ApplyWave|'
    r'GrowFromEdge|GrowFromPoint|SpinInFromNothing|'
    r'LaggedStart|AnimationGroup|Succession)\s*[\(.]',
    re.IGNORECASE,
)

# Regex: text-construction calls
_RE_TEXT = re.compile(
    r'\b(?:Text|MarkupText|MathTex|Tex|Paragraph|BulletedList)\s*\(',
    re.IGNORECASE,
)

# Regex: shape-construction calls (includes custom element primitives so they
# count as visual objects in the construct body, offsetting the watermark Text)
_RE_SHAPE = re.compile(
    r'\b(?:Circle|Square|Rectangle|Dot|Line|Arrow|Arc|Polygon|'
    r'Ellipse|Star|Triangle|RoundedRectangle|VGroup|Annulus|'
    r'Sector|Brace|DashedLine|CurvedArrow|'
    r'Node|DataPacket|IconBadge|TagPill|GlassCard|CodeBlock|'
    r'BoundaryBox|Checkpoint|StarBadge|FlowArrow|ProgressBar|'
    r'AnnulusRing|SectorChart|BraceAnnotation)\s*\(',
    re.IGNORECASE,
)

# Regex: purely static play calls (FadeIn with no shift, Write)
_RE_STATIC_PLAY = re.compile(
    r'self\.play\s*\(\s*(?:FadeIn|Write)\s*\(',
    re.IGNORECASE,
)

# Regex: container primitives in generated code
_RE_CONTAINER_CLASS = re.compile(
    r'\b(?:GlassCard|BoundaryBox|CodeBlock)\s*\(',
    re.IGNORECASE,
)


def _extract_construct_body(script: str) -> str:
    """Extract only the construct() method body for accurate object counting.

    Generated scripts include primitive class definitions (GlassCard, Node,
    DataPacket, etc.) whose __init__ methods contain Text() and shape
    constructors.  Scanning the FULL script inflates text/container ratios
    because every primitive definition adds ~1 Text() and ~2 shapes.

    This function returns the portion of the script from ``def construct``
    to the next class-level ``def`` (e.g. ``_get_grid_positions``), so
    only ACTUAL scene objects created by the user are counted.
    """
    match = re.search(r'def construct\(self\)\s*:', script)
    if not match:
        return script  # fallback: scan everything

    body_start = match.end()
    rest = script[body_start:]

    # End at next method at 4-space indent (class-level method)
    end_match = re.search(r'\n    def ', rest)
    if end_match:
        return rest[:end_match.start()]

    return rest


# ════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ════════════════════════════════════════════════════════════════════

@dataclass
class IntegrityResult:
    """Result of an integrity check.  `passed` is the ONLY field callers
    should branch on."""
    passed: bool
    issues: List[str] = field(default_factory=list)
    container_ratio: float = 0.0
    motion_ratio: float = 0.0
    text_ratio: float = 0.0
    transform_count: int = 0

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[{status}] containers={self.container_ratio:.0%} "
            f"motion={self.motion_ratio:.0%} text={self.text_ratio:.0%} "
            f"transforms={self.transform_count} issues={len(self.issues)}"
        )


# ════════════════════════════════════════════════════════════════════
# SPEC-LEVEL INTEGRITY GATE
# ════════════════════════════════════════════════════════════════════

def validate_spec_integrity(
    spec_dict: dict,
    visual_contract: dict,
) -> IntegrityResult:
    """
    HARD gate for scene specifications.

    Returns IntegrityResult.passed == False when ANY of:
      1. Container elements > 30% of total elements
      2. No transformation sequence at all
      3. Zero motion actions in transformation sequence
      4. > 50% of non-arrow elements don't match contract entities
      5. Text/label elements > 25% of total

    This is NOT a scoring function — it's a binary pass/fail.
    """
    result = IntegrityResult(passed=True)
    mode = visual_contract.get("depiction_mode", "simulation")

    # No enforcement for explicit diagram mode
    if mode != "simulation":
        return result

    metaphor = spec_dict.get("visual_metaphor", {})
    elements = metaphor.get("visual_elements", [])
    transform = spec_dict.get("transformation", {})
    sequence = transform.get("sequence", [])

    if not elements:
        result.passed = False
        result.issues.append("No visual elements in specification")
        return result

    # ── 1. Container ratio (HARD: ≤ 30%) ──
    container_count = sum(
        1 for e in elements
        if e.get("element_type", "").lower() in CONTAINER_ELEMENT_TYPES
    )
    result.container_ratio = container_count / len(elements)
    if result.container_ratio > 0.30:
        result.passed = False
        result.issues.append(
            f"Container elements {container_count}/{len(elements)} "
            f"({result.container_ratio:.0%}) exceeds 30% limit"
        )

    # ── 2. Transformation sequence exists ──
    if not sequence:
        result.passed = False
        result.issues.append("No transformation sequence — simulation needs state changes")

    # ── 3. Motion actions present ──
    if sequence:
        motion_count = sum(
            1 for s in sequence
            if s.get("action", "").lower() in MOTION_ACTIONS
        )
        total = len(sequence)
        result.motion_ratio = motion_count / total if total > 0 else 0.0
        result.transform_count = motion_count
        if motion_count == 0:
            result.passed = False
            result.issues.append(
                f"Zero motion actions in {total} transformation steps"
            )

    # ── 4. Entity origin check ──
    contract_entities = visual_contract.get("entities", [])
    contract_names = set()
    for e in contract_entities:
        if isinstance(e, dict):
            for key in ("type", "semantic_role", "label"):
                val = e.get(key, "").lower().strip()
                if val:
                    contract_names.add(val)
        elif isinstance(e, str):
            contract_names.add(e.lower().strip())
    contract_names.discard("")

    if contract_names:
        non_arrow = [
            e for e in elements
            if e.get("element_type", "").lower() != "arrow"
        ]
        if non_arrow:
            foreign = 0
            for e in non_arrow:
                label = (e.get("label", "") or "").lower()
                etype = (e.get("element_type", "") or "").lower()
                eid = (e.get("id", "") or "").lower()
                combined = f"{label} {etype} {eid}"
                if not any(cn in combined or combined.strip() and cn in combined for cn in contract_names):
                    foreign += 1
            if foreign / len(non_arrow) > 0.50:
                result.passed = False
                result.issues.append(
                    f"{foreign}/{len(non_arrow)} elements don't match contract entities"
                )

    # ── 5. Text/label element ratio (HARD: ≤ 25%) ──
    text_types = {"label", "text_block", "title"}
    text_count = sum(
        1 for e in elements
        if e.get("element_type", "").lower() in text_types
    )
    result.text_ratio = text_count / len(elements) if elements else 0.0
    if result.text_ratio > 0.25:
        result.passed = False
        result.issues.append(
            f"Text elements {text_count}/{len(elements)} "
            f"({result.text_ratio:.0%}) exceeds 25% limit"
        )

    if not result.passed:
        logger.warning(
            f"🚫 SPEC INTEGRITY FAILED: {result.summary()}"
        )
    else:
        logger.info(f"✅ Spec integrity passed: {result.summary()}")

    return result


# ════════════════════════════════════════════════════════════════════
# SCRIPT-LEVEL INTEGRITY GATE
# ════════════════════════════════════════════════════════════════════

def validate_script_integrity(
    script: str,
    visual_contract: dict,
) -> IntegrityResult:
    """
    HARD gate for generated Manim scripts.

    Returns IntegrityResult.passed == False when ANY of:
      1. Motion animations < 40% of all self.play() calls
      2. Text objects > 30% of all constructed objects (in construct body only)
      3. Container classes (GlassCard/BoundaryBox/CodeBlock) > 25% of shapes
      4. Zero Transform/ReplacementTransform AND no animate.shift/move_to/scale
         AND motion_ratio < 50%  (relaxed: template code uses GrowFromCenter/
         Indicate/Circumscribe which count as motion but not as Transform)

    NOTE: Text/shape/container counting is scoped to the construct() method
    body only.  Primitive class definitions (GlassCard, Node, etc.) included
    in every generated script contain Text() and shape constructors that would
    inflate ratios if counted globally.

    This is NOT a scoring function — it's a binary pass/fail.
    """
    result = IntegrityResult(passed=True)
    mode = visual_contract.get("depiction_mode", "simulation")

    if mode != "simulation":
        return result

    # ── Scope text/shape/container counting to construct() body only ──
    # The full script includes primitive class definitions (GlassCard, Node
    # etc.) whose __init__ methods contain Text() and shape constructors
    # that would inflate ratios if counted.
    construct_body = _extract_construct_body(script)

    # Count various code patterns
    motion_hits = len(_RE_MOTION.findall(script))  # self.play only in construct anyway
    text_count = len(_RE_TEXT.findall(construct_body))
    shape_count = len(_RE_SHAPE.findall(construct_body))
    container_hits = len(_RE_CONTAINER_CLASS.findall(construct_body))
    play_count = script.count("self.play")
    total_objs = text_count + shape_count

    # Count transforms specifically
    transform_count = len(re.findall(
        r'\b(?:Transform|ReplacementTransform|TransformFromCopy|FadeTransform)\s*\(',
        script, re.IGNORECASE
    ))
    result.transform_count = transform_count

    # ── 1. Motion ratio (HARD: ≥ 40%) ──
    if play_count > 0:
        result.motion_ratio = motion_hits / play_count
        if result.motion_ratio < 0.40:
            result.passed = False
            result.issues.append(
                f"Motion {motion_hits}/{play_count} ({result.motion_ratio:.0%}) "
                f"below 40% minimum"
            )
    elif motion_hits == 0:
        result.passed = False
        result.motion_ratio = 0.0
        result.issues.append("No self.play() calls and no motion animations")

    # ── 2. Text ratio (HARD: ≤ 30%) ──
    if total_objs > 0:
        result.text_ratio = text_count / total_objs
        if result.text_ratio > 0.30:
            result.passed = False
            result.issues.append(
                f"Text objects {text_count}/{total_objs} ({result.text_ratio:.0%}) "
                f"exceeds 30% limit"
            )
    else:
        result.text_ratio = 0.0

    # ── 3. Container class ratio (HARD: ≤ 25%) ──
    if shape_count > 0:
        result.container_ratio = container_hits / shape_count
        if result.container_ratio > 0.25:
            result.passed = False
            result.issues.append(
                f"Container classes {container_hits}/{shape_count} "
                f"({result.container_ratio:.0%}) exceeds 25% limit"
            )
    else:
        result.container_ratio = 0.0

    # ── 4. Has animate.shift / move_to / scale ──
    # Template-generated code uses GrowFromCenter / Indicate / Circumscribe
    # which register as motion but NOT as Transform() or animate.shift().
    # Only fail this check when the script also lacks motion overall.
    has_animate = bool(re.search(
        r'\b(?:animate\.shift|animate\.move_to|animate\.scale|animate\.rotate)\s*[\(.]',
        script, re.IGNORECASE,
    ))
    if not has_animate and transform_count == 0 and result.motion_ratio < 0.50:
        result.passed = False
        result.issues.append(
            "No animate.shift/move_to/scale and no Transform and low motion — "
            "simulation must move/morph elements"
        )

    if not result.passed:
        logger.warning(
            f"🚫 SCRIPT INTEGRITY FAILED: {result.summary()}"
        )
    else:
        logger.info(f"✅ Script integrity passed: {result.summary()}")

    return result


# ════════════════════════════════════════════════════════════════════
# SPEC ENFORCER — HARD REPLACEMENT OF CONTAINER ELEMENTS
# ════════════════════════════════════════════════════════════════════

# Map container types → simulation-appropriate replacements
_ELEMENT_REPLACEMENT_MAP = {
    "glass_card": "node",
    "boundary_box": "icon_badge",
    "code_block": "tag_pill",
    "text_block": "tag_pill",
    "rounded_rectangle": "node",
}


def enforce_simulation_elements(
    spec_dict: dict,
    visual_contract: dict,
) -> Tuple[dict, List[str]]:
    """
    HARD enforcement: replace container elements with simulation-appropriate
    types when depiction_mode == "simulation".

    Unlike restrict_quality_pipeline_authority() in visual_quality_validator.py,
    this function:
      - ALWAYS runs (not optional)
      - Logs replacements as ENFORCED, not just "patched"
      - Ensures motion actions exist in transformation sequence
      - Injects contract entities that are missing

    Returns (modified_spec_dict, list_of_enforcements).
    """
    mode = visual_contract.get("depiction_mode", "simulation")
    enforcements: List[str] = []

    if mode != "simulation":
        return spec_dict, enforcements

    metaphor = spec_dict.get("visual_metaphor", {})
    elements = metaphor.get("visual_elements", [])

    # ── 1. Replace container elements ──
    for elem in elements:
        etype = elem.get("element_type", "").lower()
        if etype in _ELEMENT_REPLACEMENT_MAP:
            new_type = _ELEMENT_REPLACEMENT_MAP[etype]
            enforcements.append(
                f"ENFORCED: {etype} → {new_type} (element '{elem.get('label', elem.get('id', '?'))}')"
            )
            elem["element_type"] = new_type

    # ── 2. Ensure transformation sequence has motion ──
    transform = spec_dict.get("transformation", {})
    sequence = transform.get("sequence", [])

    has_motion = any(
        s.get("action", "").lower() in MOTION_ACTIONS
        for s in sequence
    )
    if not has_motion:
        # Upgrade all fade_in → grow_from_center
        upgraded = 0
        for step in sequence:
            action = step.get("action", "").lower()
            if action in ("fade_in", "write", "appear"):
                step["action"] = "grow_from_center"
                upgraded += 1
        if upgraded:
            enforcements.append(
                f"ENFORCED: Upgraded {upgraded} static actions → grow_from_center"
            )
        # If still no motion, inject one
        if not any(s.get("action", "").lower() in MOTION_ACTIONS for s in sequence):
            if elements:
                target_id = elements[0].get("id", "element_0")
                sequence.insert(0, {
                    "action": "grow_from_center",
                    "target": target_id,
                    "description": "Initial element emergence (enforced by simulation integrity)",
                })
                enforcements.append(
                    f"ENFORCED: Injected grow_from_center for '{target_id}'"
                )

    # ── 3. Inject missing contract entities ──
    contract_entities = visual_contract.get("entities", [])
    existing_labels = set()
    for e in elements:
        label = (e.get("label", "") or "").lower().strip()
        eid = (e.get("id", "") or "").lower().strip()
        if label:
            existing_labels.add(label)
        if eid:
            existing_labels.add(eid)

    for ce in contract_entities[:5]:
        ce_name = ""
        if isinstance(ce, dict):
            ce_name = ce.get("type", ce.get("label", ""))
        elif isinstance(ce, str):
            ce_name = ce
        if not ce_name:
            continue

        ce_lower = ce_name.lower().strip()
        # Check if ANY existing element label/id contains this entity name
        if not any(ce_lower in el or el in ce_lower for el in existing_labels if el):
            safe_id = f"contract_{ce_lower.replace(' ', '_')[:20]}"
            new_elem = {
                "id": safe_id,
                "element_type": "node",
                "label": ce_name[:25],
                "position": "center",
                "size": "medium",
                "color": "TEAL",
            }
            elements.append(new_elem)
            existing_labels.add(ce_lower)
            enforcements.append(
                f"ENFORCED: Injected missing contract entity '{ce_name}' as node"
            )

    if enforcements:
        logger.info(
            f"🔒 SIMULATION INTEGRITY enforced {len(enforcements)} corrections:"
        )
        for e in enforcements:
            logger.info(f"   → {e}")

    return spec_dict, enforcements


# ════════════════════════════════════════════════════════════════════
# ELEMENT-TYPE ENFORCEMENT FOR CODE GENERATOR
# ════════════════════════════════════════════════════════════════════

def get_enforced_element_type(
    original_type: str,
    visual_contract: Optional[dict],
) -> str:
    """
    Called by ManimCodeGenerator._generate_element_code() to enforce
    element type at code-generation time.

    When depiction_mode == "simulation", container types are replaced
    with simulation-appropriate types BEFORE the template is selected.

    This is the LAST LINE OF DEFENSE — even if the spec slipped through
    with a glass_card, the code generator will NOT emit GlassCard().
    """
    if not visual_contract:
        return original_type

    mode = visual_contract.get("depiction_mode", "simulation")
    if mode != "simulation":
        return original_type

    original_lower = original_type.lower() if isinstance(original_type, str) else str(original_type).lower()
    # Also handle enum values like "ElementType.GLASS_CARD"
    clean = original_lower.replace("elementtype.", "").strip()

    if clean in _ELEMENT_REPLACEMENT_MAP:
        replacement = _ELEMENT_REPLACEMENT_MAP[clean]
        logger.debug(
            f"🔒 Code generator: enforced {clean} → {replacement}"
        )
        return replacement

    return original_type
