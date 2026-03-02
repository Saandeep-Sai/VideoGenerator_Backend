"""
Template-Based Manim Code Generator
===================================

Generates Manim code from validated scene specifications.
Uses the visual primitive library instead of generating arbitrary code.

Key principles:
1. Code is CONSTRAINED by the specification
2. Uses primitives from visual_primitives.py
3. Grid-aligned positioning only
4. Deterministic animation sequences
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from textwrap import dedent, indent

from .scene_specification import (
    SceneSpecification, VisualElement, TransformationStep,
    ElementType, TransformAction, Position, MetaphorType
)

logger = logging.getLogger(__name__)


# =============================================================================
# CODE TEMPLATES
# =============================================================================

# D4: Per-segment accent color rotation for visual variety
SEGMENT_PALETTES = [
    {"accent": "BLUE"},
    {"accent": "TEAL"},
    {"accent": "PURPLE"},
    {"accent": "GOLD"},
    {"accent": "PINK"},
    {"accent": "GREEN"},
]

SCENE_TEMPLATE = '''from manim import *
from typing import Dict
import random
import numpy as np

# Aspect ratio configuration
{aspect_ratio_config}

# =============================================================================
# SPATIAL SAFETY SYSTEM — Screen-safe scaling & overflow prevention
# =============================================================================

# Safe frame: 94% of screen dimensions — generous safe zone for creative layouts
SAFE_W = config.frame_width * 0.94
SAFE_H = config.frame_height * 0.94
SAFE_MARGIN_X = config.frame_width * 0.03   # 3% margin each side
SAFE_MARGIN_Y = config.frame_height * 0.03  # 3% margin top/bottom

# Mobile readability: minimum element size
MIN_ELEMENT_SIZE = min(config.frame_width, config.frame_height) * 0.06

# Hierarchy scale factors relative to SAFE_W
HIERARCHY_SCALES = {{
    "primary":    {{"w_frac": 0.42, "h_frac": 0.22}},   # Dominant element
    "secondary":  {{"w_frac": 0.32, "h_frac": 0.17}},   # 60-75% of primary
    "annotation": {{"w_frac": 0.22, "h_frac": 0.12}},   # 40-50% of primary
}}

# Element count for this scene (set by generator)
_ELEMENT_COUNT = {element_count}


def auto_density_scale(element_count: int) -> float:
    """Reduce element sizes proportionally when count increases.
    Less aggressive scaling to allow more creative freedom.
    1-4: 1.0 | 5-6: 0.88 | 7-8: 0.75 | 9+: 0.62
    """
    if element_count <= 4:
        return 1.0
    elif element_count <= 6:
        return 0.88
    elif element_count <= 8:
        return 0.75
    else:
        return 0.62


def clamp_to_safe_frame(mobject, padding=0.1):
    """Ensure a mobject fits within the safe frame. Rescale + nudge if needed."""
    m_w = mobject.width
    m_h = mobject.height
    max_w = SAFE_W - padding * 2
    max_h = SAFE_H - padding * 2
    
    if m_w > max_w or m_h > max_h:
        sf = min(max_w / max(m_w, 0.01), max_h / max(m_h, 0.01))
        mobject.scale(sf)
    
    # Nudge back inside safe zone if edges overflow
    cx, cy, _ = mobject.get_center()
    half_w = mobject.width / 2
    half_h = mobject.height / 2
    dx, dy = 0, 0
    
    if cx + half_w > SAFE_W / 2:
        dx = SAFE_W / 2 - (cx + half_w) - padding
    elif cx - half_w < -SAFE_W / 2:
        dx = -SAFE_W / 2 - (cx - half_w) + padding
    
    if cy + half_h > SAFE_H / 2:
        dy = SAFE_H / 2 - (cy + half_h) - padding
    elif cy - half_h < -SAFE_H / 2:
        dy = -SAFE_H / 2 - (cy - half_h) + padding
    
    if dx != 0 or dy != 0:
        mobject.shift(np.array([dx, dy, 0]))
    return mobject


def safe_scale_factor(mobject, target_scale, max_allowed=1.40):
    """Clamp animation scale factor to prevent safe-frame overflow.
    max_allowed raised to 1.40 so camera zooms and emphasis pulses are clearly visible."""
    proj_w = mobject.width * target_scale
    proj_h = mobject.height * target_scale
    if proj_w > SAFE_W * 0.92 or proj_h > SAFE_H * 0.92:
        safe_sf = min(
            (SAFE_W * 0.92) / max(mobject.width, 0.01),
            (SAFE_H * 0.92) / max(mobject.height, 0.01)
        )
        return min(target_scale, safe_sf)
    return min(target_scale, max_allowed)


def density_adjusted_size(base_w, base_h):
    """Scale element dimensions by auto-density factor."""
    ds = auto_density_scale(_ELEMENT_COUNT)
    return base_w * ds, base_h * ds


# =============================================================================
# PRIMITIVE DEFINITIONS (inline for portability)
# =============================================================================

class PrimitiveConfig:
    COLORS = {{
        "BLUE": BLUE, "RED": RED, "GREEN": GREEN, "YELLOW": YELLOW,
        "WHITE": WHITE, "ORANGE": ORANGE, "PINK": PINK, "PURPLE": PURPLE,
        "TEAL": TEAL, "GOLD": GOLD, "MAROON": MAROON, "GRAY": GRAY
    }}
    ACCENT_BLUE = "#4FC3F7"
    ACCENT_PURPLE = "#B388FF"
    ACCENT_TEAL = "#64FFDA"
    ACCENT_PINK = "#FF80AB"
    ACCENT_GOLD = "#FFD54F"
    FONT_SIZES = {{"title": 36, "heading": 28, "body": 22, "label": 18, "small": 14}}
    
    @classmethod
    def get_color(cls, color_name: str):
        return cls.COLORS.get(color_name.upper(), BLUE)

    # Colors whose fill is too bright for WHITE text
    LIGHT_COLORS = {{"YELLOW", "WHITE", "GOLD", "ORANGE", "PINK", "#FFD54F", "#FF80AB", "#64FFDA"}}


def contrast_text_color(element_color):
    """Return a text color that is readable on top of element_color."""
    # Convert Manim Color objects to hex string for comparison
    try:
        cname = str(element_color).upper()
    except Exception:
        return WHITE
    # Check against known light colors
    if cname in PrimitiveConfig.LIGHT_COLORS:
        return "#1a1a2e"
    # Also catch hex values that are bright
    if cname.startswith("#"):
        try:
            hex_c = cname.lstrip("#")
            if len(hex_c) == 6:
                r, g, b = int(hex_c[0:2], 16), int(hex_c[2:4], 16), int(hex_c[4:6], 16)
                luminance = 0.299 * r + 0.587 * g + 0.114 * b
                if luminance > 160:
                    return "#1a1a2e"
        except Exception:
            pass
    return WHITE


# --- Background System ---

class GradientBackground(VGroup):
    """Dark gradient background with subtle color accent."""
    def __init__(self, accent_color=BLUE, **kwargs):
        super().__init__(**kwargs)
        fw, fh = config.frame_width, config.frame_height
        base = Rectangle(width=fw + 1, height=fh + 1, fill_opacity=1.0, stroke_width=0)
        base.set_fill(color=["#0a0a1a", "#0f1629", "#0a0a1a"])
        self.add(base)
        glow = Circle(radius=fw * 0.06, fill_opacity=0.015, stroke_width=0, color=accent_color)
        glow.shift(UP * fh * 0.4 + RIGHT * fw * 0.35)
        self.add(glow)


class AmbientParticles(VGroup):
    """Floating dots that drift slowly — adds life to every frame."""
    def __init__(self, count=6, **kwargs):
        super().__init__(**kwargs)
        fw, fh = config.frame_width, config.frame_height
        random.seed(42)
        for _ in range(count):
            r = random.uniform(0.03, 0.07)
            opacity = random.uniform(0.12, 0.25)
            dot = Dot(radius=r, fill_opacity=opacity, color=WHITE, stroke_width=0)
            x = random.uniform(-fw * 0.45, fw * 0.45)
            y = random.uniform(-fh * 0.45, fh * 0.45)
            dot.move_to([x, y, 0])
            self.add(dot)


class SubtleGrid(VGroup):
    """Very faint grid lines for visual structure."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        fw, fh = config.frame_width, config.frame_height
        for i in range(-3, 4):
            x = i * fw / 6
            line = Line([x, -fh/2, 0], [x, fh/2, 0], stroke_width=0.3, stroke_opacity=0.06, color=WHITE)
            self.add(line)
        for i in range(-5, 6):
            y = i * fh / 10
            line = Line([-fw/2, y, 0], [fw/2, y, 0], stroke_width=0.3, stroke_opacity=0.06, color=WHITE)
            self.add(line)


# --- Glass & Modern Primitives ---

class GlassCard(VGroup):
    """Glassmorphism card — frosted glass with label. Auto-sizes compact for label-only."""
    def __init__(self, label=None, width=4.5, height=3.0, color=BLUE, **kwargs):
        super().__init__(**kwargs)
        # Density-aware sizing
        width, height = density_adjusted_size(width, height)
        max_w = SAFE_W * 0.90
        max_h = SAFE_H * 0.50
        width = min(width, max_w)
        if label and height > 3.5:
            height = min(height, 3.5)
        height = min(height, max_h)
        # Outer glow (subtle)
        outer = RoundedRectangle(corner_radius=0.35, width=width + 0.08, height=height + 0.08,
                                  color=color, fill_opacity=0.06, stroke_width=0)
        self.add(outer)
        # Glass surface — solid frosted glass
        glass = RoundedRectangle(corner_radius=0.3, width=width, height=height,
                                  color=color, fill_opacity=0.35, stroke_width=2, stroke_opacity=0.7)
        self.add(glass)
        # Top highlight line
        hl = Line([-width*0.4, height/2 - 0.05, 0], [width*0.4, height/2 - 0.05, 0],
                  stroke_width=1.5, stroke_opacity=0.25, color=WHITE)
        self.add(hl)
        if label:
            _tc = contrast_text_color(color)
            txt = Text(label, font_size=32, color=_tc, weight=BOLD, font="sans-serif")
            if txt.width > width * 0.85:
                txt.scale_to_fit_width(width * 0.85)
            txt.move_to(glass)
            self.add(txt)
        self.glass = glass


class CodeBlock(VGroup):
    """Monospace code snippet with syntax-colored background."""
    def __init__(self, code_text="// code", width=3.5, color=GREEN, **kwargs):
        super().__init__(**kwargs)
        width, _ = density_adjusted_size(width, 1.2)
        max_w = SAFE_W * 0.88
        width = min(width, max_w)
        # Dark code background
        bg = RoundedRectangle(corner_radius=0.2, width=width, height=1.2,
                               fill_color="#1e1e2e", fill_opacity=0.9, stroke_width=1, stroke_color="#3e3e5e")
        self.add(bg)
        # Colored accent bar on left
        bar = Rectangle(width=0.06, height=1.0, fill_opacity=0.8, fill_color=color, stroke_width=0)
        bar.next_to(bg, LEFT, buff=0).shift(RIGHT * 0.06)
        self.add(bar)
        # Code text in monospace
        code = Text(code_text, font_size=14, color="#e0e0e0", font="Monospace")
        if code.width > width * 0.85:
            code.scale_to_fit_width(width * 0.85)
        code.move_to(bg)
        self.add(code)
        self.bg = bg


class IconBadge(VGroup):
    """Circular icon badge with glow — for emphasis points."""
    def __init__(self, icon_text="⚡", color=GOLD, size=0.6, **kwargs):
        super().__init__(**kwargs)
        size, _ = density_adjusted_size(size, size)
        max_s = min(SAFE_W, SAFE_H) * 0.11
        size = min(size, max_s)
        # Glow ring
        glow = Circle(radius=size * 1.3, fill_opacity=0.06, stroke_width=0, color=color)
        self.add(glow)
        # Badge circle — visible with strong fill
        badge = Circle(radius=size, color=color, fill_opacity=0.30, stroke_width=2.5)
        self.add(badge)
        # Icon text
        _tc = contrast_text_color(color)
        icon = Text(icon_text, font_size=int(30 * size), color=_tc, font="sans-serif")
        if icon.width > size * 1.4:
            icon.scale_to_fit_width(size * 1.4)
        icon.move_to(badge)
        self.add(icon)


