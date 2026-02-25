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

SCENE_TEMPLATE = '''from manim import *
from typing import Dict

# Aspect ratio configuration
{aspect_ratio_config}

# =============================================================================
# PRIMITIVE DEFINITIONS (inline for portability)
# =============================================================================

class PrimitiveConfig:
    # Allowed Manim colors - CYAN removed as it's not reliably defined
    COLORS = {{
        "BLUE": BLUE, "RED": RED, "GREEN": GREEN, "YELLOW": YELLOW,
        "WHITE": WHITE, "ORANGE": ORANGE, "PINK": PINK, "PURPLE": PURPLE,
        "TEAL": TEAL, "GOLD": GOLD, "MAROON": MAROON, "GRAY": GRAY
    }}
    FONT_SIZES = {{"title": 36, "heading": 28, "body": 22, "label": 18, "small": 14}}
    
    @classmethod
    def get_color(cls, color_name: str):
        """Get color with fallback to BLUE for unknown colors."""
        return cls.COLORS.get(color_name.upper(), BLUE)


class BoundaryBox(VGroup):
    def __init__(self, label=None, width=4.0, height=3.0, color=BLUE, fill_opacity=0.1, **kwargs):
        super().__init__(**kwargs)
        # Constrain to frame bounds
        max_width = config.frame_width * 0.85
        max_height = config.frame_height * 0.4
        width = min(width, max_width)
        height = min(height, max_height)
        self.box = RoundedRectangle(corner_radius=0.3, width=width, height=height, 
                                     color=color, fill_opacity=0.5, stroke_width=4)
        self.add(self.box)
        if label:
            self.label_text = Text(label, font_size=18, color=color)
            max_w = width * 0.8
            if self.label_text.width > max_w:
                self.label_text.scale_to_fit_width(max_w)
            self.label_text.next_to(self.box, UP, buff=0.15)
            self.add(self.label_text)


class DataPacket(VGroup):
    def __init__(self, label=None, color=GREEN, radius=0.35, **kwargs):
        super().__init__(**kwargs)
        # Constrain radius to frame bounds
        max_radius = min(config.frame_width, config.frame_height) * 0.1
        radius = min(radius, max_radius)
        self.body = Circle(radius=radius, color=color, fill_opacity=0.9, stroke_width=3)
        self.add(self.body)
        if label:
            self.label_text = Text(label, font_size=14, color=WHITE)
            if self.label_text.width > radius * 1.5:
                self.label_text.scale_to_fit_width(radius * 1.5)
            self.label_text.move_to(self.body)
            self.add(self.label_text)


class Node(VGroup):
    def __init__(self, label=None, color=BLUE, node_type="circle", size=0.5, **kwargs):
        super().__init__(**kwargs)
        # Constrain size to frame bounds
        max_size = min(config.frame_width, config.frame_height) * 0.15
        size = min(size, max_size)
        if node_type == "circle":
            self.shape = Circle(radius=size, color=color, fill_opacity=0.6, stroke_width=3)
        elif node_type == "square":
            self.shape = Square(side_length=size*1.8, color=color, fill_opacity=0.6, stroke_width=3)
        else:
            self.shape = Circle(radius=size, color=color, fill_opacity=0.6, stroke_width=3)
        self.add(self.shape)
        if label:
            self.label_text = Text(label, font_size=18, color=color)
            if self.label_text.width > size * 1.5:
                self.label_text.scale_to_fit_width(size * 1.5)
            self.label_text.move_to(self.shape)
            self.add(self.label_text)


class Checkpoint(VGroup):
    def __init__(self, label="✓", color=GOLD, size=1.0, **kwargs):
        super().__init__(**kwargs)
        # Constrain size to frame bounds
        max_size = min(config.frame_width, config.frame_height) * 0.2
        size = min(size, max_size)
        self.left_bar = Rectangle(width=0.15*size, height=1.2*size, color=color, fill_opacity=0.8)
        self.right_bar = Rectangle(width=0.15*size, height=1.2*size, color=color, fill_opacity=0.8)
        self.left_bar.shift(LEFT * 0.3 * size)
        self.right_bar.shift(RIGHT * 0.3 * size)
        self.add(self.left_bar, self.right_bar)
        self.symbol = Text(label, font_size=int(28*size), color=color)
        self.add(self.symbol)


class FlowArrow(VGroup):
    def __init__(self, start=LEFT, end=RIGHT, label=None, color=GRAY, **kwargs):
        super().__init__(**kwargs)
        self.arrow = Arrow(start=start, end=end, color=color, stroke_width=3, buff=0.1)
        self.add(self.arrow)
        if label:
            self.label_text = Text(label, font_size=14, color=color)
            self.label_text.next_to(self.arrow, UP, buff=0.1)
            self.add(self.label_text)


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
        # Element registry for referencing
        elements: Dict[str, VMobject] = {{}}
        
        # Grid positions for {aspect_ratio}
        positions = self._get_grid_positions()
        
        # Create visual elements
{element_creation_code}
        
        # Animation sequence
{animation_sequence_code}
        
        # Hold final frame
        self.wait(1.0)
    
    def _get_grid_positions(self):
        """Grid-aligned positions for deterministic layout."""
        fw = config.frame_width
        fh = config.frame_height
        return {{
            "top_left": np.array([-fw*0.3, fh*0.35, 0]),
            "top_center": np.array([0, fh*0.35, 0]),
            "top_right": np.array([fw*0.3, fh*0.35, 0]),
            "center_left": np.array([-fw*0.3, 0, 0]),
            "center": np.array([0, 0, 0]),
            "center_right": np.array([fw*0.3, 0, 0]),
            "bottom_left": np.array([-fw*0.3, -fh*0.35, 0]),
            "bottom_center": np.array([0, -fh*0.35, 0]),
            "bottom_right": np.array([fw*0.3, -fh*0.35, 0]),
            # Simplified aliases (LLM often uses these)
            "top": np.array([0, fh*0.35, 0]),
            "bottom": np.array([0, -fh*0.35, 0]),
            "left": np.array([-fw*0.3, 0, 0]),
            "right": np.array([fw*0.3, 0, 0]),
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
    
    ElementType.LABEL: '''elements["{id}"] = Text("{label}", font_size=18, color={color})
        if elements["{id}"].width > config.frame_width * 0.45:
            elements["{id}"].scale_to_fit_width(config.frame_width * 0.45)
        elements["{id}"].move_to(positions["{position}"])''',
    
    ElementType.TITLE: '''elements["{id}"] = Text("{label}", font_size=36, color={color}, weight=BOLD)
        if elements["{id}"].width > config.frame_width * 0.65:
            elements["{id}"].scale_to_fit_width(config.frame_width * 0.65)
        elements["{id}"].move_to(positions["{position}"])''',
    
    ElementType.CIRCLE: '''elements["{id}"] = Circle(radius={radius}, color={color}, fill_opacity=0.7)
        elements["{id}"].move_to(positions["{position}"])''',
    
    ElementType.RECTANGLE: '''elements["{id}"] = Rectangle(width={width}, height={height}, color={color}, fill_opacity=0.6, stroke_width=3)
        elements["{id}"].move_to(positions["{position}"])''',
}


# =============================================================================
# ANIMATION TEMPLATES
# =============================================================================

ANIMATION_TEMPLATES = {
    # Core animations
    TransformAction.APPEAR: '''self.play(GrowFromCenter(elements["{target}"]), run_time={run_time})
        self.play(Flash(elements["{target}"], color=YELLOW, flash_radius=0.3), run_time=0.2)''',
    
    TransformAction.DISAPPEAR: 'self.play(ShrinkToCenter(elements["{target}"]), run_time={run_time})',
    
    TransformAction.MOVE: '''self.play(
            elements["{target}"].animate.move_to(
                elements["{relative_to}"].get_center() if "{relative_to}" in elements else positions["{to_position}"]
            ),
            run_time={run_time}
        )''',
    
    TransformAction.TRANSFORM: '''self.play(
            ReplacementTransform(elements["{target}"], elements["{to_element}"]),
            run_time={run_time}
        )''',
    
    TransformAction.HIGHLIGHT: '''self.play(
            Circumscribe(elements["{target}"], color=YELLOW, time_width=2),
            run_time={run_time}
        )''',
    
    TransformAction.PULSE: '''self.play(
            Flash(elements["{target}"], color=GOLD, flash_radius=0.5),
            run_time={run_time}
        )
        self.play(Indicate(elements["{target}"], color=WHITE, scale_factor=1.15), run_time=0.3)''',
    
    TransformAction.SCALE: '''self.play(
            elements["{target}"].animate.scale({scale_factor}),
            run_time={run_time}
        )''',
    
    # LLM-friendly alias animations
    TransformAction.SLIDE_IN: 'self.play(FadeIn(elements["{target}"], shift=LEFT), run_time={run_time})',
    
    TransformAction.FADE_IN: 'self.play(FadeIn(elements["{target}"]), run_time={run_time})',
    
    TransformAction.FADE_OUT: 'self.play(FadeOut(elements["{target}"]), run_time={run_time})',
    
    TransformAction.GROW_FROM_CENTER: '''self.play(GrowFromCenter(elements["{target}"]), run_time={run_time})
        self.play(Flash(elements["{target}"], color=YELLOW, flash_radius=0.3), run_time=0.2)''',
    
    TransformAction.SHRINK: 'self.play(ShrinkToCenter(elements["{target}"]), run_time={run_time})',
    
    TransformAction.ZOOM: '''self.play(
            elements["{target}"].animate.scale({scale_factor}),
            run_time={run_time}
        )''',
    
    TransformAction.SPIN: '''self.play(
            Rotate(elements["{target}"], angle=2*PI),
            run_time={run_time}
        )''',
    
    TransformAction.BOUNCE: '''self.play(
            elements["{target}"].animate.shift(UP*0.3),
            run_time={run_time}/2
        )
        self.play(
            elements["{target}"].animate.shift(DOWN*0.3),
            run_time={run_time}/2
        )''',
    
    TransformAction.WIGGLE: '''self.play(
            Wiggle(elements["{target}"]),
            run_time={run_time}
        )''',
    
    # Additional LLM-friendly aliases
    TransformAction.ZOOM_IN: '''self.play(
            elements["{target}"].animate.scale(1.3),
            run_time={run_time}
        )''',
    
    TransformAction.ZOOM_OUT: '''self.play(
            elements["{target}"].animate.scale(0.7),
            run_time={run_time}
        )''',
    
    TransformAction.FLASH: '''self.play(
            Flash(elements["{target}"], color=GOLD, flash_radius=0.5),
            run_time={run_time}
        )''',
    
    TransformAction.ENTER: '''self.play(GrowFromCenter(elements["{target}"]), run_time={run_time})
        self.play(Flash(elements["{target}"], color=YELLOW, flash_radius=0.3), run_time=0.2)''',
    
    TransformAction.EXIT: 'self.play(ShrinkToCenter(elements["{target}"]), run_time={run_time})',
    
    TransformAction.EMPHASIZE: '''self.play(
            Indicate(elements["{target}"], color=YELLOW, scale_factor=1.2),
            run_time={run_time}
        )''',
    
    TransformAction.FOCUS: '''self.play(
            Circumscribe(elements["{target}"], color=WHITE, time_width=2),
            run_time={run_time}
        )''',
    
    TransformAction.GLOW: '''self.play(
            Flash(elements["{target}"], color=YELLOW, flash_radius=0.6),
            run_time={run_time}
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
    default_run_time: float = 0.6
    pause_between_animations: float = 0.3
    element_size_map: Dict[str, float] = None
    
    def __post_init__(self):
        if self.element_size_map is None:
            self.element_size_map = {
                "small": 0.35,
                "medium": 0.5,
                "large": 0.8,
            }
    
    def get_frame_dimensions(self) -> tuple:
        """Get frame width and height for current aspect ratio."""
        dims = ASPECT_RATIO_DIMENSIONS.get(self.aspect_ratio, ASPECT_RATIO_DIMENSIONS["9:16"])
        return dims["frame_width"], dims["frame_height"]
    
    def get_element_size_for_aspect(self, size_name: str) -> dict:
        """Get element dimensions scaled for aspect ratio."""
        base_size = self.element_size_map.get(size_name, 0.5)
        fw, fh = self.get_frame_dimensions()
        
        # Scale based on minimum frame dimension to keep elements proportional
        min_dim = min(fw, fh)
        scale_factor = min_dim / 9  # Normalize to 9:16 base
        
        scaled_size = base_size * scale_factor
        
        return {
            "size": scaled_size,
            "radius": scaled_size,
            "width": min(scaled_size * 3, fw * 0.4),   # Max 40% of frame width
            "height": min(scaled_size * 2.5, fh * 0.3),  # Max 30% of frame height
        }


class ManimCodeGenerator:
    """
    Generates Manim code from validated scene specifications.
    
    The code is constrained by:
    1. Only using defined primitives
    2. Grid-aligned positioning
    3. Specification-defined animation sequence
    """
    
    def __init__(self, config: GeneratorConfig = None):
        self.config = config or GeneratorConfig()
    
    def generate_scene_code(
        self,
        spec: SceneSpecification,
        scene_index: int = 0
    ) -> str:
        """Generate complete Manim code for a scene specification."""
        
        # Generate element creation code
        element_code = self._generate_element_code(spec)
        
        # Generate animation sequence code
        animation_code = self._generate_animation_code(spec)
        
        # Build complete scene
        class_name = f"Segment{scene_index:03d}"
        
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
        )
        
        return code
    
    def _generate_element_code(self, spec: SceneSpecification) -> str:
        """Generate code to create all visual elements."""
        lines = []
        
        for elem in spec.visual_metaphor.visual_elements:
            template = ELEMENT_TEMPLATES.get(elem.element_type)
            
            if not template:
                # Fallback to basic node
                template = ELEMENT_TEMPLATES[ElementType.NODE]
            
            # Prepare template parameters with aspect-ratio-aware sizing
            size_dims = self.config.get_element_size_for_aspect(elem.size)
            position = elem.position.value if elem.position else "center"
            
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
        
    def _estimate_beat_times(
        self,
        narration: str,
        beats: list,
        total_duration: float
    ) -> list:
        """
        Estimate when each semantic beat occurs in the narration.
        
        Returns list of (beat, start_time, duration) tuples.
        """
        if not narration or not beats:
            return []
        
        # Calculate words per second (average speaking rate: ~150 WPM = 2.5 WPS)
        words = narration.split()
        total_words = len(words)
        if total_words == 0:
            return []
        
        words_per_second = total_words / total_duration
        
        beat_timings = []
        
        for beat in beats:
            beat_phrase = beat.beat_phrase.lower()
            narration_lower = narration.lower()
            
            # Find phrase position in narration
            phrase_start = narration_lower.find(beat_phrase)
            
            if phrase_start == -1:
                # Phrase not found - estimate from beat order
                beat_index = beats.index(beat)
                start_time = (beat_index / max(1, len(beats))) * total_duration
            else:
                # Calculate word position of phrase
                words_before = len(narration[:phrase_start].split())
                start_time = words_before / words_per_second
            
            # Clamp to valid range
            start_time = max(0.0, min(start_time, total_duration - 1.0))
            
            # Duration based on phrase length (minimum 0.8s)
            phrase_words = len(beat_phrase.split())
            duration = max(0.8, phrase_words / words_per_second)
            
            beat_timings.append((beat, start_time, duration))
        
        # Sort by start time
        beat_timings.sort(key=lambda x: x[1])
        
        return beat_timings
    
    def _generate_animation_code(self, spec: SceneSpecification) -> str:
        """
        Generate NARRATION-SYNCED animation code.
        
        Animations are timed to when their associated phrases are spoken,
        creating a dynamic, engaging experience where visuals match audio.
        """
        lines = []
        
        # Get all element IDs and their elements
        elements = {elem.id: elem for elem in spec.visual_metaphor.visual_elements}
        element_ids = list(elements.keys())
        
        # Get timing info
        audio_duration = spec.timing.audio_duration_seconds or 10.0
        num_elements = max(1, len(element_ids))
        
        # Get semantic beats for narration sync
        beats = spec.narration.semantic_beats if spec.narration else []
        beat_timings = self._estimate_beat_times(
            narration=spec.narration.text if spec.narration else "",
            beats=beats,
            total_duration=audio_duration
        )
        
        # Track which elements have been introduced
        introduced_elements = set()
        current_time = 0.0
        
        # ============================================
        # INTRO: Quick entry of first elements
        # ============================================
        lines.append("# Quick Intro - First elements appear")
        intro_time = min(1.5, audio_duration * 0.1)
        
        # Introduce first 1-2 elements immediately for visual impact
        intro_elements = element_ids[:min(2, len(element_ids))]
        for elem_id in intro_elements:
            lines.append(f'self.play(GrowFromCenter(elements["{elem_id}"]), run_time={intro_time:.2f})')
            introduced_elements.add(elem_id)
        
        current_time = intro_time * len(intro_elements)
        
        # ============================================
        # BEAT-SYNCED: Animate on narration cues
        # ============================================
        if beat_timings:
            lines.append("")
            lines.append("# Beat-Synced Animations (timed to narration)")
            
            for beat, beat_start, beat_duration in beat_timings:
                target_elems = beat.target_elements
                
                if not target_elems:
                    continue
                
                # Calculate wait time to sync with narration
                wait_time = max(0.0, beat_start - current_time)
                
                if wait_time > 0.1:
                    lines.append(f'self.wait({wait_time:.2f})  # Wait for: "{beat.beat_phrase[:30]}..."')
                    current_time += wait_time
                
                # Animate each target element
                for elem_id in target_elems:
                    if elem_id not in elements:
                        continue
                    
                    if elem_id not in introduced_elements:
                        # First appearance - dramatic entry
                        lines.append(f'# "{beat.beat_phrase[:25]}..." → {elem_id} appears')
                        lines.append(f'self.play(FadeIn(elements["{elem_id}"], shift=UP*0.3), run_time={beat_duration:.2f})')
                        lines.append(f'self.play(Flash(elements["{elem_id}"], color=YELLOW, flash_radius=0.3), run_time=0.2)')
                        introduced_elements.add(elem_id)
                    else:
                        # Already visible - emphasis animation
                        lines.append(f'# "{beat.beat_phrase[:25]}..." → emphasize {elem_id}')
                        lines.append(f'self.play(Indicate(elements["{elem_id}"], color=GOLD, scale_factor=1.15), run_time={beat_duration:.2f})')
                
                current_time += beat_duration
        
        # ============================================
        # FALLBACK: If no beats, use generic animations
        # ============================================
        remaining_elements = [e for e in element_ids if e not in introduced_elements]
        
        if remaining_elements:
            lines.append("")
            lines.append("# Remaining elements")
            
            remaining_time = max(1.0, (audio_duration - current_time) * 0.5)
            time_per_elem = max(0.8, remaining_time / len(remaining_elements))
            
            for elem_id in remaining_elements:
                lines.append(f'self.play(FadeIn(elements["{elem_id}"]), run_time={time_per_elem:.2f})')
                introduced_elements.add(elem_id)
                current_time += time_per_elem
        
        # ============================================
        # HOLD & EXIT: End sequence
        # ============================================
        lines.append("")
        lines.append("# Hold for final moments")
        
        hold_time = max(0.5, audio_duration - current_time - 1.0)
        if hold_time > 0.3:
            lines.append(f'self.wait({hold_time:.2f})')
        
        # Quick exit animation
        lines.append("")
        lines.append("# Exit sequence")
        exit_time = min(0.8, max(0.3, (audio_duration - current_time) / num_elements))
        
        for elem_id in element_ids:
            lines.append(f'self.play(FadeOut(elements["{elem_id}"], shift=DOWN*0.2), run_time={exit_time:.2f})')
        
        return "\n".join(f"        {line}" for line in lines)
    
    def generate_all_scenes(
        self,
        specs: List[SceneSpecification]
    ) -> List[str]:
        """Generate code for all scenes."""
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
        if code.count("Text(") > 3:
            issues.append(f"Too many Text objects ({code.count('Text(')})")
        
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
