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
