"""
Scene Specification Generator
=============================

Generates structured scene specifications from topics using LLM.
This replaces the freeform narration + visual description approach with
a constrained specification format that enforces quality.

The LLM generates JSON specs that are validated before code generation.
"""

import json
import logging
import difflib
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from .scene_specification import (
    SceneSpecification, Concept, VisualMetaphor, Transformation,
    Constraints, Narration, Timing, VisualElement, TransformationStep,
    SemanticBeat, MetaphorType, ElementType, TransformAction, Position, TextRole
)

logger = logging.getLogger(__name__)


# =============================================================================
# METAPHOR MAPPING TAXONOMY
# =============================================================================

METAPHOR_TAXONOMY = {
    # Abstract concept keywords → suggested metaphor types and visual elements
    "process": {
        "metaphor_type": MetaphorType.PROCESS_FLOW,
        "suggested_elements": [ElementType.ARROW, ElementType.DATA_PACKET, ElementType.NODE, ElementType.GLASS_CARD, ElementType.ICON_BADGE],
        "keywords": ["flow", "pipeline", "sequence", "steps", "order", "execute", "run"]
    },
    "container": {
        "metaphor_type": MetaphorType.CONTAINER,
        "suggested_elements": [ElementType.GLASS_CARD, ElementType.BOUNDARY_BOX, ElementType.TAG_PILL, ElementType.ICON_BADGE],
        "keywords": ["scope", "function", "class", "module", "encapsulate", "contains", "inside"]
    },
    "security": {
        "metaphor_type": MetaphorType.PROCESS_FLOW,
        "suggested_elements": [ElementType.ICON_BADGE, ElementType.GLASS_CARD, ElementType.CHECKPOINT, ElementType.GATE, ElementType.LOCK],
        "keywords": ["verify", "authenticate", "trust", "secure", "protect", "access", "permission"]
    },
    "transformation": {
        "metaphor_type": MetaphorType.TRANSFORMATION,
        "suggested_elements": [ElementType.GLASS_CARD, ElementType.CODE_BLOCK, ElementType.ARROW, ElementType.ICON_BADGE],
        "keywords": ["convert", "transform", "change", "compile", "parse", "encode", "decode"]
    },
    "relationship": {
        "metaphor_type": MetaphorType.RELATIONSHIP,
        "suggested_elements": [ElementType.GLASS_CARD, ElementType.ARROW, ElementType.ICON_BADGE, ElementType.TAG_PILL],
        "keywords": ["connect", "link", "inherit", "depend", "relate", "associate", "reference"]
    },
    "state": {
        "metaphor_type": MetaphorType.STATE,
        "suggested_elements": [ElementType.ICON_BADGE, ElementType.TAG_PILL, ElementType.GLASS_CARD],
        "keywords": ["state", "status", "toggle", "switch", "enable", "disable", "active", "inactive"]
    },
    "quantity": {
        "metaphor_type": MetaphorType.QUANTITY,
        "suggested_elements": [ElementType.PROGRESS_BAR, ElementType.GLASS_CARD, ElementType.TAG_PILL, ElementType.NODE],
        "keywords": ["array", "list", "collection", "count", "iterate", "loop", "memory", "stack"]
    },
    "comparison": {
        "metaphor_type": MetaphorType.COMPARISON,
        "suggested_elements": [ElementType.GLASS_CARD, ElementType.PROGRESS_BAR, ElementType.TAG_PILL, ElementType.ICON_BADGE],
        "keywords": ["compare", "versus", "difference", "similar", "contrast", "advantage"]
    },
    "hierarchy": {
        "metaphor_type": MetaphorType.HIERARCHY,
        "suggested_elements": [ElementType.GLASS_CARD, ElementType.ICON_BADGE, ElementType.ARROW, ElementType.TAG_PILL],
        "keywords": ["tree", "parent", "child", "layer", "level", "inherit", "extend", "hierarchy"]
    }
}


# =============================================================================
# SCENE SPECIFICATION GENERATION PROMPT
# =============================================================================

