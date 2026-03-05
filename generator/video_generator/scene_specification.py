"""
Scene Specification System for High-Quality Manim Video Generation
===================================================================

This module defines the structured scene specification format that enforces:
- One idea per scene
- Maximum object counts
- Visual metaphor mapping
- Semantic beat synchronization

Every scene MUST be defined by a validated specification BEFORE code generation.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Literal
from enum import Enum
import json


# =============================================================================
# ENUMS: Constrained Vocabularies
# =============================================================================

class MetaphorType(str, Enum):
    """Abstract-to-concrete metaphor families."""
    PROCESS_FLOW = "process_flow"        # Arrows, pipelines, conveyor belts
    CONTAINER = "container"               # Boxes, boundaries, nested frames
    TRANSFORMATION = "transformation"     # Morphing shapes, before/after
    RELATIONSHIP = "relationship"         # Lines, connections, graphs
    STATE = "state"                       # Color changes, toggles
    QUANTITY = "quantity"                 # Stacks, grids, counters
    COMPARISON = "comparison"             # Side-by-side, scales
    HIERARCHY = "hierarchy"               # Trees, layers, pyramids


class ElementType(str, Enum):
    """Visual element primitive types."""
    # Containers
    BOUNDARY_BOX = "boundary_box"
    ROUNDED_RECTANGLE = "rounded_rectangle"
    CIRCLE_CONTAINER = "circle_container"
    
    # Flow elements
    ARROW = "arrow"
    CURVED_ARROW = "curved_arrow"
    FLOW_LINE = "flow_line"
    
    # Entities
    DATA_PACKET = "data_packet"
    NODE = "node"
    ICON = "icon"
    
    # Text (strictly labels only)
    LABEL = "label"
    TITLE = "title"
    TEXT = "text"  # Alias for label (LLM often uses this)
    
    # Shapes
    CIRCLE = "circle"
    RECTANGLE = "rectangle"
    TRIANGLE = "triangle"
    
    # Special
    CHECKPOINT = "checkpoint"
    GATE = "gate"
    LOCK = "lock"
    
    # Modern primitives (engagement-optimized)
    GLASS_CARD = "glass_card"
    CODE_BLOCK = "code_block"
    ICON_BADGE = "icon_badge"
    TAG_PILL = "tag_pill"
    PROGRESS_BAR = "progress_bar"
    # v0.19.0 enriched primitives
    STAR_BADGE = "star_badge"                # Star-shaped emphasis marker
    CURVED_ARROW_ELEM = "curved_arrow_elem"  # Curved connection arrow
    DASHED_LINE_ELEM = "dashed_line_elem"    # Dashed connection line
    BRACE_ANNOTATION = "brace_annotation"    # Curly brace with label
    ANNULUS_RING = "annulus_ring"             # Ring shape for cycles/states
    SECTOR_CHART = "sector_chart"            # Pie-slice sector


class TransformAction(str, Enum):
    """Allowed transformation actions."""
    # Core actions
    APPEAR = "appear"           # Element enters scene
    DISAPPEAR = "disappear"     # Element exits scene
    MOVE = "move"               # Element changes position
    TRANSFORM = "transform"     # Element morphs into another
    HIGHLIGHT = "highlight"     # Element gets emphasis
    PULSE = "pulse"             # Element pulses/flashes
    SCALE = "scale"             # Element grows/shrinks
    CONNECT = "connect"         # Line appears connecting elements
    FLOW = "flow"               # Motion along a path
    # LLM-friendly aliases (common generation patterns)
    SLIDE_IN = "slide_in"       # Alias for appear with slide
    FADE_IN = "fade_in"         # Alias for appear
    FADE_OUT = "fade_out"       # Alias for disappear
    GROW_FROM_CENTER = "grow_from_center"  # Alias for appear
    SHRINK = "shrink"           # Alias for scale down
    ZOOM = "zoom"               # Alias for scale
    ZOOM_IN = "zoom_in"         # Scale up
    ZOOM_OUT = "zoom_out"       # Scale down / exit
    SPIN = "spin"               # Rotation effect
    BOUNCE = "bounce"           # Bounce animation
    WIGGLE = "wiggle"           # Wiggle effect
    FLASH = "flash"             # Flash emphasis
    ENTER = "enter"             # Alias for appear
    EXIT = "exit"               # Alias for disappear
    EMPHASIZE = "emphasize"     # Alias for highlight
    FOCUS = "focus"             # Alias for highlight
    GLOW = "glow"               # Glow effect
    # Directional entries
    SLIDE_IN_FROM_LEFT = "slide_in_from_left"
    SLIDE_IN_FROM_RIGHT = "slide_in_from_right"
    SLIDE_IN_FROM_TOP = "slide_in_from_top"
    SLIDE_IN_FROM_BOTTOM = "slide_in_from_bottom"
    # Drawing / emphasis extras
    DRAW_BORDER_THEN_FILL = "draw_border_then_fill"
    DRAW_ARROW = "draw_arrow"
    CIRCUMSCRIBE = "circumscribe"
    # v0.19.0 enriched animations
    WRITE = "write"                          # Progressive stroke reveal
    APPLY_WAVE = "apply_wave"                # Wave distortion emphasis
    CIRCLE_INDICATE = "circle_indicate"      # Circle drawn around element
    SURROUND = "surround"                    # SurroundingRectangle highlight
    GROW_FROM_POINT = "grow_from_point"      # Grow from specific point
    FADE_TRANSFORM = "fade_transform"        # Smooth morph between elements
    SHOW_PASSING_FLASH = "show_passing_flash" # Flash along element border
    WAVE = "wave"                            # Alias for apply_wave
    RIPPLE = "ripple"                        # Alias for apply_wave
    TRACE = "trace"                          # Alias for write
    MORPH = "morph"                          # Alias for fade_transform


class Position(str, Enum):
    """Grid-aligned positions for deterministic layouts."""
    # 3x3 primary grid
    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    CENTER_LEFT = "center_left"
    CENTER = "center"
    CENTER_RIGHT = "center_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_RIGHT = "bottom_right"
    # 5-row extended grid (upper/lower mid rows)
    UPPER_LEFT = "upper_left"
    UPPER_CENTER = "upper_center"
    UPPER_RIGHT = "upper_right"
    LOWER_LEFT = "lower_left"
    LOWER_CENTER = "lower_center"
    LOWER_RIGHT = "lower_right"
    # Relative positions
    LEFT_OF = "left_of"
    RIGHT_OF = "right_of"
    ABOVE = "above"
    BELOW = "below"
    # Simplified aliases (LLM often uses these)
    TOP = "top"           # Maps to top_center
    BOTTOM = "bottom"     # Maps to bottom_center  
    LEFT = "left"         # Maps to center_left
    RIGHT = "right"       # Maps to center_right


class TextRole(str, Enum):
    """Strict text usage roles - NO paragraphs allowed."""
    LABEL = "label"     # 1-3 words, identifies an element
    TITLE = "title"     # 3-6 words, scene heading


# =============================================================================
# DATA CLASSES: Scene Specification Structure
# =============================================================================

@dataclass
class VisualElement:
    """A single visual element in the scene."""
    id: str                                     # Unique identifier for referencing
    element_type: ElementType                   # Type from constrained vocabulary
    label: Optional[str] = None                 # Max 4 words
    color: str = "BLUE"                         # From allowed palette
    position: Optional[Position] = None         # Grid position
    relative_to: Optional[str] = None           # ID of element for relative positioning
    size: str = "medium"                        # small, medium, large
    
    def validate(self) -> List[str]:
        """Validate this element against constraints."""
        errors = []
        
        # NOTE: Word count limit removed - labels can be any length
        
        # Color validation
        allowed_colors = {"BLUE", "RED", "GREEN", "YELLOW", "WHITE", "ORANGE", 
                         "PINK", "PURPLE", "TEAL", "GOLD", "MAROON", "GRAY"}
        if self.color.upper() not in allowed_colors:
            errors.append(f"Element '{self.id}': color '{self.color}' not in allowed palette")
        
        return errors


@dataclass
class TransformationStep:
    """A single step in the scene's transformation sequence."""
    action: TransformAction
    target: str                                 # Element ID
    to_position: Optional[Position] = None      # For MOVE action
    to_element: Optional[str] = None            # For TRANSFORM action (target element ID)
    relative_to: Optional[str] = None           # For relative positioning
    duration_weight: float = 1.0                # Relative timing weight
    
    def validate(self, element_ids: set) -> List[str]:
        """Validate this step against available elements."""
        errors = []
        
        if self.target != "all" and self.target not in element_ids:
            errors.append(f"Transformation target '{self.target}' not found in elements")
        
        if self.action == TransformAction.TRANSFORM and self.to_element:
            if self.to_element not in element_ids:
                errors.append(f"Transform target element '{self.to_element}' not found")
        
        if self.action == TransformAction.MOVE and not self.to_position and not self.relative_to:
            errors.append(f"MOVE action for '{self.target}' requires to_position or relative_to")
        
        return errors


