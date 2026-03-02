"""
DEPRECATED — All prompts now live in prompt_registry.py
This module is unused and can be safely deleted.
"""

OPTIMIZED_NARRATION_PROMPT = """Create a {duration}-second educational video script about "{topic}" for {aspect_ratio} format.

**FORMAT:**
SEGMENT 1: [duration]
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

OPTIMIZED_INDIVIDUAL_SCRIPT_PROMPT = """You are a Manim expert. Create a clean, professional animation script.

**REQUIREMENTS:**
- Class: Segment{index:03d}(Scene)
- Duration: {duration:.2f} seconds EXACTLY
- Content: "{text}"
- Visuals: {visual_description}
- Aspect: {aspect_ratio}

**CRITICAL RULES:**
1. **Timing**: Fill entire {duration:.2f}s with animations (max 1s wait)
2. **Text Scaling**: EVERY Text object MUST use .scale_to_fit_width({max_text_width})
3. **Spacing**: 1.5+ units between text objects
4. **Animation Variety**: Use Write(), GrowFromCenter(), Indicate(), Transform()

**STRUCTURE:**
```python
from manim import *

{aspect_ratio_config}

class Segment{index:03d}(Scene):
    def construct(self):
        # Entry animations (30% of time)
        title = Text("Title", font_size={max_font_title})
        title.scale_to_fit_width({max_text_width})
        title.move_to(UP * 2)
        self.play(Write(title), run_time={entry_time:.1f})
        
        # Content animations (40% of time)
        content = Text("Content", font_size={max_font_body})
        content.scale_to_fit_width({max_text_width})
        content.move_to(ORIGIN)
        self.play(GrowFromCenter(content), run_time={content_time:.1f})
        self.play(Indicate(content), run_time={content_time:.1f})
        
        # Exit animations (30% of time)
        self.play(FadeOut(title, content), run_time={exit_time:.1f})
        
        # Fill remaining time
        self.wait({remaining_time:.1f})
```

**COLORS:** WHITE, BLUE, GREEN, RED, YELLOW, ORANGE, PINK, PURPLE

Generate the complete script now."""

OPTIMIZED_BULK_SCRIPT_PROMPT = """Generate {num_segments} Manim scripts. Each script must be complete and executable.

**GLOBAL REQUIREMENTS:**
- Aspect ratio: {aspect_ratio}
- Use diverse animations: Write(), GrowFromCenter(), Indicate(), Transform()
- EVERY Text object needs .scale_to_fit_width({max_text_width})
- Fill entire duration with animations (max 1s wait per script)

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
        self.wait(exact_duration)

===SCRIPT START===
from manim import *

{aspect_ratio_config}

class Segment002(Scene):
    def construct(self):
        # Your animation code here
        self.wait(exact_duration)
```

**ANIMATION PATTERNS:**
- Entry: Write(title) → shift/scale
- Content: GrowFromCenter(text) → Indicate() → movement
- Exit: FadeOut() or Uncreate()

**COLORS:** WHITE, BLUE, GREEN, RED, YELLOW, ORANGE, PINK, PURPLE

Generate all {num_segments} scripts now."""