SCENE_SPEC_GENERATION_PROMPT = '''You are directing a cinematic educational YouTube Short.

Your task is NOT to design slides or list animations.
Your task is to design VISUAL INTENT — how ideas should unfold visually over time.

The VisualDirector system will handle choreography.
You must decide WHAT should happen and WHY.

---

## PRIMARY PRINCIPLE

Every scene must visually THINK.

The viewer should understand the idea even without audio.

Motion exists to explain meaning, not decorate narration.

If visuals stop communicating, redesign the scene.

---

## VISUAL STORY MODEL

Each scene follows a visual arc:

1. INTRODUCE — establish the main idea clearly.
2. DEVELOP — relationships or structure appear progressively.
3. FOCUS — attention shifts to the key insight.
4. HOLD — viewer understands the completed diagram.

Never reveal the full diagram immediately.
Build understanding step-by-step.

---

## SPATIAL GOVERNANCE (MANDATORY)

Design layouts for mobile viewing.

Rules:

- No element may exceed safe frame bounds (90% width/height).
- Maintain clear margins from edges.
- Primary concept = largest visual element.
- Supporting elements scale proportionally smaller.
- If many elements exist, distribute across space instead of shrinking excessively.
- Readability is more important than screen coverage.

Avoid overcrowding.

---

## LAYOUT SELECTION

Choose ONE layout strategy per scene based on meaning:

- Comparison — opposing sides (glass_cards LEFT + RIGHT, icon_badges above each, arrow between)
- Process — directional flow (nodes/cards LEFT→RIGHT with arrows between steps)
- Hierarchy — top-down structure (parent glass_card TOP, children spread BOTTOM)
- Definition — central concept with supporting details (glass_card CENTER, tag_pills/icon_badges around it)
- Cause/Effect — connection (two elements with arrow between them)

Layout must match explanation logic.

---

## VISUAL INTERACTION PRINCIPLE

Elements should influence each other.

Prefer:
- growth (grow_from_center, draw_border_then_fill)
- connection (draw_arrow, flow between elements)
- transformation (morph, color shift, scale change)
- emphasis shifts (pulse, circumscribe, flash on key insight)

Avoid unrelated sequential appearances.

At least one meaningful interaction must occur in every CONTENT scene.

---

## MOTION PHILOSOPHY

Motion should feel continuous but calm.

Use motion to guide attention:
- introduce (grow_from_center, slide_in)
- connect (draw_arrow, flow)
- emphasize (pulse, circumscribe, flash)
- reveal (zoom_out, fade_in)

Avoid constant aggressive animation.

Moments of stillness are allowed ONLY after understanding is achieved.

HOLD all elements visible at end — NEVER FadeOut everything.

---

## NARRATION STYLE

Conversational, concise, curious.
35-50 words per scene.
Sound natural, not academic.

Good: "Okay wait, have you ever wondered why..."
Good: "So basically, think of it like this..."
Good: "Boom! That's actually it. Simple, right?"

Bad: "Today we will explore the concept of..."
Bad: "X is defined as a mechanism whereby..."

---

## AVAILABLE VISUAL PRIMITIVES

| Type | Best For |
|------|----------|
| `glass_card` | Key concepts, main ideas, definitions (large, frosted glass panel) |
| `code_block` | Code snippets, commands, syntax (dark editor style) |
| `icon_badge` | Key symbols, comparison icons, status (glowing badge) |
| `tag_pill` | Labels, categories, keywords (rounded pill) |
| `progress_bar` | Metrics, comparisons, before/after (animated fill bar) |
| `boundary_box` | Grouping related elements together (container) |
| `node` | Entities in flow diagrams (styled circle/shape) |
| `label` | Short annotations, captions, callouts |
| `arrow` | Connections, data flow, cause→effect |

Prefer `glass_card` and `icon_badge` over basic `node` — they look better.
Use `medium` or `large` sizes — small elements are invisible on phones.
Include at least 1 `arrow` in CONTENT scenes to show connections.

---

## TOPIC
"{topic}"

## TIMING
Total: {duration} seconds
Scenes: EXACTLY {num_scenes} scenes
Per scene: ~{seconds_per_scene} seconds

## ASPECT RATIO
{aspect_ratio}

## OUTPUT FORMAT (JSON Array)

Return a JSON array. Each scene object:

```json
[
  {{
    "scene_id": "scene_001",
    "type": "INTRO|CONTENT|OUTRO",
    "concept": {{
      "idea": "What this scene communicates",
      "pedagogical_goal": "What the viewer should understand"
    }},
    "visual_metaphor": {{
      "abstract_concept": "the core idea",
      "concrete_representation": "relatable real-world analogy",
      "metaphor_type": "container|process_flow|relationship|state|transformation|quantity|comparison|hierarchy",
      "visual_elements": [
        {{
          "id": "elem1",
          "element_type": "glass_card|code_block|icon_badge|tag_pill|progress_bar|node|label|boundary_box|arrow",
          "label": "1-4 words MAX",
          "position": "center|top_center|bottom_center|center_left|center_right|upper_center|lower_center|upper_left|upper_right|lower_left|lower_right",
          "size": "medium|large",
          "color": "BLUE|GREEN|RED|YELLOW|ORANGE|PURPLE|GOLD|WHITE|TEAL"
        }}
      ]
    }},
    "transformation": {{
      "type": "intro_hook|explanation|reveal|conclusion",
      "sequence": [
        {{"action": "grow_from_center|slide_in_from_left|slide_in_from_right|draw_arrow|draw_border_then_fill|pulse|circumscribe|flash|fade_in|bounce", "target": "elem1", "narration_cue": "what narration phrase triggers this"}}
      ]
    }},
    "narration": {{
      "text": "35-50 words, conversational tone",
      "semantic_beats": [
        {{"beat_phrase": "3-6 word phrase from narration", "visual_sync": "what visual event happens and why", "target_elements": ["elem1"]}}
      ]
    }},
    "timing": {{ "cognitive_duration_estimate_seconds": {seconds_per_scene} }}
  }}
]
```

---

## QUALITY CHECK

Before outputting, verify:
1. Does each scene visually communicate its idea without audio?
2. Are elements spread across at least 3 different positions per scene?
3. Does each CONTENT scene have at least one connection (arrow) between elements?
4. Is the diagram built progressively, not revealed all at once?
5. Does every element label name a concept from the narration?
6. Is narration 35-50 words per scene, conversational?
7. Does the primary concept dominate visually?

---

Generate {num_scenes} scenes for "{topic}".
Focus on visual intent and meaning. VisualDirector handles the rest.
'''


# =============================================================================
# SCENE SPEC GENERATOR CLASS
# =============================================================================

@dataclass
class GenerationConfig:
    """Configuration for scene specification generation."""
    max_scenes: int = 4
    min_scene_duration: float = 12.0
    max_scene_duration: float = 20.0
    target_scene_duration: float = 15.0
    aspect_ratio: str = "9:16"
    video_type: str = "short"  # "short" = casual/friendly, "regular" = professional