class TagPill(VGroup):
    """Rounded pill tag — for labels, categories, keywords."""
    def __init__(self, label="Tag", color=TEAL, **kwargs):
        super().__init__(**kwargs)
        ds = auto_density_scale(_ELEMENT_COUNT)
        _tc = contrast_text_color(color)
        txt = Text(label, font_size=max(12, int(18 * ds)), color=_tc, weight=BOLD, font="sans-serif")
        padding_x = 0.35 * ds
        padding_y = 0.18 * ds
        w = min(txt.width + padding_x * 2, SAFE_W * 0.40)
        h = txt.height + padding_y * 2
        pill = RoundedRectangle(corner_radius=h/2, width=w, height=h,
                                 color=color, fill_opacity=0.35, stroke_width=2)
        if txt.width > w - padding_x * 2:
            txt.scale_to_fit_width(w - padding_x * 2)
        txt.move_to(pill)
        self.add(pill, txt)


class ProgressBar(VGroup):
    """Animated progress bar for showing completion or comparison."""
    def __init__(self, progress=0.5, width=3.0, color=GREEN, label=None, **kwargs):
        super().__init__(**kwargs)
        width, _ = density_adjusted_size(width, 0.25)
        max_w = SAFE_W * 0.65
        width = min(width, max_w)
        # Track
        track = RoundedRectangle(corner_radius=0.1, width=width, height=0.25,
                                  fill_color="#2a2a3a", fill_opacity=0.6, stroke_width=1, stroke_color="#3e3e5e")
        self.add(track)
        # Fill
        fill_w = max(0.05, width * progress)
        fill = RoundedRectangle(corner_radius=0.1, width=fill_w, height=0.25,
                                 fill_color=color, fill_opacity=0.8, stroke_width=0)
        fill.align_to(track, LEFT)
        self.add(fill)
        if label:
            lbl = Text(label, font_size=12, color=contrast_text_color(color))
            lbl.next_to(track, UP, buff=0.1)
            self.add(lbl)
        self.track = track
        self.fill = fill


# --- Legacy Primitives (enhanced) ---

class BoundaryBox(VGroup):
    def __init__(self, label=None, width=4.0, height=3.0, color=BLUE, fill_opacity=0.1, **kwargs):
        super().__init__(**kwargs)
        width, height = density_adjusted_size(width, height)
        max_width = SAFE_W * 0.80
        max_height = SAFE_H * 0.35
        width = min(width, max_width)
        height = min(height, max_height)
        self.box = RoundedRectangle(corner_radius=0.3, width=width, height=height, 
                                     color=color, fill_opacity=0.20, stroke_width=2.5, stroke_opacity=0.7)
        self.add(self.box)
        if label:
            _tc = contrast_text_color(color)
            self.label_text = Text(label, font_size=22, color=_tc, weight=BOLD, font="sans-serif")
            max_w = width * 0.85
            if self.label_text.width > max_w:
                self.label_text.scale_to_fit_width(max_w)
            self.label_text.next_to(self.box, UP, buff=0.15)
            self.add(self.label_text)


class DataPacket(VGroup):
    def __init__(self, label=None, color=GREEN, radius=0.35, **kwargs):
        super().__init__(**kwargs)
        radius, _ = density_adjusted_size(radius, radius)
        max_radius = min(SAFE_W, SAFE_H) * 0.09
        radius = min(radius, max_radius)
        # Glow effect
        glow = Circle(radius=radius * 1.4, color=color, fill_opacity=0.06, stroke_width=0)
        self.add(glow)
        self.body = Circle(radius=radius, color=color, fill_opacity=0.8, stroke_width=2)
        self.add(self.body)
        if label:
            _tc = contrast_text_color(color)
            self.label_text = Text(label, font_size=18, color=_tc, weight=BOLD, font="sans-serif")
            if self.label_text.width > radius * 1.6:
                self.label_text.scale_to_fit_width(radius * 1.6)
            self.label_text.move_to(self.body)
            self.add(self.label_text)


class Node(VGroup):
    def __init__(self, label=None, color=BLUE, node_type="circle", size=0.5, **kwargs):
        super().__init__(**kwargs)
        size, _ = density_adjusted_size(size, size)
        max_size = min(SAFE_W, SAFE_H) * 0.13
        size = min(size, max_size)
        if node_type == "circle":
            self.shape = Circle(radius=size, color=color, fill_opacity=0.2, stroke_width=2)
        elif node_type == "square":
            self.shape = Square(side_length=size*1.8, color=color, fill_opacity=0.2, stroke_width=2)
        else:
            self.shape = Circle(radius=size, color=color, fill_opacity=0.2, stroke_width=2)
        self.add(self.shape)
        if label:
            _tc = contrast_text_color(color)
            self.label_text = Text(label, font_size=22, color=_tc, weight=BOLD, font="sans-serif")
            if self.label_text.width > size * 1.6:
                self.label_text.scale_to_fit_width(size * 1.6)
            self.label_text.move_to(self.shape)
            self.add(self.label_text)


class Checkpoint(VGroup):
    def __init__(self, label="✓", color=GOLD, size=1.0, **kwargs):
        super().__init__(**kwargs)
        size, _ = density_adjusted_size(size, size)
        max_size = min(SAFE_W, SAFE_H) * 0.17
        size = min(size, max_size)
        # Modern badge style instead of bars
        badge = Circle(radius=size * 0.5, color=color, fill_opacity=0.15, stroke_width=2)
        self.add(badge)
        self.symbol = Text(label, font_size=int(32*size), color=color, font="sans-serif")
        self.add(self.symbol)


class FlowArrow(VGroup):
    def __init__(self, start=LEFT, end=RIGHT, label=None, color="#4FC3F7", **kwargs):
        super().__init__(**kwargs)
        self.arrow = Arrow(start=start, end=end, color=color, stroke_width=4, buff=0.1,
                            max_tip_length_to_length_ratio=0.18)
        self.add(self.arrow)
        if label:
            self.label_text = Text(label, font_size=18, color=contrast_text_color(color), font="sans-serif")
            self.label_text.next_to(self.arrow, UP, buff=0.12)
            self.add(self.label_text)


# --- Manim v0.19.0 Expanded Primitives ---

class StarBadge(VGroup):
    """Star-shaped badge for achievement/emphasis markers."""
    def __init__(self, label=None, color=GOLD, size=0.6, n_points=5, **kwargs):
        super().__init__(**kwargs)
        size, _ = density_adjusted_size(size, size)
        max_s = min(SAFE_W, SAFE_H) * 0.12
        size = min(size, max_s)
        # Glow ring
        glow = Circle(radius=size * 1.4, fill_opacity=0.05, stroke_width=0, color=color)
        self.add(glow)
        # Star shape
        star = Star(n=n_points, outer_radius=size, inner_radius=size*0.45,
                    color=color, fill_opacity=0.35, stroke_width=2)
        self.add(star)
        if label:
            _tc = contrast_text_color(color)
            txt = Text(label, font_size=max(12, int(22 * size)), color=_tc, weight=BOLD, font="sans-serif")
            if txt.width > size * 1.2:
                txt.scale_to_fit_width(size * 1.2)
            txt.move_to(star)
            self.add(txt)


class BraceAnnotation(VGroup):
    """Brace with label — for annotating relationships between elements."""
    def __init__(self, target_width=2.0, label="note", color=WHITE, direction=DOWN, **kwargs):
        super().__init__(**kwargs)
        target_width, _ = density_adjusted_size(target_width, 0.5)
        max_w = SAFE_W * 0.70
        target_width = min(target_width, max_w)
        # Reference line for the brace
        ref = Line(LEFT * target_width / 2, RIGHT * target_width / 2)
        brace = Brace(ref, direction=direction, color=color)
        self.add(brace)
        lbl = Text(label, font_size=16, color=color, font="sans-serif")
        if lbl.width > target_width * 0.85:
            lbl.scale_to_fit_width(target_width * 0.85)
        brace.put_at_tip(lbl, buff=0.1)
        self.add(lbl)


class AnnulusRing(VGroup):
    """Annulus ring — for showing ranges, zones, or layered concepts."""
    def __init__(self, inner_radius=0.3, outer_radius=0.7, color=TEAL, label=None, **kwargs):
        super().__init__(**kwargs)
        outer_radius, _ = density_adjusted_size(outer_radius, outer_radius)
        inner_radius = outer_radius * 0.45
        max_r = min(SAFE_W, SAFE_H) * 0.15
        outer_radius = min(outer_radius, max_r)
        inner_radius = min(inner_radius, outer_radius * 0.6)
        ring = Annulus(inner_radius=inner_radius, outer_radius=outer_radius,
                       color=color, fill_opacity=0.25, stroke_width=2)
        self.add(ring)
        if label:
            _tc = contrast_text_color(color)
            txt = Text(label, font_size=16, color=_tc, font="sans-serif")
            if txt.width > outer_radius * 1.4:
                txt.scale_to_fit_width(outer_radius * 1.4)
            txt.move_to(ring)
            self.add(txt)


class SectorChart(VGroup):
    """Sector slice — for pie-chart-style data visualization."""
    def __init__(self, angle=PI/3, radius=0.8, color=BLUE, label=None, **kwargs):
        super().__init__(**kwargs)
        radius, _ = density_adjusted_size(radius, radius)
        max_r = min(SAFE_W, SAFE_H) * 0.14
        radius = min(radius, max_r)
        sector = Sector(outer_radius=radius, angle=angle, start_angle=PI/2 - angle/2,
                        color=color, fill_opacity=0.35, stroke_width=2)
        self.add(sector)
        if label:
            _tc = contrast_text_color(color)
            txt = Text(label, font_size=14, color=_tc, font="sans-serif")
            # Place label at sector midpoint
            mid_angle = PI/2
            txt.move_to(sector.get_center() + np.array([
                radius * 0.5 * np.cos(mid_angle),
                radius * 0.5 * np.sin(mid_angle), 0
            ]))
            if txt.width > radius * 1.0:
                txt.scale_to_fit_width(radius * 1.0)
            self.add(txt)


# =============================================================================
# SCENE: {scene_id}
# Concept: {concept_idea}
# =============================================================================

