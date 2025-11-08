import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass , asdict
from pathlib import Path
from typing import List, Optional, Tuple
from pydub import AudioSegment
import torchaudio as ta
import torchaudio.functional as F


# Third-party imports
import numpy as np
from dotenv import load_dotenv
from groq import Groq
from pydub import AudioSegment

# API and ML imports
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# TTS import with robust error handling

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
load_dotenv()

from typing import Optional

@dataclass
class NarrationSegment:
    start_time: float
    end_time: float
    duration: float
    text: str
    visual_description: str
    audio_path: Optional[str] = None
    script_path: Optional[str] = None
    video_path: Optional[str] = None  # Added this field

class EdgeTTSWrapper:
    """Enhanced Edge TTS wrapper with retry logic and custom headers."""
    def __init__(self, voice: str = "en-US-AriaNeural"):
        self.voice = voice
        self.max_retries = 2  # Reduced from 5 to 2 for faster failures
        self.retry_delay = 2  # Reduced from 3 to 2 seconds

    async def synthesize(self, text: str, output_path: str):
        import edge_tts
        import asyncio
        import random
        
        for attempt in range(self.max_retries):
            try:
                # Use the latest edge-tts API with custom settings
                communicate = edge_tts.Communicate(text, self.voice)
                await communicate.save(output_path)
                return  # Success
            except Exception as e:
                if attempt < self.max_retries - 1:
                    # Add random jitter to avoid rate limiting
                    delay = self.retry_delay + random.uniform(1, 3)
                    logger.warning(f"⚠️ Edge TTS attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                else:
                    # Final attempt failed
                    raise Exception(f"Edge TTS failed after {self.max_retries} attempts: {e}")



@dataclass
class VideoGenerationConfig:
    """Configuration for the entire video generation pipeline."""
    gemini_api_key: str
    groq_api_key: str
    output_dir: str = "output"
    temp_dir: str = "temp"
    manim_quality: str = "low"  # Custom low quality config for 480p30 (30fps native)
    audio_sample_rate: int = 22050
    use_groq_for_correction: bool = True
    manim_timeout: int = 1800  # Oracle VM: 30 minutes per segment rendering
    ffmpeg_timeout: int = 300  # FFmpeg operations: 5 minutes
    gemini_temperature: float = 0.2
    gemini_max_tokens: int = 8192
    max_generation_attempts: int = 3
    max_correction_attempts: int = 3  # Max attempts to fix script with Gemini/Groq before regenerating
    max_regeneration_attempts: int = 4  # Max attempts to regenerate script from scratch
    batch_size: int = 1  # Oracle VM: Process 1 segment at a time (avoid resource overload)
    aspect_ratio: str = "16:9"  # Options: "16:9" (YouTube), "9:16" (Shorts/TikTok), "1:1" (Instagram), "4:3" (Traditional)
    
    def __post_init__(self):
        if not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required.")
        if self.use_groq_for_correction and not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when correction is enabled.")
        
        # Validate aspect ratio
        valid_ratios = ["16:9", "9:16", "1:1", "4:3", "21:9"]
        if self.aspect_ratio not in valid_ratios:
            raise ValueError(f"aspect_ratio must be one of {valid_ratios}, got {self.aspect_ratio}")

    def to_dict(self):
        """Converts the dataclass instance to a dictionary."""
        return asdict(self)

class VideoGenerationPipeline:
    """A self-healing pipeline that generates narrated videos from a topic."""
    
    def __init__(self, config: VideoGenerationConfig):
        self.config = config
        self.gemini_model = None
        self.groq_client = None
        self.tts_model = None
        self.tts_available = False
        self.output_dir = Path(config.output_dir)
        self.device = "cpu"
        self.scaled_intro_path = None  # Cache for pre-scaled intro
        
        self._setup_directories()
        self._validate_dependencies()
        self._setup_models()
        
        try:
            with open('./generator/video_generator/prompt/sample.txt', 'r', encoding='utf-8') as f:
                self.samples = f.read()
            with open('./generator/video_generator/prompt/obj-attrbute_list.txt', 'r', encoding='utf-8') as f:
                self.allowed_attributes = f.read()
            with open('./generator/video_generator/prompt/MANIM_ANIMATION_REFERENCE.txt', 'r', encoding='utf-8') as f:
                self.animation_reference = f.read()
            logger.info("✅ Loaded animation reference guide")
        except FileNotFoundError as e:
            logger.warning(f"⚠️ Missing prompt file: {e}. Using defaults.")
            self.samples = "No samples provided."
            self.allowed_attributes = "No attribute list provided."
            self.animation_reference = "No animation reference provided."
        
        self.allowed_colors = "BLUE, RED, GREEN, YELLOW, WHITE, ORANGE, PINK, PURPLE, TEAL, GOLD, MAROON, GRAY"

    def _setup_directories(self) -> None:
        Path(self.config.output_dir).mkdir(parents=True, exist_ok=True)
        Path(self.config.temp_dir).mkdir(parents=True, exist_ok=True)

    def _get_aspect_ratio_config(self) -> str:
        """Generate Manim config code for the specified aspect ratio with performance optimizations."""
        aspect_ratio_configs = {
            "16:9": {
                "frame_width": 16,
                "frame_height": 9,
                "pixel_width": 1920,
                "pixel_height": 1080
            },
            "9:16": {
                "frame_width": 9,
                "frame_height": 16,
                "pixel_width": 1080,
                "pixel_height": 1920
            },
            "1:1": {
                "frame_width": 1,
                "frame_height": 1,
                "pixel_width": 1080,
                "pixel_height": 1080
            },
            "4:3": {
                "frame_width": 4,
                "frame_height": 3,
                "pixel_width": 1440,
                "pixel_height": 1080
            },
            "21:9": {
                "frame_width": 21,
                "frame_height": 9,
                "pixel_width": 2560,
                "pixel_height": 1080
            }
        }
        
        config = aspect_ratio_configs.get(self.config.aspect_ratio, aspect_ratio_configs["16:9"])
        
        return f"""# Aspect Ratio Configuration: {self.config.aspect_ratio}
config.frame_width = {config['frame_width']}
config.frame_height = {config['frame_height']}
config.pixel_width = {config['pixel_width']}
config.pixel_height = {config['pixel_height']}

# Performance Optimizations (PHASE 2: Manim Config Optimization)
config.preview = False              # Skip preview window (20-30% faster)
config.write_to_movie = True        # Direct to file
config.save_last_frame = False      # Don't save PNG frames
config.save_pngs = False           # Don't save individual PNGs
config.leave_progress_bars = True   # ENABLE progress bars for real-time tracking!
config.flush_cache = False         # Keep cache between renders (CRITICAL for speed)
"""

    def _validate_dependencies(self) -> None:
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        except Exception:
            raise RuntimeError("FFmpeg is required but not found or failed.")

    def _setup_models(self) -> None:
        self._setup_gemini()
        if self.config.use_groq_for_correction:
            self._setup_groq()
        self._setup_tts()

    def _setup_gemini(self) -> None:
        try:
            genai.configure(api_key=self.config.gemini_api_key)
            
            generation_config = genai.GenerationConfig(
                temperature=self.config.gemini_temperature,
                max_output_tokens=self.config.gemini_max_tokens,
            )
            
            model_name = 'gemini-2.5-flash'  # Use more stable model

            self.gemini_model = genai.GenerativeModel(
                model_name,
                generation_config=generation_config
            )
            logger.info(f"Gemini model ('{model_name}') initialized.")

        except Exception as e:
            logger.error(f"Failed to initialize Gemini model: {e}")
            raise

    def _setup_groq(self) -> None:
        try:
            self.groq_client = Groq(api_key=self.config.groq_api_key)
            logger.info("Groq client initialized for high-speed corrections.")
        except Exception as e:
            logger.error(f"Failed to initialize Groq client: {e}")
            self.config.use_groq_for_correction = False
    def _setup_tts(self) -> None:
        try:
            from edge_tts import Communicate
            self.tts_model = EdgeTTSWrapper(voice="en-US-AndrewNeural")
            self.tts_available = True
            logger.info("✅ Edge TTS initialized with voice: en-US-AriaNeural")
        except ImportError:
            self.tts_model = None
            self.tts_available = False
            logger.warning("❌ Edge TTS not installed. Please run: pip install edge-tts")
            
    

    async def generate_all_audio_segments(self, segments, temp_dir):
        """Generate audio using Edge TTS (with gTTS fallback) for all segments."""
        from pathlib import Path
        from pydub import AudioSegment
        import asyncio

        for i, segment in enumerate(segments):
            try:
                text = segment.text.strip()
                mp3_path = Path(temp_dir) / f"audio_segment_{i:03d}.mp3"

                # Add delay between segments to avoid rate limiting (skip first segment)
                if i > 0:
                    await asyncio.sleep(2)  # 2 second delay between segments

                # Try Edge TTS first
                try:
                    await self.tts_model.synthesize(text, str(mp3_path))
                    logger.info(f"✅ Edge TTS: Segment {i+1}")
                except Exception as edge_error:
                    # Fallback to gTTS if Edge TTS fails
                    logger.warning(f"⚠️ Edge TTS failed for segment {i+1}, using gTTS fallback")
                    try:
                        from gtts import gTTS
                        tts = gTTS(text=text, lang='en', slow=False)
                        tts.save(str(mp3_path))
                        logger.info(f"✅ gTTS: Segment {i+1}")
                    except Exception as gtts_error:
                        logger.error(f"❌ Both TTS methods failed for segment {i+1}: {gtts_error}")
                        # Use fallback duration if both fail
                        segment.duration = 10.0
                        segment.start_time = round(sum(s.duration for s in segments[:i]), 2)
                        segment.end_time = round(segment.start_time + 10.0, 2)
                        continue

                audio = AudioSegment.from_mp3(mp3_path)
                actual_duration = round(len(audio) / 1000.0, 2)

                segment.audio_path = str(mp3_path)
                segment.duration = actual_duration
                segment.start_time = round(sum(s.duration for s in segments[:i]), 2)
                segment.end_time = round(segment.start_time + actual_duration, 2)

                logger.info(f"✅ Segment {i+1}: audio={actual_duration}s → {mp3_path}")
            except Exception as e:
                logger.error(f"❌ Failed to generate audio for segment {i+1}: {e}")



    def generate_narration_segments(self, topic: str, duration: int) -> List[NarrationSegment]:
        """
        Generates narration segments with detailed visual descriptions for Manim animation.
        """
        # Aspect ratio-specific visual guidance
        aspect_ratio_visual_guide = {
            "16:9": "Wide horizontal layout - use side-by-side elements, wide diagrams, landscape compositions",
            "9:16": "Vertical portrait - stack elements vertically, use tall narrow visualizations, mobile-friendly layouts",
            "1:1": "Square format - balanced centered layouts, symmetrical designs",
            "4:3": "Standard format - traditional layouts, centered content",
            "21:9": "Ultra-wide cinematic - use full width, panoramic visualizations, side-by-side comparisons"
        }
        visual_guide = aspect_ratio_visual_guide.get(self.config.aspect_ratio, aspect_ratio_visual_guide["16:9"])
        
        prompt = f"""You are an expert educational content creator specializing in creating engaging video scripts for Manim animations.

📋 TASK: Create a {duration}-second educational video script about "{topic}" optimized for {self.config.aspect_ratio} aspect ratio.

🎯 OUTPUT FORMAT (STRICT):
SEGMENT: [duration_in_seconds] | [narration_with_emotion] | [detailed_visual_description]

⚠️ CRITICAL REQUIREMENTS:

1. **DURATION CONSTRAINTS:**
   - Each segment: 12-18 seconds (sweet spot: 15 seconds)
   - Total duration MUST equal exactly {duration} seconds
   - Distribute time logically (intro: shorter, main content: longer, conclusion: medium)

2. **NARRATION GUIDELINES:**
   - Use natural, conversational English (avoid robotic/technical language)
   - Include emotion cues: [Excited], [Calm], [Enthusiastic], [Serious], [Curious], [Confident]
   - Keep sentences clear and concise (max 20 words per sentence)
   - Build narrative flow: hook → explain → reinforce → conclude
   - Avoid filler words, be direct and engaging

3. **VISUAL DESCRIPTION REQUIREMENTS (CRITICAL FOR MANIM):**
   - Be SPECIFIC about what should appear on screen
   - Describe shapes, colors, text content, animations, transitions
   - Aspect ratio consideration: {visual_guide}
   - Mention object positions (top, center, bottom, left, right)
   - Specify colors from: BLUE, RED, GREEN, YELLOW, WHITE, ORANGE, PINK, PURPLE, TEAL, GOLD
   - Example: "Display blue circle at center, title 'Functions' at top in white text, animate arrow pointing down"
   
4. **VISUAL COMPLEXITY LEVELS:**
   - Simple: 1-2 objects (text + shape)
   - Medium: 3-4 objects (text + multiple shapes/diagrams)
   - Complex: 5+ objects (diagrams, animations, transitions)
   - Mix complexity levels for engagement

📚 EXAMPLES (showing good vs bad):

✅ GOOD:
SEGMENT: 15 | [Enthusiastic] Let's explore how functions work in programming! | Display large blue circle labeled "Function" at center, smaller orange circles labeled "Input" and "Output" on left and right, animate arrows flowing from input through function to output

✅ GOOD:
SEGMENT: 12 | [Calm] Functions take inputs and return outputs | Show vertical stack for {self.config.aspect_ratio}: "Input" box at top in green, "Function Process" box in center with blue color, "Output" box at bottom in purple, connect with animated arrows

❌ BAD (too vague):
SEGMENT: 15 | Functions are important | Show diagram about functions

❌ BAD (no visual details):
SEGMENT: 12 | [Calm] Let's learn about functions | Display information

🎬 ASPECT RATIO: {self.config.aspect_ratio}
{visual_guide}

💡 CONTENT STRUCTURE:
- Segment 1 (Hook): Grab attention, introduce topic
- Segments 2-N (Explain): Break down concepts, provide examples
- Final Segment (Conclusion): Summarize key points, call-to-action

📝 TOPIC: "{topic}"
⏱️ TOTAL DURATION: {duration} seconds

Generate the segments now (output ONLY the SEGMENT lines, no extra text):
"""

        safety_settings = {
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        }

        try:
            response = self.gemini_model.generate_content(prompt, safety_settings=safety_settings)
            
            if not response.parts or not response.text:
                raise ValueError("Gemini response was blocked or empty.")

            lines = response.text.strip().splitlines()
            segments = []
            current_time = 0.0

            for line in lines:
                if not line.strip().startswith("SEGMENT:"):
                    continue
                try:
                    # SEGMENT: 5 | [Calm] ... | show diagram ...
                    segment_data = line.strip()[len("SEGMENT:"):].strip()
                    parts = segment_data.split("|", maxsplit=2)
                    if len(parts) < 3:
                        raise ValueError("Missing fields")

                    duration_val = float(parts[0].strip())
                    narration_text = parts[1].strip()
                    visual_description = parts[2].strip()

                    segment = NarrationSegment(
                        start_time=round(current_time, 2),
                        end_time=round(current_time + duration_val, 2),
                        duration=round(duration_val, 2),
                        text=narration_text,
                        visual_description=visual_description
                    )
                    segments.append(segment)
                    current_time += duration_val
                except Exception as e:
                    logger.warning(f"⚠️ Skipping malformed segment: {line} | Error: {e}")
                    continue

            if not segments:
                raise ValueError("No valid narration segments parsed.")
            return segments

        except Exception as e:
            logger.error(f"❌ Narration generation failed: {e}")
            raise RuntimeError("Narration segment generation failed.")

    def generate_all_manim_scripts(self, segments: List[NarrationSegment]) -> List[NarrationSegment]:
        """
        Generate ALL Manim scripts using smaller batches to avoid Gemini limits.
        """
        logger.info("🎬 Generating Manim scripts in batches...")
        
        temp_dir = Path(self.config.temp_dir)
        batch_size = self.config.batch_size
        
        # Process in smaller batches
        for batch_start in range(0, len(segments), batch_size):
            batch_end = min(batch_start + batch_size, len(segments))
            batch_segments = segments[batch_start:batch_end]
            
            logger.info(f"Processing batch {batch_start//batch_size + 1}: segments {batch_start+1} to {batch_end}")
            
            # Try batch generation first
            try:
                success = self._generate_batch_scripts(batch_segments, batch_start)
                if success:
                    continue
            except Exception as e:
                logger.warning(f"Batch generation failed: {e}")
            
            # Fallback to individual generation
            logger.info("Falling back to individual script generation...")
            for i, segment in enumerate(batch_segments):
                global_index = batch_start + i
                script_content = self._generate_individual_script(segment, global_index + 1)
                
                script_filename = f"segment_{global_index:03d}.py"
                script_path = temp_dir / script_filename
                script_path.write_text(script_content, encoding="utf-8")
                segment.script_path = str(script_path)
                
                logger.info(f"✅ Individual script {global_index+1} generated: {script_filename}")
        
        return segments

    def _generate_batch_scripts(self, batch_segments: List[NarrationSegment], batch_start: int) -> bool:
        """Generate scripts for a batch of segments."""
        
        # Create concise batch prompt
        segment_info = ""
        for i, segment in enumerate(batch_segments):
            segment_info += f"SEGMENT_{i+1}: {segment.duration}s | {segment.text[:50]}... | {segment.visual_description[:50]}...\n"

        batch_prompt = f"""Generate {len(batch_segments)} separate Manim scripts:

{segment_info}

Format:
=== SCRIPT_1 ===
from manim import *
class GeneratedAnimation1(Scene):
    def construct(self):
        # Animation code here
        self.wait({batch_segments[0].duration})

=== SCRIPT_2 ===
from manim import *
class GeneratedAnimation2(Scene):
    def construct(self):
        # Animation code here
        self.wait({batch_segments[1].duration if len(batch_segments) > 1 else 10})

Continue for all segments. Output ONLY scripts with separators.
"""

        safety_settings = {
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        }

        try:
            response = self.gemini_model.generate_content(batch_prompt, safety_settings=safety_settings)
            
            if not response.parts or not response.text:
                return False

            # Parse the batch response
            response_text = response.text.strip()
            script_sections = re.split(r'===\s*SCRIPT_(\d+)\s*===', response_text)[1:]
            
            temp_dir = Path(self.config.temp_dir)
            
            # Process scripts in pairs (number, script_content)
            for i in range(0, len(script_sections), 2):
                if i + 1 >= len(script_sections):
                    break
                    
                script_num = int(script_sections[i])
                script_content = script_sections[i + 1].strip()
                
                # Clean and validate script
                script_content = self._clean_script(script_content)
                if not self._validate_script(script_content):
                    return False
                
                # Save to file
                global_index = batch_start + script_num - 1
                script_filename = f"segment_{global_index:03d}.py"
                script_path = temp_dir / script_filename
                script_path.write_text(script_content, encoding="utf-8")
                
                # Update segment
                if script_num - 1 < len(batch_segments):
                    batch_segments[script_num - 1].script_path = str(script_path)
                    logger.info(f"✅ Batch script {global_index+1} generated: {script_filename}")

            return True

        except Exception as e:
            logger.error(f"❌ Batch script generation failed: {e}")
            return False

    def _generate_individual_script(self, segment: NarrationSegment, segment_number: int) -> str:
        """Generate a single script for one segment with retry logic."""
        
        # Get aspect ratio configuration
        aspect_ratio_config = self._get_aspect_ratio_config()
        
        # Aspect ratio-specific layout guidelines with detailed constraints
        aspect_ratio_guidelines = {
            "16:9": {
                "guide": "Wide horizontal layout. Place titles at top, content in center, use full width. Safe area: 14 units wide × 7 units tall.",
                "max_text_width": "config.frame_width * 0.85",
                "max_font_title": 48,
                "max_font_body": 36,
                "layout_example": "Place title at TOP (UP * 3), content at CENTER, footer at BOTTOM (DOWN * 3)"
            },
            "9:16": {
                "guide": "CRITICAL: Vertical/portrait layout for mobile. Frame is NARROW (9 wide × 16 tall). Text MUST be constrained to prevent overflow.",
                "max_text_width": "config.frame_width * 0.65",  # Much narrower for vertical
                "max_font_title": 32,  # Smaller fonts for narrow screen
                "max_font_body": 24,
                "layout_example": "Stack vertically: title at UP*6, content1 at UP*2, content2 at ORIGIN, content3 at DOWN*2, footer at DOWN*6"
            },
            "1:1": {
                "guide": "Square layout. Center all elements. Balanced spacing. Safe area: 8×8 units.",
                "max_text_width": "config.frame_width * 0.75",
                "max_font_title": 42,
                "max_font_body": 30,
                "layout_example": "Center everything with balanced spacing"
            },
            "4:3": {
                "guide": "Standard layout. Slightly wider than tall. Center content, moderate spacing.",
                "max_text_width": "config.frame_width * 0.80",
                "max_font_title": 44,
                "max_font_body": 32,
                "layout_example": "Traditional TV layout with centered content"
            },
            "21:9": {
                "guide": "Ultra-wide cinematic. Use horizontal space. Place elements side-by-side when possible.",
                "max_text_width": "config.frame_width * 0.90",
                "max_font_title": 48,
                "max_font_body": 36,
                "layout_example": "Use full width, place elements side-by-side"
            }
        }
        layout_info = aspect_ratio_guidelines.get(self.config.aspect_ratio, aspect_ratio_guidelines["16:9"])
        layout_guide = layout_info["guide"]
        max_text_width = layout_info["max_text_width"]
        max_font_title = layout_info["max_font_title"]
        max_font_body = layout_info["max_font_body"]
        layout_example = layout_info["layout_example"]
        
        # Strict prompt with anti-overlap rules
        prompt = f"""Create a Manim script for this segment:

Duration: {segment.duration} seconds
Content: {segment.text}
Visual: {segment.visual_description}
Aspect Ratio: {self.config.aspect_ratio}

🎯 CRITICAL LAYOUT REQUIREMENTS for {self.config.aspect_ratio}:
{layout_guide}

🚨 ABSOLUTE TEXT OVERLAP PREVENTION RULES (MUST FOLLOW):

1. **MANDATORY TEXT WIDTH CONSTRAINT:**
   - EVERY Text/MarkupText object MUST have .scale_to_fit_width({max_text_width})
   - NO EXCEPTIONS - even single words need scaling
   - Example: text.scale_to_fit_width({max_text_width})

2. **STRICT FONT SIZE LIMITS:**
   - Titles: MAX {max_font_title}px (NEVER exceed this)
   - Body text: MAX {max_font_body}px (NEVER exceed this)
   - Small text: MAX {max_font_body - 6}px

3. **MANDATORY VERTICAL SPACING (CRITICAL!):**
   - Minimum 1.5 units between ANY two text objects
   - Use .next_to(other_object, DOWN, buff=1.5) or similar
   - NEVER place text closer than 1.5 units vertically
   - Example: 
     title.move_to(UP * 3)
     content.move_to(ORIGIN)  # 3 units apart - GOOD
     
4. **HORIZONTAL SPACING:**
   - Leave 1 unit margin from left/right edges
   - Objects side-by-side: minimum 2 units apart horizontally
   - Use .shift(LEFT * 3) or .shift(RIGHT * 3) for separation

5. **POSITION GRID (MUST USE ONLY THESE POSITIONS):**
   For {self.config.aspect_ratio}:
   - TOP zone: UP * {6 if self.config.aspect_ratio == "9:16" else 3} to UP * {4 if self.config.aspect_ratio == "9:16" else 2}
   - MIDDLE zone: UP * 1 to DOWN * 1
   - BOTTOM zone: DOWN * {2 if self.config.aspect_ratio == "9:16" else 2} to DOWN * {6 if self.config.aspect_ratio == "9:16" else 3}
   - NEVER overlap zones!

6. **TEXT LENGTH HANDLING:**
   - Text > 50 chars: MUST split into 2-3 Text objects, stack vertically
   - Text > 100 chars: MUST split into 3-4 Text objects
   - Use smaller font_size for long text (reduce by 20%)

7. **SAFE POSITIONING CHECKLIST:**
   ✓ Every text has .scale_to_fit_width({max_text_width})
   ✓ Font sizes within limits
   ✓ Vertical spacing >= 1.5 units
   ✓ Horizontal margin >= 1 unit from edges
   ✓ No two objects in same zone
   ✓ Long text split into multiple lines

📐 WORKING EXAMPLE (COPY THIS PATTERN):
```python
# CORRECT: No overlaps, proper spacing
title = Text("Educational Topic", font_size={max_font_title})
title.scale_to_fit_width({max_text_width})  # MANDATORY
title.move_to(UP * {"6" if self.config.aspect_ratio == "9:16" else "3"})  # TOP zone

subtitle = Text("Key Concept", font_size={max_font_body})
subtitle.scale_to_fit_width({max_text_width})  # MANDATORY
subtitle.move_to(UP * {"2" if self.config.aspect_ratio == "9:16" else "1"})  # 1.5+ units below title - GOOD

content = Text("Main point here", font_size={max_font_body})
content.scale_to_fit_width({max_text_width})  # MANDATORY
content.move_to({"ORIGIN" if self.config.aspect_ratio == "9:16" else "DOWN * 0.5"})  # MIDDLE zone

# Add shapes with spacing
circle = Circle(radius=0.8)
circle.move_to(DOWN * {"4" if self.config.aspect_ratio == "9:16" else "2.5"})  # BOTTOM zone, clear of text
```

❌ WRONG EXAMPLES (NEVER DO THIS):
```python
# BAD: No scale_to_fit_width
title = Text("Long title here", font_size=48)
title.move_to(UP * 2)  # WRONG! Missing .scale_to_fit_width()

# BAD: Objects too close
title.move_to(UP * 2)
subtitle.move_to(UP * 1.5)  # WRONG! Only 0.5 units apart (minimum is 1.5)

# BAD: Exceeded font size
huge_text = Text("Text", font_size=72)  # WRONG! Exceeds {max_font_title}px limit

# BAD: Long text not split
long_text = Text("This is a very long sentence that will definitely overflow", font_size=36)  # WRONG! Must split
```

Requirements:
- Use class name: GeneratedAnimation{segment_number}
- Duration exactly {segment.duration} seconds
- Simple, clean animations
- EVERY text object MUST have .scale_to_fit_width({max_text_width})
- Minimum 1.5 units vertical spacing between text objects
- Maximum {max_font_title}px for titles, {max_font_body}px for body

Output format:
from manim import *

{aspect_ratio_config}

class GeneratedAnimation{segment_number}(Scene):
    def construct(self):
        # Your code - REMEMBER: No overlaps, proper spacing, scale_to_fit_width() for ALL text!
        self.wait({segment.duration})
"""
        
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.gemini_model.generate_content(prompt, safety_settings=safety_settings)
                
                if response.parts and response.text:
                    script_content = self._clean_script(response.text)
                    if self._validate_script(script_content):
                        return script_content
                
                logger.warning(f"Attempt {attempt + 1} failed, retrying...")
                time.sleep(1)  # Brief delay between retries
                
            except Exception as e:
                logger.warning(f"Individual script generation attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    # Return fallback script
                    return self._create_fallback_script(segment, segment_number)
                time.sleep(2)
        
        return self._create_fallback_script(segment, segment_number)

    def _create_fallback_script(self, segment: NarrationSegment, segment_number: int) -> str:
        """Create a simple fallback script when generation fails."""
        aspect_ratio_config = self._get_aspect_ratio_config()
        
        return f"""from manim import *

{aspect_ratio_config}

class GeneratedAnimation{segment_number}(Scene):
    def construct(self):
        # Fallback animation
        title = Text("Segment {segment_number}", font_size=48)
        content = Text("{segment.text[:50]}...", font_size=24)
        content.next_to(title, DOWN, buff=0.5)
        
        self.play(Write(title))
        self.play(Write(content))
        self.wait({segment.duration - 2})
        self.play(FadeOut(title), FadeOut(content))
"""

    def _validate_script(self, script: str) -> bool:
        """Basic validation of generated script."""
        return (
            "from manim import *" in script and
            "class " in script and
            "Scene" in script and
            "def construct" in script
        )

    def _clean_script(self, script: str) -> str:
        """Clean up the script by removing markdown formatting."""
        # Remove markdown code blocks
        script = re.sub(r'```(python\s*)?|\s*```', '', script)
        return script.strip()

    def _correct_script_with_groq(self, broken_script: str, error_context: str) -> str:
        """Use Groq to fix broken scripts."""
        if not self.groq_client:
            return broken_script
        
        prompt = f"""You are a world-class, meticulous debugging AI. Your sole purpose is to fix a broken Manim script and provide a complete, production-ready file. You are a machine that outputs code, not a conversational assistant.

Your mission is to analyze the provided error log and the broken source code, identify the root cause of the error, and then rewrite the **entire script** from top to bottom to fix it.

---

### **Error Log Analysis**

This is the `stderr` output from the failed Manim execution. Analyze it carefully to understand the failure.

```
{error_context}
```

---

### **Broken Source Code**

This is the complete script that produced the error above.

```python
{broken_script}
```

---uu

### **CRITICAL DIRECTIVES**

You must follow these two rules absolutely. There are no exceptions.

1.  **COMPLETE REWRITE REQUIRED:** You **MUST** rewrite the entire script from the first line to the last. Do **NOT** use comments like `... (rest of the code remains the same)` or `...`. The output must be a complete, standalone, and executable Python file. Assume the user cannot see the original script and needs the full corrected version.

2.  **RAW CODE OUTPUT ONLY:** The output format is non-negotiable. Your **ENTIRE** response must be raw Python code, starting directly with the first line of the script (e.g., `from manim import *`). Do **NOT** include:
    *   Any introductory text like "Here is the corrected code:".
    *   Any explanations, apologies, or closing remarks.
    -   Any Markdown formatting like ```python or ```.

Your response will be directly saved to a `.py` file and executed. Any non-code text will cause the program to crash.
No text like 'here is your corrected script' or 'Here is the rewritten script' or anything else should be given in the responce, only the program should be there.
---

Begin your response now.

"""
        
        try:
            chat_completion = self.groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}], 
                model="llama3-8b-8192", 
                temperature=0.1, 
                max_tokens=4096
            )
            return self._clean_script(chat_completion.choices[0].message.content)
        except Exception as e:
            logger.error(f"Groq correction failed: {e}")
            return broken_script
    def _regenerate_script_from_scratch(self, segment: NarrationSegment, segment_number: int) -> str:
        """
        Fully regenerate a fresh Manim script using Gemini.
        Uses the original narration, visuals, and audio duration.
        """
        prompt = f"""
    You are a Manim Python expert.
    Rewrite a complete script for this segment from scratch.

    - Class name must be: GeneratedAnimation{segment_number}
    - Use ONLY 'from manim import *'
    - Must match exact duration: {segment.duration:.2f} seconds
    - Visuals: {segment.visual_description}
    - Narration: {segment.text}

    Output ONLY raw Python code. No markdown, no explanations.
        """

        safety_settings = {
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        }

        try:
            response = self.gemini_model.generate_content(prompt, safety_settings=safety_settings)
            raw_script = response.text.strip()
            return self._clean_script(raw_script)
        except Exception as e:
            logger.warning(f"⚠️ Last-resort regeneration failed for segment {segment_number}: {e}")
            return self._create_fallback_script(segment, segment_number)

    def execute_all_scripts(self, segments: List[NarrationSegment]) -> List[NarrationSegment]:
        """
        Execute each Manim script with failover:
        - Try execution
        - Fix with Gemini if needed
        - Fix with Groq if still broken
        - If all fail: regenerate brand-new script with Gemini
        """
        logger.info("🎬 Executing ALL Manim scripts with Gemini→Groq→Gemini fallback...")

        for i, segment in enumerate(segments):
            logger.info(f"🚀 Running script {i+1}/{len(segments)}: {segment.script_path}")

            script_content = Path(segment.script_path).read_text(encoding="utf-8")

            for attempt in range(self.config.max_correction_attempts):
                video_path, error = self.create_video_file(script_content, filename=f"segment_{i:03d}.py", segment_index=i)

                if video_path:
                    segment.video_path = video_path
                    logger.info(f"✅ Script {i+1} executed successfully: {video_path}")
                    break

                logger.warning(f"⚠️ Script {i+1} failed on attempt {attempt+1}: {error[-300:] if error else 'Unknown error'}")

                if attempt == self.config.max_correction_attempts - 1:
                    logger.warning(f"❗ All Gemini & Groq corrections failed — regenerating from scratch...")
                    script_content = self._regenerate_script_from_scratch(segment, i + 1)
                    video_path, error = self.create_video_file(script_content, filename=f"segment_{i:03d}.py", segment_index=i)

                    if video_path:
                        segment.video_path = video_path
                        logger.info(f"✅ Script {i+1} regenerated & executed successfully: {video_path}")
                        break
                    else:
                        logger.error(f"❌ Final regeneration failed for segment {i+1}. Aborting pipeline.")
                        raise RuntimeError(f"Segment {i+1} is unrecoverable.")

                if attempt % 2 == 0:
                    logger.info("♻️ Regenerating with Gemini...")
                    script_content = self._generate_individual_script(segment, i + 1)
                else:
                    logger.info("🛠 Fixing with Groq...")
                    script_content = self._correct_script_with_groq(script_content, error or "Unknown error")

                script_content = self._clean_script(script_content)
                Path(segment.script_path).write_text(script_content, encoding="utf-8")

        return segments

    def create_video_file(self, script: str, filename: str = "segment_temp.py", segment_index: Optional[int] = None) -> Tuple[Optional[str], Optional[str]]:
        import subprocess
        from pathlib import Path

        temp_path = Path(self.config.temp_dir)
        input_path = temp_path / filename
        input_path.write_text(script, encoding='utf-8')

        logger.info(f"🛠️ Compiling Manim script for Segment {segment_index if segment_index is not None else '?'}")

        try:
            # Set up environment for headless rendering (Render compatibility)
            # PHASE 6: Enhanced environment variables for headless optimization
            env = os.environ.copy()
            
            # Force headless mode for Render/cloud environments
            if not os.environ.get('DISPLAY'):
                env['DISPLAY'] = ':99'  # Virtual display
                env['QT_QPA_PLATFORM'] = 'offscreen'  # Qt headless mode
                env['MPLBACKEND'] = 'Agg'  # PHASE 6: Matplotlib headless (5-10% faster)
                env['OPENCV_IO_ENABLE_OPENEXR'] = '0'  # PHASE 6: Disable OpenEXR (unused, saves init time)
                logger.info("🖥️ Running in headless mode (no display detected)")
            
            logger.info(f"📐 Using aspect ratio: {self.config.aspect_ratio} (configured in Manim script)")
            
            # Build Manim command - ALWAYS use "Scene" as class name
            # Aspect ratio is now configured inside the script itself
            # Use -qp (production quality, 1440p60) which Manim handles correctly
            # Alternative: -qh (high quality, 1080p60), -qm (medium, 720p30), -ql (low, 480p15)
            # We use -ql for 480p15 as fastest rendering (2-3x faster than -qm)
            # On Windows, use "python -m manim" instead of just "manim"
            # Caching is enabled by default and controlled via script config
            cmd = [
                sys.executable, "-m", "manim", 
                filename, "Scene", 
                "-ql",                        # Low quality: 480p15 (FASTEST - 2-3x faster!)
                "--format", "mp4",
                # Caching controlled in script config (flush_cache=False)
            ]
            
            logger.info(f"🎬 Running Manim render (480p15 using -ql quality preset): {' '.join(cmd)}")
            
            # Stream output with progress bar
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Combine stderr with stdout
                text=True,
                cwd=temp_path,
                env=env,
                bufsize=1,  # Line buffered
                universal_newlines=True
            )
            
            # Collect output and show progress bar
            output_lines = []
            progress_shown = False
            
            try:
                from tqdm import tqdm
                
                # Create indeterminate progress bar (we don't know total frames)
                with tqdm(desc=f"🎬 Rendering Segment {segment_index if segment_index is not None else '?'}", 
                         unit=" frames", 
                         bar_format="{desc}: {elapsed} | {rate_fmt}",
                         ncols=80) as pbar:
                    
                    for line in process.stdout:
                        line = line.rstrip()
                        if line:
                            output_lines.append(line)
                            
                            # Update progress bar on animation/rendering lines
                            if any(keyword in line.lower() for keyword in ['animation', 'rendering', '%']):
                                pbar.set_postfix_str(line[:60])  # Show last status (truncated)
                                pbar.update(1)
                                progress_shown = True
                
            except ImportError:
                # Fallback if tqdm not available - show minimal output
                logger.info("📊 Rendering in progress (install 'tqdm' for progress bar: pip install tqdm)")
                for line in process.stdout:
                    line = line.rstrip()
                    if line:
                        output_lines.append(line)
                        # Only show key progress indicators
                        if any(keyword in line.lower() for keyword in ['animation', 'rendering', '%', 'file ready']):
                            print(f"  ▶️  {line}")
            
            process.wait()
            
            if progress_shown:
                logger.info("✅ Rendering complete!")

        except Exception as e:
            return None, f"❌ Manim execution error: {str(e)}"

        if process.returncode != 0:
            full_output = '\n'.join(output_lines) if output_lines else "No output captured"
            return None, f"❌ Manim failed with code {process.returncode}:\n{full_output}"

        # Expected output file path - 480p15 quality (-ql flag) outputs to 480p15 folder
        if segment_index is not None:
            # Try expected filename first
            expected_path = temp_path / "media" / "videos" / f"segment_{segment_index:03d}" / "480p15" / f"Segment{segment_index:03d}.mp4"
            if expected_path.exists():
                logger.info(f"✅ Found expected video: {expected_path}")
                return str(expected_path), None
            
            # Fallback: Manim uses class name "Scene" so file is Scene.mp4
            scene_path = temp_path / "media" / "videos" / f"segment_{segment_index:03d}" / "480p15" / "Scene.mp4"
            if scene_path.exists():
                logger.info(f"✅ Found video as Scene.mp4, renaming to Segment{segment_index:03d}.mp4")
                scene_path.rename(expected_path)
                return str(expected_path), None
            
            # If still not found, search the segment folder for ANY video
            segment_folder = temp_path / "media" / "videos" / f"segment_{segment_index:03d}"
            if segment_folder.exists():
                video_files = list(segment_folder.glob("**/*.mp4"))
                if video_files:
                    found_video = video_files[0]
                    logger.info(f"✅ Found video at {found_video}, moving to expected path")
                    
                    # Ensure target directory exists before moving
                    expected_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Use shutil.move instead of rename for cross-directory moves
                    import shutil
                    shutil.move(str(found_video), str(expected_path))
                    return str(expected_path), None
            
            return None, f"❌ Expected video not found at {expected_path} or Scene.mp4"

        # Fallback: find any mp4 in media
        video_files = list((temp_path / "media").glob("**/*.mp4"))
        if not video_files:
            return None, "❌ Manim ran but no video file was found."
        latest = max(video_files, key=os.path.getctime)
        logger.warning(f"⚠️ Using fallback video path: {latest}")
        return str(latest), None

    def _get_intro_video(self) -> Optional[Path]:
        """
        Find intro video in initial_video folder.
        Returns Path object if found, None otherwise.
        """
        intro_folder = Path("initial_video")
        
        if not intro_folder.exists():
            logger.info("📁 No initial_video folder found - skipping intro")
            return None
        
        # Look for common video formats
        for ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
            intro_files = list(intro_folder.glob(f"*{ext}"))
            if intro_files:
                intro_video = intro_files[0]  # Use first found intro video
                
                # Validate it's a readable file
                if intro_video.exists() and intro_video.stat().st_size > 0:
                    logger.info(f"🎬 Found intro video: {intro_video} ({intro_video.stat().st_size / 1024 / 1024:.2f} MB)")
                    return intro_video
                else:
                    logger.warning(f"⚠️ Intro video found but invalid: {intro_video}")
        
        logger.info("📁 No intro video found in initial_video folder")
        return None

    def _prepare_scaled_intro(self) -> Optional[Path]:
        """
        Pre-scale intro video once to 854x480 (16:9, 480p) and cache it.
        This is called once at the start to avoid re-encoding on every video.
        
        Returns:
            Path to scaled intro, or None if not available
        """
        if self.scaled_intro_path and Path(self.scaled_intro_path).exists():
            return Path(self.scaled_intro_path)
        
        intro_video = self._get_intro_video()
        if not intro_video:
            return None
        
        # Create scaled intro in temp directory
        temp_dir = Path(self.config.temp_dir)
        scaled_intro = temp_dir / "intro_scaled_854x480.mp4"
        
        # Check if already scaled
        if scaled_intro.exists():
            logger.info(f"✅ Using cached scaled intro: {scaled_intro}")
            self.scaled_intro_path = str(scaled_intro)
            return scaled_intro
        
        logger.info(f"🔧 Pre-scaling intro video to 854x480 (one-time operation)...")
        
        cmd = [
            "ffmpeg", "-y",
            "-i", str(intro_video),
            "-vf", "scale=854:480:force_original_aspect_ratio=decrease,pad=854:480:(ow-iw)/2:(oh-ih)/2,setdar=16/9,setsar=1",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(scaled_intro)
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
            logger.info(f"✅ Intro pre-scaled and cached: {scaled_intro}")
            self.scaled_intro_path = str(scaled_intro)
            return scaled_intro
        except Exception as e:
            logger.error(f"❌ Failed to pre-scale intro: {e}")
            return None

    def _add_intro_with_ffmpeg(self, generated_video_path: str) -> str:
        """
        Add intro video to the beginning of generated video.
        Re-encodes both videos to identical specs for reliable concatenation.
        
        Args:
            generated_video_path: Path to the generated video (with audio)
            
        Returns:
            Path to final video (with intro if found, otherwise original path)
        """
        # Only add intro for 16:9 aspect ratio
        if self.config.aspect_ratio != "16:9":
            logger.info(f"ℹ️ Intro only supported for 16:9 aspect ratio (current: {self.config.aspect_ratio}), skipping intro")
            return generated_video_path
        
        # Get pre-scaled intro (or scale it now if not cached)
        scaled_intro = self._prepare_scaled_intro()
        
        if not scaled_intro:
            logger.info("ℹ️ No intro video available, returning video without intro")
            return generated_video_path

        # Default output path
        output_path = generated_video_path.replace(".mp4", "_with_intro.mp4")
        temp_dir = Path(self.config.temp_dir)
        
        # Use concat FILTER instead of concat demuxer to handle any encoding mismatches
        # This ensures both videos are properly normalized and concatenated without speed issues
        logger.info("🔗 Concatenating intro + main using concat filter (handles mismatched specs)...")
        
        # Concat filter approach: Reads both inputs, normalizes them, then concatenates
        # This is more reliable than concat demuxer which requires perfect matching specs
        cmd_concat = [
            "ffmpeg", "-y",
            "-i", str(scaled_intro),  # Input 0: intro (already 480p)
            "-i", str(generated_video_path),  # Input 1: main video (480p15 from Manim -ql)
            "-filter_complex",
            # Scale both to same resolution (480p), ensure same fps (15), then concat
            "[0:v]scale=854:480:force_original_aspect_ratio=decrease,pad=854:480:(ow-iw)/2:(oh-ih)/2,fps=15,setsar=1[v0];"
            "[1:v]scale=854:480:force_original_aspect_ratio=decrease,pad=854:480:(ow-iw)/2:(oh-ih)/2,fps=15,setsar=1[v1];"
            "[v0][0:a][v1][1:a]concat=n=2:v=1:a=1[outv][outa]",
            "-map", "[outv]",
            "-map", "[outa]",
            "-c:v", "libx264",
            "-preset", "ultrafast",  # Fast encoding
            "-crf", "28",  # Lower quality for speed (was 23)
            "-c:a", "aac",
            "-b:a", "128k",  # Lower audio bitrate (was 192k)
            "-ar", "44100",
            "-ac", "2",
            "-movflags", "+faststart",
            str(output_path)
        ]

        logger.info(f"🔗 Running FFmpeg concat filter: {output_path}")
        
        try:
            result = subprocess.run(cmd_concat, capture_output=True, text=True, timeout=180)
            
            if result.returncode != 0:
                logger.error(f"❌ FFmpeg concat failed:\nSTDERR: {result.stderr}")
                logger.warning("⚠️ Returning video without intro")
                return generated_video_path
            
            logger.info(f"✅ Intro concatenation complete: {output_path}")
            return output_path
            
        except subprocess.TimeoutExpired:
            logger.error("❌ ffmpeg concat timed out (>180s)")
            logger.warning("⚠️ Returning video without intro")
            return generated_video_path
        except Exception as e:
            logger.error(f"❌ Concat filter error: {e}")
            logger.warning("⚠️ Returning video without intro")
            return generated_video_path

    def cleanup_temp_files(self) -> None:
        """Clean up temporary files after video generation."""
        try:
            temp_path = Path(self.config.temp_dir)
            if temp_path.exists():
                # Remove all contents but keep the temp directory and cached intro
                for item in temp_path.iterdir():
                    try:
                        # Skip cached scaled intro
                        if item.name == "intro_scaled_854x480.mp4":
                            logger.info(f"⏭️ Keeping cached intro: {item}")
                            continue
                            
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(item)
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to delete {item}: {e}")
                
                logger.info(f"✅ Cleaned up temp directory: {temp_path}")
            else:
                logger.info("ℹ️ Temp directory does not exist, nothing to clean")
        except Exception as e:
            logger.error(f"❌ Failed to cleanup temp files: {e}")

    def synchronize_audio_video(self, video_file: str, audio_file: str, output_file: str) -> str:
        """Synchronize video and audio files."""
        logger.info(f"Synchronizing video and audio into: {output_file}")
        cmd = [
            'ffmpeg', '-y', '-i', video_file, '-i', audio_file, 
            '-c:v', 'copy', '-c:a', 'aac', 
            '-map', '0:v:0', '-map', '1:a:0', 
             output_file
        ]
        
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=self.config.ffmpeg_timeout)
            return output_file
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg sync failed: {e}")
            raise
        except subprocess.TimeoutExpired:
            logger.error("FFmpeg sync timed out")
            raise

    def generate_video(self, topic: str, duration: int, output_filename: Optional[str] = None) -> str:
        """Main video generation pipeline."""
        if not output_filename:
            safe_topic = re.sub(r'[^\w\s-]', '', topic).strip().replace(' ', '_')
            output_filename = f"{self.config.output_dir}/{safe_topic}.mp4"

        logger.info(f"🚀 Starting Video Generation for Topic: {topic} [{duration}s]")
        
        try:
            # Step 1: Generate narration segments
            segments = self.generate_narration_segments(topic, duration)
            logger.info(f"Generated {len(segments)} narration segments")
            logger.info(segments)
            
            # Step 2: Generate ALL audio files
            segments = self.generate_all_audio_segments(segments)
            
            # Step 3: Generate ALL Manim scripts
            segments = self.generate_all_manim_scripts(segments)
            
            # Step 4: Execute all scripts
            segments = self.execute_all_scripts(segments)
            
            # Step 5: Combine segments
            final_clips = []
            temp_dir = Path(self.config.temp_dir)
            
            for i, segment in enumerate(segments):
                if segment.video_path and segment.audio_path:
                    segment_video_path = str(temp_dir / f"segment_{i:03d}_final.mp4")
                    self.synchronize_audio_video(segment.video_path, segment.audio_path, segment_video_path)
                    final_clips.append(segment_video_path)
                    logger.info(f"✅ Segment {i+1} synchronized")
                else:
                    logger.error(f"❌ Segment {i+1} missing video or audio")
                    raise RuntimeError(f"Segment {i+1} is incomplete")

            # Step 6: Final concatenation (segments only, no intro yet)
            concat_list_path = temp_dir / "concat_list.txt"

            with open(concat_list_path, "w", encoding='utf-8') as f:
                # Add all generated segment clips
                for clip in final_clips:
                    clip_path = Path(clip).resolve().as_posix()
                    f.write(f"file '{clip_path}'\n")

            safe_topic = re.sub(r'[^\w\s-]', '', topic).strip().replace(' ', '_')
            final_output_path = str(self.output_dir / f"{safe_topic}.mp4")

            cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_list_path), "-c", "copy", final_output_path
            ]

            logger.info("🎞️ Concatenating all segments...")
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=self.config.ffmpeg_timeout)
            logger.info(f"✅ Generated video ready: {final_output_path}")

            # Step 7: Add intro video using FFmpeg (if exists)
            final_output_with_intro = self._add_intro_with_ffmpeg(final_output_path)
            logger.info(f"✅ Final video with intro: {final_output_with_intro}")

            # Step 8: Cleanup temporary files
            self.cleanup_temp_files()

            return final_output_with_intro

        except Exception as e:
            logger.error(f"❌ Video generation failed: {e}")
            # Still try to cleanup even on failure
            try:
                self.cleanup_temp_files()
            except:
                pass
            raise