@dataclass
class SemanticBeat:
    """Maps a narration phrase to a visual synchronization point."""
    beat_phrase: str                            # Key phrase from narration
    visual_sync: str                            # Description of what happens visually
    target_elements: List[str] = field(default_factory=list)  # Element IDs involved
    
    def validate(self, element_ids: set) -> List[str]:
        """Validate beat against available elements."""
        errors = []
        
        for elem_id in self.target_elements:
            if elem_id not in element_ids:
                errors.append(f"Beat '{self.beat_phrase}': element '{elem_id}' not found")
        
        if not self.visual_sync:
            errors.append(f"Beat '{self.beat_phrase}': missing visual_sync description")
        
        return errors


@dataclass
class Concept:
    """The single pedagogical concept for this scene."""
    idea: str                                   # Single sentence, no conjunctions
    pedagogical_goal: str                       # What viewer should understand
    prerequisite_concepts: List[str] = field(default_factory=list)
    
    def validate(self) -> List[str]:
        """Validate concept constraints."""
        errors = []
        
        # Check for multiple concepts (simple heuristic)
        conjunctions = [" and ", " also ", " additionally ", " furthermore "]
        idea_lower = self.idea.lower()
        
        for conj in conjunctions:
            if conj in idea_lower:
                # Check if it's genuinely two concepts
                parts = idea_lower.split(conj)
                if len(parts) >= 2 and len(parts[0].split()) > 3 and len(parts[1].split()) > 3:
                    errors.append(f"Concept may contain multiple ideas: '{self.idea}'")
                    break
        
        # Length check
        if len(self.idea.split()) > 20:
            errors.append(f"Concept idea too long ({len(self.idea.split())} words, max 20)")
        
        return errors


