"""
Correction Prompt Builder
==========================

Builds structured 7-section correction prompts for the Ollama models.
Injects retrieved fix memories, safe API reference, and minimal script context.

Creative Preservation Rule: prompts explicitly instruct the model to
preserve animation intent, scene composition, and cinematic pacing.
Only technical failures are corrected.
"""

import re
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# SAFE API REFERENCE (compact version for correction prompts)
# ═══════════════════════════════════════════════════════════════════

MANIM_SAFE_API_COMPACT = """
MANIM v0.19.0 — SAFE API RULES

ALLOWED: Circle, Rectangle, Square, Arrow, Line, Dot, Text, MathTex,
VGroup, Group, Axes, NumberPlane, Graph, Table, Brace, Arc, Polygon,
Star, Sector, Annulus, DashedLine, RoundedRectangle, Triangle

TEXT: Text(text, font_size=24, color=WHITE, weight=BOLD)
  WRONG: size=, bold=True  |  RIGHT: font_size=, weight=BOLD
  ALWAYS: .scale_to_fit_width(config.frame_width * 0.6)

ANIMATIONS: Create, Write, FadeIn(shift=UP), FadeOut, Transform,
ReplacementTransform, GrowFromCenter, Indicate, Flash, Circumscribe,
AnimationGroup, LaggedStart, LaggedStartMap, Succession

self.play(..., run_time=1.0)  — NOT duration=
FadeIn(mob, shift=UP)         — NOT direction=
mob.move_to([x, y, 0])       — NOT move_to(x, y)

FORBIDDEN: ThreeDScene, Surface, Sphere, Cube, ShowCreation,
get_graph, HGroup, OpenGLRenderer, time.sleep, input(), print()

DEPRECATED → REPLACEMENT:
  ShowCreation → Create
  get_graph → plot
  FadeInFrom → FadeIn(shift=)
"""


def build_correction_prompt(
    error_type: str,
    traceback: str,
    failing_line: Optional[str],
    script_context: str,
    segment_index: int,
    duration: float,
    aspect_ratio: str,
    retrieved_fixes: Optional[List[dict]] = None,
) -> str:
    """
    Build a structured 7-section correction prompt.
    
    Args:
        error_type: Classified error category.
        traceback: Full or truncated traceback.
        failing_line: The specific line that failed.
        script_context: Relevant portion of the script (NOT full script).
        segment_index: Segment number.
        duration: Expected scene duration.
        aspect_ratio: Video aspect ratio.
        retrieved_fixes: List of similar fix dicts from memory.
    
    Returns:
        Complete prompt string for the correction model.
    """
    sections = []

    # ── SECTION 1: SYSTEM ROLE ──
    sections.append("""You are a Manim script correction engine.
Your role: fix ONLY the technical failure in this Manim Python script.
You must produce a MINIMAL-DIFF correction — change as few lines as possible.
You must NOT rewrite the entire script.
You must NOT change animation intent, scene composition, or creative choices.
You are a surgical repair tool, not a rewriter.""")

    # ── SECTION 2: MANIM VERSION / RULES ──
    sections.append(MANIM_SAFE_API_COMPACT)

    # ── SECTION 3: CURRENT FAILURE ──
    tb_truncated = traceback[-1500:] if len(traceback) > 1500 else traceback
    failure_section = f"""CURRENT FAILURE
Error Type: {error_type}
Segment: Segment{segment_index:03d}
Duration: {duration:.2f}s
Aspect Ratio: {aspect_ratio}

Traceback:
{tb_truncated}"""

    if failing_line:
        failure_section += f"\n\nFailing Line:\n{failing_line}"

    sections.append(failure_section)

    # ── SECTION 4: SCRIPT CONTEXT ──
    sections.append(f"""SCRIPT CONTEXT (relevant portion only)
{script_context}""")

    # ── SECTION 5: RETRIEVED FIX MEMORIES ──
    if retrieved_fixes:
        memory_lines = ["SIMILAR SUCCESSFUL FIXES FROM MEMORY"]
        total_chars = 0
        for i, fix in enumerate(retrieved_fixes[:3]):  # Hard limit: 3
            fix_text = (
                f"\nFix {i+1}:\n"
                f"  Error: {fix.get('error_type', 'unknown')}\n"
                f"  Summary: {fix.get('fix_summary', 'N/A')}\n"
            )
            diff = fix.get('code_diff', '')
            if diff:
                # Only include first 500 chars of diff
                fix_text += f"  Diff:\n{diff[:500]}\n"

            if total_chars + len(fix_text) > 2000:  # Token budget
                break
            memory_lines.append(fix_text)
            total_chars += len(fix_text)

        sections.append("\n".join(memory_lines))
    else:
        sections.append("NO SIMILAR FIXES IN MEMORY — this may be a new error pattern.")

    # ── SECTION 6: CORRECTION OBJECTIVE ──
    sections.append(f"""CORRECTION OBJECTIVE
1. Fix ONLY the {error_type} described above
2. Preserve ALL animation intent and visual design
3. Preserve scene composition, pacing, and cinematic structure
4. Maintain exact class name: Segment{segment_index:03d}
5. Maintain exact duration: {duration:.2f}s
6. Do NOT restructure or rewrite unrelated code
7. Do NOT remove animations to "simplify"
8. Prefer the smallest possible change that fixes the error""")

    # ── SECTION 7: OUTPUT FORMAT ──
    sections.append("""OUTPUT FORMAT
Return ONLY the corrected Python code.
No explanations. No markdown. No code fences.
The output must start with 'from manim import *' or an import statement.
The output must be a complete, executable Manim script.""")

    prompt = "\n\n---\n\n".join(sections)
    logger.debug(f"📝 Built correction prompt: {len(prompt)} chars, {len(sections)} sections")
    return prompt


