"""
CONCEPT VISUALIZER — Pipeline Intelligence Layer
=================================================

Sits between Narrative Director and Scene Director:

  Topic → Narrative Director → **Concept Visualizer** → Scene Direction → Manim Execution

Purpose:
  Convert narration MEANING into VISUAL BEHAVIOR MODELS so that
  downstream stages animate PROCESSES rather than draw labeled boxes.

Design principle:
  Every concept must become something that MOVES or CHANGES.
  Text labels are a last resort.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# ================================================================
# CONCEPT → VISUAL MODEL TAXONOMY
# ================================================================

# Each entry: (keywords, visual_model, default_depiction, canonical_entities, canonical_behaviors)
_CONCEPT_MAP: List[tuple] = [
    # Neural / network concepts
    (
        ["neural", "neuron", "network", "perceptron", "synapse", "brain"],
        "neural_network",
        "simulation",
        [
            {"type": "node",     "semantic_role": "neuron / processing unit"},
            {"type": "signal",   "semantic_role": "activation propagating forward"},
            {"type": "boundary", "semantic_role": "layer boundary"},
        ],
        [
            "nodes appear in layers",
            "signals propagate forward through connections",
            "activated nodes glow/scale up sequentially",
            "connections strengthen visually (line thickens)",
        ],
        ["grow_network", "pulse_signal", "activate_layer"],
    ),
    # Flow / pipeline / request concepts
    (
        ["flow", "request", "pipeline", "stream", "queue", "message",
         "packet", "route", "endpoint", "api", "http", "server"],
        "data_flow",
        "simulation",
        [
            {"type": "particle",  "semantic_role": "data / request moving through system"},
            {"type": "container", "semantic_role": "processing stage / server"},
            {"type": "signal",    "semantic_role": "acknowledgement / response"},
        ],
        [
            "particles enter from one side",
            "particles flow through processing containers",
            "containers pulse on receive",
            "output particles exit transformed",
        ],
        ["emit_particle", "flow_through", "transform_particle"],
    ),
    # Learning / training concepts
    (
        ["learn", "train", "gradient", "loss", "optimiz", "epoch",
         "backpropagat", "convergence", "weight", "parameter"],
        "transformation",
        "simulation",
        [
            {"type": "node",     "semantic_role": "model state"},
            {"type": "signal",   "semantic_role": "error / gradient signal"},
            {"type": "boundary", "semantic_role": "target / ideal state"},
        ],
        [
            "initial state appears rough / random",
            "error signal flows backward",
            "state transforms step by step toward target",
            "final state matches target shape",
        ],
        ["morph_state", "pulse_error", "converge_to_target"],
    ),
    # Classification / boundary concepts
    (
        ["classif", "decision boundary", "cluster", "category",
         "label", "predict", "logistic", "svm", "k-nearest"],
        "classification",
        "simulation",
        [
            {"type": "particle",  "semantic_role": "data point"},
            {"type": "boundary",  "semantic_role": "decision surface"},
            {"type": "container", "semantic_role": "class region"},
        ],
        [
            "scattered data points appear",
            "boundary line/curve emerges",
            "points migrate to correct side",
            "boundary adjusts iteratively",
        ],
        ["scatter_points", "draw_boundary", "evolve_boundary"],
    ),
    # Layer / stack / architecture concepts
    (
        ["layer", "stack", "architecture", "model", "encoder", "decoder",
         "transformer", "attention", "embedding", "module"],
        "hierarchy",
        "simulation",
        [
            {"type": "container", "semantic_role": "layer / module block"},
            {"type": "signal",    "semantic_role": "data flowing between layers"},
            {"type": "node",      "semantic_role": "operation within layer"},
        ],
        [
            "layers build upward sequentially",
            "data signal enters bottom layer",
            "signal transforms as it passes through each layer",
            "output emerges from top layer",
        ],
        ["stack_layers", "flow_between_layers", "transform_signal"],
    ),
    # Comparison / vs concepts
    (
        ["vs", "versus", "compar", "differ", "advantage", "disadvantage",
         "trade-off", "tradeoff", "pro", "con"],
        "comparison",
        "comparison",
        [
            {"type": "container", "semantic_role": "option A"},
            {"type": "container", "semantic_role": "option B"},
            {"type": "signal",    "semantic_role": "evaluation criterion"},
        ],
        [
            "two entities appear on opposite sides",
            "criteria slide in between them",
            "winning side grows / glows for each criterion",
            "final verdict highlights dominant side",
        ],
        ["split_stage", "evaluate_criteria", "highlight_winner"],
    ),
    # Interaction / communication concepts
    (
        ["interact", "communicat", "protocol", "handshake",
         "client", "server", "send", "receiv", "connect"],
        "interaction",
        "simulation",
        [
            {"type": "node",   "semantic_role": "actor / endpoint"},
            {"type": "signal", "semantic_role": "message / packet"},
        ],
        [
            "two actor nodes appear",
            "signal travels from sender to receiver",
            "receiver acknowledges with return signal",
            "exchange repeats showing protocol steps",
        ],
        ["show_actors", "send_signal", "acknowledge_signal"],
    ),
    # Sorting / algorithm concepts
    (
        ["sort", "algorithm", "search", "binary", "merge",
         "recursion", "recursive", "loop", "iteration", "swap"],
        "data_flow",
        "simulation",
        [
            {"type": "particle",  "semantic_role": "data element"},
            {"type": "boundary",  "semantic_role": "pointer / cursor"},
            {"type": "container", "semantic_role": "sorted region"},
        ],
        [
            "array of elements appears as bars/circles",
            "pointer highlights current comparison pair",
            "elements swap positions with animation",
            "sorted region grows from one end",
        ],
        ["show_array", "highlight_compare", "animate_swap"],
    ),
    # Security / encryption concepts
    (
        ["encrypt", "decrypt", "security", "hash", "token",
         "auth", "key", "password", "ssl", "tls", "cipher"],
        "transformation",
        "simulation",
        [
            {"type": "particle",  "semantic_role": "plaintext data"},
            {"type": "container", "semantic_role": "encryption process"},
            {"type": "signal",    "semantic_role": "key"},
        ],
        [
            "readable data appears",
            "key enters the encryption container",
            "data transforms into scrambled form inside container",
            "scrambled output exits as ciphertext",
        ],
        ["show_plaintext", "apply_key", "morph_to_ciphertext"],
    ),
    # Database / storage concepts
    (
        ["database", "sql", "nosql", "table", "query",
         "index", "schema", "record", "crud", "storage"],
        "data_flow",
        "simulation",
        [
            {"type": "container", "semantic_role": "database / table"},
            {"type": "particle",  "semantic_role": "record / row"},
            {"type": "signal",    "semantic_role": "query"},
        ],
        [
            "storage container appears",
            "query signal enters",
            "matching records highlight and float up",
            "result set assembles outside container",
        ],
        ["show_storage", "send_query", "retrieve_records"],
    ),
    # Generic process / mechanism fallback (broad)
    (
        ["process", "mechanism", "system", "work", "function",
         "how", "step", "phase", "stage"],
        "data_flow",
        "simulation",
        [
            {"type": "container", "semantic_role": "processing stage"},
            {"type": "particle",  "semantic_role": "input being processed"},
            {"type": "signal",    "semantic_role": "control / trigger"},
        ],
        [
            "input enters first stage",
            "stages activate in sequence",
            "data transforms at each stage",
            "final output emerges",
        ],
        ["sequential_stages", "transform_at_stage", "emit_output"],
    ),
]


# ================================================================
# DEPICTION TYPE RULES
# ================================================================

def _infer_depiction_type(narration: str, idea: str, layout_strategy: str) -> str:
    """
    Rule: if the narration describes a PROCESS, depiction MUST be simulation.
    Comparison only if layout says so AND no process language found.
    """
    combined = f"{narration} {idea}".lower()

    process_signals = [
        "how", "when", "process", "step", "flow", "propagat",
        "learn", "train", "transform", "connect", "send",
        "receiv", "encrypt", "sort", "build", "creat", "work",
        "happen", "run", "execut", "travell", "pass through",
        "activate", "trigger", "signal",
    ]
    for kw in process_signals:
        if kw in combined:
            return "simulation"

    if layout_strategy == "comparison":
        return "comparison"

    return "simulation"  # default — always prefer motion


# ================================================================
# CAMERA STRATEGY
# ================================================================

_CAMERA_MAP = {
    "neural_network":  "follow_process",
    "data_flow":       "follow_process",
    "transformation":  "zoom_reveal",
    "classification":  "stabilize",
    "hierarchy":       "zoom_reveal",
    "comparison":      "stabilize",
    "interaction":     "follow_process",
}


# ================================================================
# PUBLIC API
# ================================================================

def generate_visual_model(segment_data: dict) -> dict:
    """
    Convert a narrative segment into a visual behavior model.

    Parameters
    ----------
    segment_data : dict
        Must contain at least:
          idea        – the learning concept
          narration   – the spoken narration text
          visual_intent – intended visual approach
          layout_strategy – comparison | process_flow | hierarchy | …

    Returns
    -------
    dict with keys:
        depiction_type, visual_model, entities, behaviors,
        animation_primitives, camera_strategy
    """
    idea = segment_data.get("idea", "")
    narration = segment_data.get("narration", "")
    visual_intent = segment_data.get("visual_intent", "")
    layout_strategy = segment_data.get("layout_strategy", "process_flow")

    combined_text = f"{idea} {narration} {visual_intent}".lower()

    # --- Match concept ---
    best_match = None
    best_score = 0
    for entry in _CONCEPT_MAP:
        keywords, model_name, default_dep, entities, behaviors, primitives = entry
        score = sum(1 for kw in keywords if kw in combined_text)
        if score > best_score:
            best_score = score
            best_match = (model_name, default_dep, entities, behaviors, primitives)

    # Fallback to generic process
    if best_match is None or best_score == 0:
        fallback = _CONCEPT_MAP[-1]  # generic process
        best_match = (fallback[1], fallback[2], fallback[3], fallback[4], fallback[5])

    visual_model, default_depiction, entities, behaviors, primitives = best_match

    # Override depiction with rule engine
    depiction_type = _infer_depiction_type(narration, idea, layout_strategy)

    camera = _CAMERA_MAP.get(visual_model, "follow_process")

    return {
        "depiction_type": depiction_type,
        "visual_model": visual_model,
        "entities": entities,
        "behaviors": behaviors,
        "animation_primitives": primitives,
        "camera_strategy": camera,
    }


def generate_visual_models_batch(segments_data: list[dict]) -> list[dict]:
    """Run generate_visual_model for every segment in one call."""
    return [generate_visual_model(s) for s in segments_data]


# ================================================================
# VISUAL VALIDATION (TASK 6)
# ================================================================

_LABEL_ONLY_SIGNALS = [
    "box", "label", "text", "title", "heading", "card",
    "container labeled", "rectangle with text",
]

_MOTION_SIGNALS = [
    "propagat", "flow", "pulse", "morph", "transform", "grow",
    "travel", "move", "shift", "scale", "fade", "rotate",
    "glow", "activate", "emit", "swap", "slide", "bounce",
    "converge", "diverge", "split", "merge",
]


def validate_visual_depiction(scene_direction: dict) -> dict:
    """
    Check that a scene direction describes MOTION, not just labels.

    Returns
    -------
    dict:
        valid        – bool
        issues       – list[str]   (empty when valid)
        score        – float 0..1  (>0.5 = acceptable)
    """
    issues: list[str] = []
    score = 1.0

    # --- 1. Check if most elements are label-heavy ---
    elements = scene_direction.get("elements", [])
    if elements:
        label_count = 0
        for el in elements:
            el_str = json.dumps(el).lower()
            if any(sig in el_str for sig in _LABEL_ONLY_SIGNALS):
                label_count += 1
        label_ratio = label_count / len(elements)
        if label_ratio > 0.6:
            issues.append(f"Too many label-only elements ({label_count}/{len(elements)})")
            score -= 0.3

    # --- 2. Check behaviors are present ---
    beats = scene_direction.get("direction_beats", [])
    if not beats:
        issues.append("No direction_beats found — scene will be static")
        score -= 0.3
    else:
        has_motion = False
        for beat in beats:
            beat_str = json.dumps(beat).lower()
            if any(sig in beat_str for sig in _MOTION_SIGNALS):
                has_motion = True
                break
        if not has_motion:
            issues.append("No motion verbs in direction_beats — slide-show risk")
            score -= 0.25

    # --- 3. Check for continuous motion (>3s at 30%) ---
    total_beats = len(beats) if beats else 0
    if total_beats < 3:
        issues.append(f"Only {total_beats} beats — need at least 3 for continuous motion")
        score -= 0.2

    # --- 4. Check transformation chain ---
    transforms = scene_direction.get("transformation_chain", [])
    if not transforms:
        issues.append("No transformation_chain — nothing evolves visually")
        score -= 0.15

    # --- 5. Check depiction_mode ---
    dep_mode = scene_direction.get("depiction_mode", "")
    if dep_mode == "diagram":
        issues.append("depiction_mode is 'diagram' — should be 'simulation' for processes")
        score -= 0.1

    score = max(0.0, min(1.0, score))
    return {
        "valid": score >= 0.5,
        "issues": issues,
        "score": round(score, 2),
    }


def format_visual_model_context(visual_model: dict) -> str:
    """
    Render a visual model dict into a prompt-injectable text block
    that the Scene Direction and Manim Execution prompts can consume.
    """
    lines = [
        "VISUAL BEHAVIOR MODEL (MANDATORY SOURCE OF TRUTH)",
        "=" * 52,
        f"Depiction Type : {visual_model.get('depiction_type', 'simulation')}",
        f"Visual Model   : {visual_model.get('visual_model', 'data_flow')}",
        f"Camera Strategy: {visual_model.get('camera_strategy', 'follow_process')}",
        "",
        "ENTITIES (what appears on screen):",
    ]
    for ent in visual_model.get("entities", []):
        lines.append(f"  - {ent['type']:12s} → {ent['semantic_role']}")

    lines.append("")
    lines.append("BEHAVIORS (what must happen — animate these, NOT static labels):")
    for beh in visual_model.get("behaviors", []):
        lines.append(f"  • {beh}")

    lines.append("")
    lines.append("ANIMATION PRIMITIVES (preferred Manim approach):")
    for prim in visual_model.get("animation_primitives", []):
        lines.append(f"  ▸ {prim}")

    lines.append("")
    lines.append("RULES:")
    lines.append("  - Text labels are LAST RESORT. Prefer shapes, motion, color.")
    lines.append("  - Every entity must MOVE or CHANGE during the scene.")
    lines.append("  - If depiction_type == simulation: animate behaviors continuously.")
    lines.append("  - Minimum 3 distinct animation beats.")

    return "\n".join(lines)
