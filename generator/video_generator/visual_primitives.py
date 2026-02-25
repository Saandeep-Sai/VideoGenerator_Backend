"""
Visual Primitive Library for Manim
==================================

A fixed set of reusable, consistently-styled Manim components that enforce:
- Deterministic layouts (grid-aligned positions)
- Consistent styling (colors, fonts, sizing)
- Constrained object counts
- Professional educational aesthetics

These primitives are the ONLY visual elements that should be used in generated scenes.
"""

from manim import *
from typing import Optional, Tuple, List
from enum import Enum


# =============================================================================
# CONFIGURATION: Consistent Styling
# =============================================================================

class PrimitiveConfig:
    """Global configuration for all primitives."""
    
    # Colors - Professional palette
    COLORS = {
        # Semantic colors
        "primary": BLUE,
        "secondary": TEAL,
        "accent": GOLD,
        "success": GREEN,
        "warning": ORANGE,
        "danger": RED,
        "neutral": GRAY,
        "highlight": YELLOW,
        "text": WHITE,
        "muted": GRAY_B,
        # Direct Manim colors (allowed palette)
        "BLUE": BLUE,
        "RED": RED,
        "GREEN": GREEN,
        "YELLOW": YELLOW,
        "WHITE": WHITE,
        "ORANGE": ORANGE,
        "PINK": PINK,
        "PURPLE": PURPLE,
        "TEAL": TEAL,
        "GOLD": GOLD,
        "MAROON": MAROON,
        "GRAY": GRAY,
    }
    
    # Typography
    FONT_SIZES = {
        "title": 36,
        "heading": 28,
        "body": 22,
        "label": 18,
        "small": 14,
    }
    
    # Sizing
    SIZES = {
        "small": 0.5,
        "medium": 1.0,
        "large": 1.5,
        "xlarge": 2.0,
    }
    
    # Spacing
    SPACING = {
        "tight": 0.3,
        "normal": 0.5,
        "relaxed": 0.8,
        "loose": 1.2,
    }
    
    # Animation defaults
    ANIMATION = {
        "fast": 0.3,
        "normal": 0.5,
        "slow": 0.8,
        "emphasis": 1.0,
    }


# =============================================================================
# GRID SYSTEM: Deterministic Positioning
# =============================================================================

class GridPosition(Enum):
    """Grid-aligned positions for 9:16 (portrait) and 16:9 (landscape) layouts."""
    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    CENTER_LEFT = "center_left"
    CENTER = "center"
    CENTER_RIGHT = "center_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_RIGHT = "bottom_right"


