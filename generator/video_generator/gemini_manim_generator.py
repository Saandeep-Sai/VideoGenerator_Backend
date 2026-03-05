"""
Gemini Direct Manim Script Generator
=====================================

Replaces template-based code generation in the quality pipeline.
Gemini receives scene direction + narration and outputs RAW EXECUTABLE
Manim Python scripts — no templates involved.

Flow:
  narration + scene_spec + visual_intent + duration + config
  → Gemini prompt
  → Raw Manim Python script
  → Static validation
  → Error correction loop (reuses legacy correction)
  → Render-ready script

This module provides:
  • generate_manim_script()      — single-segment Gemini → Manim code
  • generate_manim_scripts_bulk() — batch generation for all segments
  • validate_script_static()      — pre-render static validation
  • correct_script_error()        — post-render error correction
"""

import re
import json
import logging
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════
# ASPECT RATIO CONFIGS
# ═════════════════════════════════════════════════════════════════════

ASPECT_RATIO_CONFIGS = {
    "16:9": {
        "frame_width": 16, "frame_height": 9,
        "pixel_width": 1920, "pixel_height": 1080,
        "safe_x": 7.0, "safe_y": 3.5,
        "layout_hint": "horizontal",
    },
    "9:16": {
        "frame_width": 9, "frame_height": 16,
        "pixel_width": 1080, "pixel_height": 1920,
        "safe_x": 3.8, "safe_y": 6.5,  # Tighter horizontal, generous vertical
        "layout_hint": "vertical",
    },
    "1:1": {
        "frame_width": 1, "frame_height": 1,
        "pixel_width": 1080, "pixel_height": 1080,
        "safe_x": 4.0, "safe_y": 4.0,
        "layout_hint": "square",
    },
    "4:3": {
        "frame_width": 4, "frame_height": 3,
        "pixel_width": 1440, "pixel_height": 1080,
        "safe_x": 5.5, "safe_y": 4.0,
        "layout_hint": "horizontal",
    },
}

# ═════════════════════════════════════════════════════════════════════
# SAFE MANIM API REFERENCE (injected into every prompt)
# ═════════════════════════════════════════════════════════════════════