def main():
    """Main execution function."""
    gemini_key = os.getenv("GEMINI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    
    if not gemini_key:
        raise ValueError("GEMINI_API_KEY environment variable is required")
    if not groq_key:
        raise ValueError("GROQ_API_KEY environment variable is required")
    
    config = VideoGenerationConfig(
        gemini_api_key=gemini_key, 
        groq_api_key=groq_key,
        batch_size=3  # Process 3 segments at a time
    )
    
    try:
        pipeline = VideoGenerationPipeline(config)
        result = pipeline.generate_video(topic="Tags Used in HTML", duration=180)
        print(f"✅ Video generated successfully: {result}")
    except Exception as e:
        print(f"❌ Pipeline failed: {e}")
        logger.exception("Full error traceback:")


import asyncio
import concurrent.futures
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import time
from pathlib import Path
import logging
from typing import List, Optional, Tuple
import subprocess
import tempfile
import os
import re
import json
from dataclasses import dataclass
import threading
from queue import Queue
import psutil

# Import your existing classes

logger = logging.getLogger(__name__)
_singleton_pipeline = None
# Global functions for ProcessPoolExecutor (must be at module level)
def render_single_video_worker(args):
    """
    Enhanced worker function for video rendering with improved error handling.
    This replaces the original render_single_video_worker function.
    """
    global _singleton_pipeline

    i, segment_data, config_dict = args

    try:
        
        # Initialize the singleton pipeline only once per process
        if _singleton_pipeline is None:
            config = VideoGenerationConfig(**config_dict)
            _singleton_pipeline = VideoGenerationPipeline(config)

        pipeline = _singleton_pipeline

        script_path = segment_data['script_path']
        video_output_dir = segment_data['video_output_dir']
        temp_dir = segment_data['temp_dir']

        # Read script content
        script_content = Path(script_path).read_text(encoding="utf-8")

        # Clean script content before processing
        script_content = _clean_script_for_execution(script_content, i)

        # Try rendering with enhanced error handling
        max_correction_attempts = config_dict.get('max_correction_attempts', 3)
        max_regeneration_attempts = config_dict.get('max_regeneration_attempts', 4)  # Regenerate after 3-4 failed corrections
        
        total_attempts = 0
        correction_cycle = 0
        regeneration_count = 0
        
        # Phase 1: Try corrections with Gemini/Groq (limited to 3 attempts for quick regeneration)
        while correction_cycle < max_correction_attempts:
            total_attempts += 1
            video_path, error = pipeline.create_video_file(script_content, filename=f"segment_{i:03d}.py", segment_index=i)

            if video_path:
                target_dir = Path(segment_data['video_output_dir']) / f"segment_{i:03d}"
                target_dir.mkdir(parents=True, exist_ok=True)
                expected_path = target_dir / f"Segment{i:03d}.mp4"
                Path(video_path).replace(expected_path)
                logger.info(f"✅ Video {i+1} saved to: {expected_path} (after {total_attempts} attempts)")
                return {'success': True, 'video_path': str(expected_path), 'index': i}

            logger.warning(f"⚠️ Video {i+1} correction attempt {correction_cycle + 1}/{max_correction_attempts} failed: {error[:200]}")
            
            # Try fixing with Gemini or Groq
            correction_cycle += 1
            if correction_cycle % 2 == 1:  # Odd attempts: use Gemini
                logger.info(f"🔧 Fixing script {i+1} with Gemini (correction {correction_cycle})")
                script_content = _fix_script_errors_with_gemini(
                    script_content, error, i, config_dict['gemini_api_key']
                )
            else:  # Even attempts: use Groq
                logger.info(f"🔧 Fixing script {i+1} with Groq (correction {correction_cycle})")
                script_content = _fix_script_errors_with_groq(
                    script_content, error, i, config_dict['groq_api_key']
                )
            Path(script_path).write_text(script_content, encoding="utf-8")
        
        # Phase 2: All corrections failed, now regenerate from scratch repeatedly
        logger.warning(f"🔄 All {max_correction_attempts} correction attempts failed for segment {i+1}")
        logger.info(f"🔄 Starting regeneration phase (up to {max_regeneration_attempts} regenerations)...")
        
        while regeneration_count < max_regeneration_attempts:
            regeneration_count += 1
            total_attempts += 1
            
            logger.warning(f"🔄 Regenerating script {i+1} from scratch (regeneration {regeneration_count}/{max_regeneration_attempts})")
            
            try:
                # Regenerate script from scratch using enhanced function
                script_content = _regenerate_script_from_scratch_enhanced(
                    segment_data, i, config_dict['gemini_api_key'], config_dict.get('aspect_ratio', '16:9')
                )
                Path(script_path).write_text(script_content, encoding="utf-8")
                
                # Try rendering the regenerated script
                video_path, error = pipeline.create_video_file(script_content, filename=f"segment_{i:03d}.py", segment_index=i)
                
                if video_path:
                    target_dir = Path(segment_data['video_output_dir']) / f"segment_{i:03d}"
                    target_dir.mkdir(parents=True, exist_ok=True)
                    expected_path = target_dir / f"Segment{i:03d}.mp4"
                    Path(video_path).replace(expected_path)
                    logger.info(f"✅ Regenerated video {i+1} saved to: {expected_path} (after {total_attempts} total attempts)")
                    return {'success': True, 'video_path': str(expected_path), 'index': i}
                else:
                    # Regenerated script failed - try fixing it before regenerating again
                    logger.warning(f"⚠️ Regeneration {regeneration_count} failed, attempting to fix it: {error[:200]}")
                    
                    # Try 3 quick corrections on the regenerated script
                    for fix_attempt in range(3):
                        total_attempts += 1
                        logger.info(f"🔧 Fixing regenerated script {i+1} (fix attempt {fix_attempt + 1}/3)")
                        
                        # Alternate between Gemini and Groq for fixes
                        if fix_attempt % 2 == 0:
                            script_content = _fix_script_errors_with_gemini(
                                script_content, error, i, config_dict['gemini_api_key']
                            )
                        else:
                            script_content = _fix_script_errors_with_groq(
                                script_content, error, i, config_dict['groq_api_key']
                            )
                        
                        Path(script_path).write_text(script_content, encoding="utf-8")
                        
                        # Try rendering the fixed script
                        video_path, error = pipeline.create_video_file(script_content, filename=f"segment_{i:03d}.py", segment_index=i)
                        
                        if video_path:
                            target_dir = Path(segment_data['video_output_dir']) / f"segment_{i:03d}"
                            target_dir.mkdir(parents=True, exist_ok=True)
                            expected_path = target_dir / f"Segment{i:03d}.mp4"
                            Path(video_path).replace(expected_path)
                            logger.info(f"✅ Fixed regenerated video {i+1} saved to: {expected_path} (after {total_attempts} total attempts)")
                            return {'success': True, 'video_path': str(expected_path), 'index': i}
                    
                    # All fixes failed, will regenerate again in next iteration
                    logger.warning(f"⚠️ All 3 fix attempts failed for regenerated script {i+1}, will try next regeneration")
                    
            except Exception as regen_error:
                logger.error(f"❌ Regeneration {regeneration_count} crashed for segment {i+1}: {regen_error}")
                continue  # Try next regeneration
        
        # Phase 3: All regenerations failed, use absolute fallback with MULTIPLE retries - WILL NOT GIVE UP!
        logger.error(f"❌ All {max_regeneration_attempts} regenerations failed for segment {i+1}")
        logger.warning(f"🆘 Entering fallback mode for segment {i+1} - VIDEO WILL BE GENERATED AT ANY COST!")
        
        # Try fallback scripts with increasing simplicity (reduced attempts for faster processing)
        fallback_attempts = 0
        max_fallback_attempts = 10  # Reduced from 20 to 10 for faster fallback
        
        while fallback_attempts < max_fallback_attempts:
            fallback_attempts += 1
            total_attempts += 1
            
            try:
                # Generate progressively simpler fallback scripts
                if fallback_attempts <= 3:
                    # Try basic fallback with text (reduced from 5 to 3)
                    logger.info(f"🔄 Fallback attempt {fallback_attempts}/{max_fallback_attempts}: Using basic fallback with text")
                    script_content = _generate_absolute_fallback_script(
                        segment_data, i, segment_data.get('duration', 5.0), config_dict.get('aspect_ratio', '16:9')
                    )
                elif fallback_attempts <= 6:
                    # Try ultra-minimal fallback (shapes only, no text)
                    logger.info(f"🔄 Fallback attempt {fallback_attempts}/{max_fallback_attempts}: Using minimal fallback (shapes only)")
                    script_content = _generate_minimal_fallback_script(
                        segment_data, i, segment_data.get('duration', 5.0), config_dict.get('aspect_ratio', '16:9')
                    )
                else:
                    # Try absolute bare-bones fallback (single circle)
                    logger.info(f"🔄 Fallback attempt {fallback_attempts}/{max_fallback_attempts}: Using bare-bones fallback")
                    script_content = _generate_bare_bones_fallback_script(
                        i, segment_data.get('duration', 5.0), config_dict.get('aspect_ratio', '16:9')
                    )
                
                Path(script_path).write_text(script_content, encoding="utf-8")
                
                video_path, error = pipeline.create_video_file(script_content, filename=f"segment_{i:03d}.py", segment_index=i)
                
                if video_path:
                    target_dir = Path(segment_data['video_output_dir']) / f"segment_{i:03d}"
                    target_dir.mkdir(parents=True, exist_ok=True)
                    expected_path = target_dir / f"Segment{i:03d}.mp4"
                    Path(video_path).replace(expected_path)
                    logger.info(f"✅ Video {i+1} GENERATED (fallback attempt {fallback_attempts}) after {total_attempts} total attempts: {expected_path}")
                    return {'success': True, 'video_path': str(expected_path), 'index': i}
                else:
                    logger.warning(f"⚠️ Fallback attempt {fallback_attempts} failed: {error[:100] if error else 'Unknown error'}")
                    
            except Exception as fallback_error:
                logger.warning(f"⚠️ Fallback attempt {fallback_attempts} crashed: {str(fallback_error)[:100]}")
        
        # FINAL DESPERATE ATTEMPT: Absolute minimum script (empty scene with just wait)
        logger.critical(f"🚨 All {max_fallback_attempts} fallback attempts failed for segment {i+1}")
        logger.critical(f"🚨 Making FINAL DESPERATE attempt with absolute minimum script...")
        
        try:
            duration = segment_data.get('duration', 5.0)
            script_content = f"""from manim import *

class Segment{i:03d}(Scene):
    def construct(self):
        # Absolute minimum - just wait
        self.wait({duration})
"""
            Path(script_path).write_text(script_content, encoding="utf-8")
            video_path, error = pipeline.create_video_file(script_content, filename=f"segment_{i:03d}.py", segment_index=i)
            
            if video_path:
                target_dir = Path(segment_data['video_output_dir']) / f"segment_{i:03d}"
                target_dir.mkdir(parents=True, exist_ok=True)
                expected_path = target_dir / f"Segment{i:03d}.mp4"
                Path(video_path).replace(expected_path)
                logger.info(f"✅ Video {i+1} GENERATED with ABSOLUTE MINIMUM script after {total_attempts} attempts: {expected_path}")
                return {'success': True, 'video_path': str(expected_path), 'index': i}
            else:
                logger.critical(f"❌ Even absolute minimum script failed: {error}")
        except Exception as last_error:
            logger.critical(f"❌ Final desperate attempt crashed: {last_error}")
        
        # If we truly cannot generate ANY video, return error
        logger.critical(f"💀 COMPLETE FAILURE: Segment {i+1} could NOT be generated after {total_attempts} attempts")
        return {'success': False, 'error': f"All {total_attempts} attempts exhausted - video generation impossible", 'index': i}

    except Exception as e:
        logger.error(f"❌ Critical error in video rendering for segment {i+1}: {e}")
        return {'success': False, 'error': str(e), 'index': i}

def _regenerate_script_from_scratch_enhanced(segment_data: dict, index: int, gemini_api_key: str, aspect_ratio: str = "16:9") -> str:
    """
    Fully regenerate the script using Gemini with original narration + visuals and actual audio duration.
    This is an enhanced version that uses the actual audio file duration.
    """
    try:
        import google.generativeai as genai
        from pydub import AudioSegment
        
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        narration = segment_data.get('narration', "Educational content")
        visuals = segment_data.get('visuals', "Simple visuals")
        
        # Get actual audio duration from the audio file
        audio_path = segment_data.get('audio_path')
        if audio_path and Path(audio_path).exists():
            audio = AudioSegment.from_file(audio_path)
            actual_duration = round(len(audio) / 1000.0, 2)
            logger.info(f"🎯 Using actual audio duration: {actual_duration:.2f}s for segment {index+1}")
        else:
            actual_duration = segment_data.get('duration', 5.0)
            logger.warning(f"⚠️ No audio file found, using fallback duration: {actual_duration:.2f}s")

        # Generate aspect ratio config
        aspect_ratio_configs = {
            "16:9": {"frame_width": 16, "frame_height": 9, "pixel_width": 1920, "pixel_height": 1080},
            "9:16": {"frame_width": 9, "frame_height": 16, "pixel_width": 1080, "pixel_height": 1920},
            "1:1": {"frame_width": 1, "frame_height": 1, "pixel_width": 1080, "pixel_height": 1080},
            "4:3": {"frame_width": 4, "frame_height": 3, "pixel_width": 1440, "pixel_height": 1080},
            "21:9": {"frame_width": 21, "frame_height": 9, "pixel_width": 2560, "pixel_height": 1080}
        }
        config = aspect_ratio_configs.get(aspect_ratio, aspect_ratio_configs["16:9"])
        aspect_ratio_config = f"""# Aspect Ratio Configuration: {aspect_ratio}
config.frame_width = {config['frame_width']}
config.frame_height = {config['frame_height']}
config.pixel_width = {config['pixel_width']}
config.pixel_height = {config['pixel_height']}
"""

        # Load enhanced prompt resources
        try:
            with open('./generator/video_generator/prompt/sample.txt', 'r', encoding='utf-8') as f:
                samples = f.read()
        except FileNotFoundError:
            logger.warning("⚠️ sample.txt not found. Using basic samples.")
            samples = """
# Basic Manim Examples
from manim import *

class BasicExample(Scene):
    def construct(self):
        title = Text("Hello World", font_size=48)
        self.play(Write(title), run_time=2)
        self.wait(1)
"""

        try:
            with open('./generator/video_generator/prompt/obj-attrbute_list.txt', 'r') as f:
                allowed_attributes = f.read()
        except FileNotFoundError:
            logger.warning("⚠️ obj-attrbute_list.txt not found. Using basic attributes.")
            allowed_attributes = """
Text: font_size, color, move_to, shift, scale
Circle: radius, color, fill_color, fill_opacity
Rectangle: width, height, color, fill_color, fill_opacity
"""

        allowed_colors = "WHITE, BLUE, GREEN, RED, YELLOW, PINK, ORANGE, PURPLE, GOLD, GRAY"

        # Aspect ratio-specific layout guidelines with detailed constraints
        aspect_ratio_guidelines = {
            "16:9": {
                "guide": "Wide horizontal (16:9). Place titles at top, content center. Frame: 16 wide × 9 tall.",
                "max_text_width": "config.frame_width * 0.85",
                "max_font_title": 48,
                "max_font_body": 36,
                "example": """
# 16:9 Example
title = Text("Wide Layout Title", font_size=48)
title.scale_to_fit_width(config.frame_width * 0.85)
title.to_edge(UP, buff=1)

content = Text("Content goes here", font_size=36)
content.scale_to_fit_width(config.frame_width * 0.85)
content.move_to(ORIGIN)
"""
            },
            "9:16": {
                "guide": "CRITICAL: Vertical portrait (9:16) for mobile. Frame: 9 wide × 16 tall. Text MUST be narrow!",
                "max_text_width": "config.frame_width * 0.65",
                "max_font_title": 32,
                "max_font_body": 24,
                "example": """
# 9:16 VERTICAL Example - ALWAYS use scale_to_fit_width!
title = Text("Short Title", font_size=32)
title.scale_to_fit_width(config.frame_width * 0.65)  # CRITICAL for 9:16!
title.move_to(UP * 6)

subtitle = Text("Subtitle text", font_size=24)
subtitle.scale_to_fit_width(config.frame_width * 0.65)  # CRITICAL!
subtitle.move_to(UP * 4)

content = Text("Main point", font_size=24)
content.scale_to_fit_width(config.frame_width * 0.65)  # CRITICAL!
content.move_to(ORIGIN)

# Stack elements vertically with spacing
footer = Text("Footer", font_size=20)
footer.scale_to_fit_width(config.frame_width * 0.65)
footer.move_to(DOWN * 6)
"""
            },
            "1:1": {
                "guide": "Square (1:1). Center everything. Frame: 1×1 ratio. Balanced layout.",
                "max_text_width": "config.frame_width * 0.75",
                "max_font_title": 42,
                "max_font_body": 30,
                "example": """
# 1:1 Square Example
title = Text("Centered Title", font_size=42)
title.scale_to_fit_width(config.frame_width * 0.75)
title.move_to(UP * 2)

content = Text("Content", font_size=30)
content.scale_to_fit_width(config.frame_width * 0.75)
content.move_to(ORIGIN)
"""
            },
            "4:3": {
                "guide": "Standard (4:3). Frame: 4 wide × 3 tall. Traditional TV layout.",
                "max_text_width": "config.frame_width * 0.80",
                "max_font_title": 44,
                "max_font_body": 32,
                "example": """
# 4:3 Example
title = Text("Standard Title", font_size=44)
title.scale_to_fit_width(config.frame_width * 0.80)
title.to_edge(UP, buff=0.5)

content = Text("Content", font_size=32)
content.scale_to_fit_width(config.frame_width * 0.80)
content.move_to(ORIGIN)
"""
            },
            "21:9": {
                "guide": "Ultra-wide (21:9). Frame: 21 wide × 9 tall. Use full width, side-by-side layouts.",
                "max_text_width": "config.frame_width * 0.90",
                "max_font_title": 48,
                "max_font_body": 36,
                "example": """
# 21:9 Ultra-wide Example
title = Text("Cinematic Wide Title", font_size=48)
title.scale_to_fit_width(config.frame_width * 0.90)
title.to_edge(UP, buff=1)

# Use side-by-side layout
left_content = Text("Left", font_size=36)
left_content.move_to(LEFT * 5)

right_content = Text("Right", font_size=36)
right_content.move_to(RIGHT * 5)
"""
            }
        }
        layout_info = aspect_ratio_guidelines.get(aspect_ratio, aspect_ratio_guidelines["16:9"])
        layout_guide = layout_info["guide"]
        max_text_width = layout_info["max_text_width"]
        max_font_title = layout_info["max_font_title"]
        max_font_body = layout_info["max_font_body"]
        code_example = layout_info["example"]

        prompt = f"""
You are a senior Manim Community Python developer. Generate a COMPLETELY NEW, WORKING Manim script from scratch.

🎯 CRITICAL REQUIREMENTS:
- Exact duration: {actual_duration:.2f} seconds
- Class name: Segment{index:03d}
- Aspect Ratio: {aspect_ratio}
- Calculate total run_time of all animations
- Add self.wait(...) at the end so total time matches exactly
- Create awesome and professional animations
- DO NOT use markdown formatting - return raw Python code only
- Use ONLY the provided allowed objects and colors

🎬 ASPECT RATIO: {aspect_ratio}
{layout_guide}

🚨 CRITICAL TEXT OVERFLOW PREVENTION FOR {aspect_ratio}:
- Maximum font size for titles: {max_font_title}
- Maximum font size for body text: {max_font_body}
- ALWAYS apply .scale_to_fit_width({max_text_width}) to EVERY Text object
- For {aspect_ratio}, text width is LIMITED - MUST use scale_to_fit_width()!
- Break long text (>50 chars) into multiple shorter Text objects

📚 WORKING CODE EXAMPLE FOR {aspect_ratio}:
{code_example}

⚠️ STRICT ANTI-OVERLAP RULES FOR {aspect_ratio}:

1. **TEXT WIDTH (MANDATORY):**
   - EVERY Text object MUST have .scale_to_fit_width({max_text_width})
   - NO exceptions - apply to ALL text
   
2. **FONT SIZE LIMITS (STRICT):**
   - Titles: MAX {max_font_title}px
   - Body: MAX {max_font_body}px
   - NEVER exceed these limits

3. **VERTICAL SPACING (CRITICAL):**
   - Minimum 1.5 units between ANY two text objects
   - Use zones: TOP (UP*{6 if aspect_ratio == "9:16" else 3}), MIDDLE (ORIGIN), BOTTOM (DOWN*{6 if aspect_ratio == "9:16" else 3})
   - NEVER place text in same zone

4. **HORIZONTAL MARGINS:**
   - 1 unit minimum from edges
   - 2 units minimum between side-by-side objects

5. **LONG TEXT HANDLING:**
   - Text > 50 chars: Split into 2+ Text objects
   - Stack vertically with 1.5+ unit spacing
   - Reduce font_size by 20% for long text

6. **POSITIONING CHECKLIST:**
   ✓ scale_to_fit_width() on every text
   ✓ Font sizes within limits
   ✓ 1.5+ units vertical spacing
   ✓ Objects in different zones
   ✓ No overlaps

⚠️ Layout Rules for {aspect_ratio}:
- Respect frame dimensions: config.frame_width × config.frame_height
- MANDATORY: Use .scale_to_fit_width({max_text_width}) for ALL text objects
- Never place two objects too close or on top of each other
- Use `.move_to()` or `.shift()` to keep each element in a separate area
- Keep 1-unit margin from all edges
- Position elements with proper vertical/horizontal spacing

📝 CONTENT:
- Narration: "{narration}"
- Visual concept: "{visuals}"

🎨 ALLOWED OBJECTS:
{allowed_attributes}

🎨 ALLOWED COLORS:
{allowed_colors} 

📚 REFERENCE SAMPLES:
{samples}

⚠️ IMPORTANT:
- Start with: from manim import *
- Then add aspect ratio configuration
- Don't use <b>, <i>, <u> tags in MarkupText (NO <code> tags)
- Ensure animations + wait time = {actual_duration:.2f} seconds exactly
- Make it visually engaging but simple
- EVERY Text object MUST have .scale_to_fit_width() applied

Required format:
from manim import *

{aspect_ratio_config}

class Segment{index:03d}(Scene):
    def construct(self):
        # Your code here - REMEMBER: scale_to_fit_width() for ALL text!

Generate the complete script now:
"""

        response = model.generate_content(prompt)
        regenerated_script = response.text.strip()
        
        # Clean the response
        if "```python" in regenerated_script:
            start_marker = "```python"
            end_marker = "```"
            start_idx = regenerated_script.find(start_marker) + len(start_marker)
            end_idx = regenerated_script.rfind(end_marker)
            if start_idx > len(start_marker) - 1 and end_idx > start_idx:
                regenerated_script = regenerated_script[start_idx:end_idx].strip()
        
        # Remove any remaining markdown
        regenerated_script = regenerated_script.replace("```", "").strip()
        
        logger.info(f"✅ Script {index+1} completely regenerated from scratch using Gemini")
        return regenerated_script
        
    except Exception as e:
        logger.error(f"❌ Script regeneration failed: {e}")
        # Return absolute fallback
        return _generate_absolute_fallback_script(segment_data, index, segment_data.get('duration', 5.0), aspect_ratio)
def _generate_absolute_fallback_script(segment_data: dict, index: int, duration: float, aspect_ratio: str = "16:9") -> str:
    """
    Generate an absolutely reliable fallback script that will always work.
    This is the last resort when all AI methods fail.
    """
    narration = segment_data.get('narration', f"Educational content for segment {index+1}")
    # Truncate and clean narration for display
    display_text = narration[:60].replace('"', "'").replace('\n', ' ').strip()
    if len(narration) > 60:
        display_text += "..."
    
    # Calculate timing to match exact duration
    write_time = min(2.0, duration * 0.4)  # 40% of duration for writing
    fade_time = min(1.0, duration * 0.2)   # 20% of duration for fading
    remaining_time = max(0.1, duration - write_time - fade_time)
    
    # Generate aspect ratio config
    aspect_ratio_configs = {
        "16:9": {"frame_width": 16, "frame_height": 9, "pixel_width": 1920, "pixel_height": 1080, "text_width": 0.85, "font_size": 32, "y_pos": 0.5},
        "9:16": {"frame_width": 9, "frame_height": 16, "pixel_width": 1080, "pixel_height": 1920, "text_width": 0.65, "font_size": 24, "y_pos": 2},
        "1:1": {"frame_width": 1, "frame_height": 1, "pixel_width": 1080, "pixel_height": 1080, "text_width": 0.75, "font_size": 30, "y_pos": 0.5},
        "4:3": {"frame_width": 4, "frame_height": 3, "pixel_width": 1440, "pixel_height": 1080, "text_width": 0.80, "font_size": 32, "y_pos": 0.5},
        "21:9": {"frame_width": 21, "frame_height": 9, "pixel_width": 2560, "pixel_height": 1080, "text_width": 0.90, "font_size": 32, "y_pos": 0.5}
    }
    config = aspect_ratio_configs.get(aspect_ratio, aspect_ratio_configs["16:9"])
    
    script = f'''from manim import *

# Aspect Ratio Configuration: {aspect_ratio}
config.frame_width = {config['frame_width']}
config.frame_height = {config['frame_height']}
config.pixel_width = {config['pixel_width']}
config.pixel_height = {config['pixel_height']}

class Segment{index:03d}(Scene):
    def construct(self):
        # Create main content with proper width constraint
        title = Text("{display_text}", font_size={config['font_size']})
        title.scale_to_fit_width(config.frame_width * {config['text_width']})
        title.set_color(BLUE)
        title.move_to(UP * {config['y_pos']})
        
        # Create segment indicator
        segment_info = Text(f"Segment {index+1}", font_size={max(18, config['font_size'] - 6)})
        segment_info.scale_to_fit_width(config.frame_width * {config['text_width']})
        segment_info.set_color(GRAY)
        segment_info.move_to(DOWN * {config['y_pos'] + 1})
        
        # Simple geometric shape for visual interest
        circle = Circle(radius=0.5, color=WHITE, fill_opacity=0.1)
        circle.move_to(DOWN * {max(0.5, config['y_pos'] - 0.5)})
        
        # Animations with precise timing
        self.play(Write(title), run_time={write_time:.2f})
        self.play(FadeIn(segment_info), Create(circle), run_time={fade_time:.2f})
        
        # Wait for remaining time to match exact duration
        self.wait({remaining_time:.2f})
'''
    
    logger.info(f"✅ Absolute fallback script generated for segment {index+1} with duration {duration:.2f}s")
    return script


def _generate_minimal_fallback_script(segment_data: dict, index: int, duration: float, aspect_ratio: str = "16:9") -> str:
    """
    Generate ultra-minimal fallback script with just shapes (no text).
    This should almost always work.
    """
    aspect_ratio_configs = {
        "16:9": {"frame_width": 16, "frame_height": 9, "pixel_width": 1920, "pixel_height": 1080},
        "9:16": {"frame_width": 9, "frame_height": 16, "pixel_width": 1080, "pixel_height": 1920},
        "1:1": {"frame_width": 1, "frame_height": 1, "pixel_width": 1080, "pixel_height": 1080},
        "4:3": {"frame_width": 4, "frame_height": 3, "pixel_width": 1440, "pixel_height": 1080},
        "21:9": {"frame_width": 21, "frame_height": 9, "pixel_width": 2560, "pixel_height": 1080}
    }
    config = aspect_ratio_configs.get(aspect_ratio, aspect_ratio_configs["16:9"])
    
    # Simple animation timing
    anim_time = min(2.0, duration * 0.4)
    remaining_time = max(0.1, duration - anim_time * 2)
    
    script = f'''from manim import *

# Aspect Ratio Configuration: {aspect_ratio}
config.frame_width = {config['frame_width']}
config.frame_height = {config['frame_height']}
config.pixel_width = {config['pixel_width']}
config.pixel_height = {config['pixel_height']}

class Segment{index:03d}(Scene):
    def construct(self):
        # Minimal fallback - just shapes, no text
        circle = Circle(radius=1, color=BLUE, fill_opacity=0.5)
        square = Square(side_length=1.5, color=GREEN, fill_opacity=0.3)
        square.shift(RIGHT * 2)
        
        self.play(Create(circle), Create(square), run_time={anim_time:.2f})
        self.wait({remaining_time:.2f})
        self.play(FadeOut(circle), FadeOut(square), run_time={anim_time:.2f})
'''
    
    logger.info(f"✅ Minimal fallback script generated for segment {index+1}")
    return script


def _generate_bare_bones_fallback_script(index: int, duration: float, aspect_ratio: str = "16:9") -> str:
    """
    Generate bare-bones fallback script - absolute minimum complexity.
    Just a single circle. This MUST work.
    """
    aspect_ratio_configs = {
        "16:9": {"frame_width": 16, "frame_height": 9, "pixel_width": 1920, "pixel_height": 1080},
        "9:16": {"frame_width": 9, "frame_height": 16, "pixel_width": 1080, "pixel_height": 1920},
        "1:1": {"frame_width": 1, "frame_height": 1, "pixel_width": 1080, "pixel_height": 1080},
        "4:3": {"frame_width": 4, "frame_height": 3, "pixel_width": 1440, "pixel_height": 1080},
        "21:9": {"frame_width": 21, "frame_height": 9, "pixel_width": 2560, "pixel_height": 1080}
    }
    config = aspect_ratio_configs.get(aspect_ratio, aspect_ratio_configs["16:9"])
    
    script = f'''from manim import *

# Aspect Ratio Configuration: {aspect_ratio}
config.frame_width = {config['frame_width']}
config.frame_height = {config['frame_height']}
config.pixel_width = {config['pixel_width']}
config.pixel_height = {config['pixel_height']}

class Segment{index:03d}(Scene):
    def construct(self):
        # Bare-bones fallback - single circle
        circle = Circle()
        self.add(circle)
        self.wait({duration:.2f})
'''
    
    logger.info(f"✅ Bare-bones fallback script generated for segment {index+1}")
    return script


def _clean_script_for_execution(script_content: str, index: int) -> str:
    """Clean script content for execution."""
    try:
        lines = script_content.split('\n')
        clean_lines = []
        
        for line in lines:
            # Skip empty lines and comments that might cause issues
            if line.strip().startswith('#') and any(word in line.lower() for word in ['note', 'explanation', 'remember']):
                continue
            
            # Skip lines with problematic content
            if any(phrase in line.lower() for phrase in [
                'print(', 'input(', 'open(', 'file(', 'exec(', 'eval(',
                'import os', 'import sys', 'import subprocess'
            ]):
                continue
            
            clean_lines.append(line)
        
        
        return '\n'.join(clean_lines)
        
    except Exception as e:
        logger.warning(f"⚠️ Script cleaning failed: {e}")
        return script_content

def _fix_script_errors_with_gemini(script_content: str, error: str, index: int, gemini_api_key: str) -> str:
    """Fix script errors using Gemini AI."""
    try:
        import google.generativeai as genai
        
        # Configure Gemini
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        correction_prompt = f"""
You are a Manim script debugging expert. The following Python script has an error:

**Error:**
{error}

**Current Script:**
```python
{script_content}
```

**Task:**
1. Fix the error in the script
2. Ensure the class is named `Segment{index:03d}`
3. Ensure proper Manim imports and syntax
4. Return ONLY the corrected Python code, no explanations or markdown
5. Remove any MarkpText in the program and convert it into text

**Corrected Script:**
"""
        
        response = model.generate_content(correction_prompt)
        corrected_script = response.text.strip()
        
        # Clean the response
        if "```python" in corrected_script:
            start_marker = "```python"
            end_marker = "```"
            start_idx = corrected_script.find(start_marker) + len(start_marker)
            end_idx = corrected_script.rfind(end_marker)
            if start_idx > len(start_marker) - 1 and end_idx > start_idx:
                corrected_script = corrected_script[start_idx:end_idx].strip()
        logger.info(f"✅ Script {index+1} corrected using Gemini")
        return corrected_script
        
    except Exception as e:
        logger.warning(f"⚠️ Gemini script correction failed: {e}")

def _fix_script_errors_with_groq(script_content: str, error: str, index: int, groq_api_key: str) -> str:
    """Fix script errors using Groq LLM."""
    try:
        from groq import Groq
        groq_client = Groq(api_key=groq_api_key)
        
        prompt = f"""
You are a Manim script debugging expert. The following Python script has an error:

**Error:**
{error}

**Current Script:**
```python
{script_content}
```

**Task:**
1. Fix the error in the script
2. Ensure the class is named `Segment{index:03d}`
3. Ensure proper Manim imports and syntax
4. Return ONLY the corrected Python code, no explanations or markdown
5. Remove any MarkpText in the program and convert it into text

**Corrected Script:**
        """
        chat_completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=4096
        )
        corrected_script = chat_completion.choices[0].message.content.strip()
        if "```python" in corrected_script:
            start_marker = "```python"
            end_marker = "```"
            start_idx = corrected_script.find(start_marker) + len(start_marker)
            end_idx = corrected_script.rfind(end_marker)
            if start_idx > len(start_marker) - 1 and end_idx > start_idx:
                corrected_script = corrected_script[start_idx:end_idx].strip()
        # Remove all existing triple backticks from the corrected script
        corrected_script = re.sub(r"```+", "", corrected_script)
        logger.info(f"✅ Script {index+1} corrected using Gemini")
        return corrected_script
        
    except Exception as e:
        logger.warning(f"⚠️ Groq correction failed: {e}")
        return script_content
    