class LayoutGrid:
    """
    Manages deterministic positioning on a grid.
    
    For 9:16 (portrait/vertical):
        - 3 columns, 5 rows
        - Elements stack vertically
        
    For 16:9 (landscape/horizontal):
        - 5 columns, 3 rows
        - Elements spread horizontally
    """
    
    def __init__(self, aspect_ratio: str = "9:16"):
        self.aspect_ratio = aspect_ratio
        self._setup_grid()
    
    def _setup_grid(self):
        """Setup grid positions based on aspect ratio."""
        if self.aspect_ratio == "9:16":
            # Portrait: narrow and tall
            self.frame_width = config.frame_width
            self.frame_height = config.frame_height
            
            # Vertical margins for safe zones
            self.x_positions = {
                "left": -self.frame_width * 0.3,
                "center": 0,
                "right": self.frame_width * 0.3,
            }
            self.y_positions = {
                "top": self.frame_height * 0.35,
                "upper": self.frame_height * 0.15,
                "center": 0,
                "lower": -self.frame_height * 0.15,
                "bottom": -self.frame_height * 0.35,
            }
        else:
            # Landscape: wide and short
            self.frame_width = config.frame_width
            self.frame_height = config.frame_height
            
            self.x_positions = {
                "far_left": -self.frame_width * 0.35,
                "left": -self.frame_width * 0.18,
                "center": 0,
                "right": self.frame_width * 0.18,
                "far_right": self.frame_width * 0.35,
            }
            self.y_positions = {
                "top": self.frame_height * 0.3,
                "center": 0,
                "bottom": -self.frame_height * 0.3,
            }
    
    def get_position(self, grid_pos: GridPosition) -> np.ndarray:
        """Get the actual coordinates for a grid position."""
        pos_map = {
            GridPosition.TOP_LEFT: (
                self.x_positions.get("left", self.x_positions.get("far_left")),
                self.y_positions["top"]
            ),
            GridPosition.TOP_CENTER: (self.x_positions["center"], self.y_positions["top"]),
            GridPosition.TOP_RIGHT: (
                self.x_positions.get("right", self.x_positions.get("far_right")),
                self.y_positions["top"]
            ),
            GridPosition.CENTER_LEFT: (
                self.x_positions.get("left", self.x_positions.get("far_left")),
                self.y_positions["center"]
            ),
            GridPosition.CENTER: (self.x_positions["center"], self.y_positions["center"]),
            GridPosition.CENTER_RIGHT: (
                self.x_positions.get("right", self.x_positions.get("far_right")),
                self.y_positions["center"]
            ),
            GridPosition.BOTTOM_LEFT: (
                self.x_positions.get("left", self.x_positions.get("far_left")),
                self.y_positions["bottom"]
            ),
            GridPosition.BOTTOM_CENTER: (self.x_positions["center"], self.y_positions["bottom"]),
            GridPosition.BOTTOM_RIGHT: (
                self.x_positions.get("right", self.x_positions.get("far_right")),
                self.y_positions["bottom"]
            ),
        }
        x, y = pos_map[grid_pos]
        return np.array([x, y, 0])
    
    def get_relative_position(
        self, 
        reference: VMobject, 
        direction: str, 
        spacing: float = None
    ) -> np.ndarray:
        """Get position relative to another element."""
        spacing = spacing or PrimitiveConfig.SPACING["normal"]
        
        directions = {
            "left_of": reference.get_center() + LEFT * (reference.width/2 + spacing),
            "right_of": reference.get_center() + RIGHT * (reference.width/2 + spacing),
            "above": reference.get_center() + UP * (reference.height/2 + spacing),
            "below": reference.get_center() + DOWN * (reference.height/2 + spacing),
        }
        return directions.get(direction, reference.get_center())


# =============================================================================
# CONTAINER PRIMITIVES: Boundaries, Scopes, Groups
# =============================================================================

class BoundaryBox(VGroup):
    """
    Represents a scope, container, or boundary.
    Use for: functions, classes, network perimeters, security zones.
    """
    
    def __init__(
        self,
        label: str = None,
        width: float = 4.0,
        height: float = 3.0,
        color: str = "primary",
        fill_opacity: float = 0.1,
        corner_radius: float = 0.3,
        **kwargs
    ):
        super().__init__(**kwargs)
        
        actual_color = PrimitiveConfig.COLORS.get(color, BLUE)
        
        self.box = RoundedRectangle(
            corner_radius=corner_radius,
            width=width,
            height=height,
            color=actual_color,
            fill_opacity=0.5,
            stroke_width=4
        )
        self.add(self.box)
        
        if label:
            self.label = Text(
                label,
                font_size=PrimitiveConfig.FONT_SIZES["label"],
                color=actual_color
            )
            max_label_width = width * 0.8
            if self.label.width > max_label_width:
                self.label.scale_to_fit_width(max_label_width)
            self.label.next_to(self.box, UP, buff=0.15)
            self.add(self.label)
        else:
            self.label = None
    
    def get_entry_point(self) -> np.ndarray:
        """Get the left edge center for flow entry."""
        return self.box.get_left()
    
    def get_exit_point(self) -> np.ndarray:
        """Get the right edge center for flow exit."""
        return self.box.get_right()


class ZoneBox(VGroup):
    """
    Represents a security zone or region.
    Use for: trust zones, network segments, classification levels.
    """
    
    def __init__(
        self,
        label: str = None,
        zone_type: str = "neutral",  # "safe", "danger", "neutral"
        width: float = 2.5,
        height: float = 2.0,
        **kwargs
    ):
        super().__init__(**kwargs)
        
        zone_colors = {
            "safe": (GREEN, 0.15),
            "danger": (RED, 0.15),
            "neutral": (GRAY, 0.1),
            "warning": (ORANGE, 0.12),
        }
        color, opacity = zone_colors.get(zone_type, (GRAY, 0.1))
        
        self.zone = RoundedRectangle(
            corner_radius=0.2,
            width=width,
            height=height,
            color=color,
            fill_opacity=opacity,
            stroke_width=2
        )
        self.add(self.zone)
        
        if label:
            self.label = Text(
                label,
                font_size=PrimitiveConfig.FONT_SIZES["small"],
                color=color
            )
            self.label.move_to(self.zone.get_corner(UL) + DR * 0.3)
            self.add(self.label)


