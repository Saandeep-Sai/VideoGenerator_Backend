"""
VISUAL SIMULATION VALIDATOR
============================

Global gate used by BOTH legacy and quality pipelines.

Called BEFORE Manim execution to reject slide-show directions
and AFTER script generation to reject text-box-heavy code.

Architecture position:
  Concept Visualizer → Scene Direction → **VALIDATOR** → Manim Execution
"""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ================================================================
# VISUAL CONTRACT — GLOBAL STRUCTURE
# ================================================================

def make_visual_contract(
    visual_model: str = "data_flow",
    depiction_mode: str = "simulation",
    entities: Optional[List[dict]] = None,
    behaviors: Optional[List[str]] = None,
    animation_primitives: Optional[List[str]] = None,
    camera_strategy: str = "follow_process",
    transformation_chain: Optional[List[dict]] = None,
) -> dict:
    """
    Build a canonical visual_contract dict.

    This object is the SINGLE SOURCE OF TRUTH for what must appear
    on screen.  It persists unchanged through every pipeline stage.

    Fields
    ------
    depiction_mode : "simulation" | "diagram"
        When "simulation" — the scene MUST show moving entities,
        state changes, and continuous motion.  Downstream stages
        MUST NOT convert this into labeled boxes / glass_cards.

    entities : list[dict]
        Objects that MUST appear on screen.  Each dict has at least
        ``{"type": ..., "semantic_role": ...}``.

    behaviors : list[str]
        Verbs that MUST be animated (e.g. "propagate", "activate").

    transformation_chain : list[dict]
        Ordered sequence of state transitions the scene MUST walk
        through.  Each entry: ``{"from_state": ..., "to_state": ...,
        "trigger": ...}``.  Quality pipeline may NOT skip entries.

    animation_primitives : list[str]
        Manim-level primitives expected (e.g. "MoveAlongPath").

    camera_strategy : str
        Camera intent ("follow_process", "zoom_to_detail", …).
    """
    return {
        "visual_model": visual_model,
        "depiction_mode": depiction_mode,
        "entities": entities or [
            {"type": "node", "semantic_role": "primary element"},
        ],
        "behaviors": behaviors or ["appear", "transform"],
        "transformation_chain": transformation_chain or [],
        "animation_primitives": animation_primitives or ["sequential_stages"],
        "camera_strategy": camera_strategy,
        # Enforcement metadata
        "_contract_version": 2,
        "_frozen": True,  # Downstream stages MUST NOT mutate
    }


def contract_from_visualizer(visualizer_output: dict) -> dict:
    """Convert raw concept_visualizer output into a frozen contract."""
    # Build transformation_chain from visualizer's stages / sequence
    raw_chain = visualizer_output.get("transformation_chain", [])
    if not raw_chain:
        # Derive from stages if available
        stages = visualizer_output.get("stages", [])
        if stages:
            raw_chain = []
            for idx in range(len(stages) - 1):
                raw_chain.append({
                    "from_state": stages[idx] if isinstance(stages[idx], str) else str(stages[idx]),
                    "to_state": stages[idx + 1] if isinstance(stages[idx + 1], str) else str(stages[idx + 1]),
                    "trigger": "progression",
                })
    return make_visual_contract(
        visual_model=visualizer_output.get("visual_model", "data_flow"),
        depiction_mode=visualizer_output.get("depiction_type", "simulation"),
        entities=visualizer_output.get("entities", []),
        behaviors=visualizer_output.get("behaviors", []),
        animation_primitives=visualizer_output.get("animation_primitives", []),
        camera_strategy=visualizer_output.get("camera_strategy", "follow_process"),
        transformation_chain=raw_chain,
    )


def serialize_contract(contract: dict) -> str:
    """JSON-encode a contract for storage on segment objects."""
    return json.dumps(contract, ensure_ascii=False)


def deserialize_contract(contract_json: str) -> dict:
    """Restore a contract from JSON string."""
    if not contract_json:
        return make_visual_contract()
    try:
        return json.loads(contract_json)
    except (json.JSONDecodeError, TypeError):
        return make_visual_contract()


