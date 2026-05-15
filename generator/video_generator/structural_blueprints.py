"""
Structural Blueprints
======================

Reusable safe scene architecture patterns for Manim script generation.

These are NOT rigid templates — they are structural GUIDES that ensure:
  - Safe object lifecycle
  - Proper animation composition
  - Stable hierarchy management
  - Correct synchronization

While preserving:
  - Full cinematic freedom
  - Creative choreography
  - Visual storytelling
  - Animation richness

Blueprint categories:
  - ConceptFlowScene    — linear concept flow with transitions
  - ComparisonScene     — side-by-side or before/after
  - TimelineScene       — sequential temporal events
  - TransformationScene — morphing/evolving concepts
  - SystemArchScene     — multi-component system visualization

Usage:
  blueprint = select_blueprint(scene_spec, narration)
  guidance = blueprint.to_prompt_guidance()
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# BLUEPRINT DEFINITIONS
# ═══════════════════════════════════════════════════════════════════

@dataclass
class StructuralBlueprint:
    """A structural scene architecture guide."""
    name: str
    description: str
    structure_rules: List[str]    # Structural safety rules
    animation_pattern: str        # Recommended animation flow
    max_concurrent_anims: int = 4
    max_objects: int = 15
    recommended_play_calls: int = 8
    example_skeleton: str = ""    # Minimal safe skeleton code

    def to_prompt_guidance(self) -> str:
        """Convert blueprint to prompt-injectable guidance text."""
        rules = "\n".join(f"  - {r}" for r in self.structure_rules)
        return f"""## STRUCTURAL BLUEPRINT: {self.name}
{self.description}

### Architecture Rules (MUST FOLLOW)
{rules}

### Animation Pattern
{self.animation_pattern}

### Complexity Budget
- Max concurrent animations per self.play(): {self.max_concurrent_anims}
- Max Mobject creations: {self.max_objects}
- Target self.play() calls: ~{self.recommended_play_calls}

### Safe Skeleton Pattern
```python
{self.example_skeleton}
```
"""


# ── CONCEPT FLOW ──
CONCEPT_FLOW = StructuralBlueprint(
    name="ConceptFlow",
    description="Linear concept presentation: introduce → explain → visualize → conclude.",
    structure_rules=[
        "Create all objects BEFORE animating them",
        "Use VGroup() for related objects — never .add() text to shapes",
        "One concept focus at a time — FadeOut before introducing next",
        "Max 4 animations per self.play() block",
        "Use self.wait(0.3-0.5) between concept transitions",
    ],
    animation_pattern="FadeIn → Indicate/Transform → self.wait → FadeOut → next concept",
    max_concurrent_anims=4,
    max_objects=12,
    recommended_play_calls=8,
    example_skeleton="""# Phase 1: Create objects
title = Text("Title", font_size=28).scale_to_fit_width(config.frame_width * 0.55)
box = Rectangle(width=3, height=1.5, color=BLUE, fill_opacity=0.2)
label = Text("Label", font_size=22)
concept = VGroup(box, label).arrange(DOWN, buff=0.3)

# Phase 2: Animate introduction
self.play(Write(title), run_time=1)
self.wait(0.5)
self.play(FadeOut(title), FadeIn(concept, shift=UP*0.3), run_time=1)

# Phase 3: Visual explanation
self.play(Indicate(concept, scale_factor=1.1), run_time=1)
self.wait(0.5)

# Phase 4: Cleanup
self.play(FadeOut(concept), run_time=0.8)
""",
)


# ── COMPARISON ──
COMPARISON_SCENE = StructuralBlueprint(
    name="Comparison",
    description="Side-by-side or sequential comparison of two concepts.",
    structure_rules=[
        "Create BOTH sides completely before animating either",
        "Use VGroup for each side — position with .arrange(RIGHT, buff=1)",
        "Show one side first, then the other, then both together",
        "Never animate children of a VGroup independently after grouping",
        "Use SurroundingRectangle for emphasis, not .add()",
    ],
    animation_pattern="Show A → Show B → Highlight difference → Conclude",
    max_concurrent_anims=4,
    max_objects=15,
    recommended_play_calls=10,
    example_skeleton="""# Create both sides