SAFE_MANIM_API = """
## MANIM v0.19.0 — COMPLETE SAFE API REFERENCE

### Shapes (from manim import *)
Circle, Ellipse, Dot, SmallDot, LabeledDot, Square, Rectangle, RoundedRectangle,
Triangle, Polygon, RegularPolygon, Star, Sector, AnnularSector, Annulus,
Arc, ArcBetweenPoints, Arrow, DoubleArrow, Vector, Line, DashedLine,
CurvedArrow, CurvedDoubleArrow, Cross, Checkmark, Angle, RightAngle,
ArrowTip, Elbow, TangentLine, ConvexHull (NEW v0.19.0), LabeledPolygram (NEW v0.19.0)

### Text & LaTeX
Text(text, font="sans-serif", font_size=24, color=WHITE, weight=BOLD/NORMAL,
     slant=NORMAL/ITALIC, t2c={"word": RED}, t2f={}, t2w={}, line_spacing=-1)
MarkupText(text) — Pango markup for inline rich styling
MathTex(r"\\latex") — LaTeX math expressions
Tex(r"\\latex") — LaTeX text
Title, BulletedList, Paragraph, Code (rewritten in v0.19.0)
Integer, DecimalNumber, Variable
IMPORTANT: Always use .scale_to_fit_width(config.frame_width * WIDTH_FACTOR) on Text!

### Groups & Layout
VGroup(*mobjects) — group VMobjects (supports iterables in v0.19.0)
Group(*mobjects) — group any Mobjects
VDict — dictionary of VMobjects by key
.arrange(direction, buff=0.5) — arrange children in a line
.arrange_in_grid(rows, cols) — grid layout

### Brace & Annotations
Brace, BraceBetweenPoints, BraceLabel, BraceText
Label (NEW v0.19.0), SurroundingRectangle, BackgroundRectangle, UnderLine

### Graphing & Data
Axes, NumberPlane, PolarPlane, NumberLine, BarChart
axes.plot(func), axes.get_area(graph), axes.get_riemann_rectangles(graph)
axes.coords_to_point(x, y), axes.get_vertical_line(x)

### Graph Theory
Graph(vertices, edges), DiGraph(vertices, edges)

### Matrix & Table
Matrix, IntegerMatrix, Table, MathTable, MobjectTable

### Animations — Creation
Create, Uncreate, DrawBorderThenFill, Write, Unwrite,
ShowPassingFlash, ShowIncreasingSubsets, ShowSubobjectsOneByOne,
AddTextLetterByLetter (NEW), RemoveTextLetterByLetter (NEW),
AddTextWordByWord (NEW), Add (NEW — instant add, run_time=0)

### Animations — Transform
Transform, ReplacementTransform, TransformFromCopy,
MoveToTarget, ApplyMethod, ApplyFunction, ApplyMatrix,
CyclicReplace, Swap, Rotate, ScaleInPlace, ShrinkToCenter, Restore,
ClockwiseTransform, CounterclockwiseTransform, FadeTransform

### Animations — Fading
FadeIn(mob, shift=UP*0.3, scale=0.8), FadeOut(mob, shift=DOWN*0.2),
FadeInFromPoint, FadeOutToPoint, FadeInFromLarge,
FadeOutAndShift, FadeTransform, FadeTransformPieces

### Animations — Growing & Shrinking
GrowFromCenter, GrowFromEdge, GrowFromPoint, GrowArrow,
SpinInFromNothing, ShrinkToCenter

### Animations — Indication
Indicate(mob, color=YELLOW, scale_factor=1.2),
Flash(mob, color=YELLOW, flash_radius=0.5, num_lines=12),
CircleIndicate, Circumscribe(mob, color=WHITE, time_width=1.5),
ApplyWave(mob, amplitude=0.2, direction=UP),
Wiggle(mob, scale_value=1.1, rotation_angle=0.05*TAU),
WiggleOutThenIn, Blink, FocusOn,
ShowCreationThenDestructionAround, ShowCreationThenFadeAround

### Animations — Movement
MoveAlongPath(mob, path), Rotating(mob, angle=TAU),
Homotopy, PhaseFlow

### Animations — Composition
AnimationGroup(*anims, lag_ratio=0), LaggedStart(*anims, lag_ratio=0.15),
LaggedStartMap(anim_class, group, lag_ratio=0.1),
Succession(*anims), Wait(duration)

### Rate Functions — Direct (rate_func=NAME)
linear, smooth, smoothstep, smootherstep, rush_into, rush_from,
slow_into, double_smooth, there_and_back, there_and_back_with_pause,
running_start, not_quite_there, wiggle, lingering, exponential_decay

### Rate Functions — via rate_functions.NAME prefix
rate_functions.ease_in_sine, ease_out_sine, ease_in_out_sine
rate_functions.ease_in_quad, ease_out_quad, ease_in_out_quad
rate_functions.ease_in_cubic, ease_out_cubic, ease_in_out_cubic
rate_functions.ease_in_quart, ease_out_quart, ease_in_out_quart
rate_functions.ease_in_expo, ease_out_expo, ease_in_out_expo
rate_functions.ease_in_back, ease_out_back, ease_in_out_back
rate_functions.ease_in_elastic, ease_out_elastic, ease_in_out_elastic
rate_functions.ease_in_bounce, ease_out_bounce, ease_in_out_bounce

### Updater Utilities (use sparingly — max 3 per scene)
always_redraw(lambda: ...), ValueTracker, DecimalNumber
mob.add_updater(func), mob.clear_updaters()

### Color Constants
RED, BLUE, GREEN, YELLOW, WHITE, ORANGE, PURPLE, TEAL, PINK,
GOLD, MAROON, GREY/GRAY, DARK_GREY, LIGHT_GREY,
RED_A through RED_E, BLUE_A through BLUE_E, GREEN_A through GREEN_E,
TEAL_A through TEAL_E, GOLD_A through GOLD_E, PURPLE_A through PURPLE_E

### Direction & Math Constants
UP, DOWN, LEFT, RIGHT, ORIGIN, UL, UR, DL, DR, IN, OUT
PI, TAU, DEGREES, BOLD, NORMAL, ITALIC

### Mobject Methods (commonly needed)
.move_to(point), .next_to(mob, direction, buff=0.2), .shift(vector)
.to_edge(direction, buff=0.5), .to_corner(corner), .center()
.scale(factor), .scale_to_fit_width(w), .scale_to_fit_height(h)
.set_color(color), .set_fill(color, opacity), .set_stroke(color, width)
.set_opacity(alpha), .rotate(angle), .flip(axis)
.get_center(), .get_width(), .get_height(), .get_top(), .get_bottom()
.copy(), .become(other), .align_to(mob, direction)
.arrange(direction, buff), .arrange_in_grid(rows, cols, buff)
.animate — property animator for smooth transitions (e.g. mob.animate.shift(UP))

### Scene Methods
self.play(*animations, run_time=1.0, rate_func=smooth)
self.wait(duration), self.add(*mobs), self.remove(*mobs)
self.bring_to_front(*mobs), self.bring_to_back(*mobs)

### Config
config.frame_width, config.frame_height, config.pixel_width, config.pixel_height
config.background_color

## COMMON ERRORS TO AVOID (CRITICAL — read carefully!)

### 1. Text/MathTex Errors
- WRONG: Text("Hello", size=24) — 'size' does not exist
- RIGHT: Text("Hello", font_size=24)
- WRONG: Text("Hi", bold=True) — 'bold' does not exist  
- RIGHT: Text("Hi", weight=BOLD)
- ALWAYS scale Text to fit: text.scale_to_fit_width(config.frame_width * 0.6)

### 2. Transform Errors
- WRONG: Transform(a, b, c) — Transform only takes 2 mobjects
- RIGHT: Transform(a, b), then Transform(b, c) separately
- WRONG: ReplacementTransform(a, b, c)
- RIGHT: AnimationGroup(ReplacementTransform(a, b), ReplacementTransform(c, d))

### 3. Position/Movement Errors
- WRONG: mob.move_to(3, 2) — move_to takes a SINGLE point
- RIGHT: mob.move_to([3, 2, 0]) or mob.move_to(RIGHT*3 + UP*2)
- WRONG: mob.shift(UP, 2) — shift takes a vector, not separate args
- RIGHT: mob.shift(UP * 2)

### 4. Animation Parameter Errors
- WRONG: self.play(Create(mob), duration=2) — 'duration' does not exist
- RIGHT: self.play(Create(mob), run_time=2)
- WRONG: FadeIn(mob, direction=UP)
- RIGHT: FadeIn(mob, shift=UP)

### 5. Color Errors
- WRONG: mob.set_color("red") — colors are constants, not strings
- RIGHT: mob.set_color(RED)
- WRONG: Circle(color="#FF0000") — hex colors need special handling
- RIGHT: Circle(color=RED) or Circle(color=ManimColor("#FF0000"))

### 6. VGroup Errors
- WRONG: VGroup.add(mob) — VGroup is a class, not an instance
- RIGHT: group = VGroup(); group.add(mob)
- WRONG: for mob in vgroup.submobjects: mob.shift(UP) — modifies during iteration
- RIGHT: for mob in list(vgroup): mob.shift(UP) — copy list first

### 7. Axes/Graph Errors
- WRONG: axes.plot(lambda x: x**2) without axes being added to scene first
- RIGHT: self.add(axes) THEN self.play(Create(axes.plot(...)))
- WRONG: axes.get_graph(func) — deprecated
- RIGHT: axes.plot(func) — v0.19.0 syntax

### 8. Rate Function Errors
- WRONG: rate_func=ease_out_expo — not directly imported
- RIGHT: rate_func=rate_functions.ease_out_expo (need prefix)
- Directly available: linear, smooth, rush_into, rush_from, slow_into, wiggle

### 9. Index Out of Bounds
- ALWAYS check list length before accessing: if len(items) > i: items[i]
- Use enumerate() for safer iteration: for i, item in enumerate(items):

### 10. Timing Errors
- Total animation time MUST equal segment duration
- Calculate: sum(all run_times) + sum(all self.wait()) = duration
- End with self.wait(remaining_time) to fill any gap

## FORBIDDEN (will crash)
- ThreeDScene, Surface, ParametricSurface, Sphere, Cube (3D objects)
- OpenGLRenderer references
- External file I/O (open, PIL, requests, subprocess, os.system)
- input(), print() inside construct()
- Infinite loops without self.wait()
- time.sleep() — use self.wait() instead
- HGroup — does NOT exist in Manim v0.19.0
- ShowCreation — DEPRECATED, use Create instead
"""