# =============================================================================
# ENTITY PRIMITIVES: Data Packets, Nodes, Icons
# =============================================================================

class DataPacket(VGroup):
    """
    Represents a piece of data or request moving through a system.
    Use for: API requests, data flow, network packets, messages.
    """
    
    def __init__(
        self,
        label: str = None,
        color: str = "success",
        size: str = "medium",
        **kwargs
    ):
        super().__init__(**kwargs)
        
        actual_color = PrimitiveConfig.COLORS.get(color, GREEN)
        radius = PrimitiveConfig.SIZES.get(size, 1.0) * 0.35
        
        self.body = Circle(
            radius=radius,
            color=actual_color,
            fill_opacity=0.9,
            stroke_width=3
        )
        self.add(self.body)
        
        if label:
            self.label = Text(
                label,
                font_size=PrimitiveConfig.FONT_SIZES["small"],
                color=WHITE
            )
            max_width = radius * 1.5
            if self.label.width > max_width:
                self.label.scale_to_fit_width(max_width)
            self.label.move_to(self.body)
            self.add(self.label)


class Node(VGroup):
    """
    Represents a node in a graph or network.
    Use for: network nodes, decision points, process steps.
    """
    
    def __init__(
        self,
        label: str = None,
        node_type: str = "circle",  # "circle", "square", "diamond"
        color: str = "primary",
        size: str = "medium",
        **kwargs
    ):
        super().__init__(**kwargs)
        
        actual_color = PrimitiveConfig.COLORS.get(color, BLUE)
        scale = PrimitiveConfig.SIZES.get(size, 1.0)
        
        if node_type == "circle":
            self.shape = Circle(radius=0.5 * scale, color=actual_color, fill_opacity=0.6)
        elif node_type == "square":
            self.shape = Square(side_length=0.9 * scale, color=actual_color, fill_opacity=0.6)
        elif node_type == "diamond":
            self.shape = Square(side_length=0.7 * scale, color=actual_color, fill_opacity=0.6)
            self.shape.rotate(PI/4)
        else:
            self.shape = Circle(radius=0.5 * scale, color=actual_color, fill_opacity=0.6)
            
        self.shape.set_stroke(width=3)
        self.add(self.shape)
        
        if label:
            self.label = Text(
                label,
                font_size=PrimitiveConfig.FONT_SIZES["label"],
                color=actual_color
            )
            max_width = 0.8 * scale
            if self.label.width > max_width:
                self.label.scale_to_fit_width(max_width)
            self.label.move_to(self.shape)
            self.add(self.label)


class Checkpoint(VGroup):
    """
    Represents a verification or gate point.
    Use for: security checkpoints, validation gates, approval steps.
    """
    
    def __init__(
        self,
        label: str = "✓",
        color: str = "accent",
        size: str = "medium",
        **kwargs
    ):
        super().__init__(**kwargs)
        
        actual_color = PrimitiveConfig.COLORS.get(color, GOLD)
        scale = PrimitiveConfig.SIZES.get(size, 1.0)
        
        # Gate shape (vertical bars with gap)
        self.left_bar = Rectangle(
            width=0.15 * scale,
            height=1.2 * scale,
            color=actual_color,
            fill_opacity=0.8
        )
        self.right_bar = Rectangle(
            width=0.15 * scale,
            height=1.2 * scale,
            color=actual_color,
            fill_opacity=0.8
        )
        self.left_bar.shift(LEFT * 0.3 * scale)
        self.right_bar.shift(RIGHT * 0.3 * scale)
        
        self.add(self.left_bar, self.right_bar)
        
        # Check symbol
        self.symbol = Text(
            label,
            font_size=int(PrimitiveConfig.FONT_SIZES["heading"] * scale),
            color=actual_color
        )
        self.add(self.symbol)


# =============================================================================
# FLOW PRIMITIVES: Arrows, Connections, Paths
# =============================================================================

