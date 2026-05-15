"""
Manim Error Classifier & Deterministic Pre-Repair
===================================================

Deterministic classification of Manim render failures + regex-based
auto-fixes for the most common error patterns.

This module runs BEFORE any LLM call or vector retrieval.
Zero cost, instant execution.

Provides:
  - classify_error()       — categorize traceback into error domains
  - generate_failure_hash() — SHA256 for dedup / cache lookup
  - auto_fix_common_errors() — regex fixes for top 10 patterns
"""

import re
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# ERROR CATEGORIES
# ═══════════════════════════════════════════════════════════════════

class ErrorType:
    SYNTAX_ERROR = "SyntaxError"
    IMPORT_ERROR = "ImportError"
    ATTRIBUTE_ERROR = "AttributeError"
    TYPE_ERROR = "TypeError"
    NAME_ERROR = "NameError"
    ANIMATION_CONFLICT = "AnimationConflict"
    LAYOUT_OVERFLOW = "LayoutOverflow"
    TIMING_MISMATCH = "TimingMismatch"
    RENDERER_CRASH = "RendererCrash"
    API_COMPATIBILITY = "APICompatibilityError"
    LATEX_ERROR = "LaTeXError"
    SEMANTIC_SCENE_FAILURE = "SemanticSceneFailure"


@dataclass
class ErrorClassification:
    """Result of classifying a Manim traceback."""
    error_type: str
    failing_line: Optional[str] = None
    failing_line_number: Optional[int] = None
    failing_api: Optional[str] = None
    confidence: float = 1.0
    suggested_fix: Optional[str] = None  # Description of regex fix if available
    failure_hash: str = ""


# ═══════════════════════════════════════════════════════════════════
# CLASSIFICATION PATTERNS (ordered by specificity)
# ═══════════════════════════════════════════════════════════════════

_CLASSIFICATION_RULES = [
    # (regex_pattern, error_type, confidence)
    (r"SyntaxError:", ErrorType.SYNTAX_ERROR, 1.0),
    (r"IndentationError:", ErrorType.SYNTAX_ERROR, 1.0),
    (r"ImportError:|ModuleNotFoundError:", ErrorType.IMPORT_ERROR, 1.0),
    (r"LaTeX|dvipng|dvisvgm|latex.*error|Tex.*compilation", ErrorType.LATEX_ERROR, 0.95),
    (r"cannot animate.*already animating|animation.*conflict", ErrorType.ANIMATION_CONFLICT, 0.9),
    (r"out of bounds|position.*exceed|beyond.*frame", ErrorType.LAYOUT_OVERFLOW, 0.85),
    (r"ShowCreation|get_graph|FadeInFrom\b|GrowFromCenter.*deprecated", ErrorType.API_COMPATIBILITY, 0.9),
    (r"cairo|renderer.*crash|segfault|Segmentation", ErrorType.RENDERER_CRASH, 0.95),
    (r"duration|timing|run_time.*exceed", ErrorType.TIMING_MISMATCH, 0.8),
    (r"AttributeError:", ErrorType.ATTRIBUTE_ERROR, 1.0),
    (r"TypeError:", ErrorType.TYPE_ERROR, 1.0),
    (r"NameError:", ErrorType.NAME_ERROR, 1.0),
]


def classify_error(traceback_text: str) -> ErrorClassification:
    """
    Classify a Manim render traceback into an error domain.

    Args:
        traceback_text: Full traceback string from failed render.

    Returns:
        ErrorClassification with type, failing line, failing API, and hash.
    """
    traceback_lower = traceback_text.lower()

    # Determine error type
    error_type = ErrorType.SEMANTIC_SCENE_FAILURE  # default
    confidence = 0.5

    for pattern, etype, conf in _CLASSIFICATION_RULES:
        if re.search(pattern, traceback_text, re.IGNORECASE):
            error_type = etype
            confidence = conf
            break

    # Extract failing line
    failing_line, failing_line_number = _extract_failing_line(traceback_text)

    # Extract failing API
    failing_api = _extract_failing_api(traceback_text)

    # Generate failure hash
    failure_hash = generate_failure_hash(error_type, failing_api or "", traceback_text)

    classification = ErrorClassification(
        error_type=error_type,
        failing_line=failing_line,
        failing_line_number=failing_line_number,
        failing_api=failing_api,
        confidence=confidence,
        failure_hash=failure_hash,
    )

    logger.info(
        f"🏷️ Error classified: {error_type} (conf={confidence:.0%}) "
        f"API={failing_api or 'unknown'} hash={failure_hash[:12]}..."
    )

    return classification


def _extract_failing_line(traceback_text: str) -> Tuple[Optional[str], Optional[int]]:
    """Extract the specific failing line and line number from traceback."""
    # Pattern: File "...", line N
    #              code_line
    matches = re.findall(
        r'File\s+"[^"]*",\s+line\s+(\d+).*?\n\s+(.+)',
        traceback_text
    )
    if matches:
        last_match = matches[-1]  # Last frame is usually the actual failure
        try:
            return last_match[1].strip(), int(last_match[0])
        except (ValueError, IndexError):
            pass

    return None, None