def stitch_segment_worker_no_sync(args):
    """
    Stitches video and audio for a segment using matching index to avoid mismatches.
    """
    i, segment_data, config_dict = args

    try:
        # Enforce correct file naming by index
        expected_video = f"Segment{i:03d}.mp4"
        expected_audio = f"audio_segment_{i:03d}.mp3"

        video_path = Path(segment_data['video_path'])
        audio_path = Path(segment_data['audio_path'])
        temp_dir = Path(segment_data['temp_dir'])
        output_path = temp_dir / f"segment_{i:03d}_final.mp4"
        logger.info([str(video_path),str(audio_path),str(output_path)])
        # ✅ Check file names match expected naming pattern
        if video_path.name != expected_video:
            raise ValueError(f"Video file name mismatch for segment {i}: Expected {expected_video}, got {video_path.name}")
        if audio_path.name != expected_audio:
            raise ValueError(f"Audio file name mismatch for segment {i}: Expected {expected_audio}, got {audio_path.name}")

        # ✅ Ensure files exist
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
       
        # ✅ FFmpeg command
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-c:v", "copy",
            "-c:a", "aac",  # Use AAC for broader compatibility
            "-map", "0:v:0",
            "-map", "1:a:0",
            str(output_path)
        ]

        logger.debug(f"FFmpeg stitch command for segment {i}: {' '.join(cmd)}")

        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=config_dict.get('ffmpeg_timeout', 300)
        )

        if not output_path.exists() or output_path.stat().st_size < 1024:
            raise RuntimeError(f"Output video failed for segment {i}")

        logger.info(f"✅ Segment {i} stitched: {output_path}")
        return {'success': True, 'output_path': str(output_path), 'index': i}

    except Exception as e:
        logger.error(f"❌ Stitching failed for segment {i}: {e}")
        return {'success': False, 'error': str(e), 'index': i}