class {class_name}(Scene):
    """
    {concept_idea}
    
    Visual Metaphor: {abstract_concept} → {concrete_representation}
    """
    
    def construct(self):
        # Element registry
        elements: Dict[str, VMobject] = {{}}
        
        # Grid positions for {aspect_ratio}
        positions = self._get_grid_positions()
        
        # === CLEAN BACKGROUND (minimal — let content be the star) ===
        bg = GradientBackground(accent_color={accent_color})
        self.add(bg)
        
        # D3: Progress bar (fills with scene progress)
        _pb_total_w = config.frame_width * 0.85
        _pb_bg = Rectangle(width=_pb_total_w, height=0.06, fill_opacity=0.15,
                           fill_color=WHITE, stroke_width=0)
        _pb_bg.move_to(np.array([0, -config.frame_height/2 + 0.12, 0]))
        self.add(_pb_bg)
        _pb_bar = Rectangle(width=0.01, height=0.06, fill_opacity=0.6,
                            fill_color={accent_color}, stroke_width=0)
        _pb_bar.move_to(_pb_bg.get_center())
        _pb_bar.align_to(_pb_bg, LEFT)
        self.add(_pb_bar)
        _pb_bar._pt = 0
        _scene_dur = {audio_duration}
        def _pb_upd(m, dt):
            m._pt += dt
            frac = min(1.0, m._pt / max(0.1, _scene_dur))
            new_w = max(0.01, _pb_total_w * frac)
            m.stretch_to_fit_width(new_w)
            m.align_to(_pb_bg, LEFT)
        _pb_bar.add_updater(_pb_upd)
        
        # D5: Channel branding watermark
        _wm = Text("Code Tapasya", font_size=14, color=WHITE,
                    font="sans-serif", fill_opacity=0.25)
        _wm.move_to(np.array([config.frame_width/2 - 1.2,
                              -config.frame_height/2 + 0.35, 0]))
        self.add(_wm)
        
        # Create visual elements
{element_creation_code}
        
        # === SPATIAL SAFETY: Clamp all elements to safe frame after creation ===
        for _sf_key, _sf_elem in list(elements.items()):
            clamp_to_safe_frame(_sf_elem, padding=0.15)
        
        # C3: "all" target for bulk animations
        if elements:
            elements["all"] = VGroup(*list(elements.values()))
        
        # Animation sequence
{animation_sequence_code}
        
        # C1: End buffer — hold final state so scene doesn't feel cut off
        self.wait(0.3)
        
        # Clean up updaters
        for _eid_key, _elem_obj in elements.items():
            if hasattr(_elem_obj, 'clear_updaters'):
                _elem_obj.clear_updaters()
        _pb_bar.clear_updaters()
    
    def _get_grid_positions(self):
        """Precise grid-aligned positions for deterministic layout.
        
        Grid uses SAFE FRAME margins (not raw frame edges) to guarantee
        no element center is placed where it could overflow the screen.
        Horizontal spread is generous to use the FULL screen width.
        """
        fw = config.frame_width
        fh = config.frame_height
        # Use generous positioning — spread elements across the screen
        # Horizontal: 38% of fw — uses most of the safe frame
        # Vertical: 30% of fh (top/bot rows), 15% (upper/lower mid rows)
        gx = fw * 0.38   # horizontal grid spread (wider for better use of space)
        gy = fh * 0.30   # vertical grid spread (top/bottom rows)
        my = fh * 0.15   # mid-row vertical offset
        return {{
            # 3x3 primary grid
            "top_left": np.array([-gx, gy, 0]),
            "top_center": np.array([0, gy, 0]),
            "top_right": np.array([gx, gy, 0]),
            "center_left": np.array([-gx, 0, 0]),
            "center": np.array([0, 0, 0]),
            "center_right": np.array([gx, 0, 0]),
            "bottom_left": np.array([-gx, -gy, 0]),
            "bottom_center": np.array([0, -gy, 0]),
            "bottom_right": np.array([gx, -gy, 0]),
            # Simple aliases
            "top": np.array([0, gy, 0]),
            "bottom": np.array([0, -gy, 0]),
            "left": np.array([-gx, 0, 0]),
            "right": np.array([gx, 0, 0]),
            # Upper/lower mid rows (5-row grid)
            "upper_left": np.array([-gx, my, 0]),
            "upper_center": np.array([0, my, 0]),
            "upper_right": np.array([gx, my, 0]),
            "lower_left": np.array([-gx, -my, 0]),
            "lower_center": np.array([0, -my, 0]),
            "lower_right": np.array([gx, -my, 0]),
        }}
'''


# =============================================================================
# ASPECT RATIO CONFIGURATIONS
# =============================================================================

ASPECT_RATIO_CONFIGS = {
    "9:16": '''config.frame_width = 9
config.frame_height = 16
config.pixel_width = 1080
config.pixel_height = 1920''',
    
    "16:9": '''config.frame_width = 16
config.frame_height = 9
config.pixel_width = 1920
config.pixel_height = 1080''',
    
    "1:1": '''config.frame_width = 10
config.frame_height = 10
config.pixel_width = 1080
config.pixel_height = 1080''',
    
    "4:3": '''config.frame_width = 4
config.frame_height = 3
config.pixel_width = 1440
config.pixel_height = 1080''',
    
    "21:9": '''config.frame_width = 21