class SceneSpecGenerator:
    """
    Generates validated scene specifications from topics.
    
    Flow:
    1. Call LLM with structured prompt
    2. Parse JSON response
    3. Validate against schema constraints
    4. Return validated specifications or errors
    """
    
    def __init__(self, llm_client, config: GenerationConfig = None):
        """
        Initialize generator.
        
        Args:
            llm_client: Any LLM client with a `generate(prompt: str) -> str` method
            config: Generation configuration
        """
        self.llm_client = llm_client
        self.config = config or GenerationConfig()
    
    def generate_specifications(
        self,
        topic: str,
        total_duration: int
    ) -> Tuple[List[SceneSpecification], List[str]]:
        """
        Generate scene specifications for a topic.
        
        Args:
            topic: The educational topic to explain
            total_duration: Total video duration in seconds
            
        Returns:
            Tuple of (list of validated specs, list of error messages)
        """
        # Calculate scene count - FORCE 3 scenes minimum for Intro/Content/Outro if short
        if getattr(self.config, 'video_type', 'short') == 'short' and total_duration < 60:
             num_scenes = 3 # Intro, Content, Outro
        else:
            num_scenes = max(3, min(
                self.config.max_scenes,
                int(total_duration / self.config.target_scene_duration)
            ))
            
        seconds_per_scene = total_duration / num_scenes
        
        logger.info(f"🎭 Generating specs for '{topic}' ({total_duration}s)")
        logger.info(f"   Target: {num_scenes} scenes (~{seconds_per_scene:.1f}s each)")
        logger.info(f"   Style: {getattr(self.config, 'video_type', 'short').upper()} (Head/Tail enforced)")
        
        # Build prompt
        prompt = SCENE_SPEC_GENERATION_PROMPT.format(
            topic=topic,
            duration=total_duration,
            num_scenes=num_scenes,
            seconds_per_scene=int(seconds_per_scene),
            aspect_ratio=self.config.aspect_ratio
        )
        
        try:
            # Call LLM
            logger.info(f"📤 Calling LLM for {num_scenes} scene specs...")
            response = self.llm_client.generate(prompt)
            
            if not response:
                raise ValueError("LLM returned empty response")
            
            # Log the raw narration for analysis (Requested by user)
            self._log_generated_narration(response)
            
            logger.info(f"📥 Received response: {len(response)} chars")
            
            # Parse JSON from response
            specs_data = self._extract_json(response)
            logger.info(f"✅ Parsed {len(specs_data)} scene specifications from JSON")
            
            # Convert to SceneSpecification objects and validate
            specs = []
            all_errors = []
            
            for i, spec_data in enumerate(specs_data):
                try:
                    # Enforce timing match
                    if "timing" not in spec_data:
                        spec_data["timing"] = {}
                    spec_data["timing"]["cognitive_duration_estimate_seconds"] = seconds_per_scene

                    spec = self._parse_spec(spec_data, i)
                    is_valid, errors = spec.validate()
                    
                    if is_valid:
                        specs.append(spec)
                        logger.debug(f"✅ Scene {i+1} validated successfully")
                    else:
                        all_errors.extend([f"Scene {i+1}: {e}" for e in errors])
                        logger.warning(f"⚠️ Scene {i+1} validation failed: {errors[:2]}")
                        # Try to fix common issues
                        fixed_spec = self._attempt_fix(spec_data, errors)
                        if fixed_spec:
                            specs.append(fixed_spec)
                            logger.info(f"🔧 Scene {i+1} fixed and added")
                        
                except Exception as e:
                    all_errors.append(f"Scene {i+1}: Failed to parse - {str(e)}")
            
            return specs, all_errors
            
        except Exception as e:
            logger.error(f"Scene spec generation failed: {e}")
            return [], [f"Generation failed: {str(e)}"]

    def _log_generated_narration(self, response_text: str):
        """Extract and log narration for analysis."""
        try:
            logger.info("📜 --- GENERATED NARRATION ANALYSIS ---")
            import re
            narrations = re.findall(r'"text":\s*"(.*?)"', response_text)
            for i, text in enumerate(narrations):
                logger.info(f"   Scene {i+1}: \"{text}\"")
                if i == 0: logger.info("   (Check: Is this a good hook?)")
                if i == len(narrations)-1: logger.info("   (Check: Is this a good wrap-up?)")
            logger.info("----------------------------------------")
        except Exception:
            pass # Don't fail if logging fails
    
    def _extract_json(self, response: str) -> List[Dict[str, Any]]:
        """Extract JSON array from LLM response with robust parsing."""
        import re
        
        if not response:
            raise ValueError("Empty response from LLM")
        
        original_response = response
        response = response.strip()
        
        # Log first 500 chars for debugging
        logger.debug(f"🔍 Raw LLM response (first 500 chars): {response[:500]}")
        
        # Strategy 1: Try to find ```json ... ``` blocks
        json_block_match = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', response)
        if json_block_match:
            json_str = json_block_match.group(1)
            logger.debug(f"✅ Found JSON in markdown code block")
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ JSON in code block invalid: {e}")
        
        # Strategy 2: Remove all markdown code block markers and try again
        response_cleaned = re.sub(r'```(?:json)?', '', response)
        response_cleaned = response_cleaned.strip()
        
        # Strategy 3: Find the outermost [ ... ] pair
        start = response_cleaned.find("[")
        if start != -1:
            # Find matching closing bracket
            bracket_count = 0
            end = -1
            for i, char in enumerate(response_cleaned[start:], start):
                if char == '[':
                    bracket_count += 1
                elif char == ']':
                    bracket_count -= 1
                    if bracket_count == 0:
                        end = i + 1
                        break
            
            if end > start:
                json_str = response_cleaned[start:end]
                logger.debug(f"✅ Extracted JSON array from position {start} to {end}")
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError as e:
                    logger.warning(f"⚠️ Extracted JSON invalid: {e}")
                    logger.debug(f"🔍 Attempted JSON (first 300 chars): {json_str[:300]}")
                    
                    # Strategy 4: Try to fix common JSON issues
                    json_str_fixed = self._fix_common_json_issues(json_str)
                    try:
                        return json.loads(json_str_fixed)
                    except json.JSONDecodeError:
                        pass
        
        # Log failure details
        logger.error(f"❌ Could not extract JSON from response")
        logger.error(f"🔍 Response preview: {original_response[:1000]}")
        raise ValueError(f"No valid JSON array found in response. Response started with: '{original_response[:100]}...'")
    
    def _fix_common_json_issues(self, json_str: str) -> str:
        """Attempt to fix common JSON formatting issues from LLMs."""
        import re
        
        # Fix trailing commas before ] or }
        json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
        
        # Fix single quotes to double quotes (careful with apostrophes)
        # Only replace single quotes that are likely JSON delimiters
        json_str = re.sub(r"(?<=[{,:\[])\s*'([^']*?)'\s*(?=[},:\]])", r'"\1"', json_str)
        
        # Remove comments (// style)
        json_str = re.sub(r'//.*?(?=\n|$)', '', json_str)
        
        # Fix unquoted keys (e.g., {key: "value"} -> {"key": "value"})
        json_str = re.sub(r'{\s*(\w+)\s*:', r'{"\1":', json_str)
        json_str = re.sub(r',\s*(\w+)\s*:', r',"\1":', json_str)
        
        return json_str
    
    # Allowed Manim colors
    ALLOWED_COLORS = {"BLUE", "RED", "GREEN", "YELLOW", "WHITE", "ORANGE", 
                      "PINK", "PURPLE", "TEAL", "GOLD", "MAROON", "GRAY"}
    
    # Color mapping for common invalid colors
    COLOR_FALLBACKS = {
        "CYAN": "TEAL",
        "LIME": "GREEN", 
        "MAGENTA": "PINK",
        "AQUA": "TEAL",
        "NAVY": "BLUE",
        "SILVER": "GRAY",
        "BLACK": "GRAY",
        "BROWN": "MAROON",
        "INDIGO": "PURPLE",
        "VIOLET": "PURPLE",
    }
    
    def _sanitize_color(self, color: str) -> str:
        """Ensure color is from allowed Manim palette."""
        if not color:
            return "BLUE"
        color_upper = color.upper()
        if color_upper in self.ALLOWED_COLORS:
            return color_upper
        # Try fallback mapping
        if color_upper in self.COLOR_FALLBACKS:
            logger.debug(f"🎨 Color '{color}' mapped to '{self.COLOR_FALLBACKS[color_upper]}'")
            return self.COLOR_FALLBACKS[color_upper]
        # Default fallback
        logger.warning(f"⚠️ Unknown color '{color}', defaulting to BLUE")
        return "BLUE"
    
    # =========================================================================
    # ROBUST ENUM PARSING WITH ALIAS MAPPINGS
    # =========================================================================
    
    # ElementType aliases - maps common LLM outputs to valid enum values
    ELEMENT_TYPE_ALIASES = {
        "text": "label", "TEXT": "label", "title": "label", "heading": "label",
        "box": "boundary_box", "container": "boundary_box", "frame": "boundary_box",
        "rect": "rectangle", "square": "rectangle", "block": "rectangle",
        "ball": "circle", "dot": "node", "point": "node", "icon": "node",
        "line": "arrow", "connector": "arrow", "link": "arrow",
        "checkpoint": "checkpoint", "check": "checkpoint", "checkmark": "checkpoint",
        # v0.19.0 expanded element type aliases
        "star": "star_badge", "star_badge": "star_badge", "badge_star": "star_badge", "achievement": "star_badge",
        "curved_arrow": "curved_arrow_elem", "curved_arrow_elem": "curved_arrow_elem", "arc_arrow": "curved_arrow_elem",
        "dashed_line": "dashed_line_elem", "dashed_line_elem": "dashed_line_elem", "dotted_line": "dashed_line_elem",
        "brace": "brace_annotation", "brace_annotation": "brace_annotation", "annotation": "brace_annotation", "bracket": "brace_annotation",
        "annulus": "annulus_ring", "annulus_ring": "annulus_ring", "ring": "annulus_ring", "donut": "annulus_ring",
        "sector": "sector_chart", "sector_chart": "sector_chart", "pie": "sector_chart", "pie_slice": "sector_chart",
    }
    
    # Position aliases - maps simplified position names to valid enum values  
    POSITION_ALIASES = {
        "center": "center", "middle": "center", "mid": "center",
        "top": "top_center", "up": "top_center", "upper": "upper_center",
        "bottom": "bottom_center", "down": "bottom_center", "lower": "lower_center",
        "left": "center_left", "leftside": "center_left",
        "right": "center_right", "rightside": "center_right",
        # Top row aliases
        "top-left": "top_left", "topleft": "top_left",
        "top-right": "top_right", "topright": "top_right",
        "top-center": "top_center", "topcenter": "top_center",
        # Upper row aliases (5-row grid — distinct from top)
        "upper-left": "upper_left", "upperleft": "upper_left", "upper_left": "upper_left",
        "upper-right": "upper_right", "upperright": "upper_right", "upper_right": "upper_right",
        "upper-center": "upper_center", "uppercenter": "upper_center", "upper_center": "upper_center",
        # Lower row aliases (5-row grid — distinct from bottom)
        "lower-left": "lower_left", "lowerleft": "lower_left", "lower_left": "lower_left",
        "lower-right": "lower_right", "lowerright": "lower_right", "lower_right": "lower_right",
        "lower-center": "lower_center", "lowercenter": "lower_center", "lower_center": "lower_center",
        # Bottom row aliases
        "bottom-left": "bottom_left", "bottomleft": "bottom_left",
        "bottom-right": "bottom_right", "bottomright": "bottom_right",
        "bottom-center": "bottom_center", "bottomcenter": "bottom_center",
    }
    
    # TransformAction aliases - maps common animation verbs to valid enum values
    ACTION_ALIASES = {
        # Appear variants
        "appear": "appear", "show": "appear", "display": "appear", "reveal": "appear",
        "enter": "enter", "come_in": "enter", "pop": "appear",
        "grow_from_center": "grow_from_center", "grow": "grow_from_center", "expand": "grow_from_center",
        "fade_in": "fade_in", "fadein": "fade_in", "materialize": "fade_in",
        "slide_in": "slide_in", "slidein": "slide_in", "slide": "slide_in",
        "slide_in_from_left": "slide_in_from_left", "slide_from_left": "slide_in_from_left",
        "slide_in_from_right": "slide_in_from_right", "slide_from_right": "slide_in_from_right",
        "slide_in_from_top": "slide_in_from_top", "slide_from_top": "slide_in_from_top",
        "slide_in_from_bottom": "slide_in_from_bottom", "slide_from_bottom": "slide_in_from_bottom",
        "bounce": "bounce", "spring": "bounce", "hop": "bounce",
        # Emphasis variants
        "pulse": "pulse", "throb": "pulse", "beat": "pulse",
        "flash": "flash", "blink": "flash", "sparkle": "flash", "pop": "flash",
        "highlight": "highlight", "emphasize": "emphasize", "focus": "focus",
        "indicate": "highlight", "point": "highlight", "call_out": "highlight",
        "wiggle": "wiggle", "shake": "wiggle", "wobble": "wiggle",
        "glow": "glow", "shine": "glow", "radiate": "glow",
        # Scale variants
        "zoom": "zoom_in", "zoom_in": "zoom_in", "magnify": "zoom_in", "enlarge": "zoom_in",
        "zoom_out": "zoom_out", "shrink_view": "zoom_out", "minimize": "zoom_out",
        "scale": "scale", "resize": "scale", "grow_scale": "scale",
        "shrink": "shrink", "reduce": "shrink", "contract": "shrink",
        # Move variants
        "move": "move", "shift": "move", "relocate": "move", "translate": "move",
        # Exit variants
        "disappear": "disappear", "hide": "disappear", "remove": "disappear",
        "exit": "exit", "leave": "exit", "go_away": "exit",
        "fade_out": "fade_out", "fadeout": "fade_out", "vanish": "fade_out",
        # Transform variants
        "transform": "transform", "morph": "transform", "change": "transform",
        # Rotate variants
        "spin": "spin", "rotate": "spin", "turn": "spin", "twist": "spin",
        # Connect variants
        "connect": "connect", "link": "connect", "attach": "connect",
        "flow": "flow", "animate_path": "flow",
        # Drawing / emphasis extras
        "draw_border_then_fill": "draw_border_then_fill", "draw_border": "draw_border_then_fill",
        "draw_and_fill": "draw_border_then_fill", "border_fill": "draw_border_then_fill",
        "draw_arrow": "draw_arrow", "arrow": "draw_arrow", "create_arrow": "draw_arrow",
        "circumscribe": "circumscribe", "circle": "circumscribe", "outline": "circumscribe",
        # v0.19.0 expanded animation aliases
        "write": "write", "handwrite": "write", "draw_text": "write", "pen": "write",
        "apply_wave": "apply_wave", "wave": "wave", "ripple": "ripple", "undulate": "apply_wave",
        "circle_indicate": "circle_indicate", "circle_highlight": "circle_indicate", "ring_highlight": "circle_indicate",
        "surround": "surround", "surround_highlight": "surround", "box_highlight": "surround",
        "grow_from_point": "grow_from_point", "grow_from": "grow_from_point", "spawn": "grow_from_point",
        "fade_transform": "fade_transform", "cross_fade": "fade_transform", "morph_fade": "fade_transform",
        "show_passing_flash": "show_passing_flash", "trace": "trace", "border_flash": "show_passing_flash",
        "morph": "morph", "shapeshift": "morph", "evolve": "morph",
    }
    
    def _safe_parse_element_type(self, value: str) -> ElementType:
        """Parse element type with alias support and fallback."""
        if not value:
            return ElementType.NODE
        
        value_lower = value.lower().strip()
        
        # Direct match
        try:
            return ElementType(value_lower)
        except ValueError:
            pass
        
        # Alias match
        if value_lower in self.ELEMENT_TYPE_ALIASES:
            aliased = self.ELEMENT_TYPE_ALIASES[value_lower]
            logger.debug(f"🔄 ElementType '{value}' → '{aliased}'")
            return ElementType(aliased)
        
        # Fallback
        logger.warning(f"⚠️ Unknown element_type '{value}', using NODE")
        return ElementType.NODE
    
    def _safe_parse_position(self, value: str) -> Position:
        """Parse position with alias support and fallback."""
        if not value:
            return Position.CENTER
        
        value_lower = value.lower().strip().replace(" ", "_")
        
        # Direct match
        try:
            return Position(value_lower)
        except ValueError:
            pass
        
        # Alias match
        if value_lower in self.POSITION_ALIASES:
            aliased = self.POSITION_ALIASES[value_lower]
            logger.debug(f"🔄 Position '{value}' → '{aliased}'")
            return Position(aliased)
        
        # Fuzzy match: strip trailing punctuation, fix double chars
        import re as _re
        import difflib
        cleaned = _re.sub(r"['\"\s]+$", "", value_lower)  # strip trailing quotes
        cleaned = _re.sub(r'(.)\1{2,}', r'\1\1', cleaned)  # collapse triple+ chars
        # Try cleaned value
        try:
            return Position(cleaned)
        except ValueError:
            pass
        if cleaned in self.POSITION_ALIASES:
            return Position(self.POSITION_ALIASES[cleaned])
        
        # Closest match from valid positions
        valid_positions = [p.value for p in Position]
        matches = difflib.get_close_matches(cleaned, valid_positions, n=1, cutoff=0.7)
        if matches:
            logger.info(f"🔄 Fuzzy position '{value}' → '{matches[0]}'")
            return Position(matches[0])
        
        # Fallback
        logger.warning(f"⚠️ Unknown position '{value}', using CENTER")
        return Position.CENTER
    
    def _safe_parse_action(self, value: str) -> TransformAction:
        """Parse transform action with alias support and fallback."""
        if not value:
            return TransformAction.APPEAR
        
        value_lower = value.lower().strip().replace(" ", "_")
        
        # Direct match
        try:
            return TransformAction(value_lower)
        except ValueError:
            pass
        
        # Alias match
        if value_lower in self.ACTION_ALIASES:
            aliased = self.ACTION_ALIASES[value_lower]
            logger.debug(f"🔄 TransformAction '{value}' → '{aliased}'")
            return TransformAction(aliased)
        
        # Strip trailing 's' (LLM sometimes pluralizes: "fades" → "fade", "draws" → "draw")
        if value_lower.endswith('s') and len(value_lower) > 3:
            stripped = value_lower[:-1]
            try:
                return TransformAction(stripped)
            except ValueError:
                pass
            if stripped in self.ACTION_ALIASES:
                aliased = self.ACTION_ALIASES[stripped]
                logger.debug(f"🔄 TransformAction '{value}' (depluralized) → '{aliased}'")
                return TransformAction(aliased)
        
        # Fuzzy match against all valid action values
        valid_actions = [a.value for a in TransformAction]
        all_candidates = valid_actions + list(self.ACTION_ALIASES.keys())
        matches = difflib.get_close_matches(value_lower, all_candidates, n=1, cutoff=0.7)
        if matches:
            best = matches[0]
            if best in self.ACTION_ALIASES:
                best = self.ACTION_ALIASES[best]
            logger.info(f"🔄 Fuzzy action '{value}' → '{best}'")
            return TransformAction(best)
        
        # Final fallback — pick the closest semantic match instead of APPEAR
        # Map unknown actions to reasonable defaults based on keyword presence
        for keyword, action in [
            ("slide", "slide_in"), ("fade", "fade_in"), ("draw", "draw_border_then_fill"),
            ("grow", "grow_from_center"), ("shrink", "shrink"), ("zoom", "zoom_in"),
            ("scale", "scale"), ("spin", "spin"), ("flash", "flash"),
            ("glow", "glow"), ("pulse", "pulse"), ("wiggle", "wiggle"),
            ("bounce", "bounce"), ("arrow", "draw_arrow"), ("circle", "circumscribe"),
            ("highlight", "highlight"), ("emphasize", "emphasize"),
            ("move", "move"), ("exit", "exit"), ("enter", "enter"),
            ("disappear", "disappear"), ("appear", "appear"),
        ]:
            if keyword in value_lower:
                logger.info(f"🔄 Keyword action '{value}' → '{action}'")
                return TransformAction(action)
        
        logger.warning(f"⚠️ Unknown action '{value}', using APPEAR")
        return TransformAction.APPEAR
    
    def _parse_spec(self, data: Dict[str, Any], index: int) -> SceneSpecification:
        """Parse a single spec from dictionary data with robust fallbacks."""
        
        # Parse visual elements with safe enum parsing
        visual_elements = []
        for elem_data in data.get("visual_metaphor", {}).get("visual_elements", []):
            visual_elements.append(VisualElement(
                id=elem_data.get("id", f"elem_{index}_{len(visual_elements)}"),
                element_type=self._safe_parse_element_type(elem_data.get("element_type", "node")),
                label=elem_data.get("label"),
                color=self._sanitize_color(elem_data.get("color", "BLUE")),
                position=self._safe_parse_position(elem_data.get("position")) if elem_data.get("position") else None,
                relative_to=elem_data.get("relative_to"),
                size=elem_data.get("size", "medium")
            ))
        
        # Parse transformation steps with safe enum parsing
        transformation_steps = []
        for step_data in data.get("transformation", {}).get("sequence", []):
            transformation_steps.append(TransformationStep(
                action=self._safe_parse_action(step_data.get("action", "appear")),
                target=step_data.get("target", ""),
                to_position=self._safe_parse_position(step_data.get("to_position")) if step_data.get("to_position") else None,
                to_element=step_data.get("to_element"),
                relative_to=step_data.get("relative_to"),
                duration_weight=step_data.get("duration_weight", 1.0)
            ))
        
        # GUARANTEED FALLBACK: If no transformations, auto-generate for each element
        if not transformation_steps and visual_elements:
            logger.info(f"🔧 Auto-generating fallback transformations for {len(visual_elements)} elements")
            for elem in visual_elements:
                # Entry animation
                transformation_steps.append(TransformationStep(
                    action=TransformAction.APPEAR,
                    target=elem.id,
                    duration_weight=1.0
                ))
            # Add emphasis for first element
            if visual_elements:
                transformation_steps.append(TransformationStep(
                    action=TransformAction.HIGHLIGHT,
                    target=visual_elements[0].id,
                    duration_weight=0.5
                ))
        
        # Parse semantic beats
        semantic_beats = []
        for beat_data in data.get("narration", {}).get("semantic_beats", []):
            semantic_beats.append(SemanticBeat(
                beat_phrase=beat_data.get("beat_phrase", ""),
                visual_sync=beat_data.get("visual_sync", ""),
                target_elements=beat_data.get("target_elements", [])
            ))
        
        # Construct specification
        return SceneSpecification(
            scene_id=data.get("scene_id", f"scene_{index:03d}"),
            scene_type=data.get("type", "CONTENT").upper(),
            concept=Concept(
                idea=data.get("concept", {}).get("idea", ""),
                pedagogical_goal=data.get("concept", {}).get("pedagogical_goal", ""),
                prerequisite_concepts=data.get("concept", {}).get("prerequisite_concepts", [])
            ),
            visual_metaphor=VisualMetaphor(
                abstract_concept=data.get("visual_metaphor", {}).get("abstract_concept", ""),
                concrete_representation=data.get("visual_metaphor", {}).get("concrete_representation", ""),
                metaphor_type=MetaphorType(data.get("visual_metaphor", {}).get("metaphor_type", "process_flow")),
                visual_elements=visual_elements
            ),
            transformation=Transformation(
                transformation_type=data.get("transformation", {}).get("type", ""),
                sequence=transformation_steps
            ),
            constraints=Constraints(
                max_objects=8,
                max_text_elements=4,
                text_role=TextRole.LABEL,
                grid_alignment=True
            ),
            narration=Narration(
                text=data.get("narration", {}).get("text", ""),
                semantic_beats=semantic_beats
            ),
            timing=Timing(
                cognitive_duration_estimate_seconds=data.get("timing", {}).get(
                    "cognitive_duration_estimate_seconds", 10.0
                )
            )
        )
    
    def _attempt_fix(
        self,
        spec_data: Dict[str, Any],
        errors: List[str]
    ) -> Optional[SceneSpecification]:
        """Attempt to fix common specification errors."""
        fixed_data = spec_data.copy()
        
        for error in errors:
            # Fix: Too many visual elements
            if "Too many visual elements" in error:
                elements = fixed_data.get("visual_metaphor", {}).get("visual_elements", [])
                fixed_data["visual_metaphor"]["visual_elements"] = elements[:8]
            
            # Fix: Label too long
            if "exceeds 4 words" in error:
                elements = fixed_data.get("visual_metaphor", {}).get("visual_elements", [])
                for elem in elements:
                    if elem.get("label"):
                        words = elem["label"].split()
                        if len(words) > 4:
                            elem["label"] = " ".join(words[:4])
            
            # Fix: Too many transformation steps
            if "Too many transformation steps" in error:
                sequence = fixed_data.get("transformation", {}).get("sequence", [])
                fixed_data["transformation"]["sequence"] = sequence[:12]
            
            # Fix: Transformation target not found in elements
            if "not found in elements" in error:
                # Get element IDs
                elements = fixed_data.get("visual_metaphor", {}).get("visual_elements", [])
                element_ids = {elem.get("id") for elem in elements if elem.get("id")}
                
                # Filter transformation sequence to only include valid targets
                sequence = fixed_data.get("transformation", {}).get("sequence", [])
                valid_sequence = [
                    step for step in sequence 
                    if step.get("target") in element_ids
                ]
                
                # Also filter semantic beats
                beats = fixed_data.get("narration", {}).get("semantic_beats", [])
                for beat in beats:
                    if "target_elements" in beat:
                        beat["target_elements"] = [
                            elem for elem in beat["target_elements"] 
                            if elem in element_ids
                        ]
                
                fixed_data["transformation"]["sequence"] = valid_sequence[:6]
        
        try:
            # Re-parse and validate
            fixed_spec = self._parse_spec(fixed_data, 0)
            is_valid, remaining_errors = fixed_spec.validate()
            if is_valid:
                return fixed_spec
            else:
                # Even with remaining errors, return if we fixed critical issues
                # (Some errors like "missing semantic beats" are warnings, not blockers)
                critical_errors = [e for e in remaining_errors if "not found" in e or "Too many" in e]
                if not critical_errors:
                    logger.info(f"🔧 Spec has non-critical warnings, accepting anyway")
                    return fixed_spec
        except Exception as e:
            logger.warning(f"⚠️ Fix attempt failed: {e}")
        
        return None
    
    def suggest_metaphor(self, concept_text: str) -> Dict[str, Any]:
        """Suggest a visual metaphor for a concept based on keywords."""
        concept_lower = concept_text.lower()
        
        best_match = None
        max_matches = 0
        
        for category, mapping in METAPHOR_TAXONOMY.items():
            matches = sum(1 for kw in mapping["keywords"] if kw in concept_lower)
            if matches > max_matches:
                max_matches = matches
                best_match = mapping
        
        if best_match:
            return {
                "metaphor_type": best_match["metaphor_type"].value,
                "suggested_elements": [e.value for e in best_match["suggested_elements"]]
            }
        
        # Default fallback
        return {
            "metaphor_type": MetaphorType.PROCESS_FLOW.value,
            "suggested_elements": [ElementType.NODE.value, ElementType.ARROW.value]
        }