class FlowArrow(VGroup):
    """
    Represents directional flow between elements.
    Use for: data flow, process order, relationships.
    """
    
    def __init__(
        self,
        start: np.ndarray = LEFT,
        end: np.ndarray = RIGHT,
        label: str = None,
        color: str = "neutral",
        curved: bool = False,
        **kwargs
    ):
        super().__init__(**kwargs)
        
        actual_color = PrimitiveConfig.COLORS.get(color, GRAY)
        
        if curved:
            # Curved arrow with control point
            mid = (start + end) / 2
            control = mid + UP * 0.5
            self.arrow = CurvedArrow(
                start_point=start,
                end_point=end,
                color=actual_color,
                stroke_width=3
            )
        else:
            self.arrow = Arrow(
                start=start,
                end=end,
                color=actual_color,
                stroke_width=3,
                buff=0.1
            )
        self.add(self.arrow)
        
        if label:
            self.label = Text(
                label,
                font_size=PrimitiveConfig.FONT_SIZES["small"],
                color=actual_color
            )
            self.label.next_to(self.arrow, UP, buff=0.1)
            self.add(self.label)
    
    @classmethod
    def connect(
        cls, 
        from_element: VMobject, 
        to_element: VMobject,
        direction: str = "right",
        **kwargs
    ) -> "FlowArrow":
        """Create an arrow connecting two elements."""
        direction_map = {
            "right": (from_element.get_right(), to_element.get_left()),
            "left": (from_element.get_left(), to_element.get_right()),
            "up": (from_element.get_top(), to_element.get_bottom()),
            "down": (from_element.get_bottom(), to_element.get_top()),
        }
        start, end = direction_map.get(direction, direction_map["right"])
        return cls(start=start, end=end, **kwargs)


class ConnectionLine(VGroup):
    """
    Represents a non-directional connection.
    Use for: relationships, associations, links.
    """
    
    def __init__(
        self,
        start: np.ndarray = LEFT,
        end: np.ndarray = RIGHT,
        color: str = "muted",
        dashed: bool = False,
        **kwargs
    ):
        super().__init__(**kwargs)
        
        actual_color = PrimitiveConfig.COLORS.get(color, GRAY_B)
        
        if dashed:
            self.line = DashedLine(
                start=start,
                end=end,
                color=actual_color,
                stroke_width=2
            )
        else:
            self.line = Line(
                start=start,
                end=end,
                color=actual_color,
                stroke_width=2
            )
        self.add(self.line)


# =============================================================================
# TEXT PRIMITIVES: Labels Only (No Paragraphs!)
# =============================================================================