@dataclass  
class VisualMetaphor:
    """Maps abstract concept to concrete visual representation."""
    abstract_concept: str                       # What we're representing
    concrete_representation: str                # What we show
    metaphor_type: MetaphorType
    visual_elements: List[VisualElement] = field(default_factory=list)
    
    def validate(self) -> List[str]:
        """Validate metaphor constraints."""
        errors = []
        
        # Element count check - allow up to 12 for complex scenes
        if len(self.visual_elements) > 12:
            errors.append(f"Too many visual elements: {len(self.visual_elements)} (max 12)")
        
        # Validate each element
        for elem in self.visual_elements:
            errors.extend(elem.validate())
        
        return errors
    
    def get_element_ids(self) -> set:
        """Get all element IDs for reference validation."""
        return {elem.id for elem in self.visual_elements}


@dataclass
class Transformation:
    """The sequence of visual changes in the scene."""
    transformation_type: str                    # e.g., "demonstrate_process", "show_comparison"
    sequence: List[TransformationStep] = field(default_factory=list)
    
    def validate(self, element_ids: set) -> List[str]:
        """Validate transformation sequence."""
        errors = []
        
        # Sequence length check
        if len(self.sequence) > 12:
            errors.append(f"Too many transformation steps: {len(self.sequence)} (max 12)")
        
        # Validate each step
        for step in self.sequence:
            errors.extend(step.validate(element_ids))
        
        return errors