# ═════════════════════════════════════════════════════════════════════
# GENERATION PROMPT
# ═════════════════════════════════════════════════════════════════════

GEMINI_MANIM_PROMPT = """You are an elite Manim animation engineer creating a cinematic educational YouTube Short segment.

## YOUR TASK
Write a complete, executable Manim Python script that VISUALLY DEPICTS the narration.
You have FULL CREATIVE FREEDOM. Make it visually compelling, educational, and alive.

## SEGMENT INFO
- Class name: Segment{index:03d}
- Duration: {duration:.2f} seconds (EXACT — your animations must fill this time)
- Aspect ratio: {aspect_ratio}
- Frame: {frame_width}×{frame_height} units

## NARRATION
"{narration}"

## SCENE DIRECTION
{scene_direction}

## VISUAL INTENT
{visual_intent}

{safe_api_reference}

## SPATIAL SAFETY BOUNDS (CRITICAL FOR {aspect_ratio})
- Horizontal: LEFT*{safe_x} to RIGHT*{safe_x} (total usable width: {safe_x}*2 units)
- Vertical: UP*{safe_y} to DOWN*{safe_y} (total usable height: {safe_y}*2 units)
- All Text objects MUST use: .scale_to_fit_width(config.frame_width * {width_factor})
  or set font_size ≤ {max_font}

{layout_guidance}

## ASPECT RATIO CONFIG (MUST appear right after imports)
config.frame_width = {frame_width}
config.frame_height = {frame_height}
config.pixel_width = {pixel_width}
config.pixel_height = {pixel_height}

## CREATIVE GUIDELINES
1. Animate PROCESSES — things should move, transform, interact
2. Use motion to convey meaning: sorting → elements swap, networks → signals propagate
3. Camera movement (self.play(self.camera.frame.animate...)) every 6-8s keeps it cinematic
4. One focus object at a time — guide the viewer's eye
5. Prefer Transform/ReplacementTransform over FadeIn/FadeOut
6. No static screen longer than 1.5 seconds
7. Labels/text should be brief annotations, NOT the main content
8. Process visualization > labeled diagrams
9. End with self.wait() to fill remaining duration exactly

## STABILITY GUIDELINES
- Prefer well-known Manim patterns. Avoid experimental APIs.
- Always check that objects exist before transforming them.
- Use try/except around complex animations if needed.
- VGroup elements before bulk operations.
- Duration math: sum of all self.play(... run_time=X) + self.wait(Y) = {duration:.2f}s

## OUTPUT
Return ONLY the Python code. No markdown, no explanation.
Start with: from manim import *
"""

# ═════════════════════════════════════════════════════════════════════
# ERROR CORRECTION PROMPT  
# ═════════════════════════════════════════════════════════════════════

ERROR_CORRECTION_PROMPT = """Fix this Manim script. It crashed during rendering.

## RULES
- Fix ONLY the error. Do NOT redesign the animation.
- Preserve ALL creative intent, visual elements, and timing.
- Fix syntax errors, API errors, import errors, positioning errors.
- Do NOT remove animations to "simplify". Fix them instead.
- Do NOT change the class name or duration.
- Duration must remain: {duration:.2f}s

## 🚨 CRITICAL TEXT OVERLAP PREVENTION
1. ALL Text/MarkupText MUST have .scale_to_fit_width(config.frame_width * 0.55)
2. Font size limits: Title=28px MAX, Body=22px MAX
3. Minimum buff=1.5 spacing between elements
4. Use .next_to(other, DOWN, buff=1.5) for vertical stacking

## ERROR MESSAGE
{error}

## BROKEN SCRIPT
{script}

Return ONLY the corrected Python code. No markdown, no explanation.
Start with: from manim import *
"""

# ═════════════════════════════════════════════════════════════════════
# MINIMAL REPAIR PROMPT (last resort — more conservative)  
# ═════════════════════════════════════════════════════════════════════

MINIMAL_REPAIR_PROMPT = """This Manim script keeps failing. Apply MINIMAL fixes.

## CONSTRAINTS
- Fix ONLY the specific line/API causing the crash
- Keep all working animations intact
- If an animation is unfixable, comment it out and add self.wait() to fill the time
- Class name: Segment{index:03d}
- Duration: {duration:.2f}s (MUST be preserved)

## 🚨 TEXT RULES (MANDATORY)
- ALL Text: .scale_to_fit_width(config.frame_width * 0.55)
- ALL elements: minimum buff=1.5 spacing

## ERROR
{error}

## SCRIPT
{script}

Return ONLY corrected Python code. No markdown.
"""

# ═════════════════════════════════════════════════════════════════════
# STATIC SCRIPT VALIDATION
# ═════════════════════════════════════════════════════════════════════

class StaticValidationResult:
    """Result of pre-render static validation."""
    
    def __init__(self):
        self.passed = True
        self.issues: List[str] = []
        self.warnings: List[str] = []
    
    def fail(self, reason: str):
        self.passed = False
        self.issues.append(reason)
    
    def warn(self, reason: str):
        self.warnings.append(reason)
    
    def summary(self) -> str:
        if self.passed:
            w = f" ({len(self.warnings)} warnings)" if self.warnings else ""
            return f"PASSED{w}"
        return f"FAILED: {'; '.join(self.issues[:3])}"


