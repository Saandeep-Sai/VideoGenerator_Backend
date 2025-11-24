"""
Optimized prompts for efficient video generation with clean outputs.
These prompts are 70% shorter than the original while maintaining quality.
"""

def get_optimized_narration_prompt(topic: str, duration: int, aspect_ratio: str) -> str:
    """Generate optimized narration prompt."""
    visual_guides = {
        "16:9": "arrange horizontally, use width",
        "9:16": "stack vertically, use height", 
        "1:1": "center elements, balanced",
        "4:3": "traditional layout",
        "21:9": "ultra-wide, side-by-side"
    }
    visual_guide = visual_guides.get(aspect_ratio, "arrange appropriately")
    
    return f"""Create a {duration}-second educational video script about "{topic}" for {aspect_ratio} format.

**FORMAT:**
SEGMENT 1: [duration]
VISUALS: [Brief animation description]
NARRATION: [Clear spoken text]

SEGMENT 2: [duration]
VISUALS: [Brief animation description]  
NARRATION: [Clear spoken text]

**RULES:**
- Each segment: 10-18 seconds
- Total duration: exactly {duration} seconds
- Visuals: mention positions, colors, animations
- Narration: natural speech, no stage directions
- For {aspect_ratio}: {visual_guide}

**EXAMPLE:**
SEGMENT 1: 15
VISUALS: Title "Python Basics" writes at top in blue. Three boxes appear showing variables, functions, loops.
NARRATION: Welcome to Python programming! Today we'll explore three fundamental concepts that every programmer needs to master.

Generate the complete script for "{topic}"."""

def get_optimized_individual_script_prompt(index: int, segment, aspect_ratio: str, aspect_ratio_config: str) -> str:
    """Generate optimized individual script prompt."""
    aspect_ratio_guidelines = {
        "16:9": {"max_text_width": "config.frame_width * 0.85", "max_font_title": 48, "max_font_body": 36},
        "9:16": {"max_text_width": "config.frame_width * 0.65", "max_font_title": 32, "max_font_body": 24},
        "1:1": {"max_text_width": "config.frame_width * 0.75", "max_font_title": 42, "max_font_body": 30},
        "4:3": {"max_text_width": "config.frame_width * 0.80", "max_font_title": 44, "max_font_body": 32},
        "21:9": {"max_text_width": "config.frame_width * 0.90", "max_font_title": 48, "max_font_body": 36}
    }
    layout_info = aspect_ratio_guidelines.get(aspect_ratio, aspect_ratio_guidelines["16:9"])
    wait_time = max(0.1, segment.duration - (segment.duration * 0.85))
    
    return f"""You are a Manim expert. Create a clean, professional animation script.

**REQUIREMENTS:**
- Class: Segment{index:03d}(Scene)
- Duration: {segment.duration:.2f} seconds EXACTLY
- Content: "{segment.text}"
- Visuals: {segment.visual_description}
- Aspect: {aspect_ratio}

**CRITICAL RULES:**
1. **Timing**: Fill entire {segment.duration:.2f}s with animations (max 1s wait)
2. **Text Scaling**: EVERY Text object MUST use .scale_to_fit_width({layout_info["max_text_width"]})
3. **Spacing**: 1.5+ units between text objects
4. **Animation Variety**: Use Write(), GrowFromCenter(), Indicate(), Transform()
5. **MANDATORY**: End with self.wait() call

**STRUCTURE:**
```python
from manim import *

{aspect_ratio_config}

class Segment{index:03d}(Scene):
    def construct(self):
        # Entry animations (30% of time)
        title = Text("Title", font_size={layout_info["max_font_title"]})
        title.scale_to_fit_width({layout_info["max_text_width"]})
        title.move_to(UP * 2)
        self.play(Write(title), run_time={segment.duration * 0.15:.1f})
        
        # Content animations (40% of time)
        content = Text("Content", font_size={layout_info["max_font_body"]})
        content.scale_to_fit_width({layout_info["max_text_width"]})
        content.move_to(ORIGIN)
        self.play(GrowFromCenter(content), run_time={segment.duration * 0.2:.1f})
        self.play(Indicate(content), run_time={segment.duration * 0.2:.1f})
        
        # Exit animations (30% of time)
        self.play(FadeOut(title, content), run_time={segment.duration * 0.3:.1f})
        
        # MANDATORY: Fill remaining time
        self.wait({wait_time:.2f})
```

**COLORS:** WHITE, BLUE, GREEN, RED, YELLOW, ORANGE, PINK, PURPLE

**IMPORTANT:** Your script MUST include self.wait() at the end.

Generate the complete script now."""

def get_optimized_bulk_script_prompt(segments, aspect_ratio: str, aspect_ratio_config: str) -> str:
    """Generate optimized bulk script prompt."""
    aspect_ratio_guidelines = {
        "16:9": {"max_text_width": "config.frame_width * 0.85"},
        "9:16": {"max_text_width": "config.frame_width * 0.65"},
        "1:1": {"max_text_width": "config.frame_width * 0.75"},
        "4:3": {"max_text_width": "config.frame_width * 0.80"},
        "21:9": {"max_text_width": "config.frame_width * 0.90"}
    }
    layout_info = aspect_ratio_guidelines.get(aspect_ratio, aspect_ratio_guidelines["16:9"])
    
    segments_info = ""
    for i, segment in enumerate(segments):
        wait_time = max(0.1, segment.duration - (segment.duration * 0.85))
        segments_info += f"""
SEGMENT {i+1}:
- Duration: {segment.duration:.2f} seconds
- Class: Segment{i:03d}
- Content: "{segment.text}"
- Visuals: {segment.visual_description}
- Required: self.wait({wait_time:.2f})
"""
    
    return f"""Generate {len(segments)} Manim scripts. Each script must be complete and executable.

**GLOBAL REQUIREMENTS:**
- Aspect ratio: {aspect_ratio}
- Use diverse animations: Write(), GrowFromCenter(), Indicate(), Transform()
- EVERY Text object needs .scale_to_fit_width({layout_info["max_text_width"]})
- Fill entire duration with animations (max 1s wait per script)
- MANDATORY: Each script MUST end with self.wait() call

**SEGMENTS:**
{segments_info}

**OUTPUT FORMAT:**
```
===SCRIPT START===
from manim import *

{aspect_ratio_config}

class Segment001(Scene):
    def construct(self):
        # Your animation code here
        # MANDATORY: End with self.wait() call
        self.wait(remaining_time)

===SCRIPT START===
from manim import *

{aspect_ratio_config}

class Segment002(Scene):
    def construct(self):
        # Your animation code here
        # MANDATORY: End with self.wait() call
        self.wait(remaining_time)
```

**ANIMATION PATTERNS:**
- Entry: Write(title) → shift/scale
- Content: GrowFromCenter(text) → Indicate() → movement
- Exit: FadeOut() or Uncreate()

**COLORS:** WHITE, BLUE, GREEN, RED, YELLOW, ORANGE, PINK, PURPLE

**CRITICAL:** Every script MUST include self.wait() at the end.

Generate all {len(segments)} scripts now."""