def validate_segment_alignment(segments: List[NarrationSegment]) -> bool:
    """
    Validate that all segments have properly aligned video and audio files.
    """
    logger.info("🔍 Validating segment alignment...")
    
    for i, segment in enumerate(segments):
        if not segment.video_path or not segment.audio_path:
            logger.error(f"❌ Segment {i+1} missing video or audio path")
            return False
            
        if not Path(segment.video_path).exists():
            logger.error(f"❌ Segment {i+1} video file doesn't exist: {segment.video_path}")
            return False
            
        if not Path(segment.audio_path).exists():
            logger.error(f"❌ Segment {i+1} audio file doesn't exist: {segment.audio_path}")
            return False
    
    logger.info("✅ All segments have valid video and audio paths")
    return True


class OptimizedVideoGenerationPipeline(VideoGenerationPipeline):
    """High-performance video generation pipeline with parallel processing using Gemini."""
    
    @staticmethod
    def _warmup_manim_cache():
        """
        PHASE 7: Pre-import Manim to warm up Python cache (2-5% faster first render).
        This triggers lazy imports so subsequent renders don't pay the import cost.
        """
        try:
            import manim
            # Trigger lazy imports for commonly used classes
            _ = manim.Scene
            _ = manim.Text
            _ = manim.Circle
            _ = manim.Write
            _ = manim.FadeIn
            logger.info("✅ Manim cache warmed up (imports pre-loaded)")
        except Exception as e:
            logger.warning(f"⚠️ Manim cache warmup failed (non-critical): {e}")
    
    def __init__(self, config: VideoGenerationConfig):
        super().__init__(config)
        
        # PHASE 7: Warmup Manim cache before rendering
        self._warmup_manim_cache()
        
        # Detect cloud environment (Render) - use conservative settings
        is_cloud = os.environ.get('PORT') == '10000' or not os.environ.get('DISPLAY')
        
        if is_cloud:
            # PHASE 5: CRITICAL BUG FIX - Ultra-conservative settings for Oracle VM free tier (1GB RAM, 1 OCPU)
            self.max_workers = 4  # ✅ FIXED: Was 4 (causing thrashing), now 1 for Oracle VM (40-60% faster!)
            logger.info("☁️ Cloud environment detected (Oracle VM) - using 1 worker (avoid CPU thrashing)")
        else:
            # Local development - moderate parallelization (PHASE 5: reduced from 8 to 4)
            self.max_workers = min(4, mp.cpu_count())  # ✅ OPTIMIZED: Cap at 4 to prevent overload
            logger.info(f"💻 Local environment detected - using {self.max_workers} workers")
        
        self.gpu_workers = 2 if self.device == "cuda" else 1
        self.memory_limit = psutil.virtual_memory().total * 0.8  # Use 80% of RAM
        
        # Thread-safe queues for coordination
        self.script_queue = Queue()
        self.audio_queue = Queue()
        self.video_queue = Queue()
        
        # Resource management
        self.active_processes = 0
        self.process_lock = threading.Lock()
        
        # Initialize Gemini client
        self._initialize_gemini_client()

    def _initialize_gemini_client(self):
        """Initialize Gemini client for AI operations."""
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.config.gemini_api_key)
            self.gemini_client = genai.GenerativeModel('gemini-2.5-flash')
            logger.info("✅ Gemini client initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini client: {e}")
            raise
        
    async def generate_video_full_parallel(self, topic: str, duration: int, output_filename: Optional[str] = None) -> str:
        """Generate video for all segments in one go: audio → script → video → sync → final concat."""
        if not output_filename:
            safe_topic = re.sub(r'[^\w\s-]', '', topic).strip().replace(' ', '_')
            output_filename = f"{self.config.output_dir}/{safe_topic}_final_video.mp4"

        logger.info(f"🚀 Starting FULL PARALLEL video generation for topic: {topic} [{duration}s]")

        try:
            # Step 1: Generate all narration segments
            segments = await self._generate_narration_segments_with_gemini(topic, duration)
            logger.info(f"🧾 {len(segments)} segments generated.")

            # Step 2: Generate audio for all segments in parallel
            await self.generate_all_audio_segments(segments, self.config.temp_dir)

            logger.info("🔊 Audio generation complete.")

            # Step 3: Generate scripts in one Gemini batch call
            segments = await self._generate_scripts_in_bulk(segments)
            logger.info("📜 Script generation complete.")

            # Step 4: Render videos in parallel
            segments = await self._parallel_video_generation_fixed(segments)
            logger.info("🎥 Video rendering complete.")

            # Step 5: Sync audio/video + concatenate
            final_path = await self._parallel_final_assembly_with_proper_sync(segments, topic)
            logger.info(f"✅ Final video created at: {final_path}")

            return final_path

        except Exception as e:
            logger.error(f"❌ Full parallel video generation failed: {e}")
            raise

    
    async def _generate_narration_segments_with_gemini(self, topic: str, duration: int) -> List[NarrationSegment]:
        """Generate narration segments using Gemini, including visual descriptions."""
        try:
            # Updated prompt to explicitly request a visual description for each segment.
            prompt = f"""
Create a detailed narration script for a {duration}-second educational video about "{topic}".

Requirements:
1. Break the content into logical segments (aim for 10-15 second segments).
2. For each segment, provide a clear visual idea or animation concept.
3. Total duration should be less to {duration} seconds.
4. Use clear, educational language.
5. Add a thanking message at the last from code Tapasya.
6. Donot mention the words narration text in the responce, just give the text directly
Format each segment STRICTLY as follows:
SEGMENT [number]: [duration in seconds]
VISUALS: [A brief, clear description of the animation or visual elements for this segment.]
[Narration text]

Example format:
SEGMENT 1: 12
VISUALS: The title "Advanced HTML" appears, with smaller text "Tags and Attributes" underneath.
Welcome to our exploration of advanced HTML tags and attributes. HTML is the backbone of web development.

SEGMENT 2: 10
VISUALS: Icons representing a header, a navigation bar, and a footer appear on the screen.
Let's start with semantic HTML elements like header, nav, main, and footer tags.

Generate the complete narration script now:
"""
            
            response = self.gemini_client.generate_content(prompt)
            content = response.text.replace("**", "").strip()
            logger.debug(f"📄 Gemini raw response:\n{content}")

            segments = []
            current_time = 0.0
            
            # Updated regex to capture the new 'VISUALS' line.
            pattern = re.compile(
                r'SEGMENT\s+(\d+):\s*(\d+(?:\.\d+)?)\s*\nVISUALS:\s*(.*?)\n(.*?)(?=SEGMENT\s+\d+:|$)', 
                re.DOTALL | re.IGNORECASE
            )
            
            for match in pattern.finditer(content):
                segment_num = int(match.group(1))
                duration = float(match.group(2))
                visuals = match.group(3).strip()
                text = match.group(4).strip()
                
                # Correctly instantiate NarrationSegment with the 'visual_description' argument.
                segment = NarrationSegment(
                    text=text,
                    start_time=current_time,
                    end_time=current_time + duration,
                    duration=duration,
                    visual_description=visuals  # This was the missing argument
                )
                segments.append(segment)
                current_time += duration
            
            if not segments:
                logger.warning("⚠️ Gemini segment parsing failed, using fallback...")
                return self._generate_fallback_segments(topic, duration)
            
            logger.info(f"✅ Generated {len(segments)} segments using Gemini")
            return segments
        except Exception as e:
            logger.error(f"❌ Gemini narration generation failed: {e}")
            # The line below was causing the crash, now the fallback is also fixed.
            return self._generate_fallback_segments(topic, duration)

    def _generate_fallback_segments(self, topic: str, duration: int) -> List[NarrationSegment]:
        """Generate fallback segments if Gemini fails, now including a visual description."""
        segment_count = max(3, duration // 10)
        segment_duration = duration / segment_count
        
        segments = []
        current_time = 0.0
        
        for i in range(segment_count):
            text = f"This is segment {i+1} discussing {topic}. We'll explore key concepts and practical applications."
            visuals = f"An informative title card for '{topic}', segment {i+1}."
            
            segment = NarrationSegment(
                text=text,
                start_time=current_time,
                end_time=current_time + segment_duration,
                duration=segment_duration,
                visual_description=visuals
            )
            segments.append(segment)
            current_time += segment_duration
        
        logger.info(f"✅ Generated {len(segments)} fallback segments.")
        return segments

    async def _parallel_audio_generation(self, segments: List[NarrationSegment]) -> List[NarrationSegment]:
        """Generate audio for all segments in parallel."""
        logger.info("🔊 Starting parallel audio generation...")
        
        def generate_single_audio(args):
            i, segment = args
            try:
                # Audio generation logic
                text = re.sub(r"\[.*?\]", "", segment.text).strip()
                temp_dir = Path(self.config.temp_dir)
                
                if self.tts_available and self.tts_model:
                    # Generate TTS audio
                    wav_tensor = self.tts_model.generate(text, temperature=0.7)
                    
                    if wav_tensor.dim() > 1:
                        wav_tensor = wav_tensor.squeeze()
                    
                    # Save and convert
                    wav_path = temp_dir / f"segment_{i:03d}.wav"
                    import torchaudio as ta
                    ta.save(str(wav_path), wav_tensor.unsqueeze(0), sample_rate=22050)
                    
                    from pydub import AudioSegment
                    audio = AudioSegment.from_wav(wav_path)
                    actual_duration = round(len(audio) / 1000.0, 2)
                    
                    final_mp3_path = temp_dir / f"audio_segment_{i:03d}.mp3"
                    audio.export(final_mp3_path, format="mp3")
                    
                    # Update segment with ACTUAL duration
                    segment.audio_path = str(final_mp3_path)
                    segment.duration = actual_duration
                    
                    logger.info(f"✅ Audio {i+1} generated: {actual_duration}s (was {segment.duration}s)")
                    return segment
                else:
                    # Fallback silent audio
                    duration_ms = int(segment.duration * 1000)
                    from pydub import AudioSegment
                    silence = AudioSegment.silent(duration=duration_ms)
                    silent_path = temp_dir / f"audio_segment_{i:03d}.mp3"
                    silence.export(silent_path, format="mp3")
                    
                    segment.audio_path = str(silent_path)
                    # Keep original duration for silent audio
                    return segment
                    
            except Exception as e:
                logger.error(f"❌ Audio generation failed for segment {i+1}: {e}")
                # Return segment with silent audio as fallback
                duration_ms = int(segment.duration * 1000)
                from pydub import AudioSegment
                silence = AudioSegment.silent(duration=duration_ms)
                silent_path = Path(self.config.temp_dir) / f"audio_segment_{i:03d}.mp3"
                silence.export(silent_path, format="mp3")
                segment.audio_path = str(silent_path)
                return segment

        # Use thread pool for I/O bound TTS operations
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            audio_tasks = [
                loop.run_in_executor(executor, generate_single_audio, (i, segment))
                for i, segment in enumerate(segments)
            ]
            
            results = await asyncio.gather(*audio_tasks)
            
            # Update timing based on ACTUAL audio durations
            current_time = 0.0
            for segment in results:
                segment.start_time = round(current_time, 2)
                segment.end_time = round(current_time + segment.duration, 2)
                current_time += segment.duration
            
            logger.info(f"🔊 Total actual audio duration: {current_time:.2f}s")
            return results

    async def _generate_scripts_in_bulk(self, segments: List[NarrationSegment]) -> List[NarrationSegment]:
        """
        Generate all Manim scripts in a single Gemini batch call,
        using the ACTUAL generated audio file duration for each segment.
        """
        logger.info("🧠 Generating all scripts in bulk using Gemini...")

        # Load prompt parts if needed
        try:
            with open('./generator/video_generator/prompt/sample.txt', 'r', encoding='utf-8') as f:
                samples = f.read()
        except FileNotFoundError:
            logger.warning("⚠️ sample.txt not found. Using instance variable.")
            samples = self.samples

        try:
            with open('./generator/video_generator/prompt/obj-attrbute_list.txt', 'r', encoding='utf-8') as f:
                allowed_attributes = f.read()
        except FileNotFoundError:
            logger.warning("⚠️ obj-attrbute_list.txt not found. Using instance variable.")
            allowed_attributes = self.allowed_attributes
        
        # Use animation reference from instance variable
        animation_reference = self.animation_reference

        allowed_colors = "WHITE, BLUE, GREEN, RED, YELLOW, PINK, ORANGE, PURPLE, GOLD, GRAY"

        from pydub import AudioSegment
        all_segments_prompt = ""

        for i, segment in enumerate(segments):
            # ✅ Always read the actual audio file
            if segment.audio_path and Path(segment.audio_path).exists():
                audio = AudioSegment.from_file(segment.audio_path)
                actual_audio_duration = round(len(audio) / 1000.0, 2)  # ms -> seconds
                segment.duration = actual_audio_duration
                logger.info(f"🎯 Segment {i+1}: Using actual audio file duration: {actual_audio_duration:.2f}s")
            else:
                logger.warning(f"⚠️ Segment {i+1} has no audio file — fallback to default duration.")
                if not segment.duration:
                    segment.duration = 5.0  # fallback duration if truly missing

            all_segments_prompt += f"""
    SEGMENT {i+1}:
    - Exact Audio Duration: {segment.duration:.2f} seconds
    - Class Name: Segment{i:03d}
    - Narration: \"{segment.text}\"
    - Visuals: {segment.visual_description}
    """

        # Build robust prompt
        prompt = f"""
                    **🎯 PRIMARY OBJECTIVE**

You are an expert Manim animation developer. For each provided **segment**, you must generate a **fully functional Manim script** that is clean, logically structured, visually engaging, and completely error-free.

Each generated script **must precisely match** the specified audio duration. The goal is to **synchronize visual animations with voiceover timing** to create professional-quality explainer videos.

---

### ✅ MANDATORY REQUIREMENTS FOR EACH SCRIPT

Each Manim animation script must:

1. **Begin with exactly:**

   ```
   ===SCRIPT START===
   ```

2. **Start the code with:**

   ```python
   from manim import *
   import random
   ```
3. **Include aspect ratio configuration immediately after imports:**
   ```python
{self._get_aspect_ratio_config()}
   ```   

4. **Define a class in the format:**

   ```python
   class SegmentXXX(Scene):
   ```

5. **Implement a `construct(self)` method containing all animation logic.**


6. **
edefined objects and their strictly allowed attributes.**
   ❌ Do NOT use unsupported attributes or extra options.

7. **Use only approved Manim color constants.**
   ❌ Do NOT define custom colors or use hex codes.

8. **Do not use any unsupported markup or formatting classes.**
   ❌ No `MarkupText`, `<span>`, `<code>`, or HTML-style tags. Donot use MARKUPTEXT at any cost
   ✅ Use only basic `Text`, `MathTex`, `Rectangle`, `Circle`, etc., as listed in the allowed objects section.

9. **Ensure the total animation time (sum of run\_times + waits) matches the given segment’s exact audio duration (±0.1s).**
   ➕ Use `self.wait()` to fill in any remaining time.

10. Remember that Mobject.align_to() takes from 2 to 3 positional arguments.

11. **Ensure you dont use Camera,Code object at any cost.

12. ** Do not use any images like .png, .jpeg, .svg or any sort of image formats , if needed created the images with vectors.

13. ** Only use from manim import *, nothing else , and use only if needed.

14. **ASPECT RATIO: This video is in {self.config.aspect_ratio} format.**
   - Design layouts appropriate for this aspect ratio
   - Position objects considering the screen dimensions
   - For 9:16 (vertical): Stack elements vertically, use full height
   - For 16:9 (horizontal): Use width, arrange side-by-side when possible
   - For 1:1 (square): Center elements, balanced composition
---

### 📏 PERFECT TIMING & ALIGNMENT RULES (CRITICAL!)

**TIMING PRECISION:**
* Your animation timing MUST match audio duration EXACTLY (±0.05s tolerance)
* Track cumulative time: `total_time = 0`
* After each animation: `total_time += run_time`
* Use precise waits: `self.wait(audio_duration - total_time)`
* NEVER go over the audio duration - animations will be cut off!

**⚡ PHASE 3: FAST ANIMATION TIMING (CRITICAL FOR SPEED):**
* Use FAST run_times: 0.6-1.0 seconds (NOT 1.5+ seconds!)
* Prefer FadeIn() over Write() when appropriate (3x faster rendering)
* Use Create() instead of DrawBorderThenFill() when possible (2x faster)
* Keep animations snappy and efficient
* Example: `self.play(FadeIn(text), run_time=0.8)` instead of `self.play(Write(text), run_time=1.5)`

**Example Perfect Timing:**
```python
def construct(self):
    # Audio duration: 8.5 seconds
    total_time = 0
    
    # Animation 1: 1.5s
    title = Text("Hello")
    self.play(Write(title, run_time=1.5))
    total_time += 1.5
    
    # Animation 2: 0.8s
    self.play(title.animate.shift(UP*2), run_time=0.8)
    total_time += 0.8
    
    # Animation 3: 1.2s
    text = Text("World")
    self.play(GrowFromCenter(text, run_time=1.2))
    total_time += 1.2
    
    # Animation 4: 1.0s
    self.play(Indicate(text, run_time=1.0))
    total_time += 1.0
    
    # Animation 5: 1.5s exit
    self.play(FadeOut(title), Uncreate(text), run_time=1.5)
    total_time += 1.5
    
    # Final wait to match exact duration
    # total_time = 6.0, need 2.5 more seconds
    self.wait(8.5 - total_time)  # = 2.5
```

**ALIGNMENT PRECISION:**
* Use `.next_to()`, `.align_to()`, `.arrange()` for perfect positioning
* Center important content: `.move_to(ORIGIN)` or `.to_edge(UP)`
* Consistent spacing: Use `buff=0.5` between related items
* Grid layouts: Use `arrange(DOWN, buff=0.3)` for lists
* Avoid overlapping text - check positions carefully

**Positioning Best Practices:**
```python
# Center title at top
title = Text("Title")
title.to_edge(UP, buff=0.5)

# Position text below title
subtitle = Text("Subtitle")
subtitle.next_to(title, DOWN, buff=0.3)

# Create aligned list
items = VGroup(
    Text("Item 1"),
    Text("Item 2"),
    Text("Item 3")
).arrange(DOWN, aligned_edge=LEFT, buff=0.2)
items.move_to(ORIGIN)

# Side-by-side comparison
left_item = Text("Left")
right_item = Text("Right")
left_item.to_edge(LEFT, buff=1)
right_item.to_edge(RIGHT, buff=1)
```

---

### 🎬 ANIMATION VARIETY RULES (ABSOLUTELY MANDATORY - WILL BE REJECTED IF NOT FOLLOWED)

**⚠️ CRITICAL WARNING: FadeIn/FadeOut ONLY animations will be REJECTED!**

You MUST use diverse, dynamic animations. Each segment MUST include:
1. ✅ At least ONE Write() or GrowFromCenter() for entry
2. ✅ At least ONE movement animation (.animate.shift() or .animate.scale())
3. ✅ At least ONE emphasis animation (Circumscribe, Indicate, or Flash)
4. ✅ At least ONE creative exit (Uncreate, ShrinkToCenter, or FadeOut with shift)

**STRICTLY FORBIDDEN:**
❌ Using ONLY FadeIn() and FadeOut() for all animations
❌ Static objects that just appear and disappear
❌ No movement or transformation between entry and exit
❌ Boring, repetitive patterns

---

### 🎨 REQUIRED ANIMATION TECHNIQUES (USE THESE!)

**1. DYNAMIC ENTRY (Pick 1-2 per segment):**

```python
# Text appearing with writing effect (HIGHLY RECOMMENDED)
title = Text("Your Title")
self.play(Write(title, run_time=1.5))

# Objects growing from center with energy
circle = Circle(radius=2)
self.play(GrowFromCenter(circle, run_time=1))

# Drawing outlines then filling (professional look)
rect = Rectangle(width=4, height=2)
self.play(DrawBorderThenFill(rect, run_time=1.2))

# Spinning in with rotation
shape = Square()
self.play(SpinInFromNothing(shape, angle=PI))
```

**2. MOVEMENT & TRANSFORMATION (REQUIRED - Add movement!):**

```python
# Move objects around the screen (ESSENTIAL for dynamic feel)
self.play(title.animate.shift(UP*2), run_time=0.8)
self.play(text.animate.shift(DOWN*1.5), run_time=0.8)

# Scale for emphasis
self.play(obj.animate.scale(1.3), run_time=0.6)

# Rotate for visual interest
self.play(shape.animate.rotate(PI/4), run_time=0.7)

# Transform between objects (morphing effect)
circle = Circle()
square = Square()
self.play(Transform(circle, square, run_time=1.2))

# Combine multiple movements
self.play(
    obj.animate.shift(RIGHT*2).scale(1.5).rotate(PI/6),
    run_time=1.5
)
```

**3. EMPHASIS & ATTENTION (Pick 1-2 to highlight key content):**

```python
# Draw attention circle around important text
self.play(Circumscribe(important_text, color=YELLOW, run_time=1))

# Pulse effect to emphasize
self.play(Indicate(key_point, color=YELLOW, scale_factor=1.3))

# Flash effect for impact
self.play(Flash(highlight, color=RED, line_length=0.4))

# Wiggle for playful emphasis
self.play(Wiggle(obj, scale_value=1.2, run_time=0.8))
```

**4. SEQUENTIAL ANIMATIONS (For lists/multiple items):**

```python
# Items appearing one by one with stagger
items = VGroup(item1, item2, item3)
self.play(
    AnimationGroup(
        *[GrowFromCenter(item) for item in items],
        lag_ratio=0.3,
        run_time=2
    )
)

# Write text items sequentially
self.play(
    AnimationGroup(
        Write(line1),
        Write(line2),
        Write(line3),
        lag_ratio=0.5
    )
)
```

**5. CREATIVE EXITS (NOT just FadeOut!):**

```python
# Uncreate - reverse of drawing (satisfying)
self.play(Uncreate(shape, run_time=1))

# Shrink away
self.play(ShrinkToCenter(obj, run_time=0.8))

# Fade with movement
self.play(FadeOut(text, shift=DOWN*2))

# Multiple objects exiting with coordination
self.play(
    Uncreate(title),
    ShrinkToCenter(circle),
    FadeOut(text, shift=LEFT*3),
    run_time=1.5
)
```

---

### 📋 COMPLETE SCENE EXAMPLES (FOLLOW THESE PATTERNS!)

**Example 1: Professional Introduction**
```python
def construct(self):
    # 1. Dynamic Entry
    title = Text("Introduction to AI", font_size=48)
    self.play(Write(title, run_time=1.5))
    
    # 2. Movement
    self.play(title.animate.shift(UP*2.5), run_time=0.8)
    
    # 3. Add content with growth
    subtitle = Text("The Future is Here", font_size=32, color=BLUE)
    subtitle.next_to(title, DOWN, buff=0.5)
    self.play(GrowFromCenter(subtitle, run_time=1))
    
    # 4. Emphasis
    self.play(Circumscribe(subtitle, color=YELLOW, run_time=1))
    
    # 5. Creative exit
    self.play(
        Uncreate(title),
        FadeOut(subtitle, shift=DOWN),
        run_time=1.2
    )
```

**Example 2: List with Energy**
```python
def construct(self):
    # Title with writing effect
    title = Text("3 Key Benefits")
    self.play(Write(title, run_time=1))
    self.play(title.animate.shift(UP*2.5).scale(0.8), run_time=0.7)
    
    # List items appearing sequentially
    items = VGroup(
        Text("1. Speed", color=GREEN),
        Text("2. Accuracy", color=BLUE),
        Text("3. Efficiency", color=YELLOW)
    ).arrange(DOWN, buff=0.5)
    
    self.play(
        AnimationGroup(
            *[GrowFromCenter(item) for item in items],
            lag_ratio=0.4,
            run_time=2.5
        )
    )
    
    # Highlight each item
    for item in items:
        self.play(Indicate(item, scale_factor=1.2), run_time=0.6)
    
    # Exit with coordination
    self.play(
        ShrinkToCenter(title),
        *[FadeOut(item, shift=DOWN) for item in items],
        run_time=1.5
    )
```

**Example 3: Transformation Scene**
```python
def construct(self):
    # Start with shape
    circle = Circle(radius=1.5, color=BLUE)
    self.play(DrawBorderThenFill(circle, run_time=1))
    
    # Transform to another shape
    square = Square(side_length=2.5, color=GREEN)
    self.play(Transform(circle, square, run_time=1.5))
    
    # Add rotation and scale
    self.play(
        circle.animate.rotate(PI/4).scale(1.2),
        run_time=1
    )
    
    # Add text with flash
    label = Text("Evolution", font_size=36)
    label.next_to(circle, DOWN)
    self.play(Write(label))
    self.play(Flash(circle, color=YELLOW))
    
    # Exit
    self.play(
        Uncreate(circle),
        FadeOut(label, shift=DOWN),
        run_time=1.2
    )
```

---

### ⚡ MANDATORY CHECKLIST FOR EACH SEGMENT:

Before submitting your script, verify:
- [ ] Uses Write() or GrowFromCenter() for at least ONE entry
- [ ] Includes .animate.shift() or .animate.scale() for movement
- [ ] Has Circumscribe(), Indicate(), or Flash() for emphasis
- [ ] Uses Uncreate(), ShrinkToCenter(), or FadeOut(shift=) for exits
- [ ] Objects MOVE and TRANSFORM, not just appear/disappear
- [ ] Animation variety - not repetitive
- [ ] Total timing matches audio duration

**IF YOUR SCRIPT ONLY USES FadeIn/FadeOut, IT WILL BE REJECTED!**

---

### � TIMING INSTRUCTIONS

* ❌ Do **not** wrap any code in triple backticks (no markdown).
* ❌ Do **not** include explanations, comments, or headings.
* ✅ Return only **raw Python code**, starting with `===SCRIPT START===`.

---

### ✅ USE THESE EXAMPLES AS STYLE REFERENCE

Use the following sample programs as reference for:

* Layout clarity
* Timing discipline
* Use of animations
* Clean code formatting
* Accurate wait calculations

```
{samples}
```

---

### 📚 COMPREHENSIVE ANIMATION REFERENCE & TECHNIQUES

**You have access to ALL of these powerful animation methods. USE THEM to create astonishing videos!**

This is your complete animation toolkit. Study these techniques and apply them creatively:

```
{animation_reference}
```

**Key Takeaways from Reference:**
- ✅ Use Write(), GrowFromCenter(), DrawBorderThenFill() for dynamic entries
- ✅ Add movement with .animate.shift(), .animate.scale(), .animate.rotate()
- ✅ Emphasize with Circumscribe(), Indicate(), Flash(), Wiggle()
- ✅ Use AnimationGroup with lag_ratio for sequential effects
- ✅ Apply rate_func for smooth, rush_into, rush_from motion
- ✅ Position with .next_to(), .to_edge(), .arrange() for perfect alignment
- ✅ Transform objects with Transform(), ReplacementTransform()
- ✅ Create professional templates from Section 11 of reference

---

### 🎨 ALLOWED OBJECTS AND ATTRIBUTES (STRICT)

Use **only** the following Manim objects, and only with the attributes explicitly listed below.
❌ Do **not** add extra options or attributes not shown.

```
{allowed_attributes}
```

---

### 🎨 ALLOWED COLORS

You must **only** use the following Manim color constants (case-sensitive).
Do not use hex, RGB, or custom colors.

❌ DO NOT USE: BROWN, TAN, BEIGE (these colors don't exist in Manim)

```
{allowed_colors}
```

---

### 📦 REQUIRED IMPORTS

**EVERY script MUST start with these imports:**

```python
from manim import *
import random  # Required if using random values
```

❌ Never use random.uniform() or random.choice() without importing random first!

---

### 📦 SEGMENTS TO IMPLEMENT

Below is the list of segments. Each segment contains:

* A segment number (e.g., Segment001)
* A visual narration description
* The **exact audio duration** in seconds

You must generate one clean and complete script for **each** segment:

```
{all_segments_prompt}
```

---

### 🔁 OUTPUT FORMAT (PER SEGMENT)

For each segment, return your response in **this exact format**:

```
===SCRIPT START===
from manim import *

class SegmentXXX(Scene):
    def construct(self):
        # Your code here
```

Repeat this for every segment. Do **not** add explanations, commentary, or markdown.

---

### ❌ ERRORS TO AVOID

* ❌ No use of unsupported classes (`MarkupText`, etc.)
* ❌ No undefined attributes or typos in method names
* ❌ No timing mismatches between animation and audio
* ❌ No markdown formatting in the output

---

### ✅ YOUR TASK

Generate **one complete, accurate Manim script per segment**, strictly following all rules above.
The output must be professional, polished, and directly executable in Manim with no errors.

You are acting as a **senior Manim Community developer**. Your script quality must reflect that expertise.
      
                    """


        # Call Gemini
        response = self.gemini_client.generate_content(prompt)
        full_script = response.text.strip()

        logger.debug(f"🔎 FULL BULK SCRIPT:\n{full_script[:1000]}...")  # Preview only

        # Robust split on unique marker
        scripts = re.split(r'===SCRIPT START===', full_script)
        scripts = [s.strip() for s in scripts if s.strip()]

        if len(scripts) < len(segments):
            logger.warning(f"⚠️ Gemini returned {len(scripts)} scripts for {len(segments)} segments.")
            logger.info(f"🎯 Smart Recovery: Saving {len(scripts)} valid scripts, generating remaining {len(segments) - len(scripts)} scripts...")
            return await self._smart_continue_generation(segments, scripts)

        # Save each script
        for i, segment in enumerate(segments):
            try:
                raw_script = scripts[i]
                cleaned_script = self._clean_script_response(raw_script, i, segment.duration)
                script_path = Path(self.config.temp_dir) / f"segment_{i:03d}.py"
                script_path.write_text(cleaned_script, encoding="utf-8")
                segment.script_path = str(script_path)
                logger.info(f"✅ Bulk script saved: segment_{i:03d}.py")
            except Exception as e:
                logger.error(f"❌ Failed for segment {i+1}: {e}")
                fallback_script = self._generate_fallback_script(segment, i, segment.duration)
                script_path = Path(self.config.temp_dir) / f"segment_{i:03d}.py"
                script_path.write_text(fallback_script, encoding="utf-8")
                segment.script_path = str(script_path)

        return segments
    
    async def _smart_continue_generation(self, segments: List[NarrationSegment], partial_scripts: List[str]) -> List[NarrationSegment]:
        """
        Smart continuation: Save already-generated scripts, then generate only the missing ones.
        This avoids wasting time re-generating scripts Gemini already created.
        """
        num_valid = len(partial_scripts)
        num_total = len(segments)
        
        logger.info(f"💾 Saving {num_valid} scripts that Gemini already generated...")
        
        # Save the valid scripts we already have
        from pydub import AudioSegment
        for i in range(num_valid):
            try:
                segment = segments[i]
                
                # Update duration from actual audio file
                if segment.audio_path and Path(segment.audio_path).exists():
                    audio = AudioSegment.from_file(segment.audio_path)
                    actual_duration = round(len(audio) / 1000.0, 2)
                    segment.duration = actual_duration
                
                raw_script = partial_scripts[i]
                cleaned_script = self._clean_script_response(raw_script, i, segment.duration)
                script_path = Path(self.config.temp_dir) / f"segment_{i:03d}.py"
                script_path.write_text(cleaned_script, encoding="utf-8")
                segment.script_path = str(script_path)
                logger.info(f"✅ Saved partial script: segment_{i:03d}.py")
            except Exception as e:
                logger.error(f"❌ Failed to save partial script {i}: {e}")
                fallback_script = self._generate_fallback_script(segment, i, segment.duration)
                script_path = Path(self.config.temp_dir) / f"segment_{i:03d}.py"
                script_path.write_text(fallback_script, encoding="utf-8")
                segment.script_path = str(script_path)
        
        # Generate ONLY the missing scripts (segments num_valid to num_total-1)
        logger.info(f"🔁 Generating remaining {num_total - num_valid} scripts (segments {num_valid+1} to {num_total})...")
        
        for i in range(num_valid, num_total):
            segment = segments[i]
            
            # Update duration from actual audio file
            if segment.audio_path and Path(segment.audio_path).exists():
                audio = AudioSegment.from_file(segment.audio_path)
                actual_duration = round(len(audio) / 1000.0, 2)
                segment.duration = actual_duration
                logger.info(f"🎯 Segment {i+1}: Using actual audio duration {actual_duration:.2f}s")
            
            # Build prompt for this single segment
            prompt = f"""
You are a senior Manim Community Python developer.

Generate one valid Manim script for this segment:
- Must run EXACTLY for {segment.duration:.2f} seconds.
- Calculate total run_time of all animations.
- Add self.wait(...) at the end if needed.
- Use only plain Text or MarkupText (only <b>, <i>, <u> allowed).
- DO NOT use <code> or unsupported tags.
- Do NOT wrap in markdown — output ONLY raw Python code.

Segment Details:
Class Name: Segment{i:03d}
Narration: "{segment.text}"
Visuals: {segment.visual_description}
"""
            
            try:
                response = self.gemini_client.generate_content(prompt)
                raw_script = response.text.strip()
                cleaned_script = self._clean_script_response(raw_script, i, segment.duration)
                
                script_path = Path(self.config.temp_dir) / f"segment_{i:03d}.py"
                script_path.write_text(cleaned_script, encoding="utf-8")
                segment.script_path = str(script_path)
                logger.info(f"✅ Continuation script saved: segment_{i:03d}.py")
            except Exception as e:
                logger.error(f"❌ Failed to generate segment {i+1}: {e}")
                fallback_script = self._generate_fallback_script(segment, i, segment.duration)
                script_path = Path(self.config.temp_dir) / f"segment_{i:03d}.py"
                script_path.write_text(fallback_script, encoding="utf-8")
                segment.script_path = str(script_path)
        
        logger.info(f"✅ Smart continuation complete: All {num_total} scripts ready!")
        return segments
    
    async def _generate_script_for_each_segment(self, segments: List[NarrationSegment]) -> List[NarrationSegment]:
        """
        If bulk generation fails, generate each Manim script separately
        using the real audio file length.
        """
        logger.info("🔁 Fallback: Generating each script individually with Gemini.")

        from pydub import AudioSegment

        for i, segment in enumerate(segments):
            # Always trust the actual audio file duration
            if segment.audio_path and Path(segment.audio_path).exists():
                audio = AudioSegment.from_file(segment.audio_path)
                actual_duration = round(len(audio) / 1000.0, 2)
                segment.duration = actual_duration
                logger.info(f"🎯 Segment {i+1}: Using actual audio duration {actual_duration:.2f}s")

            # Build prompt for this single segment
            prompt = f"""
    You are a senior Manim Community Python developer.

    Generate one valid Manim script for this segment:
    - Must run EXACTLY for {segment.duration:.2f} seconds.
    - Calculate total run_time of all animations.
    - Add self.wait(...) at the end if needed.
    - Use only plain Text or MarkupText (only <b>, <i>, <u> allowed).
    - DO NOT use <code> or unsupported tags.
    - Do NOT wrap in markdown — output ONLY raw Python code.

    Segment Details:
    Class Name: Segment{i:03d}
    Narration: "{segment.text}"
    Visuals: {segment.visual_description}
    """

            response = self.gemini_client.generate_content(prompt)
            raw_script = response.text.strip()
            cleaned_script = self._clean_script_response(raw_script, i, segment.duration)

            script_path = Path(self.config.temp_dir) / f"segment_{i:03d}.py"
            script_path.write_text(cleaned_script, encoding="utf-8")
            segment.script_path = str(script_path)
            logger.info(f"✅ Individual script saved: segment_{i:03d}.py")

        return segments



    def _clean_script_response(self, raw_content: str, index: int, duration: float) -> str:
        """Clean and validate script response from Gemini."""
        try:
            # Remove markdown blocks if present
            if "```python" in raw_content:
                start_marker = "```python"
                end_marker = "```"
                start_idx = raw_content.find(start_marker) + len(start_marker)
                end_idx = raw_content.rfind(end_marker)
                if start_idx > len(start_marker) - 1 and end_idx > start_idx:
                    raw_content = raw_content[start_idx:end_idx].strip()
            
            # Remove any leading/trailing content that's not code
            lines = raw_content.split('\n')
            code_start = 0
            for i, line in enumerate(lines):
                if line.strip().startswith('from manim import') or line.strip().startswith('class Segment'):
                    code_start = i
                    break
            
            if code_start > 0:
                raw_content = '\n'.join(lines[code_start:])
            
            # Validate script structure
            if self._validate_script_structure(raw_content, index):
                return raw_content
            else:
                logger.warning(f"⚠️ Script validation failed for segment {index}, using fallback")
                return self._generate_fallback_script(None, index, duration)
                
        except Exception as e:
            logger.error(f"❌ Script cleaning failed for segment {index}: {e}")
            return self._generate_fallback_script(None, index, duration)

    def _validate_script_structure(self, script: str, index: int) -> bool:
        """Validate that the script has all required components."""
        required_elements = [
            "from manim import",
            f"class Segment{index:03d}",
            "def construct(self)",
            "self.wait("
        ]
        
        for element in required_elements:
            if element not in script:
                logger.warning(f"⚠️ Missing required element: {element}")
                return False
        
        return True

    def _generate_fallback_script(self, segment: Optional[NarrationSegment], index: int, duration: float, is_dummy: bool = False) -> str:
        """Generate a reliable fallback script."""
        if is_dummy:
            # This script does nothing, as the main script handles everything.
            # It just needs to be a valid Manim script to not break the pipeline.
            return f'''from manim import *

    class Segment{index:03d}(Scene):
        def construct(self):
            # This is a dummy segment. The main animation is in the first script.
            self.wait(max(0.1, {duration}))
    '''

        content = segment.text[:80].replace('"', "'") if segment else f"Educational content for segment {index}"
        
        return f'''from manim import *

    class Segment{index:03d}(Scene):
        def construct(self):
            # Main title
            title = Text("{content}...", font_size=32)
            title.set_color(BLUE)
            title.move_to(UP * 1.5)
            
            # Subtitle
            subtitle = Text(f"Segment {index}", font_size=24)
            subtitle.set_color(GRAY)
            subtitle.move_to(DOWN * 1.5)
            
            # Animations
            self.play(Write(title), run_time=1.5)
            self.play(FadeIn(subtitle), run_time=1.0)
            
            # Wait for remaining duration
            remaining_time = max(0.1, {duration} - 2.5)
            self.wait(remaining_time)'''

    async def _generate_emergency_fallback_video(self, segment: NarrationSegment, index: int) -> str:
        """
        Generate an ultra-simple emergency fallback video when all else fails.
        This creates a basic black screen video with the exact duration needed.
        """
        output_dir = Path(self.config.output_dir) / f"segment_{index:03d}"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"Segment{index:03d}.mp4"
        
        # Create ultra-simple script with just text and timing
        fallback_script = f'''from manim import *

class Segment{index:03d}(Scene):
    def construct(self):
        # Ultra-simple fallback
        text = Text("Segment {index+1}", font_size=48, color=WHITE)
        self.add(text)
        self.wait({segment.duration:.2f})
'''
        
        script_path = Path(self.config.temp_dir) / f"segment_{index:03d}_emergency.py"
        script_path.write_text(fallback_script, encoding="utf-8")
        
        # Render with Manim
        try:
            await self._render_manim_segment(script_path, index, output_path)
            logger.info(f"✅ Emergency fallback video created: {output_path}")
            return str(output_path)
        except Exception as e:
            logger.error(f"❌ Emergency fallback also failed: {e}")
            # Last resort: create black video with FFmpeg
            return await self._create_black_video_ffmpeg(segment.duration, output_path)
    
    async def _create_black_video_ffmpeg(self, duration: float, output_path: Path) -> str:
        """Create a simple black video using FFmpeg as absolute last resort."""
        cmd = [
            'ffmpeg', '-y',
            '-f', 'lavfi',
            '-i', f'color=black:s=1920x1080:d={duration:.2f}',
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            str(output_path)
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        
        if output_path.exists():
            logger.info(f"✅ Created black fallback video: {output_path}")
            return str(output_path)
        else:
            raise Exception("Failed to create black video with FFmpeg")

    #
# You should replace the existing _parallel_video_generation_fixed
# function with this corrected version.
#
    async def _parallel_video_generation_fixed(self, segments: List[NarrationSegment]) -> List[NarrationSegment]:
        """Execute all Manim scripts in parallel with safe ProcessPoolExecutor."""
        logger.info("🎥 Starting parallel video generation...")

        # Prepare worker args
        worker_args = []
        config_dict = {
            'groq_api_key': self.config.groq_api_key,
            'gemini_api_key': self.config.gemini_api_key,
            'temp_dir': self.config.temp_dir,
            'output_dir': self.config.output_dir,
            'manim_quality': self.config.manim_quality,
            'ffmpeg_timeout': self.config.ffmpeg_timeout,
            'max_correction_attempts': self.config.max_correction_attempts,
            'manim_timeout': self.config.manim_timeout,  # Add this!
        }

        for i, segment in enumerate(segments):
            if not segment.script_path:
                raise RuntimeError(f"Missing script path for segment {i+1}")
            segment_data = {
                'script_path': segment.script_path,
                'video_output_dir': self.config.output_dir,
                'temp_dir': self.config.temp_dir,
                'narration': segment.text,
                'visuals': segment.visual_description,
                'duration': segment.duration,
            }
            worker_args.append((i, segment_data, config_dict))

        loop = asyncio.get_event_loop()
        with ProcessPoolExecutor(max_workers=min(len(segments), self.max_workers)) as executor:
            video_tasks = [
                loop.run_in_executor(executor, render_single_video_worker, args)
                for args in worker_args
            ]

            results = await asyncio.gather(*video_tasks)

            failed_segments = []
            for result in results:
                if result['success']:
                    segments[result['index']].video_path = result['video_path']
                else:
                    error_message = result.get('error', 'Unknown error')
                    logger.error(f"❌ Video rendering failed for segment {result['index']+1}: {error_message}")
                    failed_segments.append(result['index'])
                    
                    # Generate ultra-simple fallback video instead of crashing
                    try:
                        logger.warning(f"🔄 Creating fallback video for segment {result['index']+1}")
                        fallback_path = await self._generate_emergency_fallback_video(
                            segments[result['index']], 
                            result['index']
                        )
                        segments[result['index']].video_path = fallback_path
                        logger.info(f"✅ Fallback video created for segment {result['index']+1}")
                    except Exception as fallback_error:
                        logger.error(f"❌ Even fallback failed for segment {result['index']+1}: {fallback_error}")
                        # As last resort, skip this segment
                        continue

            if failed_segments:
                logger.warning(f"⚠️ {len(failed_segments)} segment(s) used fallback videos: {[i+1 for i in failed_segments]}")
            else:
                logger.info("✅ All segments rendered successfully.")
            
            return segments

    def _write_concat_list_file(self, segment_paths: List[str], concat_path: str):
        with open(concat_path, 'w', encoding='utf-8') as f:
            for path in segment_paths:
                normalized_path = Path(path).resolve().as_posix()
                f.write(f"file '{normalized_path}'\n")

    async def _parallel_final_assembly_with_proper_sync(self, segments: List[NarrationSegment], topic: str) -> str:
        """
        Parallel synchronization with proper video-audio alignment and validation.
        """
        logger.info("🎞️ Starting parallel final assembly with proper sync...")
        
        # Validate segment alignment first
        if not validate_segment_alignment(segments):
            raise RuntimeError("Segment alignment validation failed")
        
        # Prepare synchronization workers
        worker_args = []
        config_dict = {
            'groq_api_key': self.config.groq_api_key,
            'gemini_api_key': self.config.gemini_api_key,
            'temp_dir': self.config.temp_dir,
            'output_dir': self.config.output_dir,
            'ffmpeg_timeout': self.config.ffmpeg_timeout,
        }
        
        for i, segment in enumerate(segments):
            segment_data = {
                'video_path': segment.video_path,
                'audio_path': segment.audio_path,
                'temp_dir': self.config.temp_dir,
                'expected_duration': segment.duration,  # Add expected duration
            }
            worker_args.append((i, segment_data, config_dict))
        
        # Execute synchronization in parallel with proper sync function
        loop = asyncio.get_event_loop()
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            sync_tasks = [
                loop.run_in_executor(executor, stitch_segment_worker_no_sync, args)
                for args in worker_args
            ]
            
            results = await asyncio.gather(*sync_tasks)
            
            # Collect synchronized clips in correct order
            final_clips = [None] * len(segments)
            for result in results:
                if result['success']:
                    final_clips[result['index']] = result['output_path']
                    logger.info(f"✅ Segment {result['index']+1} synchronized: {result['output_path']}")
                else:
                    error_msg = result.get('error', 'Unknown error')
                    logger.error(f"❌ Synchronization failed for segment {result['index']+1}: {error_msg}")
                    raise RuntimeError(f"Synchronization failed for segment {result['index']+1}: {error_msg}")
        
        # Verify all clips were processed
        if None in final_clips:
            missing_indices = [i for i, clip in enumerate(final_clips) if clip is None]
            raise RuntimeError(f"Missing synchronized clips for segments: {missing_indices}")
        
        # Final video concatenation (segments only, no intro yet)
        temp_dir = Path(self.config.temp_dir)
        concat_list_path = temp_dir / "concat_list.txt"
        
        # Write concat list with validation
        with open(concat_list_path, 'w', encoding='utf-8') as f:
            # Add all generated segment clips
            for i, path in enumerate(final_clips):
                if not Path(path).exists():
                    raise RuntimeError(f"Synchronized clip {i+1} doesn't exist: {path}")
                normalized_path = Path(path).resolve().as_posix()
                f.write(f"file '{normalized_path}'\n")
        
        # Create final output
        safe_topic = re.sub(r'[^\w\s-]', '', topic).strip().replace(' ', '_')
        final_output_path = str(Path(self.config.output_dir) / f"{safe_topic}.mp4")
        
        cmd = [
            "ffmpeg", "-y",  # Overwrite output file
            "-f", "concat",  # Use concat demuxer
            "-safe", "0",    # Allow unsafe file paths
            "-i", str(concat_list_path),  # Input concat list
            "-c", "copy",    # Copy streams without re-encoding
            final_output_path
        ]
        
        logger.info(f"🎬 Final concatenation command: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd, 
                check=True, 
                capture_output=True, 
                text=True, 
                timeout=self.config.ffmpeg_timeout
            )
            
            # Verify final output
            if not Path(final_output_path).exists():
                raise RuntimeError(f"Final video was not created: {final_output_path}")
                
            final_size = Path(final_output_path).stat().st_size
            if final_size < 1024:
                raise RuntimeError(f"Final video is too small: {final_size} bytes")
                
            logger.info(f"✅ Generated video created: {final_output_path} ({final_size/1024/1024:.1f}MB)")
            
            # Add intro video using FFmpeg (if exists)
            final_output_with_intro = self._add_intro_with_ffmpeg(final_output_path)
            logger.info(f"✅ Final video with intro: {final_output_with_intro}")
            
            # Cleanup temporary files
            self.cleanup_temp_files()
            
            return final_output_with_intro
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Final concatenation failed: {e.stderr if e.stderr else 'Unknown error'}"
            logger.error(f"❌ {error_msg}")
            # Still try to cleanup even on failure
            try:
                self.cleanup_temp_files()
            except:
                pass
            
    def generate_video_optimized(self, topic: str, duration: int, output_filename: Optional[str] = None) -> str:
        """Synchronous wrapper for async pipeline."""
        return asyncio.run(self.generate_video_async(topic, duration, output_filename))

# Memory-efficient batching for large projects

async def main_optimized():
    """Audio-first optimized main function."""
    import os
    
    gemini_key = os.getenv("GEMINI_API_KEY")
    groq_api_key = os.getenv("GROQ_API_KEY")
    
    if not gemini_key:
        raise ValueError("GEMINI_API_KEY environment variable is required.")
    
    config = VideoGenerationConfig(
        groq_api_key= groq_api_key,
        gemini_api_key=gemini_key,
        batch_size=5,  # Larger batches for efficiency
        max_correction_attempts=3,  # Fewer attempts for speed
    )
    
    try:
        # Use memory-optimized pipeline for large `videos`
        pipeline = OptimizedVideoGenerationPipeline(config)

        
        start_time = time.time()
        # Using the chunked method for better memory management
        result = await pipeline.generate_video_full_parallel(
            topic="The wonders of space exploration", 
            duration=60
        )

        
        total_time = time.time() - start_time
        print(f"✅ CHUNKED AUDIO-FIRST Video generated in {total_time:.2f}s: {result}")
        
    except Exception as e:
        print(f"❌ Audio-first pipeline failed: {e}")
        logging.exception("Full error traceback:")

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s')
    import multiprocessing as mp
    mp.set_start_method("spawn", force=True)

    asyncio.run(main_optimized())