def validate_script_static(script: str) -> StaticValidationResult:
    """
    Pre-render static validation of a Gemini-generated Manim script.
    
    Checks structure, imports, forbidden patterns, and basic safety.
    This catches issues BEFORE attempting Manim render (faster feedback).
    
    Returns:
        StaticValidationResult with pass/fail and issue details
    """
    result = StaticValidationResult()
    
    if not script or len(script.strip()) < 50:
        result.fail("Script is empty or too short")
        return result
    
    # ── Check 1: Must have 'from manim import *' ──
    if "from manim import" not in script:
        result.fail("Missing 'from manim import *'")
    
    # ── Check 2: Must have a Scene subclass ──
    if not re.search(r'class\s+\w+\(Scene\)', script):
        result.fail("No Scene subclass found")
    
    # ── Check 3: Must have construct() method ──
    if "def construct(self)" not in script:
        result.fail("Missing construct(self) method")
    
    # ── Check 4: Forbidden imports ──
    forbidden_imports = [
        r'import\s+subprocess', r'import\s+os\b', r'import\s+sys\b',
        r'from\s+PIL', r'import\s+requests', r'import\s+urllib',
        r'import\s+socket', r'import\s+http',
    ]
    for pattern in forbidden_imports:
        if re.search(pattern, script):
            result.fail(f"Forbidden import: {pattern}")
    
    # ── Check 5: Forbidden function calls ──
    forbidden_calls = [
        (r'\bopen\s*\(', "File I/O (open)"),
        (r'\bexec\s*\(', "exec()"),
        (r'\beval\s*\(', "eval()"),
        (r'os\.system', "os.system()"),
        (r'subprocess\.', "subprocess"),
        (r'\binput\s*\(', "input()"),
    ]
    for pattern, name in forbidden_calls:
        if re.search(pattern, script):
            result.fail(f"Forbidden call: {name}")
    
    # ── Check 6: 3D Scene (not supported in our pipeline) ──
    if re.search(r'ThreeDScene|Surface|ParametricSurface', script):
        result.fail("3D scenes not supported")
    
    # ── Check 7: Has at least one animation call ──
    animation_patterns = [
        r'self\.play\s*\(', r'self\.wait\s*\(', r'self\.add\s*\(',
    ]
    has_animation = any(re.search(p, script) for p in animation_patterns)
    if not has_animation:
        result.fail("No animation calls (self.play/self.wait/self.add) found")
    
    # ── Check 8: Basic Python syntax ──
    try:
        compile(script, "<gemini_script>", "exec")
    except SyntaxError as e:
        result.fail(f"Python syntax error: {e.msg} (line {e.lineno})")
    
    # ── Warnings (non-blocking) ──
    
    # Text without scaling
    text_count = len(re.findall(r'(?:Text|MarkupText|Tex)\s*\(', script))
    scale_count = len(re.findall(r'\.scale_to_fit_width\s*\(', script))
    if text_count > 0 and scale_count == 0:
        result.warn(f"{text_count} text objects without .scale_to_fit_width()")
    
    # Excessive updaters
    updater_count = len(re.findall(r'always_redraw|add_updater', script))
    if updater_count > 3:
        result.warn(f"High updater count ({updater_count}) — may cause performance issues")
    
    # Check if class name is reasonable
    class_match = re.search(r'class\s+(\w+)\(Scene\)', script)
    if class_match:
        class_name = class_match.group(1)
        if not re.match(r'^(Segment\d{3}|GeneratedAnimation\d+)$', class_name):
            result.warn(f"Unexpected class name '{class_name}' — may cause render issues")
    
    return result


# ═════════════════════════════════════════════════════════════════════
# SCRIPT GENERATION
# ═════════════════════════════════════════════════════════════════════

def _build_scene_direction_text(scene_spec, visual_contract: dict = None) -> str:
    """
    Convert a SceneSpecification into a rich text description for the LLM prompt.
    Extracts the creative intent without forcing templates.
    """
    parts = []
    
    if scene_spec is None:
        return "Create an engaging educational animation."
    
    # Concept
    if hasattr(scene_spec, 'concept') and scene_spec.concept:
        c = scene_spec.concept
        if hasattr(c, 'core_idea') and c.core_idea:
            parts.append(f"Core idea: {c.core_idea}")
        if hasattr(c, 'emotional_arc') and c.emotional_arc:
            parts.append(f"Emotional arc: {c.emotional_arc}")
    
    # Visual metaphor
    if hasattr(scene_spec, 'visual_metaphor') and scene_spec.visual_metaphor:
        vm = scene_spec.visual_metaphor
        if hasattr(vm, 'abstract_concept') and vm.abstract_concept:
            parts.append(f"Abstract concept: {vm.abstract_concept}")
        if hasattr(vm, 'concrete_representation') and vm.concrete_representation:
            parts.append(f"Visual representation: {vm.concrete_representation}")
        if hasattr(vm, 'metaphor_type') and vm.metaphor_type:
            mt = vm.metaphor_type.value if hasattr(vm.metaphor_type, 'value') else str(vm.metaphor_type)
            parts.append(f"Metaphor type: {mt}")
        
        # Elements — describe them as CREATIVE INTENT, not as template instructions
        if hasattr(vm, 'visual_elements') and vm.visual_elements:
            elem_descs = []
            for elem in vm.visual_elements:
                etype = elem.element_type.value if hasattr(elem.element_type, 'value') else str(elem.element_type)
                label = elem.label or ""
                pos = elem.position.value if elem.position and hasattr(elem.position, 'value') else str(elem.position or "")
                elem_descs.append(f"  - {label or etype} ({etype}) at {pos}")
            parts.append("Visual elements:\n" + "\n".join(elem_descs))
    
    # Transformation sequence — the STORY of what should happen
    if hasattr(scene_spec, 'transformation') and scene_spec.transformation:
        t = scene_spec.transformation
        if hasattr(t, 'sequence') and t.sequence:
            steps = []
            for step in t.sequence:
                action = step.action.value if hasattr(step.action, 'value') else str(step.action)
                target = step.target or ""
                desc = getattr(step, 'description', '') or ""
                step_text = f"  {action} → {target}"
                if desc:
                    step_text += f" ({desc})"
                steps.append(step_text)
            parts.append("Animation sequence:\n" + "\n".join(steps))
    
    # Semantic beats
    if hasattr(scene_spec, 'narration') and scene_spec.narration:
        n = scene_spec.narration
        if hasattr(n, 'semantic_beats') and n.semantic_beats:
            beats = []
            for beat in n.semantic_beats:
                text = beat.text if hasattr(beat, 'text') else str(beat)
                beats.append(f"  - {text}")
            parts.append("Key moments:\n" + "\n".join(beats))
    
    # Visual contract context
    if visual_contract:
        dep_mode = visual_contract.get("depiction_mode", "")
        if dep_mode:
            parts.append(f"\nDepiction mode: {dep_mode}")
        vis_model = visual_contract.get("visual_model", "")
        if vis_model:
            parts.append(f"Visual model: {vis_model}")
        entities = visual_contract.get("entities", [])
        if entities:
            entity_strs = []
            for e in entities[:8]:
                if isinstance(e, dict):
                    entity_strs.append(e.get("type", str(e)))
                else:
                    entity_strs.append(str(e))
            parts.append(f"Key entities: {', '.join(entity_strs)}")
        behaviors = visual_contract.get("behaviors", [])
        if behaviors:
            parts.append(f"Expected behaviors: {', '.join(str(b) for b in behaviors[:6])}")
        chain = visual_contract.get("transformation_chain", [])
        if chain:
            parts.append(f"Transformation chain: {' → '.join(str(c) for c in chain[:6])}")
    
    return "\n".join(parts) if parts else "Create an engaging educational animation."