def contract_prompt_block(contract: dict) -> str:
    """
    Render the contract as a prompt-injectable text block.

    This is the HIGHEST-AUTHORITY section inserted at the TOP of any
    LLM prompt that generates scene specifications, directions, or code.
    """
    mode = contract.get("depiction_mode", "simulation")
    model = contract.get("visual_model", "")
    entities = contract.get("entities", [])
    behaviors = contract.get("behaviors", [])
    chain = contract.get("transformation_chain", [])
    primitives = contract.get("animation_primitives", [])
    camera = contract.get("camera_strategy", "follow_process")

    # Format entities
    entity_lines = []
    for e in entities[:8]:
        if isinstance(e, dict):
            entity_lines.append(f"  - {e.get('type', '?')} ({e.get('semantic_role', '')})")
        else:
            entity_lines.append(f"  - {e}")
    entities_str = "\n".join(entity_lines) if entity_lines else "  (none specified)"

    # Format transformation chain
    chain_lines = []
    for step in chain[:6]:
        if isinstance(step, dict):
            chain_lines.append(
                f"  {step.get('from_state', '?')} → {step.get('to_state', '?')} "
                f"[{step.get('trigger', '')}]"
            )
        else:
            chain_lines.append(f"  {step}")
    chain_str = "\n".join(chain_lines) if chain_lines else "  (derive from behaviors)"

    behaviors_str = ", ".join(behaviors[:8]) if behaviors else "(none)"
    primitives_str = ", ".join(primitives[:8]) if primitives else "(none)"

    block = f"""
╔══════════════════════════════════════════════════════════════╗
║  VISUAL CONTRACT — HIGHEST AUTHORITY — DO NOT OVERRIDE      ║
╚══════════════════════════════════════════════════════════════╝

depiction_mode: {mode}
visual_model:   {model}
camera:         {camera}

ENTITIES (must appear on screen):
{entities_str}

BEHAVIORS (must be animated):
  {behaviors_str}

TRANSFORMATION CHAIN (must be walked in order):
{chain_str}

ANIMATION PRIMITIVES:
  {primitives_str}

RULES WHEN depiction_mode == "simulation":
  1. DO NOT replace entities with labeled boxes, glass_cards, or boundary_boxes.
  2. DO NOT convert motion behaviors into static arrows or text descriptions.
  3. EVERY entity above MUST appear as a MOVING object (Dot, Circle, Arrow path).
  4. At least ONE ReplacementTransform or MoveAlongPath MUST exist.
  5. Text objects (Text, MathTex, MarkupText) ≤ 20% of all scene objects.
  6. Total active-motion runtime ≥ 50% of scene duration.
  7. The transformation chain MUST be walked — you may NOT skip states.
"""
    return block.strip()


# ================================================================
# DIRECTION-LEVEL VALIDATION
# (Called after Scene Direction, before Manim Execution)
# ================================================================

_LABEL_SIGNALS = frozenset([
    "box", "label", "text", "title", "heading", "card",
    "rectangle with text", "glass_card", "boundary_box",
])

_MOTION_VERBS = frozenset([
    "propagat", "flow", "pulse", "morph", "transform", "grow",
    "travel", "move", "shift", "scale", "fade", "rotate",
    "glow", "activate", "emit", "swap", "slide", "bounce",
    "converge", "diverge", "split", "merge", "draw", "create",
])


