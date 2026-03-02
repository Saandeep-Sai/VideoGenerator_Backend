"""
DEPRECATED — All prompts now live in prompt_registry.py
This module is unused and can be safely deleted.
"""

def improved_generate_narration_segments_with_gemini(self, topic: str, duration: int):
    """Generate narration segments using optimized prompt."""
    try:
        visual_guides = {
            "16:9": "arrange horizontally, use width",
            "9:16": "stack vertically, use height", 
            "1:1": "center elements, balanced",
            "4:3": "traditional layout",
            "21:9": "ultra-wide, side-by-side"
        }
        visual_guide = visual_guides.get(self.config.aspect_ratio, "arrange appropriately")
        
        from .clean_prompts import OPTIMIZED_NARRATION_PROMPT
        prompt = OPTIMIZED_NARRATION_PROMPT.format(
            duration=duration,
            topic=topic,
            aspect_ratio=self.config.aspect_ratio,
            visual_guide=visual_guide
        )
        
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
                    try:
                        duration_val = float(duration_part)
                    except:
                        duration_val = 10.0
                else:
                    duration_val = 10.0
                
                # Look for VISUALS and NARRATION
                visuals = ""
                narration = ""
                
                for j in range(i+1, min(i+5, len(lines))):
                    if j < len(lines):
                        if lines[j].strip().startswith('VISUALS:'):
                            visuals = lines[j].strip()[8:].strip()
                        elif lines[j].strip().startswith('NARRATION:'):
                            narration = lines[j].strip()[10:].strip()
                
                if narration:
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

def improved_build_individual_script_prompt(self, index: int, segment, samples: str, allowed_attributes: str, animation_reference: str, allowed_colors: str):
    """Build optimized individual script prompt."""
    aspect_ratio_config = self._get_aspect_ratio_config()
    
    aspect_ratio_guidelines = {
        "16:9": {"max_text_width": "config.frame_width * 0.85", "max_font_title": 48, "max_font_body": 36},
        "9:16": {"max_text_width": "config.frame_width * 0.65", "max_font_title": 32, "max_font_body": 24},
        "1:1": {"max_text_width": "config.frame_width * 0.75", "max_font_title": 42, "max_font_body": 30},
        "4:3": {"max_text_width": "config.frame_width * 0.80", "max_font_title": 44, "max_font_body": 32},
        "21:9": {"max_text_width": "config.frame_width * 0.90", "max_font_title": 48, "max_font_body": 36}
    }
    layout_info = aspect_ratio_guidelines.get(self.config.aspect_ratio, aspect_ratio_guidelines["16:9"])
    
    # Calculate timing
    entry_time = segment.duration * 0.15
    content_time = segment.duration * 0.2
    exit_time = segment.duration * 0.3
    remaining_time = segment.duration - (entry_time + content_time * 2 + exit_time)
    
    from .clean_prompts import OPTIMIZED_INDIVIDUAL_SCRIPT_PROMPT
    return OPTIMIZED_INDIVIDUAL_SCRIPT_PROMPT.format(
        index=index,
        duration=segment.duration,
        text=segment.text,
        visual_description=segment.visual_description,
        aspect_ratio=self.config.aspect_ratio,
        max_text_width=layout_info["max_text_width"],
        max_font_title=layout_info["max_font_title"],
        max_font_body=layout_info["max_font_body"],
        aspect_ratio_config=aspect_ratio_config,
        entry_time=entry_time,
        content_time=content_time,
        exit_time=exit_time,
        remaining_time=max(0.1, remaining_time)
    )

def improved_generate_scripts_in_bulk(self, segments):
    """Generate bulk scripts using optimized prompt."""
    aspect_ratio_config = self._get_aspect_ratio_config()
    
    aspect_ratio_guidelines = {
        "16:9": {"max_text_width": "config.frame_width * 0.85"},
        "9:16": {"max_text_width": "config.frame_width * 0.65"},
        "1:1": {"max_text_width": "config.frame_width * 0.75"},
        "4:3": {"max_text_width": "config.frame_width * 0.80"},
        "21:9": {"max_text_width": "config.frame_width * 0.90"}
    }
    layout_info = aspect_ratio_guidelines.get(self.config.aspect_ratio, aspect_ratio_guidelines["16:9"])
    
    segments_info = ""
    for i, segment in enumerate(segments):
        segments_info += f"""
SEGMENT {i+1}:
- Duration: {segment.duration:.2f} seconds
- Class: Segment{i:03d}
- Content: "{segment.text}"
- Visuals: {segment.visual_description}
"""
    
    from .clean_prompts import OPTIMIZED_BULK_SCRIPT_PROMPT
    prompt = OPTIMIZED_BULK_SCRIPT_PROMPT.format(
        num_segments=len(segments),
        aspect_ratio=self.config.aspect_ratio,
        max_text_width=layout_info["max_text_width"],
        segments_info=segments_info,
        aspect_ratio_config=aspect_ratio_config
    )
    
    # Optimized token calculation
    estimated_tokens_per_script = 800  # Much less with optimized prompts
    buffer_tokens = 1500
    calculated_max_tokens = (len(segments) * estimated_tokens_per_script) + buffer_tokens
    max_tokens = max(6000, min(calculated_max_tokens, 32768))
    
    generation_config = genai.GenerationConfig(
        temperature=0.2,
        max_output_tokens=max_tokens,
    )
    
    response = self.gemini_client.generate_content(prompt, generation_config=generation_config)
    
    # Process response
    full_script = response.text.strip()
    scripts = re.split(r'===SCRIPT START===', full_script)
    scripts = [s.strip() for s in scripts if s.strip()]
    
    if len(scripts) < len(segments):
        return self._smart_continue_generation(segments, scripts)
    
    # Save scripts
    for i, segment in enumerate(segments):
        try:
            raw_script = scripts[i]
            cleaned_script = self._clean_script_response(raw_script, i, segment.duration)
            script_path = Path(self.config.temp_dir) / f"segment_{i:03d}.py"
            script_path.write_text(cleaned_script, encoding="utf-8")
            segment.script_path = str(script_path)
        except Exception as e:
            raise RuntimeError(f"Failed to process script for segment {i+1}: {e}")
    
    return segments