def _get_aspect_config(aspect_ratio: str) -> dict:
    """Get frame/pixel config for aspect ratio."""
    return ASPECT_RATIO_CONFIGS.get(aspect_ratio, ASPECT_RATIO_CONFIGS["9:16"])


def _get_layout_guidance(aspect_ratio: str) -> str:
    """Get layout-specific guidance for the aspect ratio."""
    if aspect_ratio == "9:16":
        return """VERTICAL LAYOUT (9:16 YouTube Shorts):
- Stack elements VERTICALLY using .arrange(DOWN, buff=0.5)
- Keep text SHORT (max 15 words per text object)
- Use multiple smaller text blocks instead of one large paragraph
- Position main content in CENTER, titles at TOP, labels at BOTTOM
- Break long explanations into 2-3 separate animated text blocks
- Use VGroup().arrange(DOWN) for multi-line content
- Keep diagrams/shapes COMPACT (max width: config.frame_width * 0.8)
- Leave 15% margin on left/right edges for mobile viewing
- Prefer vertical flow: TOP → CENTER → BOTTOM"""
    elif aspect_ratio == "1:1":
        return """SQUARE LAYOUT (1:1 Instagram):
- Center content both horizontally and vertically
- Use quadrant layout for multiple elements
- Keep text concise for readability"""
    else:
        return """HORIZONTAL LAYOUT (16:9/4:3):
- Use LEFT to RIGHT flow for process animations
- Wide text can span most of frame width
- Side-by-side comparisons work well"""


def generate_manim_script(
    llm_client,
    narration: str,
    scene_spec,
    index: int,
    duration: float,
    aspect_ratio: str = "9:16",
    visual_contract: dict = None,
) -> Optional[str]:
    """
    Generate a complete Manim script using Gemini (or compatible LLM).
    
    Args:
        llm_client: LLM client with .generate(prompt, temperature) method
        narration: The narration text for this segment
        scene_spec: SceneSpecification object (creative direction)
        index: Segment index (0-based)
        duration: Exact duration in seconds
        aspect_ratio: Video aspect ratio string
        visual_contract: Optional visual contract dict
    
    Returns:
        Cleaned Manim Python script string, or None on failure
    """
    config = _get_aspect_config(aspect_ratio)
    
    # Build rich scene direction from spec
    scene_direction = _build_scene_direction_text(scene_spec, visual_contract)
    
    # Build visual intent summary
    visual_intent = narration  # The narration IS the visual intent
    if scene_spec and hasattr(scene_spec, 'concept') and scene_spec.concept:
        if hasattr(scene_spec.concept, 'core_idea') and scene_spec.concept.core_idea:
            visual_intent = scene_spec.concept.core_idea
    
    # Width factor for text scaling - 9:16 needs tighter constraints
    width_factors = {"16:9": 0.85, "9:16": 0.55, "1:1": 0.70, "4:3": 0.80}
    width_factor = width_factors.get(aspect_ratio, 0.55)
    max_fonts = {"16:9": 48, "9:16": 28, "1:1": 38, "4:3": 44}
    max_font = max_fonts.get(aspect_ratio, 28)
    
    # Layout guidance based on aspect ratio
    layout_guidance = _get_layout_guidance(aspect_ratio)
    
    prompt = GEMINI_MANIM_PROMPT.format(
        index=index,
        duration=duration,
        aspect_ratio=aspect_ratio,
        frame_width=config["frame_width"],
        frame_height=config["frame_height"],
        pixel_width=config["pixel_width"],
        pixel_height=config["pixel_height"],
        safe_x=config["safe_x"],
        safe_y=config["safe_y"],
        narration=narration,
        scene_direction=scene_direction,
        visual_intent=visual_intent,
        safe_api_reference=SAFE_MANIM_API,
        width_factor=width_factor,
        max_font=max_font,
        layout_guidance=layout_guidance,
    )
    
    try:
        response = llm_client.generate(prompt, temperature=0.75)
        if response:
            script = _clean_script(response)
            # Ensure correct class name
            script = _fix_class_name(script, index)
            return script
        logger.warning(f"Segment {index+1}: Empty LLM response")
        return None
    except Exception as e:
        logger.error(f"Segment {index+1}: Gemini generation failed: {e}")
        return None