config.frame_height = 9
config.pixel_width = 2560
config.pixel_height = 1080''',
}


# =============================================================================
# ELEMENT CREATION TEMPLATES
# =============================================================================

ELEMENT_TEMPLATES = {
    ElementType.BOUNDARY_BOX: '''elements["{id}"] = BoundaryBox(
            label="{label}",
            width={width},
            height={height},
            color={color}
        )
        elements["{id}"].move_to(positions["{position}"])''',
    
    ElementType.ROUNDED_RECTANGLE: '''elements["{id}"] = BoundaryBox(
            label="{label}",
            width={width},
            height={height},
            color={color}
        )
        elements["{id}"].move_to(positions["{position}"])''',
    
    ElementType.DATA_PACKET: '''elements["{id}"] = DataPacket(
            label="{label}",
            color={color},
            radius={radius}
        )
        elements["{id}"].move_to(positions["{position}"])''',
    
    ElementType.NODE: '''elements["{id}"] = Node(
            label="{label}",
            color={color},
            size={size}
        )
        elements["{id}"].move_to(positions["{position}"])''',
    
    ElementType.CHECKPOINT: '''elements["{id}"] = Checkpoint(
            label="✓",
            color={color},
            size={size}
        )
        elements["{id}"].move_to(positions["{position}"])''',
    
    ElementType.ARROW: '''elements["{id}"] = FlowArrow(
            start=positions["{start_pos}"],
            end=positions["{end_pos}"],
            color={color}
        )''',
    
    ElementType.LABEL: '''elements["{id}"] = Text("{label}", font_size=18, color=WHITE)
        if elements["{id}"].width > SAFE_W * 0.45:
            elements["{id}"].scale_to_fit_width(SAFE_W * 0.45)
        elements["{id}"].move_to(positions["{position}"])''',
    
    ElementType.TITLE: '''elements["{id}"] = Text("{label}", font_size=36, color=WHITE, weight=BOLD)
        if elements["{id}"].width > SAFE_W * 0.60:
            elements["{id}"].scale_to_fit_width(SAFE_W * 0.60)
        elements["{id}"].move_to(positions["{position}"])''',
    
    ElementType.CIRCLE: '''elements["{id}"] = Circle(radius={radius}, color={color}, fill_opacity=0.2, stroke_width=2)
        elements["{id}"].move_to(positions["{position}"])''',
    
    ElementType.RECTANGLE: '''elements["{id}"] = Rectangle(width={width}, height={height}, color={color}, fill_opacity=0.15, stroke_width=2)
        elements["{id}"].move_to(positions["{position}"])''',
    
    # --- Modern Primitives ---
    
    ElementType.GLASS_CARD: '''elements["{id}"] = GlassCard(
            label="{label}",
            width={width},
            height={height},
            color={color}
        )
        elements["{id}"].move_to(positions["{position}"])''',
    
    ElementType.CODE_BLOCK: '''elements["{id}"] = CodeBlock(
            code_text="{label}",
            width={width},
            color={color}
        )
        elements["{id}"].move_to(positions["{position}"])''',
    
    ElementType.ICON_BADGE: '''elements["{id}"] = IconBadge(
            icon_text="{label}",
            color={color},
            size={size}
        )
        elements["{id}"].move_to(positions["{position}"])''',
    
    ElementType.TAG_PILL: '''elements["{id}"] = TagPill(
            label="{label}",
            color={color}
        )
        elements["{id}"].move_to(positions["{position}"])''',
    
    ElementType.PROGRESS_BAR: '''elements["{id}"] = ProgressBar(
            progress=0.5,
            width={width},
            color={color},
            label="{label}"
        )
        elements["{id}"].move_to(positions["{position}"])''',

    # --- Manim v0.19.0 Expanded Element Types ---

    ElementType.STAR_BADGE: '''elements["{id}"] = StarBadge(
            label="{label}",
            color={color},
            size={size}
        )
        elements["{id}"].move_to(positions["{position}"])''',

    ElementType.CURVED_ARROW_ELEM: '''elements["{id}"] = CurvedArrow(
            start_point=positions["{start_pos}"] if "{start_pos}" in positions else LEFT*1.5,
            end_point=positions["{end_pos}"] if "{end_pos}" in positions else RIGHT*1.5,
            color={color},
            stroke_width=3
        )''',

    ElementType.DASHED_LINE_ELEM: '''elements["{id}"] = DashedLine(
            start=positions["{start_pos}"] if "{start_pos}" in positions else LEFT*1.5,
            end=positions["{end_pos}"] if "{end_pos}" in positions else RIGHT*1.5,
            color={color},
            stroke_width=2,
            dash_length=0.15
        )''',

    ElementType.BRACE_ANNOTATION: '''elements["{id}"] = BraceAnnotation(
            target_width={width},
            label="{label}",
            color={color}
        )
        elements["{id}"].move_to(positions["{position}"])''',

    ElementType.ANNULUS_RING: '''elements["{id}"] = AnnulusRing(
            outer_radius={radius},
            color={color},
            label="{label}"
        )
        elements["{id}"].move_to(positions["{position}"])''',

    ElementType.SECTOR_CHART: '''elements["{id}"] = SectorChart(
            radius={radius},
            color={color},
            label="{label}"
        )
        elements["{id}"].move_to(positions["{position}"])''',
}


# =============================================================================
# ANIMATION TEMPLATES
# =============================================================================

ANIMATION_TEMPLATES = {
    # Core animations — with rate_func for fluid motion
    TransformAction.APPEAR: '''self.play(
            GrowFromCenter(elements["{target}"]),
            run_time={run_time}, rate_func=rate_functions.ease_out_back
        )''',
    
    TransformAction.DISAPPEAR: '''self.play(
            FadeOut(elements["{target}"], shift=DOWN*0.3, scale=0.5),
            run_time={run_time}, rate_func=rate_functions.ease_in_cubic
        )''',
    
    TransformAction.MOVE: '''self.play(
            elements["{target}"].animate.move_to(
                elements["{relative_to}"].get_center() if "{relative_to}" in elements else positions["{to_position}"]
            ),
            run_time={run_time}, rate_func=rate_functions.ease_in_out_cubic
        )''',
    
    TransformAction.TRANSFORM: '''self.play(
            ReplacementTransform(elements["{target}"], elements["{to_element}"]),
            run_time={run_time}, rate_func=smooth
        )''',
    
    TransformAction.HIGHLIGHT: '''self.play(
            Circumscribe(elements["{target}"], color=YELLOW, time_width=1.5, buff=0.1),
            run_time={run_time}
        )''',
    
    TransformAction.PULSE: '''self.play(
            elements["{target}"].animate.scale(1.12).set_color(GOLD),
            run_time={run_time} * 0.5, rate_func=rate_functions.ease_out_cubic
        )
        self.play(
            elements["{target}"].animate.scale(1/1.12),
            run_time={run_time} * 0.5, rate_func=rate_functions.ease_in_cubic
        )''',
    
    TransformAction.SCALE: '''self.play(
            elements["{target}"].animate.scale({scale_factor}),
            run_time={run_time}, rate_func=rate_functions.ease_out_cubic
        )''',
    
    # Entry/exit animations with directional motion
    TransformAction.SLIDE_IN: '''self.play(
            FadeIn(elements["{target}"], shift=LEFT*0.5),
            run_time={run_time}, rate_func=rate_functions.ease_out_cubic
        )''',
    
    TransformAction.FADE_IN: '''self.play(
            FadeIn(elements["{target}"], shift=UP*0.2),
            run_time={run_time}, rate_func=rate_functions.ease_out_cubic
        )''',
    
    TransformAction.FADE_OUT: '''self.play(
            FadeOut(elements["{target}"], shift=DOWN*0.2),
            run_time={run_time}, rate_func=rate_functions.ease_in_cubic
        )''',
    
    TransformAction.GROW_FROM_CENTER: '''self.play(
            GrowFromCenter(elements["{target}"]),
            run_time={run_time}, rate_func=rate_functions.ease_out_back
        )''',
    
    TransformAction.SHRINK: '''self.play(
            ShrinkToCenter(elements["{target}"]),
            run_time={run_time}, rate_func=rate_functions.ease_in_cubic
        )''',
    
    TransformAction.ZOOM: '''self.play(
            elements["{target}"].animate.scale({scale_factor}),
            run_time={run_time}, rate_func=rate_functions.ease_out_cubic
        )''',
    
    TransformAction.SPIN: '''self.play(
            Rotate(elements["{target}"], angle=2*PI),
            run_time={run_time}, rate_func=smooth
        )''',
    
    TransformAction.BOUNCE: '''self.play(
            elements["{target}"].animate.shift(UP*0.4),
            run_time={run_time}*0.4, rate_func=rate_functions.ease_out_cubic
        )
        self.play(
            elements["{target}"].animate.shift(DOWN*0.4),
            run_time={run_time}*0.6, rate_func=rate_functions.ease_in_bounce
        )''',
    
    TransformAction.WIGGLE: '''self.play(
            Wiggle(elements["{target}"], scale_value=1.1, rotation_angle=0.05*TAU),
            run_time={run_time}
        )''',
    
    TransformAction.ZOOM_IN: '''self.play(
            elements["{target}"].animate.scale(safe_scale_factor(elements["{target}"], 1.20, 1.25)),
            run_time={run_time}, rate_func=rate_functions.ease_out_cubic
        )''',
    
    TransformAction.ZOOM_OUT: '''self.play(
            elements["{target}"].animate.scale(0.75),
            run_time={run_time}, rate_func=rate_functions.ease_in_cubic
        )''',
    
    TransformAction.FLASH: '''self.play(
            Flash(elements["{target}"], color=GOLD, flash_radius=0.6, num_lines=12),
            run_time={run_time}
        )''',
    
    TransformAction.ENTER: '''self.play(
            FadeIn(elements["{target}"], shift=UP*0.4, scale=0.7),
            run_time={run_time}, rate_func=rate_functions.ease_out_back
        )''',
    
    TransformAction.EXIT: '''self.play(
            FadeOut(elements["{target}"], shift=DOWN*0.3, scale=0.5),
            run_time={run_time}, rate_func=rate_functions.ease_in_cubic
        )''',
    
    TransformAction.EMPHASIZE: '''self.play(
            Indicate(elements["{target}"], color=YELLOW, scale_factor=safe_scale_factor(elements["{target}"], 1.15, 1.20)),
            run_time={run_time}
        )''',
    
    TransformAction.FOCUS: '''self.play(
            Circumscribe(elements["{target}"], color=WHITE, time_width=1.5, buff=0.08),
            run_time={run_time}
        )''',
    
    TransformAction.GLOW: '''self.play(
            Flash(elements["{target}"], color=YELLOW, flash_radius=0.7, num_lines=16),
            run_time={run_time}
        )''',

    # Directional slide-in entries
    TransformAction.SLIDE_IN_FROM_LEFT: '''self.play(
            FadeIn(elements["{target}"], shift=RIGHT*0.6),
            run_time={run_time}, rate_func=rate_functions.ease_out_cubic
        )''',

    TransformAction.SLIDE_IN_FROM_RIGHT: '''self.play(
            FadeIn(elements["{target}"], shift=LEFT*0.6),
            run_time={run_time}, rate_func=rate_functions.ease_out_cubic
        )''',

    TransformAction.SLIDE_IN_FROM_TOP: '''self.play(
            FadeIn(elements["{target}"], shift=DOWN*0.6),
            run_time={run_time}, rate_func=rate_functions.ease_out_cubic
        )''',

    TransformAction.SLIDE_IN_FROM_BOTTOM: '''self.play(
            FadeIn(elements["{target}"], shift=UP*0.6),
            run_time={run_time}, rate_func=rate_functions.ease_out_cubic
        )''',

    # Drawing / emphasis extras
    TransformAction.DRAW_BORDER_THEN_FILL: '''self.play(
            DrawBorderThenFill(elements["{target}"]),
            run_time={run_time}, rate_func=rate_functions.ease_out_cubic
        )''',

    TransformAction.DRAW_ARROW: '''self.play(
            GrowArrow(elements["{target}"]) if hasattr(elements["{target}"], "tip") else GrowFromCenter(elements["{target}"]),
            run_time={run_time}
        )''',

    TransformAction.CIRCUMSCRIBE: '''self.play(
            Circumscribe(elements["{target}"], color=GOLD, time_width=1.5, buff=0.08),
            run_time={run_time}
        )''',

    # --- Manim v0.19.0 expanded animations ---

    TransformAction.WRITE: '''self.play(
            DrawBorderThenFill(elements["{target}"]),
            run_time={run_time}, rate_func=rate_functions.ease_out_expo
        )''',

    TransformAction.APPLY_WAVE: '''self.play(
            ApplyWave(elements["{target}"], amplitude=0.15, direction=UP),
            run_time={run_time}, rate_func=smooth
        )''',

    TransformAction.CIRCLE_INDICATE: '''self.play(
            Circumscribe(elements["{target}"], color=YELLOW, time_width=1.5, buff=0.08),
            run_time={run_time}
        )''',

    TransformAction.SURROUND: '''_srect = SurroundingRectangle(elements["{target}"], color=GOLD, buff=0.12)
        self.play(Create(_srect), run_time={run_time}*0.6)
        self.play(FadeOut(_srect), run_time={run_time}*0.4)''',

    TransformAction.GROW_FROM_POINT: '''self.play(
            GrowFromPoint(elements["{target}"], ORIGIN),
            run_time={run_time}, rate_func=rate_functions.ease_out_back
        )''',

    TransformAction.FADE_TRANSFORM: '''self.play(
            elements["{target}"].animate.set_color(GOLD),
            run_time={run_time}, rate_func=rate_functions.ease_in_out_cubic
        )''',

    TransformAction.SHOW_PASSING_FLASH: '''self.play(
            Indicate(elements["{target}"], color=YELLOW, scale_factor=1.08),
            run_time={run_time}
        )''',

    TransformAction.WAVE: '''self.play(
            ApplyWave(elements["{target}"], amplitude=0.12, direction=RIGHT),
            run_time={run_time}, rate_func=smooth
        )''',

    TransformAction.RIPPLE: '''self.play(
            ApplyWave(elements["{target}"], amplitude=0.10, direction=UP),
            run_time={run_time}*0.5, rate_func=smooth
        )
        self.play(
            ApplyWave(elements["{target}"], amplitude=0.08, direction=RIGHT),
            run_time={run_time}*0.5, rate_func=smooth
        )''',

    TransformAction.TRACE: '''self.play(
            Circumscribe(elements["{target}"], color=GOLD, time_width=1.5, buff=0.08),
            run_time={run_time}
        )''',

    TransformAction.MORPH: '''self.play(
            elements["{target}"].animate.scale(safe_scale_factor(elements["{target}"], 1.10, 1.15)).set_color(GOLD),
            run_time={run_time}, rate_func=rate_functions.ease_in_out_cubic
        )''',
}


# =============================================================================
# CODE GENERATOR CLASS
# =============================================================================

# Aspect ratio to frame dimensions mapping
ASPECT_RATIO_DIMENSIONS = {
    "9:16": {"frame_width": 9, "frame_height": 16},
    "16:9": {"frame_width": 16, "frame_height": 9},
    "1:1": {"frame_width": 10, "frame_height": 10},
    "4:3": {"frame_width": 4, "frame_height": 3},
    "21:9": {"frame_width": 21, "frame_height": 9},
}


@dataclass
class GeneratorConfig:
    """Configuration for code generation."""
    aspect_ratio: str = "9:16"
    default_run_time: float = 1.5
    pause_between_animations: float = 0.4
    element_size_map: Dict[str, float] = None
    
    def __post_init__(self):
        if self.element_size_map is None:
            self.element_size_map = {
                "small": 1.0,
                "medium": 1.5,
                "large": 2.0,
            }
    
    def get_frame_dimensions(self) -> tuple:
        """Get frame width and height for current aspect ratio."""
        dims = ASPECT_RATIO_DIMENSIONS.get(self.aspect_ratio, ASPECT_RATIO_DIMENSIONS["9:16"])
        return dims["frame_width"], dims["frame_height"]
    
    def get_element_size_for_aspect(self, size_name: str, element_count: int = 3) -> dict:
        """Get element dimensions scaled for aspect ratio and element density."""
        base_size = self.element_size_map.get(size_name, 0.85)
        fw, fh = self.get_frame_dimensions()
        
        # Scale based on minimum frame dimension to keep elements proportional
        min_dim = min(fw, fh)
        scale_factor = min_dim / 9  # Normalize to 9:16 base
        
        # Auto-density reduction based on element count
        if element_count <= 3:
            density_factor = 1.0
        elif element_count <= 5:
            density_factor = 0.82
        elif element_count <= 7:
            density_factor = 0.68
        else:
            density_factor = 0.55
        
        scaled_size = base_size * scale_factor * density_factor
        
        # Safe-frame limits (90% of frame)
        safe_w = fw * 0.90
        safe_h = fh * 0.90
        
        # Grid cell budget: elements must fit within their grid cell
        # With 3 columns, each cell is ~(fw*0.30) wide on each side of center
        # A single element should not exceed ~50% of safe width or ~30% of safe height
        max_elem_w = safe_w * 0.50
        max_elem_h = safe_h * 0.30
        
        # For 4+ elements, shrink further to prevent overlap
        if element_count >= 4:
            max_elem_w = safe_w * 0.40
            max_elem_h = safe_h * 0.25
        if element_count >= 6:
            max_elem_w = safe_w * 0.32
            max_elem_h = safe_h * 0.20
        
        return {
            "size": min(scaled_size, min_dim * 0.12),
            "radius": min(scaled_size, min_dim * 0.10),
            "width": min(scaled_size * 3.0, max_elem_w),
            "height": min(scaled_size * 2.0, max_elem_h),
        }


class ManimCodeGenerator:
    """
    Generates Manim code from validated scene specifications.
    
    Supports two modes:
    1. Timeline-driven (new): Consumes VisualTimeline from VisualDirector
    2. Legacy spec-driven: Falls back to direct spec reading
    """
    
    def __init__(self, config: GeneratorConfig = None):
        self.config = config or GeneratorConfig()
    
    def generate_scene_code(
        self,
        spec: SceneSpecification,
        scene_index: int = 0,
        timeline=None  # Optional[VisualTimeline]
    ) -> str:
        """Generate complete Manim code for a scene specification.
        
        Args:
            spec: SceneSpecification with elements and structure
            scene_index: Index for class naming
            timeline: Optional VisualTimeline from VisualDirector
        """
        
        # Generate element creation code
        element_count = len(spec.visual_metaphor.visual_elements) if spec.visual_metaphor else 0
        element_code = self._generate_element_code(spec, element_count)
        
        # Generate animation sequence code
        if timeline and timeline.events:
            animation_code = self._generate_timeline_animation_code(timeline, spec)
        else:
            animation_code = self._generate_legacy_animation_code(spec)
        
        # Build complete scene
        class_name = f"Segment{scene_index:03d}"
        
        # D4: Per-segment color variety
        palette = SEGMENT_PALETTES[scene_index % len(SEGMENT_PALETTES)]
        accent_color_name = palette["accent"]
        
        # Extract audio duration for progress bar and timing
        audio_duration = spec.timing.audio_duration_seconds or 10.0
        
        code = SCENE_TEMPLATE.format(
            aspect_ratio_config=ASPECT_RATIO_CONFIGS.get(
                self.config.aspect_ratio,
                ASPECT_RATIO_CONFIGS["9:16"]
            ),
            scene_id=spec.scene_id,
            concept_idea=spec.concept.idea,
            abstract_concept=spec.visual_metaphor.abstract_concept,
            concrete_representation=spec.visual_metaphor.concrete_representation,
            class_name=class_name,
            aspect_ratio=self.config.aspect_ratio,
            element_creation_code=element_code,
            animation_sequence_code=animation_code,
            audio_duration=f"{audio_duration:.1f}",
            accent_color=accent_color_name,
            element_count=element_count,
        )
        
        return code
    
    def _generate_element_code(self, spec: SceneSpecification, element_count: int = 3) -> str:
        """Generate code to create all visual elements with metaphor-aware layout,
        auto-connection arrows, anti-stacking, and density-aware sizing."""
        lines = []
        position_counts = {}  # Track how many elements target each position
        element_ids_ordered = []  # Track creation order for auto-connections
        
        # =====================================================================
        # FIX E: METAPHOR-AWARE LAYOUT OVERRIDE
        # Override element positions based on metaphor type for intentional layouts.
        # =====================================================================
        metaphor_type = spec.visual_metaphor.metaphor_type
        elems = spec.visual_metaphor.visual_elements
        n = len(elems)
        
        # Build layout position overrides based on metaphor type
        layout_overrides = {}
        if n >= 2:
            if metaphor_type in (MetaphorType.PROCESS_FLOW,):
                # Process: left-to-right flow (evenly spaced horizontally)
                h_positions = ["center_left", "center", "center_right", "top_left", "top_right",
                               "bottom_left", "bottom_center", "bottom_right"]
                for i, elem in enumerate(elems):
                    if i < len(h_positions):
                        layout_overrides[elem.id] = h_positions[i]
            elif metaphor_type in (MetaphorType.COMPARISON,):
                # Comparison: side-by-side (first left, second right, rest bottom)
                side_positions = ["center_left", "center_right", "bottom_center",
                                  "top_left", "top_right", "bottom_left", "bottom_right"]
                for i, elem in enumerate(elems):
                    if i < len(side_positions):
                        layout_overrides[elem.id] = side_positions[i]
            elif metaphor_type in (MetaphorType.HIERARCHY,):
                # Hierarchy: top-down tree (root at top, children spread below)
                tree_positions = ["top_center", "center_left", "center_right",
                                  "bottom_left", "bottom_center", "bottom_right"]
                for i, elem in enumerate(elems):
                    if i < len(tree_positions):
                        layout_overrides[elem.id] = tree_positions[i]
            elif metaphor_type in (MetaphorType.RELATIONSHIP,):
                # Relationship: spread around center for graph-like layout
                graph_positions = ["center", "top_left", "top_right",
                                   "bottom_left", "bottom_right", "center_left", "center_right"]
                for i, elem in enumerate(elems):
                    if i < len(graph_positions):
                        layout_overrides[elem.id] = graph_positions[i]
            elif metaphor_type in (MetaphorType.CONTAINER,):
                # Container: central large element with satellites
                container_positions = ["center", "top_right", "bottom_left",
                                       "top_left", "bottom_right", "center_right"]
                for i, elem in enumerate(elems):
                    if i < len(container_positions):
                        layout_overrides[elem.id] = container_positions[i]
        
        for elem in elems:
            template = ELEMENT_TEMPLATES.get(elem.element_type)
            
            if not template:
                # Fallback to glass_card for premium look
                template = ELEMENT_TEMPLATES.get(ElementType.GLASS_CARD, ELEMENT_TEMPLATES[ElementType.NODE])
            
            # Prepare template parameters with aspect-ratio-aware + density-aware sizing
            size_dims = self.config.get_element_size_for_aspect(elem.size, element_count)
            
            # Use layout override if available, else element's own position
            position = layout_overrides.get(elem.id, elem.position.value if elem.position else "center")
            
            # F1: Anti-stacking — offset elements that share the same position
            if position not in position_counts:
                position_counts[position] = 0
            position_counts[position] += 1
            
            params = {
                "id": elem.id,
                "label": elem.label or "",
                "color": elem.color.upper(),
                "position": position,
                "size": size_dims["size"],
                "radius": size_dims["radius"],
                "width": size_dims["width"],
                "height": size_dims["height"],
                "start_pos": "center_left",
                "end_pos": "center_right",
            }
            
            code_line = template.format(**params)
            lines.append(code_line)
            element_ids_ordered.append(elem.id)
            
            # Anti-stacking: shift duplicate-position elements vertically
            count = position_counts[position]
            if count > 1:
                # Increase spacing when more elements are present
                base_offset = 1.8 if element_count <= 4 else 2.2
                offset = (count - 1) * base_offset
                direction = 'UP' if count % 2 == 0 else 'DOWN'
                lines.append(f'elements["{elem.id}"].shift({direction} * {offset:.1f})')
                lines.append(f'clamp_to_safe_frame(elements["{elem.id}"])')
        
        # AUTO-CONNECTION ARROWS: REMOVED
        # Arrows between consecutive elements used static .get_right()/.get_left()
        # positions that became stale after anti-stacking shifts and animations,
        # causing severe overlapping. Layout now speaks through positioning alone.
        
        # GLOW BREATHING UPDATER: REMOVED  
        # Continuous updaters on elements fought with self.play() animations,
        # causing jittery rendering and cumulative state corruption.
        
        return "\n".join(f"        {line}" for line in lines) if lines else "        pass"
    
    # =========================================================================
    # TIMELINE-DRIVEN ANIMATION (New — from VisualDirector)
    # =========================================================================
    
    def _generate_timeline_animation_code(self, timeline, spec) -> str:
        """
        Generate Manim code from a VisualTimeline.
        
        RESTRUCTURED: Includes duration budget enforcement to prevent
        animations from running past audio_duration.
        """
        from generator.video_generator.visual_director import EventType
        
        lines = []
        current_time = 0.0
        # DURATION BUDGET: Track cumulative animation time to prevent overflow
        cumulative_play_time = 0.0
        audio_duration = spec.timing.audio_duration_seconds or 10.0
        # Reserve 10% of duration for waits/breathing room
        play_budget = audio_duration * 0.90
        
        events = sorted(timeline.events, key=lambda e: e.timestamp)
        
        # Map animation style names to Manim code
        # AMPLIFIED MAGNITUDES: shifts 0.4→1.0+, scales 1.08→1.25+, flashes bigger
        ENTRY_CODE = {
            "GrowFromCenter": 'self.play(GrowFromCenter(elements["{target}"]), run_time={dur}, rate_func=rate_functions.ease_out_back)',
            "FadeIn_UP": 'self.play(FadeIn(elements["{target}"], shift=UP*1.0), run_time={dur}, rate_func=rate_functions.ease_out_cubic)',
            "FadeIn_RIGHT": 'self.play(FadeIn(elements["{target}"], shift=RIGHT*1.2), run_time={dur}, rate_func=rate_functions.ease_out_cubic)',
            "FadeIn_LEFT": 'self.play(FadeIn(elements["{target}"], shift=LEFT*1.2), run_time={dur}, rate_func=rate_functions.ease_out_cubic)',
            "FadeIn_DOWN": 'self.play(FadeIn(elements["{target}"], shift=DOWN*1.0), run_time={dur}, rate_func=rate_functions.ease_out_cubic)',
            "SpinInFromNothing": 'self.play(SpinInFromNothing(elements["{target}"]), run_time={dur}, rate_func=smooth)',
            "DrawBorderThenFill": 'self.play(DrawBorderThenFill(elements["{target}"]), run_time={dur}, rate_func=rate_functions.ease_out_cubic)',
            "GrowFromEdge_LEFT": 'self.play(GrowFromEdge(elements["{target}"], LEFT), run_time={dur}, rate_func=rate_functions.ease_out_cubic)',
            "GrowFromEdge_DOWN": 'self.play(GrowFromEdge(elements["{target}"], DOWN), run_time={dur}, rate_func=rate_functions.ease_out_cubic)',
            "GrowFromEdge_RIGHT": 'self.play(GrowFromEdge(elements["{target}"], RIGHT), run_time={dur}, rate_func=rate_functions.ease_out_cubic)',
            # v0.19.0 enriched entries — safe for VGroup primitives
            "Write": 'self.play(DrawBorderThenFill(elements["{target}"]), run_time={dur}, rate_func=rate_functions.ease_out_expo)',
            "FadeIn_SCALE": 'self.play(FadeIn(elements["{target}"], scale=0.15), run_time={dur}, rate_func=rate_functions.ease_out_back)',
            "GrowFromPoint_CENTER": 'self.play(GrowFromPoint(elements["{target}"], ORIGIN), run_time={dur}, rate_func=rate_functions.ease_out_back)',
            "FadeInFromLarge": 'self.play(FadeIn(elements["{target}"], scale=3.0), run_time={dur}, rate_func=rate_functions.ease_out_cubic)',
            "Create": 'self.play(GrowFromCenter(elements["{target}"]), run_time={dur}, rate_func=rate_functions.ease_out_back)',
        }
        
        EMPHASIS_CODE = {
            "Indicate": 'self.play(Indicate(elements["{target}"], color=GOLD, scale_factor=safe_scale_factor(elements["{target}"], 1.25, 1.35)), run_time={dur})',
            "Flash": 'self.play(Flash(elements["{target}"], color=YELLOW, flash_radius=0.8, num_lines=16), run_time={dur})',
            "Circumscribe": 'self.play(Circumscribe(elements["{target}"], color=WHITE, time_width=2.0, buff=0.15, stroke_width=4), run_time={dur})',
            "Wiggle": 'self.play(Wiggle(elements["{target}"], scale_value=1.18, rotation_angle=0.06*TAU), run_time={dur})',
            "ScalePulse": """_sf = safe_scale_factor(elements["{target}"], 1.25, 1.35)
        self.play(elements["{target}"].animate.scale(_sf), run_time={half_dur}, rate_func=rate_functions.ease_out_cubic)
        self.play(elements["{target}"].animate.scale(1/_sf), run_time={half_dur}, rate_func=rate_functions.ease_in_cubic)""",
            "Circumscribe_GOLD": 'self.play(Circumscribe(elements["{target}"], color=GOLD, time_width=2.0, buff=0.15, stroke_width=4), run_time={dur})',
            "Flash_BLUE": 'self.play(Flash(elements["{target}"], color=BLUE, flash_radius=0.8, num_lines=16), run_time={dur})',
            "Indicate_WHITE": 'self.play(Indicate(elements["{target}"], color=WHITE, scale_factor=safe_scale_factor(elements["{target}"], 1.25, 1.35)), run_time={dur})',
            "FocusZoom": """_sf = safe_scale_factor(elements["{target}"], 1.30, 1.40)
        self.play(elements["{target}"].animate.scale(_sf), run_time={half_dur}, rate_func=rate_functions.ease_out_cubic)
        self.play(elements["{target}"].animate.scale(1/_sf), run_time={half_dur}, rate_func=rate_functions.ease_in_cubic)""",
            # v0.19.0 enriched emphasis
            "ApplyWave": 'self.play(ApplyWave(elements["{target}"], amplitude=0.25, direction=UP), run_time={dur}, rate_func=smooth)',
            "ShowPassingFlash": 'self.play(Indicate(elements["{target}"], color=YELLOW, scale_factor=1.18), run_time={dur})',
            "CircleIndicate": 'self.play(Circumscribe(elements["{target}"], color=YELLOW, time_width=2.0, buff=0.15, stroke_width=4), run_time={dur})',
            "WiggleOutThenIn": 'self.play(Wiggle(elements["{target}"], scale_value=1.2, rotation_angle=0.08*TAU), run_time={dur})',
            "SurroundHighlight": """_sr = SurroundingRectangle(elements["{target}"], color=GOLD, buff=0.20, corner_radius=0.15, stroke_width=4)
        self.play(Create(_sr), run_time={half_dur}, rate_func=rate_functions.ease_out_expo)
        self.play(FadeOut(_sr), run_time={half_dur}, rate_func=rate_functions.ease_in_cubic)""",
        }
        
        EXIT_CODE = {
            "FadeOut_DOWN": 'self.play(FadeOut(elements["{target}"], shift=DOWN*0.8, scale=0.3), run_time={dur}, rate_func=rate_functions.ease_in_cubic)',
            "ShrinkToCenter": 'self.play(ShrinkToCenter(elements["{target}"]), run_time={dur}, rate_func=rate_functions.ease_in_cubic)',
            "FadeOut": 'self.play(FadeOut(elements["{target}"], shift=DOWN*0.5), run_time={dur}, rate_func=rate_functions.ease_in_cubic)',
            "FadeOut_LEFT": 'self.play(FadeOut(elements["{target}"], shift=LEFT*1.0), run_time={dur}, rate_func=rate_functions.ease_in_cubic)',
            # v0.19.0 enriched exits — safe for VGroup primitives
            "Unwrite": 'self.play(FadeOut(elements["{target}"], shift=DOWN*0.5, scale=0.5), run_time={dur}, rate_func=rate_functions.ease_in_expo)',
            "FadeOut_UP": 'self.play(FadeOut(elements["{target}"], shift=UP*0.8, scale=0.3), run_time={dur}, rate_func=rate_functions.ease_in_cubic)',
            "FadeOutToPoint": 'self.play(FadeOut(elements["{target}"], scale=0.01), run_time={dur}, rate_func=rate_functions.ease_in_expo)',
            "Uncreate": 'self.play(ShrinkToCenter(elements["{target}"]), run_time={dur}, rate_func=rate_functions.ease_in_cubic)',
        }
        
        GAP_FILLER_CODE = {
            "subtle_pulse": """self.play(elements["{target}"].animate.scale(1.08), run_time={half_dur}, rate_func=rate_functions.ease_out_cubic)
        self.play(elements["{target}"].animate.scale(1/1.08), run_time={half_dur}, rate_func=rate_functions.ease_in_cubic)""",
            "color_shift": 'self.play(Indicate(elements["{target}"], color=GOLD, scale_factor=1.0), run_time={dur}, rate_func=smooth)',
            "position_drift": """self.play(elements["{target}"].animate.shift(UP*0.15), run_time={half_dur}, rate_func=rate_functions.ease_in_out_sine)
        self.play(elements["{target}"].animate.shift(DOWN*0.15), run_time={half_dur}, rate_func=rate_functions.ease_in_out_sine)""",
            "glow_pulse": 'self.play(Flash(elements["{target}"], color=YELLOW, flash_radius=0.4, num_lines=8), run_time={dur})',
            "micro_bounce": """self.play(elements["{target}"].animate.shift(UP*0.15), run_time={half_dur}, rate_func=rate_functions.ease_out_cubic)
        self.play(elements["{target}"].animate.shift(DOWN*0.15), run_time={half_dur}, rate_func=rate_functions.ease_in_cubic)""",
            "opacity_breathe": 'self.play(elements["{target}"].animate.set_opacity(0.6), run_time={half_dur}, rate_func=smooth)\n        self.play(elements["{target}"].animate.set_opacity(1.0), run_time={half_dur}, rate_func=smooth)',
            # v0.19.0 gap fillers — all self-reverting
            "wave_distortion": 'self.play(ApplyWave(elements["{target}"], amplitude=0.08, direction=RIGHT), run_time={dur}, rate_func=smooth)',
            "border_trace": 'self.play(Circumscribe(elements["{target}"], color=YELLOW, time_width=2.0, buff=0.08, stroke_width=2), run_time={dur})',
            "sheen_sweep": 'self.play(elements["{target}"].animate.set_opacity(0.6), run_time={half_dur}, rate_func=smooth)\n        self.play(elements["{target}"].animate.set_opacity(1.0), run_time={half_dur}, rate_func=smooth)',
        }
        
        # === MOVE event code templates — RESTRUCTURED: self-reverting oscillations ===
        # No more cumulative shifts that destroy layout
        MOVE_CODE = {
            "SlideToPosition": """self.play(elements["{target}"].animate.shift(RIGHT*0.3), run_time={half_dur}, rate_func=rate_functions.ease_in_out_cubic)
        self.play(elements["{target}"].animate.shift(LEFT*0.3), run_time={half_dur}, rate_func=rate_functions.ease_in_out_cubic)""",
            "ArcToPosition": """self.play(elements["{target}"].animate.shift(RIGHT*0.2 + UP*0.15), run_time={half_dur}, rate_func=rate_functions.ease_in_out_cubic)
        self.play(elements["{target}"].animate.shift(LEFT*0.2 + DOWN*0.15), run_time={half_dur}, rate_func=rate_functions.ease_in_out_cubic)""",
            "DriftToPosition": """self.play(elements["{target}"].animate.shift(UP*0.2), run_time={half_dur}, rate_func=rate_functions.ease_in_out_sine)
        self.play(elements["{target}"].animate.shift(DOWN*0.2), run_time={half_dur}, rate_func=rate_functions.ease_in_out_sine)""",
            "MoveAlongArc": 'self.play(Indicate(elements["{target}"], color=WHITE, scale_factor=1.05), run_time={dur}, rate_func=smooth)',
            "ElasticSlide": """self.play(elements["{target}"].animate.shift(RIGHT*0.25), run_time={half_dur}, rate_func=rate_functions.ease_out_back)
        self.play(elements["{target}"].animate.shift(LEFT*0.25), run_time={half_dur}, rate_func=rate_functions.ease_in_cubic)""",
        }
        
        # === TRANSFORM event code templates — RESTRUCTURED: self-reverting ===
        TRANSFORM_CODE = {
            "MorphTransform": """_sf = safe_scale_factor(elements["{target}"], 1.15, 1.20)
        self.play(elements["{target}"].animate.scale(_sf).set_color(GOLD), run_time={half_dur}, rate_func=rate_functions.ease_out_cubic)
        self.play(elements["{target}"].animate.scale(1/_sf).set_color(elements["{target}"].get_color()), run_time={half_dur}, rate_func=rate_functions.ease_in_cubic)""",
            "ScaleTransform": """_sf = safe_scale_factor(elements["{target}"], 1.15, 1.20)
        self.play(elements["{target}"].animate.scale(_sf), run_time={half_dur}, rate_func=rate_functions.ease_out_cubic)
        self.play(elements["{target}"].animate.scale(1/_sf), run_time={half_dur}, rate_func=rate_functions.ease_in_cubic)""",
            "ColorTransform": 'self.play(Indicate(elements["{target}"], color=GOLD, scale_factor=1.0), run_time={dur}, rate_func=smooth)',
            "FadeTransformMorph": 'self.play(Indicate(elements["{target}"], color=GOLD, scale_factor=1.08), run_time={dur}, rate_func=rate_functions.ease_in_out_cubic)',
            "CounterclockwiseSpin": 'self.play(Wiggle(elements["{target}"], scale_value=1.08, rotation_angle=0.04*TAU), run_time={dur}, rate_func=rate_functions.ease_in_out_back)',
        }
        
        # === CAMERA event code templates — RESTRUCTURED ===
        # No more VGroup scaling that destroys layout. Camera events now use
        # individual element emphasis (Indicate, Circumscribe) to guide attention.
        CAMERA_CODE = {
            "ZoomIn": '# Camera focus: Indicate {target}\n        self.play(Indicate(elements["{target}"], color=GOLD, scale_factor=1.12), run_time={dur}, rate_func=rate_functions.ease_out_cubic)',
            "ZoomOut": '# Camera: subtle de-emphasis\n        self.play(Indicate(elements["{target}"], color=WHITE, scale_factor=1.05), run_time={dur}, rate_func=smooth)',
            "FocusPulse": """# Camera: FocusPulse on {target}
        _sf = safe_scale_factor(elements["{target}"], 1.10, max_allowed=1.15)
        self.play(elements["{target}"].animate.scale(_sf), run_time={half_dur}, rate_func=rate_functions.ease_out_cubic)
        self.play(elements["{target}"].animate.scale(1/_sf), run_time={half_dur}, rate_func=rate_functions.ease_in_cubic)""",
            "PanLeft": 'self.play(Indicate(elements["{target}"], color=WHITE, scale_factor=1.05), run_time={dur}, rate_func=smooth)',
            "PanRight": 'self.play(Indicate(elements["{target}"], color=WHITE, scale_factor=1.05), run_time={dur}, rate_func=smooth)',
            "FocusIsolate": """# Camera: FocusIsolate {target}
        _sf = safe_scale_factor(elements["{target}"], 1.10, max_allowed=1.15)
        self.play(elements["{target}"].animate.scale(_sf), run_time={half_dur}, rate_func=rate_functions.ease_out_cubic)
        self.play(elements["{target}"].animate.scale(1/_sf), run_time={half_dur}, rate_func=rate_functions.ease_in_cubic)""",
            "RackFocus": 'self.play(Circumscribe(elements["{target}"], color=GOLD, time_width=2.0, buff=0.12, stroke_width=3), run_time={dur})',
            "DollyZoom": 'self.play(Indicate(elements["{target}"], color=GOLD, scale_factor=1.10), run_time={dur}, rate_func=rate_functions.ease_in_out_cubic)',
            "SweepPan": 'self.play(Circumscribe(elements["{target}"], color=WHITE, time_width=2.0, buff=0.10, stroke_width=2), run_time={dur})',
        }
        
        # Group nearby events for overlapped play (lag_ratio)
        # threshold=0.35: only events within 350ms merge — keeps most animations sequential & visible
        event_groups = self._group_nearby_events(events, threshold=0.35)
        
        for group in event_groups:
            first_event = group[0]
            
            # === DURATION BUDGET CHECK ===
            # If we've used 90% of audio duration in play() calls, stop adding animations
            if cumulative_play_time >= play_budget:
                break
            
            # Wait to sync with timestamp
            wait_time = max(0.0, first_event.timestamp - current_time)
            if wait_time > 0.05:
                if first_event.sync_phrase:
                    lines.append(f'self.wait({wait_time:.2f})  # Sync: "{first_event.sync_phrase[:35]}"')
                else:
                    lines.append(f'self.wait({wait_time:.2f})')
                current_time += wait_time
            
            if len(group) == 1:
                # Single event — direct play
                event = group[0]
                
                # Budget check for this specific animation
                event_dur = event.duration
                if cumulative_play_time + event_dur > play_budget:
                    break  # Would exceed budget
                
                code = self._event_to_manim_code(
                    event, ENTRY_CODE, EMPHASIS_CODE, EXIT_CODE, GAP_FILLER_CODE
                )
                if event.sync_phrase:
                    lines.append(f'# "{event.sync_phrase[:40]}"')
                lines.append(code)
                cumulative_play_time += event_dur
                current_time = event.end_time
            else:
                # Multiple events close together — AnimationGroup with lag_ratio
                # ====================================================================
                # CRITICAL: Deduplicate by target element to prevent Manim freezing.
                # ====================================================================
                
                # Budget check for group
                group_dur_estimate = max(e.duration for e in group)
                if cumulative_play_time + group_dur_estimate > play_budget:
                    break  # Would exceed budget
                
                lines.append(f'# Grouped: {len(group)} animations')
                
                # Priority: EXIT > ENTER > EMPHASIZE > TRANSFORM > CAMERA > MOVE > GAP_FILLER
                EVENT_PRIORITY = {
                    EventType.EXIT: 0,
                    EventType.ENTER: 1,
                    EventType.EMPHASIZE: 2,
                    EventType.TRANSFORM: 3,
                    EventType.CAMERA: 4,
                    EventType.MOVE: 5,
                    EventType.GAP_FILLER: 6,
                }
                
                # Sort by priority so higher-priority animations win per target
                sorted_group = sorted(group, key=lambda e: EVENT_PRIORITY.get(e.event_type, 99))
                
                seen_targets = set()
                deduped_events = []
                exit_targets = set()
                
                # First pass: collect all EXIT targets (nothing else should touch them)
                for event in sorted_group:
                    if event.event_type == EventType.EXIT:
                        exit_targets.add(event.target_element)
                
                # Second pass: keep only ONE animation per target element
                for event in sorted_group:
                    target = event.target_element
                    
                    # Skip if this target is exiting and this isn't the exit animation
                    if target in exit_targets and event.event_type != EventType.EXIT:
                        continue
                    
                    # Skip duplicate targets
                    if target in seen_targets:
                        continue
                    
                    seen_targets.add(target)
                    deduped_events.append(event)
                
                anim_parts = []
                max_end = current_time
                
                for event in deduped_events:
                    anim_expr = self._event_to_animation_expr(event)
                    if anim_expr:
                        anim_parts.append(anim_expr)
                    max_end = max(max_end, event.end_time)
                
                if anim_parts:
                    group_dur = max(0.5, max_end - current_time)
                    if len(anim_parts) == 1:
                        lines.append(f'self.play({anim_parts[0]}, run_time={group_dur:.2f})')
                    else:
                        anims_str = ",\n            ".join(anim_parts)
                        lines.append(f'self.play(AnimationGroup(\n            {anims_str},\n            lag_ratio=0.2\n        ), run_time={group_dur:.2f}, rate_func=rate_functions.ease_out_cubic)')
                    cumulative_play_time += group_dur
                    current_time = max_end
        
        # Fill remaining audio duration with wait (budget-aware)
        remaining = max(0, audio_duration - cumulative_play_time)
        if remaining > 0.1:
            lines.append(f'self.wait({remaining:.2f})')
        
        return "\n".join(f"        {line}" for line in lines)
    
    def _group_nearby_events(self, events: list, threshold: float = 0.4) -> list:
        """Group events that start within `threshold` seconds of each other."""
        if not events:
            return []
        
        groups = []
        current_group = [events[0]]
        
        for event in events[1:]:
            if event.timestamp - current_group[0].timestamp <= threshold:
                current_group.append(event)
            else:
                groups.append(current_group)
                current_group = [event]
        
        groups.append(current_group)
        return groups
    
    def _event_to_manim_code(self, event, entry_map, emphasis_map, exit_map, gap_map) -> str:
        """Convert a single TimedVisualEvent to Manim code string."""
        from generator.video_generator.visual_director import EventType
        
        dur = f"{event.duration:.2f}"
        half_dur = f"{event.duration / 2:.2f}"
        target = event.target_element
        
        if event.event_type == EventType.ENTER:
            template = entry_map.get(event.animation_style, entry_map.get("GrowFromCenter"))
        elif event.event_type == EventType.EMPHASIZE:
            template = emphasis_map.get(event.animation_style, emphasis_map.get("Indicate"))
        elif event.event_type == EventType.EXIT:
            template = exit_map.get(event.animation_style, exit_map.get("FadeOut"))
        elif event.event_type == EventType.GAP_FILLER:
            template = gap_map.get(event.animation_style, gap_map.get("subtle_pulse"))
        elif event.event_type == EventType.MOVE:
            # Cinematic: MOVE event — element repositions for diagram building (AMPLIFIED)
            move_map = {
                "SlideToPosition": 'self.play(elements["{target}"].animate.shift(RIGHT*1.0 + UP*0.4), run_time={dur}, rate_func=rate_functions.ease_in_out_cubic)',
                "ArcToPosition": 'self.play(elements["{target}"].animate.shift(RIGHT*0.8 + UP*0.3), run_time={dur}, rate_func=rate_functions.ease_in_out_cubic)',
                "DriftToPosition": 'self.play(elements["{target}"].animate.shift(RIGHT*0.6), run_time={dur}, rate_func=rate_functions.ease_in_out_sine)',
                "MoveAlongArc": 'self.play(elements["{target}"].animate.shift(RIGHT*1.0 + UP*0.5), run_time={dur}, rate_func=rate_functions.ease_in_out_cubic)',
                "ElasticSlide": 'self.play(elements["{target}"].animate.shift(RIGHT*1.0 + UP*0.3), run_time={dur}, rate_func=rate_functions.ease_out_back)',
            }
            template = move_map.get(event.animation_style, move_map.get("SlideToPosition"))
        elif event.event_type == EventType.TRANSFORM:
            # Cinematic: TRANSFORM event — element evolution (AMPLIFIED)
            transform_map = {
                "MorphTransform": 'self.play(elements["{target}"].animate.scale(safe_scale_factor(elements["{target}"], 1.25, 1.30)).set_color(GOLD), run_time={dur}, rate_func=rate_functions.ease_out_cubic)',
                "ScaleTransform": '_sf = safe_scale_factor(elements["{target}"], 1.30, 1.35)\n        self.play(elements["{target}"].animate.scale(_sf), run_time={half_dur}, rate_func=rate_functions.ease_out_cubic)\n        self.play(elements["{target}"].animate.scale(1/_sf), run_time={half_dur}, rate_func=rate_functions.ease_in_cubic)',
                "ColorTransform": 'self.play(elements["{target}"].animate.set_color(GOLD), run_time={dur}, rate_func=smooth)',
                "FadeTransformMorph": 'self.play(elements["{target}"].animate.scale(safe_scale_factor(elements["{target}"], 1.20, 1.25)).set_color(GOLD), run_time={dur}, rate_func=rate_functions.ease_in_out_expo)',
                "CounterclockwiseSpin": 'self.play(Rotate(elements["{target}"], angle=-PI/4), run_time={dur}, rate_func=rate_functions.ease_in_out_back)',
            }
            template = transform_map.get(event.animation_style, transform_map.get("MorphTransform"))
        elif event.event_type == EventType.CAMERA:
            # Cinematic: CAMERA event — GROUP-BASED zoom/focus + lateral (AMPLIFIED)
            camera_map = {
                "ZoomIn": '_content = VGroup(*[v for k, v in elements.items() if k != "all"])\n        _pivot = elements["{target}"].get_center()\n        _sf = safe_scale_factor(elements["{target}"], 1.30, 1.40)\n        self.play(_content.animate.scale(_sf, about_point=_pivot), run_time={dur}, rate_func=rate_functions.ease_out_expo)',
                "ZoomOut": '_content = VGroup(*[v for k, v in elements.items() if k != "all"])\n        self.play(_content.animate.scale(1/1.25, about_point=ORIGIN), run_time={dur}, rate_func=rate_functions.ease_in_out_cubic)',
                "FocusPulse": '_content = VGroup(*[v for k, v in elements.items() if k != "all"])\n        _pivot = elements["{target}"].get_center()\n        _sf = safe_scale_factor(elements["{target}"], 1.25, 1.30)\n        self.play(_content.animate.scale(_sf, about_point=_pivot), run_time={half_dur}, rate_func=rate_functions.ease_out_cubic)\n        self.play(_content.animate.scale(1/_sf, about_point=_pivot), run_time={half_dur}, rate_func=rate_functions.ease_in_cubic)',
                "PanLeft": '_content = VGroup(*[v for k, v in elements.items() if k != "all"])\n        self.play(_content.animate.shift(RIGHT*0.5), run_time={dur}, rate_func=rate_functions.ease_in_out_sine)',
                "PanRight": '_content = VGroup(*[v for k, v in elements.items() if k != "all"])\n        self.play(_content.animate.shift(LEFT*0.5), run_time={dur}, rate_func=rate_functions.ease_in_out_sine)',
                "FocusIsolate": '_content = VGroup(*[v for k, v in elements.items() if k != "all"])\n        _pivot = elements["{target}"].get_center()\n        _sf = safe_scale_factor(elements["{target}"], 1.25, 1.30)\n        self.play(_content.animate.scale(_sf, about_point=_pivot), run_time={half_dur}, rate_func=rate_functions.ease_out_expo)\n        self.play(_content.animate.scale(1/_sf, about_point=_pivot), run_time={half_dur}, rate_func=rate_functions.ease_in_cubic)',
                "RackFocus": '_content = VGroup(*[v for k, v in elements.items() if k != "all"])\n        _pivot = elements["{target}"].get_center()\n        _sf = safe_scale_factor(elements["{target}"], 1.20, 1.25)\n        self.play(_content.animate.scale(_sf, about_point=_pivot), run_time={half_dur}, rate_func=rate_functions.ease_out_cubic)\n        self.play(_content.animate.scale(1/_sf, about_point=_pivot), run_time={half_dur}, rate_func=rate_functions.ease_in_cubic)',
                "DollyZoom": '_content = VGroup(*[v for k, v in elements.items() if k != "all"])\n        _pivot = elements["{target}"].get_center()\n        self.play(_content.animate.scale(1.20, about_point=_pivot).shift(LEFT*0.3), run_time={dur}, rate_func=rate_functions.ease_in_out_expo)\n        self.play(_content.animate.scale(1/1.20, about_point=_pivot).shift(RIGHT*0.3), run_time={half_dur}, rate_func=rate_functions.ease_out_cubic)',
                "SweepPan": '_content = VGroup(*[v for k, v in elements.items() if k != "all"])\n        self.play(_content.animate.shift(LEFT*0.6), run_time={half_dur}, rate_func=rate_functions.ease_in_out_sine)\n        self.play(_content.animate.shift(RIGHT*0.6), run_time={half_dur}, rate_func=rate_functions.ease_in_out_sine)',
            }
            template = camera_map.get(event.animation_style, camera_map.get("FocusPulse"))
        else:
            template = emphasis_map.get("Indicate")
        
        if template is None:
            return f'self.play(Indicate(elements["{target}"]), run_time={dur})'
        
        return template.format(target=target, dur=dur, half_dur=half_dur)
    
    def _event_to_animation_expr(self, event) -> str:
        """Convert event to a Manim animation expression (for use inside AnimationGroup).
        
        Expanded for Manim v0.19.0: Write, Create, ApplyWave, ShowPassingFlash,
        CircleIndicate, WiggleOutThenIn, Unwrite, Uncreate, FadeTransform,
        group-based camera zoom, and 20+ rate functions.
        """
        from generator.video_generator.visual_director import EventType
        
        target = event.target_element
        style = event.animation_style or ""
        
        if event.event_type == EventType.ENTER:
            if style == "GrowFromCenter":
                return f'GrowFromCenter(elements["{target}"])'
            elif style == "Write":
                return f'DrawBorderThenFill(elements["{target}"])'
            elif style == "Create":
                return f'GrowFromCenter(elements["{target}"])'
            elif style == "FadeIn_SCALE":
                return f'FadeIn(elements["{target}"], scale=0.15)'
            elif style == "GrowFromPoint_CENTER":
                return f'GrowFromPoint(elements["{target}"], ORIGIN)'
            elif style == "FadeInFromLarge":
                return f'FadeIn(elements["{target}"], scale=3.0)'
            elif "FadeIn" in style:
                if "DOWN" in style:
                    direction = "DOWN*1.0"
                elif "LEFT" in style:
                    direction = "LEFT*1.2"
                elif "RIGHT" in style:
                    direction = "RIGHT*1.2"
                else:
                    direction = "UP*1.0"
                return f'FadeIn(elements["{target}"], shift={direction})'
            elif style == "SpinInFromNothing":
                return f'SpinInFromNothing(elements["{target}"])'
            elif style == "DrawBorderThenFill":
                return f'DrawBorderThenFill(elements["{target}"])'
            elif "GrowFromEdge" in style:
                if "RIGHT" in style:
                    edge = "RIGHT"
                elif "DOWN" in style:
                    edge = "DOWN"
                else:
                    edge = "LEFT"
                return f'GrowFromEdge(elements["{target}"], {edge})'
            else:
                return f'FadeIn(elements["{target}"])'
        
        elif event.event_type == EventType.EMPHASIZE:
            if style == "Indicate":
                return f'Indicate(elements["{target}"], color=GOLD, scale_factor=1.25)'
            elif style == "Flash":
                return f'Flash(elements["{target}"], color=YELLOW, flash_radius=0.8)'
            elif style == "Circumscribe":
                return f'Circumscribe(elements["{target}"], color=WHITE, stroke_width=4)'
            elif style == "Wiggle":
                return f'Wiggle(elements["{target}"], scale_value=1.18)'
            elif style == "ApplyWave":
                return f'ApplyWave(elements["{target}"], amplitude=0.25, direction=UP)'
            elif style == "ShowPassingFlash":
                return f'Indicate(elements["{target}"], color=YELLOW, scale_factor=1.18)'
            elif style == "CircleIndicate":
                return f'Circumscribe(elements["{target}"], color=YELLOW, stroke_width=4)'
            elif style == "WiggleOutThenIn":
                return f'WiggleOutThenIn(elements["{target}"], scale_value=1.18)'
            elif style == "SurroundHighlight":
                return f'Indicate(elements["{target}"], color=GOLD, scale_factor=1.20)'
            else:
                return f'Indicate(elements["{target}"])'
        
        elif event.event_type == EventType.EXIT:
            if style == "Unwrite":
                return f'FadeOut(elements["{target}"], shift=DOWN*0.5)'
            elif style == "Uncreate":
                return f'ShrinkToCenter(elements["{target}"])'
            elif style == "FadeOutToPoint":
                return f'FadeOut(elements["{target}"], scale=0.01)'
            elif style == "FadeOut_UP":
                return f'FadeOut(elements["{target}"], shift=UP*0.8)'
            elif "FadeOut" in style:
                return f'FadeOut(elements["{target}"], shift=DOWN*0.8)'
            elif style == "ShrinkToCenter":
                return f'ShrinkToCenter(elements["{target}"])'
            else:
                return f'FadeOut(elements["{target}"])'
        
        elif event.event_type == EventType.GAP_FILLER:
            if style == "wave_distortion":
                return f'ApplyWave(elements["{target}"], amplitude=0.06, direction=UP)'
            elif style == "border_trace":
                return f'Indicate(elements["{target}"], color=YELLOW, scale_factor=1.04)'
            elif style == "sheen_sweep":
                return f'elements["{target}"].animate.set_color(elements["{target}"].get_color())'
            else:
                return f'elements["{target}"].animate.scale(1.05)'
        
        elif event.event_type == EventType.MOVE:
            # RESTRUCTURED: self-reverting — small shift for AnimationGroup context
            return f'Indicate(elements["{target}"], color=WHITE, scale_factor=1.05)'
        
        elif event.event_type == EventType.TRANSFORM:
            # RESTRUCTURED: safe indication in group context
            if style == "ColorTransform":
                return f'Indicate(elements["{target}"], color=GOLD, scale_factor=1.0)'
            else:
                return f'Indicate(elements["{target}"], color=GOLD, scale_factor=1.08)'
        
        elif event.event_type == EventType.CAMERA:
            # RESTRUCTURED: individual element emphasis instead of VGroup scaling
            return f'Indicate(elements["{target}"], color=WHITE, scale_factor=1.05)'
        
        return None
    
    # =========================================================================
    # LEGACY PATH (fallback when no VisualTimeline provided)
    # =========================================================================
    
    def _estimate_beat_times(
        self,
        narration: str,
        beats: list,
        total_duration: float
    ) -> list:
        """Estimate when each semantic beat occurs in the narration."""
        if not narration or not beats:
            return []
        
        words = narration.split()
        total_words = len(words)
        if total_words == 0:
            return []
        
        words_per_second = total_words / total_duration
        beat_timings = []
        
        for beat in beats:
            beat_phrase = beat.beat_phrase.lower()
            narration_lower = narration.lower()
            phrase_start = narration_lower.find(beat_phrase)
            
            if phrase_start == -1:
                beat_index = beats.index(beat)
                start_time = (beat_index / max(1, len(beats))) * total_duration
            else:
                words_before = len(narration[:phrase_start].split())
                start_time = words_before / words_per_second
            
            start_time = max(0.0, min(start_time, total_duration - 1.0))
            phrase_words = len(beat_phrase.split())
            duration = max(0.8, phrase_words / words_per_second)
            beat_timings.append((beat, start_time, duration))
        
        beat_timings.sort(key=lambda x: x[1])
        return beat_timings
    
    def _generate_legacy_animation_code(self, spec: SceneSpecification) -> str:
        """Legacy fallback: generate animation code directly from spec.
        
        KEY PRINCIPLES:
        - Uses diverse animation types (not just FadeIn/FadeOut)
        - run_time >= 1.2 for main content, >= 0.6 for emphasis
        - NEVER FadeOuts all elements at end — keep everything visible
        - Uses the full audio duration without leaving dead time
        """
        lines = []
        
        elements = {elem.id: elem for elem in spec.visual_metaphor.visual_elements}
        element_ids = list(elements.keys())
        audio_duration = spec.timing.audio_duration_seconds or 10.0
        num_elements = max(1, len(element_ids))
        
        beats = spec.narration.semantic_beats if spec.narration else []
        beat_timings = self._estimate_beat_times(
            narration=spec.narration.text if spec.narration else "",
            beats=beats,
            total_duration=audio_duration
        )
        
        introduced_elements = set()
        current_time = 0.0
        
        # Diverse entry animations — cycle through these (expanded v0.19.0)
        entry_animations = [
            'GrowFromCenter(elements["{id}"])',
            'DrawBorderThenFill(elements["{id}"])',
            'FadeIn(elements["{id}"], shift=UP*0.5)',
            'FadeIn(elements["{id}"], shift=LEFT*0.5)',
            'FadeIn(elements["{id}"], shift=RIGHT*0.5)',
            'GrowFromEdge(elements["{id}"], LEFT)',
            'GrowFromEdge(elements["{id}"], DOWN)',
            'DrawBorderThenFill(elements["{id}"])',
            'FadeIn(elements["{id}"], scale=0.3)',
            'GrowFromPoint(elements["{id}"], ORIGIN)',
            'GrowFromCenter(elements["{id}"])',
            'SpinInFromNothing(elements["{id}"])',
        ]
        # Diverse emphasis animations — cycle through these (expanded v0.19.0)
        emphasis_animations = [
            'Indicate(elements["{id}"], color=GOLD, scale_factor=1.2)',
            'Circumscribe(elements["{id}"], color=YELLOW, buff=0.15)',
            'Flash(elements["{id}"], color=YELLOW, flash_radius=0.5, num_lines=12)',
            'Wiggle(elements["{id}"], scale_value=1.15)',
            'ApplyWave(elements["{id}"], amplitude=0.12, direction=UP)',
            'Flash(elements["{id}"], color=YELLOW, flash_radius=0.4, num_lines=10)',
            'Circumscribe(elements["{id}"], color=YELLOW, buff=0.1)',
            'WiggleOutThenIn(elements["{id}"], scale_value=1.08)',
        ]
        entry_idx = 0
        emphasis_idx = 0
        
        # INTRO — First elements appear with staggered animations
        lines.append("# Intro — First elements appear")
        intro_time = max(1.2, min(2.0, audio_duration * 0.12))
        intro_elements = element_ids[:min(3, len(element_ids))]
        for elem_id in intro_elements:
            anim = entry_animations[entry_idx % len(entry_animations)].format(id=elem_id)
            lines.append(f'self.play({anim}, run_time={intro_time:.2f})')
            introduced_elements.add(elem_id)
            entry_idx += 1
        current_time = intro_time * len(intro_elements)
        
        # BEAT-SYNCED — Rich animations timed to narration
        if beat_timings:
            lines.append("")
            lines.append("# Beat-Synced Animations (timed to narration)")
            for beat, beat_start, beat_duration in beat_timings:
                target_elems = beat.target_elements
                if not target_elems:
                    continue
                wait_time = max(0.0, beat_start - current_time)
                if wait_time > 0.1:
                    lines.append(f'self.wait({wait_time:.2f})  # Wait for: "{beat.beat_phrase[:30]}..."')
                    current_time += wait_time
                run_t = max(1.2, beat_duration)
                for elem_id in target_elems:
                    if elem_id not in elements:
                        continue
                    if elem_id not in introduced_elements:
                        anim = entry_animations[entry_idx % len(entry_animations)].format(id=elem_id)
                        lines.append(f'# "{beat.beat_phrase[:25]}..." → {elem_id} appears')
                        lines.append(f'self.play({anim}, run_time={run_t:.2f})')
                        # Follow-up emphasis
                        emp = emphasis_animations[emphasis_idx % len(emphasis_animations)].format(id=elem_id)
                        lines.append(f'self.play({emp}, run_time=0.6)')
                        introduced_elements.add(elem_id)
                        entry_idx += 1
                        emphasis_idx += 1
                    else:
                        emp = emphasis_animations[emphasis_idx % len(emphasis_animations)].format(id=elem_id)
                        lines.append(f'# "{beat.beat_phrase[:25]}..." → emphasize {elem_id}')
                        lines.append(f'self.play({emp}, run_time={run_t:.2f})')
                        emphasis_idx += 1
                current_time += beat_duration
        
        # REMAINING ELEMENTS — bring in anything not yet introduced
        remaining_elements = [e for e in element_ids if e not in introduced_elements]
        if remaining_elements:
            lines.append("")
            lines.append("# Remaining elements")
            remaining_time = max(1.5, (audio_duration - current_time) * 0.5)
            time_per_elem = max(1.2, remaining_time / len(remaining_elements))
            for elem_id in remaining_elements:
                anim = entry_animations[entry_idx % len(entry_animations)].format(id=elem_id)
                lines.append(f'self.play({anim}, run_time={time_per_elem:.2f})')
                introduced_elements.add(elem_id)
                current_time += time_per_elem
                entry_idx += 1
        
        # HOLD — Keep everything visible for remaining duration (NO FadeOut-all)
        lines.append("")
        lines.append("# Hold all elements visible — no exit FadeOut")
        hold_time = max(0.5, audio_duration - current_time)
        if hold_time > 0.3:
            # If we have significant hold time, add a subtle final emphasis
            if element_ids and hold_time > 2.0:
                last_id = element_ids[-1]
                lines.append(f'self.play(Circumscribe(elements["{last_id}"], color=WHITE, buff=0.1), run_time=1.0)')
                hold_time -= 1.0
            if hold_time > 0.3:
                lines.append(f'self.wait({hold_time:.2f})')
        
        return "\n".join(f"        {line}" for line in lines)
    
    def generate_all_scenes(
        self,
        specs: List[SceneSpecification],
        timelines: List = None
    ) -> List[str]:
        """Generate code for all scenes.
        
        Args:
            specs: List of SceneSpecifications
            timelines: Optional list of VisualTimelines (from VisualDirector)
        """
        if timelines and len(timelines) == len(specs):
            return [
                self.generate_scene_code(spec, i, timeline=tl)
                for i, (spec, tl) in enumerate(zip(specs, timelines))
            ]
        return [
            self.generate_scene_code(spec, i)
            for i, spec in enumerate(specs)
        ]


# =============================================================================
# VALIDATION: Code Quality Checks
# =============================================================================

class CodeValidator:
    """
    Validates generated Manim code against quality constraints.
    """
    
    def validate(self, code: str) -> tuple[bool, List[str]]:
        """
        Validate generated code.
        
        Returns:
            Tuple of (is_valid, list of issues)
        """
        issues = []
        
        # Check for required components
        if "class " not in code:
            issues.append("Missing Scene class definition")
        
        if "def construct(self)" not in code:
            issues.append("Missing construct method")
        
        # Check for forbidden patterns
        # Count Text() only in the construct method, not in class definitions
        construct_section = code[code.find('def construct'):] if 'def construct' in code else code
        text_count = construct_section.count('Text(')
        if text_count > 8:
            issues.append(f"Too many Text objects in construct ({text_count})")
        
        # Check for paragraph-length text
        import re
        text_matches = re.findall(r'Text\("([^"]+)"', code)
        for text in text_matches:
            if len(text.split()) > 6:
                issues.append(f"Text too long: '{text[:30]}...'")
        
        # Check for self.wait() presence
        if "self.wait" not in code:
            issues.append("Missing self.wait() call")
        
        return len(issues) == 0, issues


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    from .scene_specification import create_example_zero_trust_scene
    
    # Create example spec
    spec = create_example_zero_trust_scene()
    
    # Generate code
    generator = ManimCodeGenerator()
    code = generator.generate_scene_code(spec, scene_index=0)
    
    print("Generated Manim Code:")
    print("=" * 60)
    print(code)
    
    # Validate
    validator = CodeValidator()
    is_valid, issues = validator.validate(code)
    print("\n" + "=" * 60)
    print(f"Valid: {is_valid}")
    if issues:
        print("Issues:")
        for issue in issues:
            print(f"  - {issue}")
