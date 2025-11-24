"""
Optimized prompt replacements for efficient video generation.
These prompts are 70% shorter while maintaining all critical requirements.
"""

def optimize_narration_generation(original_method):
    """Decorator to optimize narration generation with streamlined prompt."""
    def wrapper(self, topic: str, duration: int):
        visual_guides = {
            "16:9": "arrange horizontally, use width",
            "9:16": "stack vertically, use height", 
            "1:1": "center elements, balanced",
            "4:3": "traditional layout",
            "21:9": "ultra-wide, side-by-side"
        }
        visual_guide = visual_guides.get(self.config.aspect_ratio, "arrange appropriately")
        
        prompt = f"""Create a {duration}-second educational video script about "{topic}" for {self.config.aspect_ratio} format.

**FORMAT:**
SEGMENT 1: [duration]
VISUALS: [Brief animation description]
NARRATION: [Clear spoken text]

**RULES:**
- Each segment: 10-18 seconds
- Total duration: exactly {duration} seconds
- Visuals: mention positions, colors, animations
- Narration: natural speech, no stage directions
- For {self.config.aspect_ratio}: {visual_guide}

**EXAMPLE:**
SEGMENT 1: 15
VISUALS: Title "Python Basics" writes at top in blue. Three boxes appear showing variables, functions, loops.
NARRATION: Welcome to Python programming! Today we'll explore three fundamental concepts that every programmer needs to master.

Generate the complete script for "{topic}"."""

        try:
            response = self.gemini_model.generate_content(prompt)
            content = response.text.strip()
            
            segments = []
            current_time = 0.0
            
            lines = content.split('\n')
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if line.startswith('SEGMENT'):
                    # Extract duration
                    if ':' in line:
                        duration_part = line.split(':')[1].strip()
                        duration_val = float(duration_part)
                    else:
                        duration_val = 10.0
                    
                    # Look for VISUALS and NARRATION
                    visuals = ""
                    narration = ""
                    
                    for j in range(i+1, min(i+5, len(lines))):
                        if lines[j].strip().startswith('VISUALS:'):
                            visuals = lines[j].strip()[8:].strip()
                        elif lines[j].strip().startswith('NARRATION:'):
                            narration = lines[j].strip()[10:].strip()
                    
                    if narration:
                        from . import NarrationSegment
                        segment = NarrationSegment(
                            text=narration,
                            start_time=current_time,
                            end_time=current_time + duration_val,
                            duration=duration_val,
                            visual_description=visuals or "Simple animation"
                        )
                        segments.append(segment)
                        current_time += duration_val
                
                i += 1
            
            return segments if segments else self._generate_fallback_segments(topic, duration)
            
        except Exception as e:
            return self._generate_fallback_segments(topic, duration)
    
    return wrapper

def optimize_script_generation(original_method):
    """Decorator to optimize script generation with streamlined prompts."""
    def wrapper(self, index: int, segment, *args, **kwargs):
        aspect_ratio_config = self._get_aspect_ratio_config()
        
        aspect_ratio_guidelines = {
            "16:9": {"max_text_width": "config.frame_width * 0.85", "max_font_title": 48, "max_font_body": 36},
            "9:16": {"max_text_width": "config.frame_width * 0.65", "max_font_title": 32, "max_font_body": 24},
            "1:1": {"max_text_width": "config.frame_width * 0.75", "max_font_title": 42, "max_font_body": 30},
            "4:3": {"max_text_width": "config.frame_width * 0.80", "max_font_title": 44, "max_font_body": 32},
            "21:9": {"max_text_width": "config.frame_width * 0.90", "max_font_title": 48, "max_font_body": 36}
        }
        layout_info = aspect_ratio_guidelines.get(self.config.aspect_ratio, aspect_ratio_guidelines["16:9"])
        
        prompt = f"""You are a Manim expert. Create a clean, professional animation script.

**REQUIREMENTS:**
- Class: Segment{index:03d}(Scene)
- Duration: {segment.duration:.2f} seconds EXACTLY
- Content: "{segment.text}"
- Visuals: {segment.visual_description}
- Aspect: {self.config.aspect_ratio}

**CRITICAL RULES:**
1. **Timing**: Fill entire {segment.duration:.2f}s with animations (max 1s wait)
2. **Text Scaling**: EVERY Text object MUST use .scale_to_fit_width({layout_info["max_text_width"]})
3. **Spacing**: 1.5+ units between text objects
4. **Animation Variety**: Use Write(), GrowFromCenter(), Indicate(), Transform()

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
        
        # Fill remaining time
        self.wait({segment.duration:.2f} - {segment.duration * 0.85:.1f})
```

**COLORS:** WHITE, BLUE, GREEN, RED, YELLOW, ORANGE, PINK, PURPLE

Generate the complete script now."""
        
        return prompt
    
    return wrapper