class TitleLabel(VGroup):
    """
    Scene title - max 6 words.
    Use sparingly, one per scene maximum.
    """
    
    def __init__(
        self,
        text: str,
        color: str = "text",
        max_width: float = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        
        # Enforce word limit
        words = text.split()
        if len(words) > 6:
            text = " ".join(words[:6]) + "..."
        
        actual_color = PrimitiveConfig.COLORS.get(color, WHITE)
        max_width = max_width or config.frame_width * 0.7
        
        self.text = Text(
            text,
            font_size=PrimitiveConfig.FONT_SIZES["title"],
            color=actual_color,
            weight=BOLD
        )
        if self.text.width > max_width:
            self.text.scale_to_fit_width(max_width)
        self.add(self.text)


class ElementLabel(VGroup):
    """
    Element label - max 4 words.
    Use to identify/name visual elements.
    """
    
    def __init__(
        self,
        text: str,
        color: str = "text",
        size: str = "label",
        max_width: float = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        
        # Enforce word limit
        words = text.split()
        if len(words) > 4:
            text = " ".join(words[:4])
        
        actual_color = PrimitiveConfig.COLORS.get(color, WHITE)
        font_size = PrimitiveConfig.FONT_SIZES.get(size, 18)
        max_width = max_width or config.frame_width * 0.4
        
        self.text = Text(
            text,
            font_size=font_size,
            color=actual_color
        )
        if self.text.width > max_width:
            self.text.scale_to_fit_width(max_width)
        self.add(self.text)


# =============================================================================
# EMPHASIS PRIMITIVES: Highlights, Pulses, Indicators
# =============================================================================

class HighlightRing(VGroup):
    """
    Circular highlight around an element.
    Use for: emphasis, focus, selection indication.
    """
    
    def __init__(
        self,
        target: VMobject,
        color: str = "highlight",
        padding: float = 0.2,
        **kwargs
    ):
        super().__init__(**kwargs)
        
        actual_color = PrimitiveConfig.COLORS.get(color, YELLOW)
        
        # Create ring around target
        radius = max(target.width, target.height) / 2 + padding
        self.ring = Circle(
            radius=radius,
            color=actual_color,
            stroke_width=4,
            fill_opacity=0
        )
        self.ring.move_to(target)
        self.add(self.ring)


# =============================================================================
# PRIMITIVE FACTORY: Unified Creation Interface
# =============================================================================

class PrimitiveFactory:
    """
    Factory for creating primitives from scene specifications.
    Maps specification element types to primitive classes.
    """
    
    ELEMENT_MAP = {
        "boundary_box": BoundaryBox,
        "rounded_rectangle": BoundaryBox,
        "zone_box": ZoneBox,
        "data_packet": DataPacket,
        "node": Node,
        "checkpoint": Checkpoint,
        "flow_arrow": FlowArrow,
        "connection_line": ConnectionLine,
        "title": TitleLabel,
        "label": ElementLabel,
    }
    
    def __init__(self, aspect_ratio: str = "9:16"):
        self.grid = LayoutGrid(aspect_ratio)
    
    def create(
        self,
        element_type: str,
        position: str = None,
        relative_to: VMobject = None,
        **kwargs
    ) -> VMobject:
        """Create a primitive and position it."""
        
        primitive_class = self.ELEMENT_MAP.get(element_type)
        if not primitive_class:
            raise ValueError(f"Unknown element type: {element_type}")
        
        primitive = primitive_class(**kwargs)
        
        # Position the element
        if position and relative_to:
            pos = self.grid.get_relative_position(relative_to, position)
            primitive.move_to(pos)
        elif position:
            try:
                grid_pos = GridPosition(position)
                pos = self.grid.get_position(grid_pos)
                primitive.move_to(pos)
            except ValueError:
                pass  # Invalid position, leave at origin
        
        return primitive
    
    def create_flow(
        self,
        from_element: VMobject,
        to_element: VMobject,
        **kwargs
    ) -> FlowArrow:
        """Create a flow arrow between two elements."""
        return FlowArrow.connect(from_element, to_element, **kwargs)


# =============================================================================
# ANIMATION PRESETS: Consistent, Reusable Animations
# =============================================================================

class AnimationPresets:
    """
    Predefined animation sequences for common patterns.
    These ensure consistent timing and motion across scenes.
    """
    
    @staticmethod
    def appear_with_emphasis(
        element: VMobject,
        run_time: float = 0.8
    ) -> AnimationGroup:
        """Element appears with a brief scale pulse."""
        return Succession(
            GrowFromCenter(element, run_time=run_time * 0.6),
            element.animate.scale(1.05).set_rate_func(there_and_back),
        )
    
    @staticmethod
    def flow_through(
        packet: VMobject,
        waypoints: List[np.ndarray],
        run_time: float = 1.5
    ) -> Succession:
        """Animate packet moving through waypoints."""
        animations = []
        time_per_segment = run_time / len(waypoints)
        for point in waypoints:
            animations.append(
                packet.animate.move_to(point).set_run_time(time_per_segment)
            )
        return Succession(*animations)
    
    @staticmethod
    def checkpoint_verify(
        checkpoint: Checkpoint,
        run_time: float = 0.5
    ) -> AnimationGroup:
        """Checkpoint flashes to indicate verification."""
        return Succession(
            Flash(checkpoint, color=GOLD, run_time=run_time * 0.4),
            Indicate(checkpoint, color=GREEN, run_time=run_time * 0.6),
        )
    
    @staticmethod  
    def transform_element(
        from_element: VMobject,
        to_element: VMobject,
        run_time: float = 0.8
    ) -> ReplacementTransform:
        """Smooth transformation between elements."""
        return ReplacementTransform(from_element, to_element, run_time=run_time)


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    # This would be run as a Manim scene
    print("Visual Primitive Library loaded successfully.")
    print(f"Available primitives: {list(PrimitiveFactory.ELEMENT_MAP.keys())}")
