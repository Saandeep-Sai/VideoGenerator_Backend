"""
Semantic Alignment Analyzer
============================

Scores how well a scene specification visually *depicts* the narration meaning,
rather than just displaying text or labelled containers.

This is a SCORING system, not an enforcement gate.  It guides the LLM toward
better depiction through feedback — never by restricting creative freedom.

Architecture position:
    SceneSpec (LLM draft)
        → compute_semantic_alignment(narration, scene_metadata)
            → score + missing_actions + feedback_notes
        → build_refinement_prompt(alignment, narration, scene_metadata)
            → LLM revises spec (PASS 1: Semantic Enhancement)
        → existing quality polish (PASS 2: Visual Polish)
        → render

Key design decisions:
  • No rigid rules — only soft scoring dimensions
  • No element types are forbidden
  • No templates are enforced
  • Feedback asks for *enhancement*, not correction
  • High scores skip the refinement call entirely (no extra latency)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# VERB TAXONOMY — narrative action families
# ════════════════════════════════════════════════════════════════════

# Verbs → what the viewer should SEE happening on screen.
# Each key is a semantic family; values are surface forms the narration may use.

ACTION_VERB_FAMILIES: Dict[str, List[str]] = {
    "movement": [
        "move", "travel", "flow", "propagate", "send", "pass", "transfer",
        "migrate", "route", "deliver", "forward", "push", "pull",
        "shift", "slide", "drift", "glide", "traverse", "hop",
    ],
    "comparison": [
        "compare", "versus", "differ", "contrast", "match", "weigh",
        "rank", "evaluate", "benchmark", "measure", "side by side",
    ],
    "transformation": [
        "transform", "convert", "change", "morph", "evolve", "mutate",
        "compile", "parse", "encode", "decode", "translate", "map",
        "become", "turn into", "reshape",
    ],
    "connection": [
        "connect", "link", "attach", "bind", "join", "merge",
        "integrate", "couple", "bridge", "chain", "relate",
    ],
    "separation": [
        "separate", "split", "divide", "fork", "branch", "isolate",
        "detach", "decouple", "partition", "classify", "sort",
    ],
    "growth": [
        "grow", "expand", "increase", "accumulate", "build", "stack",
        "add", "append", "extend", "scale up", "inflate",
    ],
    "state_change": [
        "activate", "enable", "disable", "toggle", "switch", "trigger",
        "fire", "lock", "unlock", "open", "close", "start", "stop",
        "on", "off", "begin", "halt", "resume",
    ],
    "interaction": [
        "interact", "collide", "swap", "exchange", "handshake",
        "negotiate", "respond", "request", "receive", "emit",
        "signal", "notify", "broadcast", "listen",
    ],
    "ordering": [
        "sort", "order", "arrange", "prioritize", "queue", "schedule",
        "sequence", "align", "organize", "reorder", "rearrange",
    ],
}

# Flatten for fast lookup: verb → family name
_VERB_TO_FAMILY: Dict[str, str] = {}
for family, verbs in ACTION_VERB_FAMILIES.items():
    for verb in verbs:
        _VERB_TO_FAMILY[verb.lower()] = family


# ════════════════════════════════════════════════════════════════════
# SPEC METADATA EXTRACTORS
# ════════════════════════════════════════════════════════════════════

# TransformAction values that imply visible motion/change
_MOTION_ACTIONS = frozenset([
    "move", "slide_in", "slide_in_from_left", "slide_in_from_right",
    "slide_in_from_top", "slide_in_from_bottom", "flow", "bounce",
    "grow_from_center", "grow_from_point", "spin", "scale", "zoom",
    "zoom_in", "zoom_out", "shrink",
])

_INTERACTION_ACTIONS = frozenset([
    "connect", "draw_arrow", "transform", "morph", "fade_transform",
])

_STATE_CHANGE_ACTIONS = frozenset([
    "highlight", "pulse", "flash", "circumscribe", "glow",
    "circle_indicate", "emphasize", "focus", "apply_wave",
    "show_passing_flash", "wave", "ripple",
])

_STATIC_ACTIONS = frozenset([
    "appear", "fade_in", "enter", "write", "trace",
    "draw_border_then_fill",
])


def _extract_narration_verbs(narration: str) -> Dict[str, List[str]]:
    """Extract action verbs from narration text, grouped by semantic family.

    Handles morphological variants (past tense, gerund, 3rd person) by
    generating suffix patterns: compare → compare|compared|comparing|compares.

    Returns {family_name: [matched_verb, ...]}
    """
    narration_lower = narration.lower()
    found: Dict[str, List[str]] = {}

    for verb, family in _VERB_TO_FAMILY.items():
        # Build pattern that matches common English inflections
        base = re.escape(verb)
        # Handle multi-word verbs like "turn into" — match as-is + inflected first word
        if " " in verb:
            parts = verb.split(" ", 1)
            first = re.escape(parts[0])
            rest = re.escape(parts[1])
            pattern = rf'\b(?:{first}(?:s|ed|ing|es|d)?)\s+{rest}\b'
        else:
            # Single-word verb inflection patterns:
            #   compare  → compare|compares|compared|comparing
            #   swap     → swap|swaps|swapped|swapping  (consonant doubling)
            #   classify → classify|classifies|classified|classifying
            last_char = verb[-1] if verb else ""
            if last_char == "e":
                # -e verbs: fade → fading, faded, fades
                pattern = rf'\b{base}(?:s|d|ing)?\b'
            elif last_char == "y" and len(verb) > 1 and verb[-2] not in "aeiou":
                # -Cy verbs: classify → classified, classifies, classifying
                stem = re.escape(verb[:-1])
                pattern = rf'\b(?:{base}(?:s|ing)?|{stem}(?:ied|ies))\b'
            elif last_char in "bdfgklmnprst" and len(verb) > 2 and verb[-2] in "aeiou" and verb[-3] not in "aeiou":
                # CVC verbs: swap → swapped/swapping, stop → stopped
                doubled = re.escape(verb + last_char)
                pattern = rf'\b(?:{base}(?:s|ed|ing)?|{doubled}(?:ed|ing))\b'
            else:
                pattern = rf'\b{base}(?:s|ed|ing|es|d)?\b'

        if re.search(pattern, narration_lower):
            found.setdefault(family, []).append(verb)

    return found


def _extract_spec_signals(scene_metadata: dict) -> Dict[str, bool]:
    """Probe scene_metadata for depiction signals.

    Accepts either a raw spec dict (from to_dict()) or a simplified metadata
    dict with keys: elements, transformation_sequence, narration, etc.

    Returns a dict of boolean signals:
        has_motion, has_interaction, has_state_change, has_static_only,
        has_spatial_variety, entity_count, action_count, unique_targets
    """
    # ── Elements ──
    vm = scene_metadata.get("visual_metaphor", {})
    elements = vm.get("visual_elements", scene_metadata.get("elements", []))
    element_ids = {e.get("id", "") for e in elements if isinstance(e, dict)}
    element_types = [
        (e.get("element_type", "") if isinstance(e, dict) else "").lower()
        for e in elements
    ]

    positions = set()
    for e in elements:
        if isinstance(e, dict):
            pos = (e.get("position") or "").lower()
            if pos:
                positions.add(pos)

    # ── Transformation sequence ──
    xform = scene_metadata.get("transformation", {})
    sequence = xform.get("sequence", scene_metadata.get("transformation_sequence", []))
    actions = [
        (s.get("action", "") if isinstance(s, dict) else "").lower()
        for s in sequence
    ]
    targets = set(
        (s.get("target", "") if isinstance(s, dict) else "").lower()
        for s in sequence
    )

    has_motion = any(a in _MOTION_ACTIONS for a in actions)
    has_interaction = any(a in _INTERACTION_ACTIONS for a in actions)
    has_state_change = any(a in _STATE_CHANGE_ACTIONS for a in actions)
    has_static_only = all(a in _STATIC_ACTIONS or a == "" for a in actions) if actions else True

    return {
        "has_motion": has_motion,
        "has_interaction": has_interaction,
        "has_state_change": has_state_change,
        "has_static_only": has_static_only,
        "has_spatial_variety": len(positions) >= 3,
        "entity_count": len(elements),
        "action_count": len(actions),
        "unique_targets": len(targets),
        "element_types": element_types,
        "actions": actions,
    }


# ════════════════════════════════════════════════════════════════════
# ALIGNMENT RESULT
# ════════════════════════════════════════════════════════════════════

@dataclass
class SemanticAlignmentResult:
    """Soft alignment score — guides improvement, never blocks."""
    score: int = 0                             # 0–100
    missing_actions: List[str] = field(default_factory=list)
    feedback_notes: List[str] = field(default_factory=list)
    # Dimension breakdown (each 0–25)
    motion_presence: int = 0
    entity_interaction: int = 0
    state_change: int = 0
    visual_narration_match: int = 0

    def summary(self) -> str:
        return (
            f"[score={self.score}] motion={self.motion_presence} "
            f"interaction={self.entity_interaction} "
            f"state={self.state_change} "
            f"match={self.visual_narration_match}"
        )


# ════════════════════════════════════════════════════════════════════
# CORE SCORING
# ════════════════════════════════════════════════════════════════════

# Threshold below which a refinement prompt is generated
ALIGNMENT_THRESHOLD = 60


def compute_semantic_alignment(
    narration: str,
    scene_metadata: dict,
) -> SemanticAlignmentResult:
    """Score how well scene_metadata visually depicts the narration.

    This is purely informational scoring — no enforcement, no hard gates.

    Dimensions (each 0–25):
        motion_presence        → scene has moving objects
        entity_interaction     → elements connect / transform / affect each other
        state_change           → visible emphasis, highlighting, state shifts
        visual_narration_match → narration verbs are reflected in the spec

    Args:
        narration: The spoken narration text for this scene.
        scene_metadata: A spec dict (from SceneSpecification.to_dict()) or a
            simplified dict with keys like elements, transformation_sequence.

    Returns:
        SemanticAlignmentResult with score 0–100, missing_actions, feedback_notes.
    """
    result = SemanticAlignmentResult()

    narration_verbs = _extract_narration_verbs(narration)
    signals = _extract_spec_signals(scene_metadata)

    # ═══════════════════════════════════════════════════════════════
    # Dimension 1: MOTION PRESENCE (0–25)
    # ═══════════════════════════════════════════════════════════════
    if signals["has_motion"]:
        motion_actions = sum(
            1 for a in signals["actions"] if a in _MOTION_ACTIONS
        )
        # Partial credit for some motion; full credit for ≥ 3 motion actions
        result.motion_presence = min(25, 10 + motion_actions * 5)
    elif not signals["has_static_only"]:
        # Some non-static actions but no explicit motion
        result.motion_presence = 8
    else:
        result.motion_presence = 0
        result.feedback_notes.append(
            "Scene has no moving objects — consider adding motion to depict the narration."
        )

    # ═══════════════════════════════════════════════════════════════
    # Dimension 2: ENTITY INTERACTION (0–25)
    # ═══════════════════════════════════════════════════════════════
    if signals["has_interaction"]:
        result.entity_interaction = 20
        if signals["unique_targets"] >= 3:
            result.entity_interaction = 25
    elif signals["unique_targets"] >= 2 and signals["action_count"] >= 3:
        # Multiple targets animated — implicit interaction
        result.entity_interaction = 12
    else:
        result.entity_interaction = 0
        if signals["entity_count"] >= 2:
            result.feedback_notes.append(
                "Multiple entities exist but don't interact — "
                "consider connecting them with arrows, transforms, or motion."
            )

    # ═══════════════════════════════════════════════════════════════
    # Dimension 3: STATE CHANGE (0–25)
    # ═══════════════════════════════════════════════════════════════
    if signals["has_state_change"]:
        state_actions = sum(
            1 for a in signals["actions"] if a in _STATE_CHANGE_ACTIONS
        )
        result.state_change = min(25, 10 + state_actions * 5)
    else:
        result.state_change = 0
        result.feedback_notes.append(
            "No visible state changes — consider highlighting key moments "
            "with pulse, flash, or color shifts."
        )

    # ═══════════════════════════════════════════════════════════════
    # Dimension 4: VISUAL-NARRATION MATCH (0–25)
    # ═══════════════════════════════════════════════════════════════
    if not narration_verbs:
        # Narration has no action verbs — probably a definition/intro scene
        # Give moderate credit since there's nothing to "depict"
        result.visual_narration_match = 15
    else:
        matched_families = set()
        unmatched_families: List[str] = []

        for family, verbs in narration_verbs.items():
            # Check if spec addresses this family
            family_addressed = False

            if family in ("movement",) and signals["has_motion"]:
                family_addressed = True
            elif family in ("comparison",) and signals["has_spatial_variety"]:
                family_addressed = True
            elif family in ("transformation",) and (
                signals["has_interaction"]
                or any(a in ("transform", "morph", "fade_transform") for a in signals["actions"])
            ):
                family_addressed = True
            elif family in ("connection",) and signals["has_interaction"]:
                family_addressed = True
            elif family in ("separation",) and signals["unique_targets"] >= 2:
                family_addressed = True
            elif family in ("growth",) and any(
                a in ("grow_from_center", "scale", "zoom_in", "grow_from_point")
                for a in signals["actions"]
            ):
                family_addressed = True
            elif family in ("state_change",) and signals["has_state_change"]:
                family_addressed = True
            elif family in ("interaction", "ordering") and (
                signals["has_interaction"] or signals["has_motion"]
            ):
                family_addressed = True

            if family_addressed:
                matched_families.add(family)
            else:
                unmatched_families.append(family)
                # Build actionable feedback
                example_verbs = ", ".join(verbs[:3])
                result.missing_actions.append(
                    f"Narration mentions {family} ({example_verbs}) "
                    f"but no matching visual action was found."
                )

        total = len(narration_verbs)
        matched = len(matched_families)
        if total > 0:
            result.visual_narration_match = round(25 * matched / total)
        else:
            result.visual_narration_match = 15

    # ═══════════════════════════════════════════════════════════════
    # AGGREGATE
    # ═══════════════════════════════════════════════════════════════
    result.score = (
        result.motion_presence
        + result.entity_interaction
        + result.state_change
        + result.visual_narration_match
    )

    logger.info(
        f"📊 Semantic alignment: {result.summary()} "
        f"(narration verbs: {list(narration_verbs.keys()) if narration_verbs else 'none'})"
    )

    return result


# ════════════════════════════════════════════════════════════════════
# REFINEMENT PROMPT BUILDER
# ════════════════════════════════════════════════════════════════════

def build_refinement_prompt(
    alignment: SemanticAlignmentResult,
    narration: str,
    scene_metadata: dict,
    scene_index: int = 0,
) -> Optional[str]:
    """Build a creative feedback prompt when alignment score is below threshold.

    Returns None if score >= ALIGNMENT_THRESHOLD (no refinement needed).

    The prompt:
      • Preserves existing layout
      • Asks for *enhancement*, not correction
      • Provides specific feedback notes
      • Never forbids element types or animation styles
    """
    if alignment.score >= ALIGNMENT_THRESHOLD:
        return None

    # Gather feedback bullets
    bullets: List[str] = []

    for note in alignment.feedback_notes:
        bullets.append(f"• {note}")

    for action in alignment.missing_actions:
        bullets.append(f"• {action}")

    if not bullets:
        bullets.append(
            "• The scene feels static — make the narration meaning more visible "
            "through motion, interaction, or transformation."
        )

    feedback_block = "\n".join(bullets)

    # Extract current element summary for context
    vm = scene_metadata.get("visual_metaphor", {})
    elements = vm.get("visual_elements", scene_metadata.get("elements", []))
    elem_summary = ", ".join(
        f"{e.get('element_type', '?')} '{e.get('label', e.get('id', '?'))}'"
        for e in elements[:6]
        if isinstance(e, dict)
    ) or "unknown elements"

    prompt = f"""You are improving how well visuals express narration meaning.