def extract_script_context(
    script: str,
    failing_line_number: Optional[int] = None,
    context_radius: int = 15,
) -> str:
    """
    Extract relevant script context around the failure point.
    
    Instead of truncating at 4000 chars (which breaks context),
    extracts:
    - Import block
    - Class declaration line
    - ±15 lines around the failing line
    - Aspect ratio config block
    
    Args:
        script: Full script.
        failing_line_number: Line number of failure (1-indexed).
        context_radius: Lines before/after failure to include.
    
    Returns:
        Focused script context string.
    """
    lines = script.splitlines()

    if not lines:
        return script

    # If we don't know the failing line, return the script
    # but cap at a reasonable length
    if failing_line_number is None or failing_line_number < 1:
        if len(script) <= 6000:
            return script
        # Return first 3000 + last 3000 chars
        return script[:3000] + "\n# ... [middle omitted] ...\n" + script[-3000:]

    # Zero-index
    fail_idx = failing_line_number - 1
    fail_idx = min(fail_idx, len(lines) - 1)

    context_parts = []

    # Always include imports (first N lines until class definition)
    import_end = 0
    for i, line in enumerate(lines):
        if re.match(r'^class\s+\w+\s*\(', line):
            import_end = i
            break
        if i > 30:  # Safety cap
            import_end = i
            break

    context_parts.append("# === IMPORTS & CONFIG ===")
    context_parts.extend(lines[:import_end])

    # Include class declaration
    class_line = None
    for i, line in enumerate(lines):
        if re.match(r'^class\s+\w+\s*\(.*Scene\s*\)', line):
            class_line = i
            break

    if class_line is not None and class_line >= import_end:
        context_parts.append(f"\n# === CLASS (line {class_line + 1}) ===")
        context_parts.append(lines[class_line])

    # Include context around failing line
    start = max(import_end, fail_idx - context_radius)
    end = min(len(lines), fail_idx + context_radius + 1)

    context_parts.append(f"\n# === FAILING AREA (lines {start+1}-{end}) ===")
    for i in range(start, end):
        marker = " >>> " if i == fail_idx else "     "
        context_parts.append(f"{marker}{lines[i]}")

    return "\n".join(context_parts)


def clean_correction_response(response: str) -> str:
    """
    Clean the LLM correction response to extract pure Python code.
    Removes markdown fences, explanations, etc.
    """
    if not response:
        return response

    # Remove markdown code fences
    if "```python" in response:
        start = response.find("```python") + len("```python")
        end = response.rfind("```")
        if end > start:
            response = response[start:end].strip()

    # Remove any remaining backticks
    response = re.sub(r'```+', '', response).strip()

    # Remove leading explanation text (before first import)
    if "from manim import" in response:
        idx = response.find("from manim import")
        if idx > 0:
            # Check if the text before is just explanation
            prefix = response[:idx].strip()
            if not prefix.startswith("import") and not prefix.startswith("#"):
                response = response[idx:]

    return response.strip()