def _extract_failing_api(traceback_text: str) -> Optional[str]:
    """Extract the Manim API call that caused the failure."""
    # Look for common Manim class/method names in the error
    api_patterns = [
        r"(Text|MathTex|Tex|MarkupText)\s*\(",
        r"(Create|Write|FadeIn|FadeOut|Transform|ReplacementTransform)\s*\(",
        r"(ShowCreation|DrawBorderThenFill|GrowFromCenter)\s*\(",
        r"(VGroup|Group|Axes|NumberPlane|Graph|Table)\s*\(",
        r"(Circle|Rectangle|Square|Arrow|Line|Dot)\s*\(",
        r"\.(move_to|shift|next_to|scale|rotate|set_color|animate)\s*[\.(]",
        r"self\.(play|add|remove|wait)\s*\(",
    ]

    for pattern in api_patterns:
        match = re.search(pattern, traceback_text)
        if match:
            return match.group(0).rstrip("(").strip()

    return None


# ═══════════════════════════════════════════════════════════════════
# FAILURE HASHING
# ═══════════════════════════════════════════════════════════════════

def generate_failure_hash(error_type: str, failing_api: str, traceback_text: str) -> str:
    """
    Generate SHA256 hash of failure signature for deduplication.

    Normalizes the traceback to remove line-specific noise (file paths, 
    line numbers) so structurally identical errors hash to the same value.
    """
    # Normalize: strip file paths, line numbers, timestamps
    normalized_tb = re.sub(r'File\s+"[^"]*"', 'File "X"', traceback_text)
    normalized_tb = re.sub(r'line\s+\d+', 'line N', normalized_tb)
    normalized_tb = re.sub(r'Segment\d+', 'SegmentN', normalized_tb)

    # Only keep the error message portion (last few lines)
    lines = normalized_tb.strip().splitlines()
    signature_lines = lines[-5:] if len(lines) > 5 else lines
    signature = "\n".join(signature_lines)

    hash_input = f"{error_type}|{failing_api}|{signature}"
    return hashlib.sha256(hash_input.encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════
# DETERMINISTIC PRE-REPAIR (regex auto-fixes)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class AutoFixResult:
    """Result of deterministic pre-repair."""
    script: str
    was_fixed: bool = False
    fixes_applied: List[str] = field(default_factory=list)


def auto_fix_common_errors(
    script: str,
    error: str,
    segment_index: int
) -> AutoFixResult:
    """
    Apply deterministic regex fixes for the most common Manim errors.
    Runs BEFORE any LLM call. Zero cost, instant.

    Args:
        script: The failing Manim script.
        error: The error traceback.
        segment_index: Expected segment index (for class name fix).

    Returns:
        AutoFixResult with fixed script and list of applied fixes.
    """
    original = script
    fixes = []

    # 1. Wrong class name
    expected_class = f"Segment{segment_index:03d}"
    class_pattern = r'class\s+(\w+)\s*\(\s*Scene\s*\)'
    match = re.search(class_pattern, script)
    if match and match.group(1) != expected_class:
        script = re.sub(class_pattern, f'class {expected_class}(Scene)', script)
        fixes.append(f"class_name: {match.group(1)} → {expected_class}")

    # 2. Missing 'from manim import *'
    if 'from manim import' not in script:
        script = "from manim import *\n" + script
        fixes.append("injected: from manim import *")

    # 3. ShowCreation → Create (deprecated API)
    if 'ShowCreation' in script:
        script = script.replace('ShowCreation', 'Create')
        fixes.append("api: ShowCreation → Create")

    # 4. Text(... size=) → font_size= 
    if re.search(r'Text\s*\([^)]*\bsize\s*=', script):
        script = re.sub(r'(Text\s*\([^)]*)\bsize\s*=', r'\1font_size=', script)
        fixes.append("api: Text size= → font_size=")

    # 5. bold=True → weight=BOLD
    if re.search(r'Text\s*\([^)]*bold\s*=\s*True', script):
        script = re.sub(r'bold\s*=\s*True', 'weight=BOLD', script)
        fixes.append("api: bold=True → weight=BOLD")

    # 6. get_graph → plot (deprecated)
    if '.get_graph(' in script:
        script = script.replace('.get_graph(', '.plot(')
        fixes.append("api: get_graph() → plot()")

    # 7. duration= → run_time= in self.play()
    if re.search(r'self\.play\s*\([^)]*\bduration\s*=', script):
        script = re.sub(
            r'(self\.play\s*\([^)]*)\bduration\s*=',
            r'\1run_time=',
            script
        )
        fixes.append("api: self.play(duration=) → run_time=")

    # 8. FadeIn(mob, direction=) → shift=
    if re.search(r'FadeIn\s*\([^)]*direction\s*=', script):
        script = re.sub(
            r'(FadeIn\s*\([^)]*)\bdirection\s*=',
            r'\1shift=',
            script
        )
        fixes.append("api: FadeIn(direction=) → shift=")

    # 9. move_to(x, y) → move_to([x, y, 0])
    if re.search(r'\.move_to\s*\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)', script):
        script = re.sub(
            r'\.move_to\s*\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)',
            r'.move_to([\1, \2, 0])',
            script
        )
        fixes.append("api: move_to(x, y) → move_to([x, y, 0])")

    # 10. LaTeX error → replace MathTex/Tex with Text (fallback)
    if 'latex' in error.lower() or 'dvipng' in error.lower() or 'dvisvgm' in error.lower():
        # Replace simple MathTex/Tex with Text equivalents
        if 'MathTex' in script or re.search(r'\bTex\s*\(', script):
            # Replace MathTex("x^2") with Text("x²")
            script = re.sub(r'MathTex\s*\(', 'Text(', script)
            script = re.sub(r'(?<!\w)Tex\s*\(', 'Text(', script)
            fixes.append("latex_fallback: MathTex/Tex → Text")

    # ── STRUCTURAL AUTO-FIXES ──

    # 11. Shape.add(text_var) → VGroup(shape, text_var)
    # Detects: var = Rectangle(...).add(other_var) — line-by-line scan (no catastrophic regex)
    shape_types = (
        'Rectangle', 'Circle', 'Square', 'RoundedRectangle', 'Ellipse',
        'Triangle', 'Polygon', 'Star', 'Arc', 'Sector', 'Arrow', 'Line',
    )
    for line in script.split('\n'):
        stripped = line.strip()
        if '.add(' not in stripped or '=' not in stripped:
            continue
        # Check if any shape type is in this line
        has_shape = any(st + '(' in stripped for st in shape_types)
        if not has_shape:
            continue
        
        eq_pos = stripped.find('=')
        add_pos = stripped.find('.add(')
        if eq_pos < 1 or add_pos < eq_pos:
            continue
        
        var_name = stripped[:eq_pos].strip()
        if not var_name.isidentifier():
            continue
        
        shape_expr = stripped[eq_pos+1:add_pos].strip()
        # Extract child from .add(child_var)
        rest = stripped[add_pos+5:]  # after '.add('
        paren_depth = 1
        child_end = 0
        for ci, ch in enumerate(rest):
            if ch == '(':
                paren_depth += 1
            elif ch == ')':
                paren_depth -= 1
                if paren_depth == 0:
                    child_end = ci
                    break
        if child_end > 0:
            child_var = rest[:child_end].strip()
            if child_var.isidentifier():
                indent = line[:len(line) - len(line.lstrip())]
                new_line = (
                    f"{indent}{var_name}_bg = {shape_expr}\n"
                    f"{indent}{var_name} = VGroup({var_name}_bg, {child_var})"
                )
                script = script.replace(line, new_line, 1)
                fixes.append(f"structural: {var_name} = Shape().add({child_var}) → VGroup")

    # 12. Chained .animate.X().Y().Z() → split (replace with first mutation only)
    # Safe line-by-line scan instead of catastrophic regex
    for line in script.split('\n'):
        if '.animate.' not in line:
            continue
        anim_pos = line.find('.animate.')
        if anim_pos < 0:
            continue
        
        after = line[anim_pos + len('.animate'):]
        # Count chained .method() calls
        chain_count = 0
        first_end = 0
        i = 0
        while i < len(after):
            if after[i] == '.':
                chain_count += 1
                i += 1
                # Skip method name
                while i < len(after) and after[i] != '(':
                    i += 1
                if i < len(after) and after[i] == '(':
                    depth = 1
                    i += 1
                    while i < len(after) and depth > 0:
                        if after[i] == '(':
                            depth += 1
                        elif after[i] == ')':
                            depth -= 1
                        i += 1
                    if chain_count == 1:
                        first_end = i  # End of first .method() call
            else:
                break
        
        if chain_count >= 3 and first_end > 0:
            # Replace full chain with just first mutation
            old_chain = line[anim_pos + len('.animate'):].rstrip()
            first_mutation = after[:first_end]
            new_line = line[:anim_pos + len('.animate')] + first_mutation
            # Preserve any trailing content like ", run_time=1)"
            script = script.replace(line.rstrip(), new_line, 1)
            fixes.append(f"structural: split chained .animate (kept first mutation)")

    # 13. Excessive concurrent animations — auto-detect but don't auto-split
    # (This is logged as a warning rather than auto-fixed due to complexity)

    was_fixed = script != original

    if fixes:
        logger.info(f"🔧 Auto-fix applied {len(fixes)} fixes: {', '.join(fixes)}")

    return AutoFixResult(
        script=script,
        was_fixed=was_fixed,
        fixes_applied=fixes,
    )