Do NOT simplify scenes into diagrams.
Prefer visible processes over textual explanation.

---

## SCENE {scene_index + 1} ENHANCEMENT REQUEST

The current scene has these elements: {elem_summary}

Narration: "{narration}"

### Semantic alignment feedback (score: {alignment.score}/100):

{feedback_block}

### Your task:

Improve this scene so narration actions become visually observable.
Prefer motion, interaction, and transformation over explanatory containers.
Do not simplify creativity. Enhance depiction.

Specific guidance:
- Keep all existing elements and their positions where possible.
- Add or upgrade transformation steps so the viewer SEES what the narration describes.
- Any animation style is welcome — there are no forbidden elements.
- Motion should communicate meaning, not just decorate.

Return the IMPROVED scene specification as JSON (same format as the original).
Only return the JSON for this ONE scene — no surrounding array.
"""

    return prompt


# ════════════════════════════════════════════════════════════════════
# CONVENIENCE: check + build in one call
# ════════════════════════════════════════════════════════════════════

def analyze_and_build_feedback(
    narration: str,
    scene_metadata: dict,
    scene_index: int = 0,
    threshold: int = ALIGNMENT_THRESHOLD,
) -> Tuple[SemanticAlignmentResult, Optional[str]]:
    """Compute alignment and return (result, refinement_prompt_or_None).

    If score >= threshold the prompt is None → no extra LLM call needed.
    """
    alignment = compute_semantic_alignment(narration, scene_metadata)
    prompt = None if alignment.score >= threshold else build_refinement_prompt(
        alignment, narration, scene_metadata, scene_index
    )
    return alignment, prompt