left_box = Rectangle(width=3, height=2, color=RED, fill_opacity=0.2)
left_label = Text("Before", font_size=22)
left_side = VGroup(left_box, left_label).arrange(DOWN, buff=0.3)

right_box = Rectangle(width=3, height=2, color=GREEN, fill_opacity=0.2)
right_label = Text("After", font_size=22)
right_side = VGroup(right_box, right_label).arrange(DOWN, buff=0.3)

comparison = VGroup(left_side, right_side).arrange(RIGHT, buff=1.5)
comparison.move_to(ORIGIN)

# Animate
self.play(FadeIn(left_side, shift=LEFT*0.5), run_time=1)
self.wait(0.5)
self.play(FadeIn(right_side, shift=RIGHT*0.5), run_time=1)
self.wait(0.5)
""",
)


# ── TIMELINE ──
TIMELINE_SCENE = StructuralBlueprint(
    name="Timeline",
    description="Sequential events along a timeline or numbered steps.",
    structure_rules=[
        "Create the timeline/axis FIRST, add to scene, then add events",
        "Each event is a VGroup(marker, label) — never nested .add()",
        "Animate events with LaggedStart for sequential reveals",
        "Keep events compact — max 4-5 visible at once",
        "Use arrows between events, created AFTER both endpoints exist",
    ],
    animation_pattern="Create axis → Add events sequentially → Highlight key event → Conclude",
    max_concurrent_anims=3,
    max_objects=18,
    recommended_play_calls=8,
    example_skeleton="""# Create timeline axis
axis = Line(LEFT*3.5, RIGHT*3.5, color=WHITE, stroke_width=2)
self.play(Create(axis), run_time=1)

# Create events as VGroups
events = []
for i, (label_text, x_pos) in enumerate(steps):
    dot = Dot(color=BLUE, radius=0.1).move_to([x_pos, 0, 0])
    label = Text(label_text, font_size=18).next_to(dot, DOWN, buff=0.3)
    event = VGroup(dot, label)
    events.append(event)

# Animate events with lag
self.play(LaggedStart(*[FadeIn(e, shift=UP*0.2) for e in events], lag_ratio=0.3), run_time=2)
""",
)


# ── TRANSFORMATION ──
TRANSFORMATION_SCENE = StructuralBlueprint(
    name="Transformation",
    description="Concepts that morph, evolve, or transform into each other.",
    structure_rules=[
        "Create source AND target objects before any Transform call",
        "Use ReplacementTransform(a, b) — NOT Transform for cross-object morphs",
        "After ReplacementTransform(a, b), only reference 'b' going forward",
        "Never transform objects that are children of a VGroup",
        "Maximum 2 transforms in sequence before a self.wait()",
    ],
    animation_pattern="Show original → Transform to new state → Explain → Transform again or conclude",
    max_concurrent_anims=3,
    max_objects=12,
    recommended_play_calls=8,
    example_skeleton="""# Create source and target
old_concept = VGroup(
    Rectangle(width=3, height=1, color=RED, fill_opacity=0.3),
    Text("Old", font_size=22)
).arrange(DOWN, buff=0.2)

new_concept = VGroup(
    Rectangle(width=3, height=1, color=GREEN, fill_opacity=0.3),
    Text("New", font_size=22)
).arrange(DOWN, buff=0.2)

# Show and transform
self.play(FadeIn(old_concept), run_time=1)
self.wait(0.5)
self.play(ReplacementTransform(old_concept, new_concept), run_time=1.5)
# Now only reference new_concept
self.play(Indicate(new_concept), run_time=1)
""",
)


# ── SYSTEM ARCHITECTURE ──
SYSTEM_ARCH_SCENE = StructuralBlueprint(
    name="SystemArchitecture",
    description="Multi-component system with connections and data flow.",
    structure_rules=[
        "Create ALL nodes as VGroup(shape, label) — never shape.add(label)",
        "Position all nodes BEFORE creating arrows/connections",
        "Create arrows AFTER both source and target nodes are positioned",
        "Use buff=0.1 in Arrow(start, end, buff=0.1) to prevent overlap",
        "Animate in layers: nodes first → arrows second → flow last",
        "Max 4-5 nodes per scene for readability",
    ],
    animation_pattern="Show nodes → Draw connections → Animate data flow → Highlight result",
    max_concurrent_anims=4,
    max_objects=20,
    recommended_play_calls=10,
    example_skeleton="""# Create nodes as VGroups (SAFE pattern)