# ═════════════════════════════════════════════════════════════════════
# BATCH GENERATION PROMPT (all scripts in one LLM call)
# ═════════════════════════════════════════════════════════════════════

GEMINI_MANIM_BATCH_PROMPT = """You are an elite Manim animation engineer creating {num_segments} cinematic educational YouTube Short segments in ONE PASS.

You have FULL CREATIVE FREEDOM. Make every segment visually compelling, educational, and alive.

## ASPECT RATIO: {aspect_ratio}
- Frame: {frame_width}×{frame_height} units
- Pixel: {pixel_width}×{pixel_height}

## ASPECT RATIO CONFIG (MUST appear right after imports in EVERY script)
config.frame_width = {frame_width}
config.frame_height = {frame_height}
config.pixel_width = {pixel_width}
config.pixel_height = {pixel_height}

{safe_api_reference}

## SPATIAL SAFETY BOUNDS
- Horizontal: LEFT*{safe_x} to RIGHT*{safe_x}
- Vertical: UP*{safe_y} to DOWN*{safe_y}
- All Text objects MUST use: .scale_to_fit_width(config.frame_width * {width_factor})
  or set font_size ≤ {max_font}

## SEGMENTS — GENERATE ONE SCRIPT PER SEGMENT

{all_segments_block}

## CREATIVE GUIDELINES
1. Animate PROCESSES — things should move, transform, interact
2. Use motion to convey meaning: sorting → elements swap, networks → signals propagate
3. Camera movement every 6-8s keeps it cinematic
4. One focus object at a time — guide the viewer's eye
5. Prefer Transform/ReplacementTransform over FadeIn/FadeOut
6. No static screen longer than 1.5 seconds
7. Labels/text should be brief annotations, NOT the main content
8. Process visualization > labeled diagrams
9. Each script: sum of all self.play(run_time=X) + self.wait(Y) = exact duration

## STABILITY GUIDELINES
- Prefer well-known Manim patterns. Avoid experimental APIs.
- Always check that objects exist before transforming them.
- VGroup elements before bulk operations.

## DURATION ENFORCEMENT (CRITICAL)
- Each segment has an EXACT duration listed above. You MUST match it precisely.
- Calculate: total_time = sum(all self.play(..., run_time=X)) + sum(all self.wait(Y))
- total_time MUST equal the segment's Duration value.
- End each construct() with self.wait() to absorb any remaining time.
- Example for 8.50s: 6 animations × 1.2s each = 7.2s → self.wait(1.3) at the end.

## OUTPUT FORMAT
Separate each script with ===SCRIPT START=== on its own line.
Return ONLY raw Python code — NO markdown fences (no ```python), NO explanation text.
Do NOT wrap scripts in a single code block. Use ===SCRIPT START=== as the ONLY separator.

===SCRIPT START===
from manim import *
import numpy as np
import random

class Segment000(Scene):
    def construct(self):
        ...
===SCRIPT START===
from manim import *
import numpy as np
import random

class Segment001(Scene):
    def construct(self):
        ...
"""


def generate_manim_scripts_bulk(
    llm_client,
    segments: list,
    aspect_ratio: str = "9:16",
) -> List[Optional[str]]:
    """
    Generate ALL Manim scripts in a SINGLE bulk LLM call.
    
    Builds one prompt containing every segment's narration + scene spec,
    and asks Gemini to return all scripts separated by ===SCRIPT START===.
    
    This mirrors the legacy bulk approach but with scene spec context
    for richer creative understanding.
    
    Args:
        llm_client: LLM client with .generate() method
        segments: List of QualityNarrationSegment with scene_spec
        aspect_ratio: Video aspect ratio
    
    Returns:
        List of script strings (None for failures)
    """
    config = _get_aspect_config(aspect_ratio)
    width_factors = {"16:9": 0.85, "9:16": 0.65, "1:1": 0.75, "4:3": 0.80}
    width_factor = width_factors.get(aspect_ratio, 0.65)
    max_fonts = {"16:9": 48, "9:16": 32, "1:1": 42, "4:3": 44}
    max_font = max_fonts.get(aspect_ratio, 32)
    
    # ── Build per-segment blocks with full scene spec context ──
    all_segments_block = ""
    for i, segment in enumerate(segments):
        narration = segment.text if hasattr(segment, 'text') else ""
        spec = segment.scene_spec if hasattr(segment, 'scene_spec') else None
        dur = (
            getattr(segment, '_audio_duration_final', None)
            or segment.duration
            or 10.0
        )
        
        # Deserialize visual contract
        contract = None
        contract_json = getattr(segment, 'visual_contract', None)
        if contract_json:
            try:
                from .visual_validation import deserialize_contract
                contract = deserialize_contract(contract_json)
            except Exception:
                pass
        
        # Build rich scene direction from spec
        scene_direction = _build_scene_direction_text(spec, contract)
        
        all_segments_block += f"""
--- Segment {i+1} ---
Class: Segment{i:03d}
Duration: {dur:.2f}s (EXACT)
Narration: "{narration}"

Scene Direction:
{scene_direction}

"""
    
    prompt = GEMINI_MANIM_BATCH_PROMPT.format(
        num_segments=len(segments),
        aspect_ratio=aspect_ratio,
        frame_width=config["frame_width"],
        frame_height=config["frame_height"],
        pixel_width=config["pixel_width"],
        pixel_height=config["pixel_height"],
        safe_x=config["safe_x"],
        safe_y=config["safe_y"],
        safe_api_reference=SAFE_MANIM_API,
        width_factor=width_factor,
        max_font=max_font,
        all_segments_block=all_segments_block,
    )
    
    logger.info(
        f"🎬 Bulk generating {len(segments)} Manim scripts in one Gemini call "
        f"(prompt: {len(prompt)} chars)"
    )
    
    # ── Call LLM ──
    try:
        response = llm_client.generate(prompt, temperature=0.75)
    except Exception as e:
        logger.error(f"❌ Bulk Gemini generation failed: {e}")
        # Fall back to per-segment generation
        return _generate_per_segment_fallback(llm_client, segments, aspect_ratio)
    
    if not response:
        logger.warning("⚠️ Empty Gemini response for bulk generation, falling back to per-segment")
        return _generate_per_segment_fallback(llm_client, segments, aspect_ratio)
    
    # ── Parse bulk response into individual scripts ──
    scripts = _parse_bulk_response(response, len(segments))
    path = "./scripts.txt"
    with open(path, "w", encoding="utf-8") as f:
        # Joins the list items into one string, separated by newlines
        content = "\n".join(scripts) 
        f.write(content)
        logger.info("Script written in scripts.txt")
    if len(scripts) < len(segments):
        logger.warning(
            f"⚠️ Bulk parse got {len(scripts)}/{len(segments)} scripts, "
            f"generating missing ones individually"
        )
        # Pad with None and fill gaps via individual generation
        while len(scripts) < len(segments):
            scripts.append(None)
        
        for i, script in enumerate(scripts):
            if script is None:
                narration = segments[i].text if hasattr(segments[i], 'text') else ""
                spec = segments[i].scene_spec if hasattr(segments[i], 'scene_spec') else None
                dur = getattr(segments[i], '_audio_duration_final', None) or segments[i].duration or 10.0
                contract = None
                contract_json = getattr(segments[i], 'visual_contract', None)
                if contract_json:
                    try:
                        from .visual_validation import deserialize_contract
                        contract = deserialize_contract(contract_json)
                    except Exception:
                        pass
                
                logger.info(f"  🔄 Generating missing segment {i+1} individually...")
                scripts[i] = generate_manim_script(
                    llm_client, narration, spec, i, dur, aspect_ratio, contract
                )
    
    # ── Static validation for each script ──
    for i, script in enumerate(scripts):
        if script:
            validation = validate_script_static(script)
            if validation.passed:
                logger.info(f"  ✅ Segment {i+1}: validated ({len(script)} chars)")
            else:
                logger.warning(f"  ⚠️ Segment {i+1} validation: {validation.summary()}")
    
    valid = sum(1 for s in scripts if s is not None)
    logger.info(f"✅ Bulk generated {valid}/{len(segments)} Manim scripts via Gemini")
    return scripts