@dataclass
class Constraints:
    """Hard constraints for this scene."""
    max_objects: int = 8
    max_text_elements: int = 5
    text_role: TextRole = TextRole.LABEL
    grid_alignment: bool = True
    allow_decorative_animation: bool = True


@dataclass
class Narration:
    """Narration with semantic beat mapping."""
    text: str                                   # The spoken narration
    semantic_beats: List[SemanticBeat] = field(default_factory=list)
    
    def validate(self, element_ids: set) -> List[str]:
        """Validate narration and beat mappings."""
        errors = []
        
        # Check each beat
        for beat in self.semantic_beats:
            errors.extend(beat.validate(element_ids))
        
        # Check for orphan narration (narration without any beats)
        if not self.semantic_beats:
            errors.append("Narration has no semantic beats defined")
        
        return errors


@dataclass
class Timing:
    """Timing information for the scene."""
    cognitive_duration_estimate_seconds: float  # Estimated time to understand
    audio_duration_seconds: Optional[float] = None  # Filled after TTS
    beat_timings: Optional[Dict[str, float]] = None  # Filled after beat extraction


# =============================================================================
# MAIN SCENE SPECIFICATION CLASS
# =============================================================================

@dataclass
class SceneSpecification:
    """
    Complete specification for a single scene.
    
    This is the authoritative source for what should be generated.
    Manim code generation is CONSTRAINED by this specification.
    """
    scene_id: str
    scene_type: str  # INTRO, CONTENT, OUTRO — used by VisualDirector for pacing
    concept: Concept
    visual_metaphor: VisualMetaphor
    transformation: Transformation
    constraints: Constraints
    narration: Narration
    timing: Timing
    
    def validate(self) -> tuple[bool, List[str]]:
        """
        Validate the entire scene specification.
        Returns (is_valid, list_of_errors).
        """
        errors = []
        
        # Validate concept
        errors.extend(self.concept.validate())
        
        # Validate visual metaphor
        errors.extend(self.visual_metaphor.validate())
        
        # Get element IDs for reference checking
        element_ids = self.visual_metaphor.get_element_ids()
        
        # Validate transformation
        errors.extend(self.transformation.validate(element_ids))
        
        # Validate narration
        errors.extend(self.narration.validate(element_ids))
        
        # Cross-validation: element count vs constraints
        if len(self.visual_metaphor.visual_elements) > self.constraints.max_objects:
            errors.append(
                f"Element count ({len(self.visual_metaphor.visual_elements)}) "
                f"exceeds max_objects constraint ({self.constraints.max_objects})"
            )
        
        # Count text elements
        text_elements = [
            e for e in self.visual_metaphor.visual_elements 
            if e.element_type in {ElementType.LABEL, ElementType.TITLE}
        ]
        if len(text_elements) > self.constraints.max_text_elements:
            errors.append(
                f"Text element count ({len(text_elements)}) "
                f"exceeds max_text_elements constraint ({self.constraints.max_text_elements})"
            )
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "scene_id": self.scene_id,
            "type": self.scene_type,
            "concept": {
                "idea": self.concept.idea,
                "pedagogical_goal": self.concept.pedagogical_goal,
                "prerequisite_concepts": self.concept.prerequisite_concepts
            },
            "visual_metaphor": {
                "abstract_concept": self.visual_metaphor.abstract_concept,
                "concrete_representation": self.visual_metaphor.concrete_representation,
                "metaphor_type": self.visual_metaphor.metaphor_type.value,
                "visual_elements": [
                    {
                        "id": e.id,
                        "element_type": e.element_type.value,
                        "label": e.label,
                        "color": e.color,
                        "position": e.position.value if e.position else None,
                        "relative_to": e.relative_to,
                        "size": e.size
                    }
                    for e in self.visual_metaphor.visual_elements
                ]
            },
            "transformation": {
                "type": self.transformation.transformation_type,
                "sequence": [
                    {
                        "action": s.action.value,
                        "target": s.target,
                        "to_position": s.to_position.value if s.to_position else None,
                        "to_element": s.to_element,
                        "relative_to": s.relative_to,
                        "duration_weight": s.duration_weight
                    }
                    for s in self.transformation.sequence
                ]
            },
            "constraints": {
                "max_objects": self.constraints.max_objects,
                "max_text_elements": self.constraints.max_text_elements,
                "text_role": self.constraints.text_role.value,
                "grid_alignment": self.constraints.grid_alignment
            },
            "narration": {
                "text": self.narration.text,
                "semantic_beats": [
                    {
                        "beat_phrase": b.beat_phrase,
                        "visual_sync": b.visual_sync,
                        "target_elements": b.target_elements
                    }
                    for b in self.narration.semantic_beats
                ]
            },
            "timing": {
                "cognitive_duration_estimate_seconds": self.timing.cognitive_duration_estimate_seconds,
                "audio_duration_seconds": self.timing.audio_duration_seconds,
                "beat_timings": self.timing.beat_timings
            }
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SceneSpecification":
        """Create SceneSpecification from dictionary."""
        # Parse visual elements
        visual_elements = [
            VisualElement(
                id=e["id"],
                element_type=ElementType(e["element_type"]),
                label=e.get("label"),
                color=e.get("color", "BLUE"),
                position=Position(e["position"]) if e.get("position") else None,
                relative_to=e.get("relative_to"),
                size=e.get("size", "medium")
            )
            for e in data["visual_metaphor"]["visual_elements"]
        ]
        
        # Parse transformation steps
        transformation_steps = [
            TransformationStep(
                action=TransformAction(s["action"]),
                target=s["target"],
                to_position=Position(s["to_position"]) if s.get("to_position") else None,
                to_element=s.get("to_element"),
                relative_to=s.get("relative_to"),
                duration_weight=s.get("duration_weight", 1.0)
            )
            for s in data["transformation"]["sequence"]
        ]
        
        # Parse semantic beats
        semantic_beats = [
            SemanticBeat(
                beat_phrase=b["beat_phrase"],
                visual_sync=b["visual_sync"],
                target_elements=b.get("target_elements", [])
            )
            for b in data["narration"]["semantic_beats"]
        ]
        
        return cls(
            scene_id=data["scene_id"],
            scene_type=data.get("type", "CONTENT").upper(),
            concept=Concept(
                idea=data["concept"]["idea"],
                pedagogical_goal=data["concept"]["pedagogical_goal"],
                prerequisite_concepts=data["concept"].get("prerequisite_concepts", [])
            ),
            visual_metaphor=VisualMetaphor(
                abstract_concept=data["visual_metaphor"]["abstract_concept"],
                concrete_representation=data["visual_metaphor"]["concrete_representation"],
                metaphor_type=MetaphorType(data["visual_metaphor"]["metaphor_type"]),
                visual_elements=visual_elements
            ),
            transformation=Transformation(
                transformation_type=data["transformation"]["type"],
                sequence=transformation_steps
            ),
            constraints=Constraints(
                max_objects=data["constraints"].get("max_objects", 4),
                max_text_elements=data["constraints"].get("max_text_elements", 2),
                text_role=TextRole(data["constraints"].get("text_role", "label")),
                grid_alignment=data["constraints"].get("grid_alignment", True)
            ),
            narration=Narration(
                text=data["narration"]["text"],
                semantic_beats=semantic_beats
            ),
            timing=Timing(
                cognitive_duration_estimate_seconds=data["timing"]["cognitive_duration_estimate_seconds"],
                audio_duration_seconds=data["timing"].get("audio_duration_seconds"),
                beat_timings=data["timing"].get("beat_timings")
            )
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> "SceneSpecification":
        """Create SceneSpecification from JSON string."""
        return cls.from_dict(json.loads(json_str))


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

def create_example_zero_trust_scene() -> SceneSpecification:
    """Example: Create a scene specification for Zero Trust concept."""
    return SceneSpecification(
        scene_id="scene_001_zero_trust_verification",
        scene_type="CONTENT",
        concept=Concept(
            idea="Zero Trust verifies every access request regardless of origin",
            pedagogical_goal="Understand that location doesn't grant trust",
            prerequisite_concepts=["network perimeter", "authentication"]
        ),
        visual_metaphor=VisualMetaphor(
            abstract_concept="trust verification",
            concrete_representation="checkpoint that inspects all traffic equally",
            metaphor_type=MetaphorType.PROCESS_FLOW,
            visual_elements=[
                VisualElement(
                    id="boundary",
                    element_type=ElementType.BOUNDARY_BOX,
                    label="Network",
                    color="BLUE",
                    position=Position.CENTER,
                    size="large"
                ),
                VisualElement(
                    id="checkpoint",
                    element_type=ElementType.CHECKPOINT,
                    label="Verify",
                    color="GOLD",
                    position=Position.LEFT_OF,
                    relative_to="boundary"
                ),
                VisualElement(
                    id="internal_request",
                    element_type=ElementType.DATA_PACKET,
                    label="Int",
                    color="GREEN",
                    position=Position.CENTER_LEFT
                ),
                VisualElement(
                    id="external_request", 
                    element_type=ElementType.DATA_PACKET,
                    label="Ext",
                    color="RED",
                    position=Position.BOTTOM_LEFT
                )
            ]
        ),
        transformation=Transformation(
            transformation_type="demonstrate_equal_treatment",
            sequence=[
                TransformationStep(action=TransformAction.APPEAR, target="boundary"),
                TransformationStep(action=TransformAction.APPEAR, target="checkpoint"),
                TransformationStep(action=TransformAction.APPEAR, target="internal_request"),
                TransformationStep(
                    action=TransformAction.MOVE, 
                    target="internal_request",
                    relative_to="checkpoint"
                ),
                TransformationStep(action=TransformAction.HIGHLIGHT, target="checkpoint"),
                TransformationStep(action=TransformAction.APPEAR, target="external_request"),
            ]
        ),
        constraints=Constraints(
            max_objects=4,
            max_text_elements=2,
            text_role=TextRole.LABEL,
            grid_alignment=True
        ),
        narration=Narration(
            text="Zero Trust architecture verifies every request, whether it comes from inside or outside the network.",
            semantic_beats=[
                SemanticBeat(
                    beat_phrase="Zero Trust architecture",
                    visual_sync="Boundary and checkpoint appear",
                    target_elements=["boundary", "checkpoint"]
                ),
                SemanticBeat(
                    beat_phrase="verifies every request",
                    visual_sync="Checkpoint highlights as request passes",
                    target_elements=["checkpoint", "internal_request"]
                ),
                SemanticBeat(
                    beat_phrase="inside or outside",
                    visual_sync="Both internal and external requests shown",
                    target_elements=["internal_request", "external_request"]
                )
            ]
        ),
        timing=Timing(
            cognitive_duration_estimate_seconds=8.0
        )
    )


if __name__ == "__main__":
    # Demo: Create and validate example scene
    scene = create_example_zero_trust_scene()
    
    is_valid, errors = scene.validate()
    print(f"Scene valid: {is_valid}")
    if errors:
        print("Errors:")
        for error in errors:
            print(f"  - {error}")
    
    print("\nJSON Output:")
    print(scene.to_json())