# =============================================================================
# VALIDATION GATE
# =============================================================================

class SpecificationValidator:
    """
    Validation gate for scene specifications.
    Enforces quality constraints before code generation proceeds.
    """
    
    STRICT_RULES = {
        "max_elements": 4,
        "max_text_elements": 2,
        "max_label_words": 4,
        "max_title_words": 6,
        "max_transformation_steps": 6,
        "max_concept_words": 20,
        "min_semantic_beats": 1,
    }
    
    def __init__(self, strict_mode: bool = True):
        self.strict_mode = strict_mode
    
    def validate_all(
        self,
        specs: List[SceneSpecification]
    ) -> Tuple[List[SceneSpecification], List[str]]:
        """
        Validate all specifications and return valid ones with error report.
        """
        valid_specs = []
        all_errors = []
        
        for i, spec in enumerate(specs):
            is_valid, errors = self.validate_single(spec)
            
            if is_valid:
                valid_specs.append(spec)
            else:
                all_errors.extend([f"Scene {i+1} ({spec.scene_id}): {e}" for e in errors])
                
                # In non-strict mode, still include the spec but log warnings
                if not self.strict_mode:
                    valid_specs.append(spec)
        
        return valid_specs, all_errors
    
    def validate_single(self, spec: SceneSpecification) -> Tuple[bool, List[str]]:
        """Validate a single specification."""
        # Use the built-in validation
        return spec.validate()
    
    def get_quality_score(self, spec: SceneSpecification) -> float:
        """
        Calculate a quality score for a specification (0.0 to 1.0).
        Higher is better.
        """
        score = 1.0
        
        # Penalize for too many elements
        elem_count = len(spec.visual_metaphor.visual_elements)
        if elem_count > 7:
            score -= 0.1 * (elem_count - 7)
        
        # Penalize for missing semantic beats
        beat_count = len(spec.narration.semantic_beats)
        if beat_count < 2:
            score -= 0.15
        
        # Penalize for long concept ideas
        idea_words = len(spec.concept.idea.split())
        if idea_words > 15:
            score -= 0.1
        
        # Reward for clear metaphor mapping
        if spec.visual_metaphor.abstract_concept and spec.visual_metaphor.concrete_representation:
            score += 0.1
        
        return max(0.0, min(1.0, score))


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    # Example: Create a mock LLM client and test generation
    class MockLLMClient:
        def generate(self, prompt: str) -> str:
            # Return a sample valid spec
            return '''[
                {
                    "scene_id": "scene_001",
                    "concept": {
                        "idea": "Functions encapsulate reusable code",
                        "pedagogical_goal": "Understand code reusability"
                    },
                    "visual_metaphor": {
                        "abstract_concept": "code reusability",
                        "concrete_representation": "factory that produces outputs",
                        "metaphor_type": "container",
                        "visual_elements": [
                            {"id": "factory", "element_type": "boundary_box", "label": "function", "color": "BLUE", "position": "center", "size": "large"},
                            {"id": "input", "element_type": "data_packet", "label": "5", "color": "GREEN", "position": "center_left", "size": "small"},
                            {"id": "output", "element_type": "data_packet", "label": "25", "color": "GOLD", "position": "center_right", "size": "small"}
                        ]
                    },
                    "transformation": {
                        "type": "demonstrate_process",
                        "sequence": [
                            {"action": "appear", "target": "factory"},
                            {"action": "appear", "target": "input"},
                            {"action": "move", "target": "input", "relative_to": "factory"},
                            {"action": "highlight", "target": "factory"},
                            {"action": "appear", "target": "output"}
                        ]
                    },
                    "narration": {
                        "text": "A function takes an input and produces an output.",
                        "semantic_beats": [
                            {"beat_phrase": "function takes an input", "visual_sync": "input enters factory", "target_elements": ["input", "factory"]},
                            {"beat_phrase": "produces an output", "visual_sync": "output appears", "target_elements": ["output"]}
                        ]
                    },
                    "timing": {"cognitive_duration_estimate_seconds": 10}
                }
            ]'''
    
    generator = SceneSpecGenerator(MockLLMClient())
    specs, errors = generator.generate_specifications("How Functions Work", 45)
    
    print(f"Generated {len(specs)} specifications")
    if errors:
        print("Errors:", errors)
    
    for spec in specs:
        print(f"\nScene: {spec.scene_id}")
        print(f"  Concept: {spec.concept.idea}")
        print(f"  Elements: {len(spec.visual_metaphor.visual_elements)}")
        
        validator = SpecificationValidator()
        score = validator.get_quality_score(spec)
        print(f"  Quality Score: {score:.2f}")