def _parse_bulk_response(response: str, expected_count: int) -> List[Optional[str]]:
    """
    Parse a bulk LLM response into individual Manim scripts.
    
    Tries multiple splitting strategies in order:
      0. JSON array of script strings (Gemini sometimes returns this)
      1. ===SCRIPT START=== / ===SCRIPT_N=== / ===SEGMENT_N=== markers
      2. Multiple ```python ... ``` code blocks (one per script)
      3. 'from manim import' boundaries
      4. 'class Segment' boundaries
    """
    # ── Step 0: Light markdown cleanup for bulk (preserve separators) ──
    content = response.strip()
    
    # Remove OUTER markdown fence if the whole response is one code block,
    # but preserve any ===...=== markers inside.
    outer_fence = re.match(r'^```(?:python)?\s*\n(.*?)\n```\s*$', content, re.DOTALL)
    if outer_fence:
        content = outer_fence.group(1).strip()

    # Log first 300 chars for debugging
    logger.debug(f"📋 Bulk response preview ({len(content)} chars): {content[:300]}...")
    
    # ── Strategy 0: JSON array of script strings ──
    # Gemini sometimes returns scripts as: ["script1", "script2", ...]
    if content.lstrip().startswith('['):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list) and len(parsed) >= 1:
                scripts = []
                for item in parsed:
                    if isinstance(item, str) and len(item.strip()) > 50:
                        # JSON strings have literal \n — they're already proper newlines after json.loads
                        cleaned = _clean_single_script(item.strip())
                        if 'class ' in cleaned and 'construct' in cleaned:
                            scripts.append(cleaned)
                if len(scripts) >= expected_count:
                    logger.info(f"📊 Bulk parse: {len(scripts)} scripts via JSON array parse")
                    return [_fix_class_name(s, i) for i, s in enumerate(scripts[:expected_count])]
                elif len(scripts) > 0:
                    logger.info(f"📊 JSON array parsed {len(scripts)}/{expected_count} scripts")
                    # Partial success — return what we have, caller fills gaps
                    return [_fix_class_name(s, i) for i, s in enumerate(scripts)]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass  # Not valid JSON, try other strategies
    
    # ── Strategy 1: Split on ===SCRIPT...=== markers ──
    marker_pattern = r'={2,}\s*(?:SCRIPT|SEGMENT)[\s_]*(?:START|\d+)?\s*={2,}'
    parts = re.split(marker_pattern, content)
    parts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 50]
    
    if len(parts) >= expected_count:
        logger.info(f"📊 Bulk parse: {len(parts)} scripts via marker split")
        return [_fix_class_name(_clean_single_script(p), i) for i, p in enumerate(parts[:expected_count])]
    
    marker_count = len(parts)
    
    # ── Strategy 2: Multiple ```python ... ``` code blocks ──
    code_blocks = re.findall(r'```python\s*\n(.*?)```', content, re.DOTALL)
    code_blocks = [b.strip() for b in code_blocks if b.strip() and len(b.strip()) > 50]
    
    if len(code_blocks) >= expected_count:
        logger.info(f"📊 Bulk parse: {len(code_blocks)} scripts via code-block split")
        return [_fix_class_name(b, i) for i, b in enumerate(code_blocks[:expected_count])]
    
    # ── Strategy 3: Split on 'from manim import' boundaries ──
    # Use \n as anchor since each script starts on a new line after previous script ends
    parts2 = re.split(r'\n(?=from manim import)', content)
    # Also handle case where content starts with 'from manim import' (no leading newline)
    if content.startswith('from manim import'):
        parts2 = [content.split('\n', 1)[0] + '\n' + p if i == 0 else p for i, p in enumerate(parts2)]
    parts2 = [p.strip() for p in parts2 if p.strip() and 'class ' in p and len(p.strip()) > 50]
    
    if len(parts2) >= expected_count:
        logger.info(f"📊 Bulk parse: {len(parts2)} scripts via 'from manim' split")
        return [_fix_class_name(_clean_single_script(p), i) for i, p in enumerate(parts2[:expected_count])]
    
    # ── Strategy 4: Split on 'class Segment' boundaries ──
    # Splits before each 'class SegmentNNN' while keeping config lines with the class
    parts3 = re.split(r'\n(?=class Segment\d+\s*\()', content)
    parts3 = [p.strip() for p in parts3 if p.strip() and 'def construct' in p]
    if parts3:
        for idx, p in enumerate(parts3):
            if 'from manim' not in p:
                parts3[idx] = 'from manim import *\nimport numpy as np\nimport random\n\n' + p
    
    if len(parts3) >= expected_count:
        logger.info(f"📊 Bulk parse: {len(parts3)} scripts via class boundary split")
        return [_fix_class_name(_clean_single_script(p), i) for i, p in enumerate(parts3[:expected_count])]
    
    # ── Return best result (caller fills gaps individually) ──
    candidates = [
        (parts, "marker"),
        (code_blocks, "code-block"),
        (parts2, "from-manim"),
        (parts3, "class-boundary"),
    ]
    best_parts, best_strategy = max(candidates, key=lambda x: len(x[0]))
    logger.warning(
        f"⚠️ Bulk parse: only {len(best_parts)}/{expected_count} scripts parsed "
        f"(best: {best_strategy}, marker={marker_count}, blocks={len(code_blocks)}, "
        f"from_manim={len(parts2)}, class={len(parts3)})"
    )
    result = [_fix_class_name(_clean_single_script(p), i) for i, p in enumerate(best_parts)]
    return result