def validate_visual_simulation(
    scene_direction: dict,
    visual_contract: dict,
) -> Tuple[bool, List[str], float]:
    """
    Gate check: does *scene_direction* honour *visual_contract*?

    Returns
    -------
    (passed, issues, score)
        passed : bool  — True when score >= 0.5
        issues : list  — human-readable problems
        score  : float — 0.0 … 1.0
    """
    issues: List[str] = []
    score = 1.0
    contract_mode = visual_contract.get("depiction_mode", "simulation")

    # ── 1. depiction_mode alignment ──
    dir_mode = scene_direction.get("depiction_mode", "")
    if contract_mode == "simulation" and dir_mode == "diagram":
        issues.append("Contract requires simulation but direction uses diagram")
        score -= 0.35

    # ── 2. Entity origin check ──
    # Contract entities are strings (names), direction elements are dicts
    contract_entities = visual_contract.get("entities", [])
    contract_entity_names = set()
    for e in contract_entities:
        if isinstance(e, str):
            contract_entity_names.add(e.lower())
        elif isinstance(e, dict):
            contract_entity_names.add(e.get("type", "").lower())
            contract_entity_names.add(e.get("label", "").lower())
    contract_entity_names.discard("")
    
    dir_elements = scene_direction.get("elements", [])
    if dir_elements and contract_entity_names:
        foreign_count = 0
        for el in dir_elements:
            el_label = ""
            if isinstance(el, dict):
                el_label = el.get("label", el.get("type", "")).lower()
            elif isinstance(el, str):
                el_label = el.lower()
            # Check if label matches any contract entity (substring match)
            if el_label and not any(ce in el_label or el_label in ce for ce in contract_entity_names):
                foreign_count += 1
        if foreign_count > len(dir_elements) * 0.5:
            issues.append(
                f"{foreign_count}/{len(dir_elements)} elements not in visual contract entities"
            )
            score -= 0.2

    # ── 3. Label-heavy check ──
    if dir_elements:
        label_count = sum(
            1 for el in dir_elements
            if any(sig in json.dumps(el).lower() for sig in _LABEL_SIGNALS)
        )
        if label_count > len(dir_elements) * 0.6:
            issues.append(f"Label-heavy: {label_count}/{len(dir_elements)} elements")
            score -= 0.25

    # ── 4. Behaviour coverage ──
    contract_behaviors = visual_contract.get("behaviors", [])
    beats = scene_direction.get("direction_beats", [])
    beats_text = json.dumps(beats).lower() if beats else ""
    matched = sum(1 for b in contract_behaviors if any(w in beats_text for w in b.lower().split()[:3]))
    if contract_behaviors and matched < max(1, len(contract_behaviors) * 0.3):
        issues.append("Contract behaviors under-represented in direction beats")
        score -= 0.15

    # ── 5. Motion presence ──
    if beats:
        has_motion = any(
            any(v in json.dumps(b).lower() for v in _MOTION_VERBS) for b in beats
        )
        if not has_motion:
            issues.append("No motion verbs in direction beats — slideshow risk")
            score -= 0.2

    # ── 6. Minimum beat count ──
    if len(beats) < 3:
        issues.append(f"Only {len(beats)} beats — need ≥3 for continuous motion")
        score -= 0.15

    # ── 7. Transformation chain ──
    if not scene_direction.get("transformation_chain"):
        issues.append("No transformation_chain — nothing evolves")
        score -= 0.1

    score = max(0.0, min(1.0, score))
    return score >= 0.5, issues, round(score, 2)


# ================================================================
# SCRIPT-LEVEL VALIDATION (execution enforcement)
# (Called after Manim code generation)
# ================================================================

_TEXT_OBJECT_PATTERN = re.compile(
    r'\b(?:Text|MarkupText|MathTex|Tex|Paragraph|BulletedList)\s*\(', re.IGNORECASE
)
_SHAPE_OBJECT_PATTERN = re.compile(
    r'\b(?:Circle|Square|Rectangle|Dot|Line|Arrow|Arc|Polygon|'
    r'Ellipse|Star|Triangle|RoundedRectangle|VGroup|Annulus)\s*\(', re.IGNORECASE
)
_MOTION_ANIMATION_PATTERN = re.compile(
    r'\b(?:MoveAlongPath|shift|animate\.shift|animate\.move_to|'
    r'Transform|ReplacementTransform|MoveToTarget|'
    r'animate\.scale|GrowFromCenter|Create|DrawBorderThenFill|'
    r'GrowArrow|Indicate|Flash|Circumscribe|'
    r'LaggedStart|AnimationGroup|Succession)\s*[\(.]', re.IGNORECASE
)
_STATIC_PLAY_PATTERN = re.compile(
    r'self\.play\s*\(\s*(?:FadeIn|Write)\s*\(', re.IGNORECASE
)


