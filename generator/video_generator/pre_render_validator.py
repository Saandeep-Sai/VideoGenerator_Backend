"""
Pre-Render Validation Gate
===========================

3-stage validation for Manim scripts:
  Stage 1: Static Validation   (instant, free — before render)
  Stage 2: Render Validation    (expensive — only after Stage 1 passes)
  Stage 3: Semantic Validation  (post-render, lightweight)

Stage 2 NEVER runs unless Stage 1 passes.
This prevents wasting 30-60s on scripts with obvious syntax errors.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# FORBIDDEN / DEPRECATED PATTERNS
# ═══════════════════════════════════════════════════════════════════

FORBIDDEN_IMPORTS = [
    "ThreeDScene", "Surface", "ParametricSurface", "Sphere", "Cube",
    "OpenGLRenderer", "PIL", "requests", "subprocess", "os.system",
]

DEPRECATED_APIS = {
    "ShowCreation": "Create",
    "get_graph": "plot",
    "FadeInFrom": "FadeIn(... shift=)",
}


@dataclass
class ValidationResult:
    """Result of pre-render validation."""
    is_valid: bool
    stage: str  # "static" | "render" | "semantic"
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    auto_fixed_script: Optional[str] = None  # If auto-fixable issues found


# ═══════════════════════════════════════════════════════════════════
# STAGE 1: STATIC VALIDATION
# ═══════════════════════════════════════════════════════════════════

def validate_static(script: str, segment_index: int) -> ValidationResult:
    """
    Stage 1: Instant, zero-cost static validation.
    
    Checks:
    1. Python compile() — catches all syntax errors
    2. Required class/method structure
    3. Required imports
    4. No forbidden imports
    5. No deprecated APIs (warning only)
    6. No time.sleep() (should be self.wait())
    
    Returns ValidationResult. If auto-fixable issues found, 
    auto_fixed_script is populated.
    """
    errors = []
    warnings = []
    auto_fixed = script

    # 1. Python compile check (catches ALL syntax errors instantly)
    try:
        compile(script, f"segment_{segment_index:03d}.py", "exec")
    except SyntaxError as e:
        errors.append(f"SyntaxError at line {e.lineno}: {e.msg}")
        return ValidationResult(
            is_valid=False,
            stage="static",
            errors=errors,
        )

    # 2. Required class structure
    expected_class = f"Segment{segment_index:03d}"
    if f"class {expected_class}(Scene)" not in script:
        # Check if ANY Scene class exists
        class_match = re.search(r'class\s+(\w+)\s*\(\s*Scene\s*\)', script)
        if class_match:
            wrong_name = class_match.group(1)
            warnings.append(f"Wrong class name: {wrong_name} (expected {expected_class})")
            auto_fixed = re.sub(
                r'class\s+\w+\s*\(\s*Scene\s*\)',
                f'class {expected_class}(Scene)',
                auto_fixed
            )
        else:
            errors.append(f"Missing class {expected_class}(Scene)")

    # 3. Required construct method
    if "def construct(self)" not in script:
        errors.append("Missing def construct(self)")

    # 4. Required manim import
    if "from manim import" not in script:
        warnings.append("Missing 'from manim import *'")
        auto_fixed = "from manim import *\n" + auto_fixed

    # 5. Forbidden imports — check actual import statements only
    for forbidden in FORBIDDEN_IMPORTS:
        # Use word-boundary regex to avoid false positives (e.g. TAG_PILL matching PIL)
        import_pattern = rf'\b(import\s+{re.escape(forbidden)}|from\s+{re.escape(forbidden)}\s+import)\b'
        for line in script.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(import_pattern, stripped):
                errors.append(f"Forbidden API/import: {forbidden}")
                break

    # 6. Deprecated API warnings
    for old_api, new_api in DEPRECATED_APIS.items():
        if old_api in script:
            warnings.append(f"Deprecated API: {old_api} → use {new_api}")

    # 7. time.sleep() check
    if re.search(r'\btime\.sleep\s*\(', script):
        warnings.append("time.sleep() found — should use self.wait()")
        auto_fixed = re.sub(r'\btime\.sleep\s*\(', 'self.wait(', auto_fixed)

    # 8. input()/print() inside construct
    construct_body = _extract_construct_body(script)
    if construct_body:
        if re.search(r'\binput\s*\(', construct_body):
            errors.append("input() call inside construct()")
        if re.search(r'\bprint\s*\(', construct_body):
            warnings.append("print() inside construct() — may cause issues")

    is_valid = len(errors) == 0
    has_fixes = auto_fixed != script

    if errors:
        logger.warning(f"❌ Static validation FAILED ({len(errors)} errors): {errors}")
    elif warnings:
        logger.info(f"⚠️ Static validation PASSED with {len(warnings)} warnings")
    else:
        logger.debug(f"✅ Static validation PASSED clean")

    return ValidationResult(
        is_valid=is_valid,
        stage="static",
        errors=errors,
        warnings=warnings,
        auto_fixed_script=auto_fixed if has_fixes else None,
    )


# ═══════════════════════════════════════════════════════════════════
# STAGE 1.5: STRUCTURAL VALIDATION (between static and render)
# ═══════════════════════════════════════════════════════════════════

# Complexity budget limits
COMPLEXITY_BUDGET = {
    "max_play_calls": 18,
    "max_concurrent_anims": 6,
    "max_updaters": 3,
    "max_mobject_creations": 40,
    "max_animate_chain_depth": 2,
    "error_concurrent_anims": 8,  # Hard error threshold
}

# Unsafe .add() patterns — shapes that should use VGroup instead
_UNSAFE_ADD_PARENTS = [
    "Rectangle", "Circle", "Square", "RoundedRectangle", "Ellipse",
    "Triangle", "Polygon", "RegularPolygon", "Star", "Arc", "Sector",
    "Arrow", "Line", "Dot",
]
_UNSAFE_ADD_CHILDREN = [
    "Text", "MathTex", "Tex", "MarkupText", "Integer", "DecimalNumber",
]


def validate_structural(script: str, segment_index: int) -> ValidationResult:
    """
    Stage 1.5: Structural validation — detects unsafe Manim patterns.
    
    This catches architecturally unstable scripts that would crash during
    render or cause infinite correction loops. Runs AFTER static validation
    and BEFORE expensive render.
    
    Detects:
    - Unsafe object ownership (.add(Text) on shapes)
    - Chained .animate mutations (>2 depth)
    - Overloaded self.play() blocks (>6 concurrent)
    - Excessive updaters
    - Removed-then-animated objects
    - Scene complexity budget violations
    
    Auto-fixes:
    - Shape.add(text) → VGroup(shape, text)
    """
    errors = []
    warnings = []
    auto_fixed = script
    
    construct_body = _extract_construct_body(script)
    if not construct_body:
        # Can't analyze without construct body — skip structural
        return ValidationResult(is_valid=True, stage="structural")

    # ── 1. Unsafe .add() ownership (THE #1 CRASH PATTERN) ──
    # Use simple string scanning instead of catastrophic regex
    for parent in _UNSAFE_ADD_PARENTS:
        # Simple line-by-line check for Pattern A: var = Shape(...).add(...)
        for line in script.split('\n'):
            stripped = line.strip()
            # Check if line has Shape(...).add(...)
            if f'{parent}(' in stripped and '.add(' in stripped:
                # Extract the variable name (before =)
                eq_pos = stripped.find('=')
                if eq_pos > 0:
                    parent_var = stripped[:eq_pos].strip()
                    if parent_var.isidentifier():
                        warnings.append(
                            f"Unsafe ownership: {parent}().add() on line — "
                            f"use VGroup() instead"
                        )
                        # Auto-fix: try to split Shape(...).add(child_var)
                        add_pos = stripped.find('.add(')
                        if add_pos > 0:
                            shape_part = stripped[eq_pos+1:add_pos].strip()
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
                                    old_line = line
                                    indent = line[:len(line) - len(line.lstrip())]
                                    new_line = (
                                        f"{indent}{parent_var}_bg = {shape_part}\n"
                                        f"{indent}{parent_var} = VGroup({parent_var}_bg, {child_var})"
                                    )
                                    auto_fixed = auto_fixed.replace(old_line, new_line, 1)

    # ── 2. Chained .animate mutations ──
    # Safe detection: count consecutive .method() after .animate
    for line in script.split('\n'):
        if '.animate.' not in line:
            continue
        # Count method calls after .animate
        anim_pos = line.find('.animate.')
        if anim_pos < 0:
            continue
        after_animate = line[anim_pos + len('.animate'):]
        # Count top-level .method() calls
        chain_depth = 0
        i = 0
        while i < len(after_animate):
            if after_animate[i] == '.':
                chain_depth += 1
                i += 1
                # Skip to end of this method call
                while i < len(after_animate) and after_animate[i] != '(':
                    i += 1
                if i < len(after_animate) and after_animate[i] == '(':
                    # Skip balanced parens
                    depth = 1
                    i += 1
                    while i < len(after_animate) and depth > 0:
                        if after_animate[i] == '(':
                            depth += 1
                        elif after_animate[i] == ')':
                            depth -= 1
                        i += 1
            else:
                i += 1
        
        if chain_depth >= 3:
            warnings.append(
                f"Deep .animate chain ({chain_depth} mutations) — "
                f"split into separate self.play() calls"
            )

    # ── 3. Overloaded self.play() blocks ──
    # Use safe extraction: find self.play( and balance parens
    play_blocks = _extract_play_blocks(construct_body)
    for i, block in enumerate(play_blocks):
        args = [
            a.strip() for a in _split_top_level_args(block)
            if a.strip()
            and not a.strip().startswith('run_time')
            and not a.strip().startswith('rate_func')
        ]
        if len(args) > COMPLEXITY_BUDGET["error_concurrent_anims"]:
            errors.append(
                f"self.play() block {i+1} has {len(args)} concurrent animations "
                f"(max {COMPLEXITY_BUDGET['error_concurrent_anims']})"
            )
        elif len(args) > COMPLEXITY_BUDGET["max_concurrent_anims"]:
            warnings.append(
                f"self.play() block {i+1} has {len(args)} concurrent animations "
                f"(recommended max {COMPLEXITY_BUDGET['max_concurrent_anims']})"
            )

    # ── 4. Excessive updaters ──
    updater_count = len(re.findall(
        r'\badd_updater\b|\balways_redraw\b', construct_body
    ))
    if updater_count > COMPLEXITY_BUDGET["max_updaters"]:
        warnings.append(
            f"{updater_count} updaters detected "
            f"(max {COMPLEXITY_BUDGET['max_updaters']}) — performance risk"
        )

    # ── 5. Removed-then-animated objects ──
    removed_objects = set()
    for match in re.finditer(r'self\.remove\s*\(\s*(\w+)', construct_body):
        removed_objects.add(match.group(1))
    if removed_objects:
        for obj_name in removed_objects:
            remove_pos = construct_body.find(f"self.remove({obj_name}")
            if remove_pos >= 0:
                after_remove = construct_body[remove_pos + len(f"self.remove({obj_name}"):]
                # Simple string search for later animation of this object
                if f'{obj_name}.animate.' in after_remove:
                    warnings.append(
                        f"Object '{obj_name}' animated after self.remove() — "
                        f"will cause silent failure or crash"
                    )

    # ── 6. Complexity budget scoring ──
    total_plays = len(play_blocks)
    if total_plays > COMPLEXITY_BUDGET["max_play_calls"]:
        warnings.append(
            f"{total_plays} self.play() calls "
            f"(budget: {COMPLEXITY_BUDGET['max_play_calls']}) — overloaded scene"
        )

    # Count mobject creations
    mobject_classes = [
        "Text", "MathTex", "Tex", "MarkupText", "Circle", "Rectangle",
        "Square", "RoundedRectangle", "Triangle", "Arrow", "Line", "Dot",
        "VGroup", "Axes", "NumberPlane", "Graph", "Table", "Star",
        "Polygon", "Arc", "Sector", "Ellipse", "Brace", "Code",
    ]
    mobject_pattern = r'\b(' + '|'.join(mobject_classes) + r')\s*\('
    mobject_count = len(re.findall(mobject_pattern, script))
    if mobject_count > COMPLEXITY_BUDGET["max_mobject_creations"]:
        warnings.append(
            f"{mobject_count} Mobject creations "
            f"(budget: {COMPLEXITY_BUDGET['max_mobject_creations']}) — memory risk"
        )

    # ── Result ──
    is_valid = len(errors) == 0
    has_fixes = auto_fixed != script

    if errors:
        logger.warning(
            f"❌ Structural validation FAILED ({len(errors)} errors, "
            f"{len(warnings)} warnings): {errors}"
        )
    elif warnings:
        logger.info(
            f"⚠️ Structural validation PASSED with {len(warnings)} warnings: "
            f"{warnings[:3]}"
        )
    else:
        logger.debug("✅ Structural validation PASSED clean")

    return ValidationResult(
        is_valid=is_valid,
        stage="structural",
        errors=errors,
        warnings=warnings,
        auto_fixed_script=auto_fixed if has_fixes else None,
    )


def _extract_play_blocks(construct_body: str) -> List[str]:
    """
    Safely extract the content of each self.play(...) call.
    Uses balanced parenthesis counting — NO regex on nested parens.
    """
    blocks = []
    search_start = 0
    marker = 'self.play('
    
    while True:
        pos = construct_body.find(marker, search_start)
        if pos < 0:
            break
        
        # Start after the opening paren
        content_start = pos + len(marker)
        depth = 1
        i = content_start
        while i < len(construct_body) and depth > 0:
            ch = construct_body[i]
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            i += 1
        
        if depth == 0:
            blocks.append(construct_body[content_start:i-1])
        
        search_start = i
    
    return blocks


def _split_top_level_args(text: str) -> List[str]:
    """Split comma-separated arguments respecting parentheses nesting."""
    args = []
    depth = 0
    current = []
    for char in text:
        if char in '([{':
            depth += 1
            current.append(char)
        elif char in ')]}':
            depth -= 1
            current.append(char)
        elif char == ',' and depth == 0:
            args.append(''.join(current))
            current = []
        else:
            current.append(char)
    if current:
        args.append(''.join(current))
    return args


# ═══════════════════════════════════════════════════════════════════
# STAGE 3: SEMANTIC VALIDATION (post-render)
# ═══════════════════════════════════════════════════════════════════

def validate_semantic(script: str) -> ValidationResult:
    """
    Stage 3: Lightweight semantic checks on the script structure.
    Run after successful render to flag quality issues.
    
    Checks:
    1. Has at least one animation (self.play)
    2. Not just a long self.wait() (empty scene)
    3. Has visible content (at least one Mobject creation)
    """
    warnings = []

    # Check for animations
    play_count = len(re.findall(r'self\.play\s*\(', script))
    if play_count == 0:
        warnings.append("No self.play() calls — scene may appear static")

    # Check for empty scene (just wait)
    construct_body = _extract_construct_body(script)
    if construct_body:
        non_wait_lines = [
            line.strip() for line in construct_body.splitlines()
            if line.strip()
            and not line.strip().startswith('#')
            and 'self.wait' not in line
        ]
        if len(non_wait_lines) < 3:
            warnings.append("Scene appears nearly empty (< 3 non-wait lines)")

    # Check for Mobject creation
    mobject_patterns = [
        r'\b(Text|MathTex|Circle|Rectangle|Square|Arrow|Line|Dot|VGroup|Axes)\s*\(',
    ]
    has_mobjects = any(
        re.search(p, script) for p in mobject_patterns
    )
    if not has_mobjects:
        warnings.append("No visible Mobjects detected in scene")

    return ValidationResult(
        is_valid=True,  # Semantic issues are warnings, not blockers
        stage="semantic",
        warnings=warnings,
    )


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _extract_construct_body(script: str) -> Optional[str]:
    """Extract the body of the construct() method."""
    match = re.search(
        r'def\s+construct\s*\(\s*self\s*\)\s*:\s*\n((?:(?:[ \t]+.+|[ \t]*)\n)*)',
        script
    )
    if match:
        return match.group(1)
    return None