def _clean_single_script(script: str) -> str:
    """Remove markdown fencing from a single extracted script chunk."""
    text = script.strip()
    # Remove leading ```python and trailing ```
    text = re.sub(r'^```(?:python)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()


def _generate_per_segment_fallback(
    llm_client,
    segments: list,
    aspect_ratio: str,
) -> List[Optional[str]]:
    """Fallback: generate each script individually when bulk fails."""
    logger.info("🔄 Per-segment fallback generation...")
    scripts = []
    for i, segment in enumerate(segments):
        narration = segment.text if hasattr(segment, 'text') else ""
        spec = segment.scene_spec if hasattr(segment, 'scene_spec') else None
        dur = getattr(segment, '_audio_duration_final', None) or segment.duration or 10.0
        
        contract = None
        contract_json = getattr(segment, 'visual_contract', None)
        if contract_json:
            try:
                from .visual_validation import deserialize_contract
                contract = deserialize_contract(contract_json)
            except Exception:
                pass
        
        logger.info(f"  🎬 Generating segment {i+1}/{len(segments)} individually...")
        script = generate_manim_script(
            llm_client, narration, spec, i, dur, aspect_ratio, contract
        )
        scripts.append(script)
    
    valid = sum(1 for s in scripts if s is not None)
    logger.info(f"✅ Per-segment fallback: {valid}/{len(segments)} scripts")
    return scripts


# ═════════════════════════════════════════════════════════════════════
# ERROR CORRECTION (reuses legacy correction strategy)
# ═════════════════════════════════════════════════════════════════════

def correct_script_error(
    llm_client,
    script: str,
    error: str,
    index: int,
    duration: float,
    attempt: int = 1,
    max_attempts: int = 3,
) -> str:
    """
    Fix a broken Manim script using LLM error correction.
    
    Uses progressive strategy:
      attempt 1-2: Full correction (preserve creative intent)
      attempt 3+:  Minimal repair (comment out broken parts)
    
    Args:
        llm_client: LLM client with .generate() method
        script: The broken script
        error: The error message / traceback
        index: Segment index
        duration: Required duration
        attempt: Current attempt number
        max_attempts: Maximum correction attempts
    
    Returns:
        Corrected script string (may be same as input if correction fails)
    """
    if attempt <= 2:
        # Full correction — preserve everything
        prompt = ERROR_CORRECTION_PROMPT.format(
            duration=duration,
            error=error[:2000],  # Truncate long errors
            script=script,
        )
        temperature = 0.2
    else:
        # Minimal repair — more conservative
        prompt = MINIMAL_REPAIR_PROMPT.format(
            index=index,
            duration=duration,
            error=error[:1500],
            script=script,
        )
        temperature = 0.1
    
    try:
        response = llm_client.generate(prompt, temperature=temperature)
        if response:
            corrected = _clean_script(response)
            corrected = _fix_class_name(corrected, index)
            
            # Quick sanity check
            if len(corrected) > 50 and "class " in corrected and "construct" in corrected:
                return corrected
            else:
                logger.warning(f"Correction attempt {attempt} produced invalid output")
                return script
        return script
    except Exception as e:
        logger.error(f"Error correction attempt {attempt} failed: {e}")
        return script


# ═════════════════════════════════════════════════════════════════════
# SCRIPT CLEANUP UTILITIES
# ═════════════════════════════════════════════════════════════════════

def _clean_script(response: str) -> str:
    """Remove markdown formatting, extract pure Python code."""
    if not response:
        return ""
    
    text = response.strip()
    
    # Extract from markdown code block
    if "```python" in text:
        start = text.find("```python") + len("```python")
        end = text.rfind("```")
        if end > start:
            text = text[start:end].strip()
    elif "```" in text:
        start = text.find("```") + 3
        end = text.rfind("```")
        if end > start:
            text = text[start:end].strip()
    
    # Remove stray backtick markers
    text = re.sub(r'^```\w*\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$', '', text, flags=re.MULTILINE)
    
    return text.strip()


def _fix_class_name(script: str, index: int) -> str:
    """Ensure the class name matches the expected Segment{index:03d} pattern."""
    expected_name = f"Segment{index:03d}"
    
    # Find existing class name
    match = re.search(r'class\s+(\w+)\(Scene\)', script)
    if match:
        current_name = match.group(1)
        if current_name != expected_name:
            # Replace class name and any self-references
            script = script.replace(f"class {current_name}(Scene)", f"class {expected_name}(Scene)")
    
    return script