def validate_script_simulation(
    script: str,
    visual_contract: dict,
) -> Tuple[bool, List[str], float]:
    """
    Post-generation gate: does the Manim *script* implement simulation?

    Checks (when contract.depiction_mode == simulation):
      - Text objects ≤ 20 % of all scene objects
      - At least one motion animation
      - At least one Transform / replacement
      - Not dominated by static FadeIn/Write

    Returns (passed, issues, score).
    """
    issues: List[str] = []
    score = 1.0
    contract_mode = visual_contract.get("depiction_mode", "simulation")

    if contract_mode != "simulation":
        return True, [], 1.0  # No enforcement for diagrams

    text_count = len(_TEXT_OBJECT_PATTERN.findall(script))
    shape_count = len(_SHAPE_OBJECT_PATTERN.findall(script))
    total_objs = text_count + shape_count

    # ── Text ratio ──
    if total_objs > 0 and text_count / total_objs > 0.4:
        issues.append(
            f"Text-heavy script: {text_count}/{total_objs} objects are text "
            f"({text_count/total_objs:.0%})"
        )
        score -= 0.3

    # ── Motion presence ──
    motion_hits = len(_MOTION_ANIMATION_PATTERN.findall(script))
    if motion_hits == 0:
        issues.append("No motion/transform animations found")
        score -= 0.35
    elif motion_hits < 3:
        issues.append(f"Only {motion_hits} motion animations — simulation requires more")
        score -= 0.15

    # ── Static dominance ──
    static_count = len(_STATIC_PLAY_PATTERN.findall(script))
    play_count = script.count("self.play")
    if play_count > 0 and static_count / play_count > 0.6:
        issues.append(
            f"Static-dominated: {static_count}/{play_count} play() calls are FadeIn/Write"
        )
        score -= 0.2

    # ── Transform presence ──
    has_transform = bool(re.search(
        r'\b(?:Transform|ReplacementTransform|TransformFromCopy)\s*\(', script
    ))
    if not has_transform:
        issues.append("No Transform animations — simulation should morph elements")
        score -= 0.1

    score = max(0.0, min(1.0, score))
    return score >= 0.45, issues, round(score, 2)


# ================================================================
# CONVENIENCE: Validate quality-pipeline SceneSpec against contract
# ================================================================

def validate_quality_spec_against_contract(
    scene_spec_dict: dict,
    visual_contract: dict,
) -> Tuple[bool, List[str]]:
    """
    Ensure a quality-pipeline SceneSpecification does not contradict
    the visual contract.

    Checks:
      - metaphor_type alignment
      - element types don't revert to text-boxes when contract says simulation
      - transformation sequence exists

    Returns (passed, issues).
    """
    issues: List[str] = []
    mode = visual_contract.get("depiction_mode", "simulation")

    if mode != "simulation":
        return True, []

    # Check visual_metaphor
    metaphor = scene_spec_dict.get("visual_metaphor", {})
    elements = metaphor.get("visual_elements", [])
    if elements:
        box_types = {"boundary_box", "glass_card", "text_block"}
        box_count = sum(
            1 for e in elements
            if e.get("element_type", "") in box_types
        )
        if box_count > len(elements) * 0.5:
            issues.append(
                f"Quality spec has {box_count}/{len(elements)} box/text elements "
                f"but contract requires simulation"
            )

    # Check transformation
    transform = scene_spec_dict.get("transformation", {})
    sequence = transform.get("sequence", [])
    if not sequence:
        issues.append("Quality spec has no transformation sequence")

    # Check at least one move/scale/transform action
    actions = [s.get("action", "") for s in sequence]
    active_actions = {"move", "scale", "transform", "morph", "connect", "pulse"}
    if not any(a in active_actions for a in actions):
        issues.append(
            f"Quality spec actions {actions[:5]} lack motion — simulation requires "
            f"move/scale/transform"
        )

    return len(issues) == 0, issues