node_a_rect = Rectangle(width=2.5, height=1, color=BLUE, fill_opacity=0.2)
node_a_text = Text("Input", font_size=20)
node_a = VGroup(node_a_rect, node_a_text).arrange(DOWN, buff=0.1)
node_a.move_to(UP * 3)

node_b_rect = Rectangle(width=2.5, height=1, color=GREEN, fill_opacity=0.2)
node_b_text = Text("Process", font_size=20)
node_b = VGroup(node_b_rect, node_b_text).arrange(DOWN, buff=0.1)
node_b.move_to(ORIGIN)

# Show nodes first
self.play(FadeIn(node_a, shift=DOWN*0.3), run_time=1)
self.play(FadeIn(node_b, shift=DOWN*0.3), run_time=1)

# THEN create and show arrows (after nodes are positioned)
arrow = Arrow(node_a.get_bottom(), node_b.get_top(), buff=0.1, color=WHITE)
self.play(Create(arrow), run_time=0.8)
""",
)


# ═══════════════════════════════════════════════════════════════════
# BLUEPRINT SELECTION
# ═══════════════════════════════════════════════════════════════════

ALL_BLUEPRINTS = {
    "concept_flow": CONCEPT_FLOW,
    "comparison": COMPARISON_SCENE,
    "timeline": TIMELINE_SCENE,
    "transformation": TRANSFORMATION_SCENE,
    "system_architecture": SYSTEM_ARCH_SCENE,
}

# Keywords for automatic blueprint selection
_BLUEPRINT_KEYWORDS = {
    "concept_flow": [
        "explain", "introduce", "what is", "how does", "concept",
        "definition", "meaning", "understanding", "basics",
    ],
    "comparison": [
        "compare", "vs", "versus", "difference", "better", "worse",
        "before", "after", "old", "new", "advantages", "disadvantages",
    ],
    "timeline": [
        "steps", "timeline", "history", "sequence", "first", "then",
        "next", "finally", "process", "workflow", "stage",
    ],
    "transformation": [
        "transform", "evolve", "change", "morph", "becomes",
        "convert", "migrate", "upgrade", "transition", "shift",
    ],
    "system_architecture": [
        "system", "architecture", "component", "module", "pipeline",
        "flow", "data", "network", "structure", "engine", "layer",
    ],
}


def select_blueprint(
    scene_spec=None,
    narration: str = "",
) -> StructuralBlueprint:
    """
    Automatically select the best structural blueprint for a scene.
    
    Uses narration keywords and scene spec analysis.
    Falls back to ConceptFlow for general scenes.
    
    Args:
        scene_spec: Optional SceneSpecification.
        narration: Narration text.
    
    Returns:
        StructuralBlueprint instance.
    """
    narration_lower = narration.lower()
    
    # Score each blueprint by keyword matches
    scores = {}
    for bp_name, keywords in _BLUEPRINT_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in narration_lower)
        scores[bp_name] = score
    
    # Check scene spec for additional signals
    if scene_spec:
        if hasattr(scene_spec, 'visual_metaphor') and scene_spec.visual_metaphor:
            vm = scene_spec.visual_metaphor
            if hasattr(vm, 'metaphor_type') and vm.metaphor_type:
                mt = str(vm.metaphor_type).lower()
                if "comparison" in mt:
                    scores["comparison"] = scores.get("comparison", 0) + 3
                elif "transformation" in mt or "process" in mt:
                    scores["transformation"] = scores.get("transformation", 0) + 3
                elif "architecture" in mt or "system" in mt:
                    scores["system_architecture"] = scores.get("system_architecture", 0) + 3
    
    # Select highest scoring blueprint
    if max(scores.values(), default=0) > 0:
        best = max(scores, key=scores.get)
        blueprint = ALL_BLUEPRINTS[best]
    else:
        blueprint = CONCEPT_FLOW  # Default
    
    logger.info(
        f"📐 Selected blueprint: {blueprint.name} "
        f"(scores: {dict(sorted(scores.items(), key=lambda x: -x[1])[:3])})"
    )
    
    return blueprint
