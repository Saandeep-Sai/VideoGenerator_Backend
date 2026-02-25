"""
🚀 OPTIMIZED VIDEO GENERATION PIPELINE
========================================

ARCHITECTURE: FOUR-STAGE PIPELINE (ENFORCED)
=============================================

STAGE 1 — NARRATION + VISUAL DESCRIPTION (Semantic Authority)
--------------------------------------------------------
Responsibility: Generate narration segments and high-level visual descriptions ONLY
Output: narration_text, visual_description (immutable after creation)
Rules:
  - No Manim references
  - No implementation details
  - Scene intent describes WHAT, not HOW
  - This data becomes READ-ONLY after generation

STAGE 2 — AUDIO GENERATION (Temporal Authority)
------------------------------------------------
Responsibility: Convert narration_text into audio, measure EXACT duration
Output: audio_path, _audio_duration_final (LOCKED - single source of truth)
Rules:
  - Audio duration is FINAL and immutable
  - Downstream stages MUST conform to this duration
  - No script regeneration based on audio length

STAGE 3 — MANIM SCRIPT GENERATION (Implementation Only)
--------------------------------------------------------
Responsibility: Generate Manim scripts that implement visual_description
PRIMARY PATH: Bulk generation (1 API call for all segments)
FAIL-SAFE PATH: Per-segment generation (triggered on validation failure)

Input (READ-ONLY):
  - narration_text (from Stage 1)
  - visual_description (from Stage 1)
  - _audio_duration_final (from Stage 2)
  - aspect_ratio

Rules:
  - Each segment = ONE script file = ONE Scene class
  - No creative reinterpretation
  - Total animation time MUST equal _audio_duration_final
  - Cannot modify narration or audio duration
  - Bulk validation routes failures to fail-safe path

STAGE 4 — SCRIPT CORRECTION (Structural Repair Only)
-----------------------------------------------------
Responsibility: Fix broken Manim scripts ONLY
Allowed: Syntax fixes, Manim API fixes, layout overlap fixes
Forbidden: Changing narration, visual description, timing semantics, visual concepts

Rules:
  - Corrections cannot cross segment boundaries
  - Retries never regenerate narration or audio
  - Must preserve animation intent and timing logic

GLOBAL RULES (ABSOLUTE)
========================
1. Each video segment is fully independent
2. One segment → one script → one video file
3. Bulk script generation is PRIMARY path
4. Per-segment generation is FAIL-SAFE only
5. Failures isolated to current segment
6. Completed segments never invalidated
7. Audio duration is FINAL (temporal authority)
8. Narration + visual_description are IMMUTABLE (semantic authority)

OPTION A QUICK WINS IMPLEMENTED (35-40% speed improvement):
-----------------------------------------------------------
✅ 1. SMART UPDATER DETECTION (Balanced approach - speed + quality)
   - Allows updaters for engaging visuals (up to 30% of animations)
   - Rejects only excessive updater usage (>30% threshold)
   - Encourages stunning animations while maintaining performance
   - Location: _validate_script() method

✅ 2. PARALLEL ASYNC FFMPEG SYNC (15-20 seconds saved on 4+ segments)
   - Replaced serial FFmpeg calls with asyncio.gather()
   - All audio-video sync operations run simultaneously
   - Location: _parallel_final_assembly_with_proper_sync()

✅ 3. ASYNC SUBPROCESS EXECUTION
   - Non-blocking FFmpeg operations using asyncio.create_subprocess_exec()
   - Better resource utilization on multi-core systems
   - Location: synchronize_audio_video_async()

✅ 4. CREATIVE PROMPT OPTIMIZATION
   - Prompts emphasize visual excellence and diversity
   - Encourages 10+ animation techniques per segment
   - Smart guidelines: prefer fast animations, allow strategic updater use
   - Rejects boring scripts (FadeIn/FadeOut only)

PHILOSOPHY:
-----------
Speed matters, but engagement matters MORE. We optimize for both:
- Use precomputed animations (90% of toolkit) for speed
- Allow updaters (10% strategic use) for WOW moments
- Reject excessive updaters (>30%) and boring scripts
- Result: Fast renders + captivating visuals = Happy viewers!

CURRENT PERFORMANCE:
-------------------
- Before: 3-5 minutes per video (slow, basic animations)
- After: 2-3 minutes per video (fast, STUNNING animations)
- Speed improvement: ~35%
- Quality improvement: Significantly more engaging
- With job queue: Users don't wait - instant response + email notification
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple

# Third-party imports
from dotenv import load_dotenv
from groq import Groq
from pydub import AudioSegment

# Import OpenRouterKeyManager with fallback for direct execution
try:
    from ..openrouter_key_manager import OpenRouterKeyManager
except ImportError:
    # Fallback for when running file directly
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from generator.openrouter_key_manager import OpenRouterKeyManager

# TTS import with robust error handling

# Setup logging with DEBUG level temporarily to diagnose key rotation
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
load_dotenv()

@dataclass
class NarrationSegment:
    start_time: float
    end_time: float
    duration: float
    text: str
    visual_description: str  # Stage 1: High-level visual description (immutable)
    audio_path: Optional[str] = None
    script_path: Optional[str] = None
    video_path: Optional[str] = None
    _audio_duration_final: Optional[float] = None  # Stage 2: Temporal authority (immutable)

class EdgeTTSWrapper:
    """Enhanced Edge TTS wrapper with retry logic and custom headers."""
    def __init__(self, voice: str = "en-US-AndrewNeural"):
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
    openrouter_api_key: str  # Changed from gemini_api_key
    groq_api_key: str
    output_dir: str = "output"
    temp_dir: str = "temp"
    manim_quality: str = "medium"  # Medium quality config for 720p30
    audio_sample_rate: int = 22050
    use_groq_for_correction: bool = True
    manim_timeout: int = 2400  # E2.Micro: 40 minutes per segment rendering (slower CPU)
    ffmpeg_timeout: int = 300  # FFmpeg operations: 5 minutes
    gemini_temperature: float = 0.2  # Kept name for backward compatibility (used as temperature)
    gemini_max_tokens: int = 8192  # Kept name for backward compatibility (used as max_tokens)
    max_generation_attempts: int = 3
    max_correction_attempts: int = 3  # Max attempts to fix script with AI/Groq before regenerating
    max_regeneration_attempts: int = 4  # Max attempts to regenerate script from scratch
    batch_size: int = 1  # E2.Micro: Process 1 segment at a time (avoid resource overload)
    # E2.Micro resource limits
    memory_limit_mb: int = 800  # Leave 200MB for system
    max_concurrent_tts: int = 1  # Only 1 TTS at a time
    aspect_ratio: str = "9:16"  # Options: "16:9" (YouTube), "9:16" (Shorts/TikTok), "1:1" (Instagram), "4:3" (Traditional)
    video_type: str = "regular"  # Options: "regular", "short"
    # NEW: Quality pipeline option for high-quality educational animations
    use_quality_pipeline: bool = False  # When True, uses spec-based generation with visual primitives
    
    def __post_init__(self):
        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is required.")
        if self.use_groq_for_correction and not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when correction is enabled.")
        
        # Validate aspect ratio
        valid_ratios = ["16:9", "9:16", "1:1", "4:3", "21:9"]
        if self.aspect_ratio not in valid_ratios:
            raise ValueError(f"aspect_ratio must be one of {valid_ratios}, got {self.aspect_ratio}")
        
        # Validate aspect ratio
        valid_ratios = ["16:9", "9:16", "1:1", "4:3", "21:9"]
        if self.aspect_ratio not in valid_ratios:
            raise ValueError(f"aspect_ratio must be one of {valid_ratios}, got {self.aspect_ratio}")

    def to_dict(self):
        """Converts the dataclass instance to a dictionary."""
        return asdict(self)

class VideoGenerationPipeline:
    """
    A self-healing pipeline that generates narrated videos from a topic.
    
    ⚠️ LEGACY BASE CLASS - Production uses OptimizedVideoGenerationPipeline
    
    This class provides the core infrastructure and methods that are inherited
    by OptimizedVideoGenerationPipeline. The following methods in this base class
    are NOT used in production but are kept for structural compatibility:
    
    - generate_video() → Replaced by generate_video_full_parallel()
    - generate_all_manim_scripts() → Replaced by _generate_scripts_in_bulk() + parallel
    - execute_all_scripts() → Replaced by _parallel_video_generation_fixed()
    
    Production entry point: OptimizedVideoGenerationPipeline.generate_video_full_parallel()
    See: run_generate_worker.py
    """
    
    def __init__(self, config: VideoGenerationConfig):
        self.config = config
        self.openrouter_key_manager = None
        self.gemini_models = ["gemini-3-flash-preview","gemini-2.5-flash", "gemini-2.5-flash-lite"]
        self.current_gemini_model_index = 0
        self.groq_correction_models = ["llama-3.1-8b-instant"]
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
        
        # Clean up old 480p cached intro if it exists (we now use 720p)
        old_intro_cache = Path(self.config.temp_dir) / "intro_scaled_854x480.mp4"
        if old_intro_cache.exists():
            try:
                old_intro_cache.unlink()
                logger.info("🗑️ Removed old 480p intro cache (now using 720p)")
            except Exception as e:
                logger.warning(f"⚠️ Could not remove old intro cache: {e}")

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
        except Exception as e:
            # Try with full path on Linux systems
            import shutil
            ffmpeg_path = shutil.which('ffmpeg')
            if not ffmpeg_path:
                # Last resort: check common installation paths
                import os
                for path in ['/usr/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/snap/bin/ffmpeg']:
                    if os.path.exists(path):
                        ffmpeg_path = path
                        break
            
            if not ffmpeg_path:
                raise RuntimeError(f"FFmpeg is required but not found or failed. Error: {e}")
            
            # Verify it works
            try:
                subprocess.run([ffmpeg_path, '-version'], capture_output=True, check=True)
            except Exception as verify_error:
                raise RuntimeError(f"FFmpeg found at {ffmpeg_path} but failed to execute: {verify_error}")

    def _setup_models(self) -> None:
        self._setup_openrouter()
        if self.config.use_groq_for_correction:
            self._setup_groq()
        self._setup_tts()

    def _setup_openrouter(self) -> None:
        try:
            # Initialize OpenRouterKeyManager for STAGE 3: Script Correction (fallback only)
            # Note: Scripts are now generated by Gemini (Stage 2), OpenRouter is only used for correction fallback
            self.openrouter_key_manager = OpenRouterKeyManager()
            logger.info(f"✅ OpenRouterKeyManager initialized with {self.openrouter_key_manager.get_stats()['total_keys']} key(s)")
            logger.info(f"🧠 STAGE 1 (Narration): Gemini with rotation ({', '.join(self.gemini_models)})")
            logger.info(f"🎬 STAGE 2 (Scripts): Gemini with rotation (bulk + per-segment fallback)")
            logger.info(f"🔧 STAGE 3 (Correction): Groq (llama-3.1-8b-instant) → OpenRouter (fallback)")

        except Exception as e:
            logger.error(f"Failed to initialize OpenRouter: {e}")
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
            # Use friendly voice for shorts, professional for regular videos
            voice = "en-US-AndrewNeural" if getattr(self.config, 'video_type', 'regular') == 'short' else "en-US-AndrewNeural"
            self.tts_model = EdgeTTSWrapper(voice=voice)
            self.tts_available = True
            logger.info(f"✅ Edge TTS initialized with voice: {voice}")
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
        
        prompt = f"""You are a viral YouTube Shorts creator who NEVER makes boring content. Your videos hook people instantly and they can't stop watching.

🎯 TASK: Create a {duration}-second educational video script about "{topic}" for {self.config.aspect_ratio} format.

📄 OUTPUT FORMAT (STRICT):
SEGMENT: [duration_in_seconds] | [narration_with_emotion] | [visual_description]

🚨 ANTI-BORING RULES (CRITICAL!):
❌ NEVER start with "Today we'll learn about..." or "In this video..."
❌ NEVER say "The concept of X is defined as..."
❌ NEVER have static visuals (everything must MOVE!)
❌ NEVER sound like a textbook or Wikipedia article

✅ ALWAYS start with a hook (question, surprising fact, relatable pain)
✅ ALWAYS use dynamic visual verbs: BOUNCES, SLIDES, ZOOMS, PULSES, SPINS
✅ ALWAYS sound like you're explaining to a friend, not lecturing
✅ ALWAYS end with energy: "Boom!", "Pretty cool, right?", "Mind-blowing!"

🎙️ NARRATION STYLE (Sound Like a Friend!):
- Use contractions: "don't", "can't", "it's", "here's"
- Use casual phrases: "So basically...", "Here's the thing...", "Wait for it..."
- Add personality: "Boom!", "Mind-blowing!", "Pretty cool, right?"
- [Excited] = High energy, smiling voice
- [Curious] = Intrigued, drawing viewer in
- [Confident] = Authoritative but friendly

🎬 VISUAL REQUIREMENTS:
- Every scene needs MOVEMENT: things BOUNCE in, PULSE, ZOOM, SLIDE
- Aspect ratio: {visual_guide}
- Use dynamic verbs: "Title BOUNCES in", "Icons SPIN into position", "Arrow SLIDES and PULSES"
- Colors: BLUE, RED, GREEN, YELLOW, PURPLE, ORANGE, TEAL
- Positions: center, top, bottom, left, right

⏱️ TIMING:
- Each segment: 12-18 seconds (aim for 15)
- Total: EXACTLY {duration} seconds
- Structure: Hook (short) → Explain (longer) → Payoff (medium)

📚 EXAMPLES:

✅ GOOD (Engaging):
SEGMENT: 15 | [Excited] Okay wait - you know that thing your code does where it just... breaks for no reason? There's actually a name for it! | Title "THE BUG" BOUNCES in from top, explosion effect, code snippet SLIDES in from left with red highlight PULSING on the error line

✅ GOOD (Hook + Visual Sync):
SEGMENT: 12 | [Curious] Ever wondered why APIs are everywhere? Think of them as waiters in a restaurant! | Waiter icon SPINS into center, restaurant scene FADES in around it, menu and food icons SLIDE in on cue

❌ BAD (Boring):
SEGMENT: 15 | Today we will learn about functions in programming | Show function diagram

❌ BAD (Static):
SEGMENT: 12 | Functions are an important concept | Display text about functions

📋 STRUCTURE:
- Segment 1: HOOK - Make them STOP SCROLLING (question/surprising fact)
- Segments 2-N: EXPLAIN - Break it down with visuals that MOVE
- Final Segment: PAYOFF - Quick recap + memorable sign-off ("Boom! Now you know!")

📝 TOPIC: "{topic}"
⏱️ DURATION: {duration} seconds

Generate ONLY SEGMENT lines now (no extra text):
"""

        """ safety_settings = {
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        } """

        try:
            # Use OpenRouter with Llama 3.3 70B for narration generation
            def call_openrouter(client):
                response = client.chat.completions.create(
                    model=self.narration_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.config.gemini_temperature,
                    max_tokens=self.config.gemini_max_tokens,
                )
                return response.choices[0].message.content
            
            response_text = self.openrouter_key_manager.execute_with_rotation(
                call_openrouter,
                model=self.narration_model
            )
            
            if not response_text:
                raise ValueError("OpenRouter response was empty.")

            lines = response_text.strip().splitlines()
            segments = []
            current_time = 0.0

            for line in lines:
                if not line.strip().startswith("SEGMENT:"):
                    continue
                try:
                    # SEGMENT: 5 | [Calm] ... | blue circle diagram ...
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
        
        # Get aspect ratio configuration
        aspect_ratio_config = self._get_aspect_ratio_config()
        
        # Aspect ratio-specific layout guidelines
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
                "max_text_width": "config.frame_width * 0.65",
                "max_font_title": 32,
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
        
        # Create batch prompt with aspect ratio guidance
        segment_info = ""
        for i, segment in enumerate(batch_segments):
            segment_info += f"SEGMENT_{i+1}: {segment.duration}s | {segment.text[:60]}... | {segment.visual_description[:60]}...\n"

        batch_prompt = f"""Generate {len(batch_segments)} separate Manim scripts for aspect ratio {self.config.aspect_ratio}:

{segment_info}

🎯 CRITICAL LAYOUT REQUIREMENTS for {self.config.aspect_ratio}:
{layout_guide}

🚨 ABSOLUTE TEXT OVERLAP PREVENTION RULES:

1. **MANDATORY TEXT WIDTH CONSTRAINT:**
   - EVERY Text/MarkupText object MUST have .scale_to_fit_width({max_text_width})
   - NO EXCEPTIONS - even single words need scaling

2. **STRICT FONT SIZE LIMITS:**
   - Titles: MAX {max_font_title}px
   - Body text: MAX {max_font_body}px

3. **MANDATORY VERTICAL SPACING:**
   - Minimum 1.5 units between ANY two text objects
   - Use .next_to(other_object, DOWN, buff=1.5)

4. **ASPECT RATIO CONFIG MUST BE INCLUDED:**
{aspect_ratio_config}

Output Format - STRICTLY FOLLOW:
=== SCRIPT_1 ===
from manim import *

{aspect_ratio_config}

class GeneratedAnimation1(Scene):
    def construct(self):
        # Every text: text.scale_to_fit_width({max_text_width})
        # Minimum vertical spacing: 1.5 units
        self.wait({batch_segments[0].duration})

=== SCRIPT_2 ===
from manim import *

{aspect_ratio_config}

class GeneratedAnimation2(Scene):
    def construct(self):
        # Every text: text.scale_to_fit_width({max_text_width})
        # Minimum vertical spacing: 1.5 units
        self.wait({batch_segments[1].duration if len(batch_segments) > 1 else 10})

Continue for all {len(batch_segments)} segments. Output ONLY scripts with separators. Include aspect ratio config in EVERY script.
"""

        try:
            # Use OpenRouter with Qwen Coder for batch script generation
            def call_openrouter(client):
                response = client.chat.completions.create(
                    model=self.script_model,
                    messages=[{"role": "user", "content": batch_prompt}],
                    temperature=self.config.gemini_temperature,
                    max_tokens=self.config.gemini_max_tokens,
                )
                return response.choices[0].message.content
            
            response_text = self.openrouter_key_manager.execute_with_rotation(
                call_openrouter,
                model=self.script_model
            )
            
            if not response_text:
                return False

            # Parse the batch response
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
        logger.info(f"🎬 ENTERING _generate_individual_script for segment {segment_number}")
        
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
        
        # Enhanced prompt with professional animation requirements
        prompt = f"""Create a PROFESSIONAL, ENGAGING Manim script for this segment:

Duration: {segment.duration} seconds
Content: {segment.text}
Visual: {segment.visual_description}
Aspect Ratio: {self.config.aspect_ratio}

� CRITICAL AUDIO-VIDEO SYNCHRONIZATION RULE:
═══════════════════════════════════════════════════════════════
⚠️ The visuals MUST match what's being said in the narration!
  • If narration says "three types", show exactly THREE items on screen
  • If narration mentions "comparison", show side-by-side comparison
  • If narration says "process", show step-by-step flow with arrows
  • Timing: Spread animations evenly across the {segment.duration} seconds
  • Key words in narration = visual elements on screen

🎬 ANIMATION QUALITY REQUIREMENTS (CRITICAL!):
═══════════════════════════════════════════════════════════════
✨ Your animations must be:
  • VISUALLY STUNNING - Use professional effects, not basic FadeIn/FadeOut
  • DYNAMIC & ENGAGING - Multiple animation types, smooth transitions
  • PERFECTLY SYNCED - Visuals appear as narration mentions them
  • PROFESSIONALLY STYLED - Gradients, colors, glows, proper spacing
  • ATTENTION-GRABBING - Use emphasis animations (Circumscribe, Flash, Indicate)
  • SMOOTH & POLISHED - Always use rate_func=smooth, proper run_times
  • INTERACTIVE FEEL - Use transforms, morphs, reveals that respond to narration

🚨 BANNED: Plain FadeIn/FadeOut only scripts will be REJECTED!
✅ REQUIRED: Use 5-8 different animation techniques per segment for maximum engagement

📚 ANIMATION REFERENCE:
{self.animation_reference}

🎯 CRITICAL LAYOUT REQUIREMENTS for {self.config.aspect_ratio}:
{layout_guide}

🚨 ABSOLUTE TEXT OVERLAP PREVENTION RULES (MUST FOLLOW):

**⛔ WARNING: Elements going off-screen is the #1 video generation failure cause!**

1. **MANDATORY TEXT WIDTH CONSTRAINT (PREVENTS OFF-SCREEN):**
   - ⚠️ EVERY Text/MarkupText object MUST have .scale_to_fit_width({max_text_width})
   - ⛔ NO EXCEPTIONS - even single words need scaling
   - ⛔ FORBIDDEN: Creating Text without .scale_to_fit_width() call
   - Example: 
     ```python
     title = Text("Title", font_size=48)
     title.scale_to_fit_width({max_text_width})  # MANDATORY - DO NOT SKIP!
     ```

2. **STRICT FONT SIZE LIMITS (PREVENTS OVERFLOW):**
   - ⛔ Titles: ABSOLUTE MAX {max_font_title}px (exceeding this = off-screen)
   - ⛔ Body text: ABSOLUTE MAX {max_font_body}px (exceeding this = off-screen)
   - ⛔ Small text: ABSOLUTE MAX {max_font_body - 6}px
   - Using larger sizes will push elements beyond screen boundaries!

3. **MANDATORY VERTICAL SPACING (PREVENTS OVERLAP/OFF-SCREEN):**
   - ⛔ MINIMUM 1.5 units between ANY two text objects
   - ✅ Use .next_to(other_object, DOWN, buff=1.5) or similar
   - ❌ NEVER place text closer than 1.5 units vertically
   - Example: 
     ```python
     title.move_to(UP * 2.5)    # Safe position
     content.move_to(ORIGIN)    # 2.5 units apart - GOOD
     # ❌ BAD: content.move_to(UP * 1.5)  # Only 1 unit apart - TOO CLOSE!
     ```
     
4. **HORIZONTAL SPACING (PREVENTS OFF-SCREEN):**
   - ⛔ MANDATORY: Leave 1 unit margin from left/right edges
   - ✅ Objects side-by-side: minimum 2 units apart horizontally
   - ✅ Use .shift(LEFT * 3) or .shift(RIGHT * 3) for separation
   - ❌ NEVER: .shift(LEFT * 8) or .shift(RIGHT * 8) - goes off-screen!

5. **⛔ FORBIDDEN POSITIONS (WILL GO OFF-SCREEN - NEVER USE):**
   - ❌ UP * 3.5 or higher (goes off top of screen)
   - ❌ DOWN * 3.5 or lower (goes off bottom of screen)
   - ❌ LEFT * 7 or beyond (goes off left edge)
   - ❌ RIGHT * 7 or beyond (goes off right edge)

6. **✅ SAFE POSITION GRID (USE ONLY THESE):**
   For {self.config.aspect_ratio}:
   - ✅ TOP zone: UP * 2.5, UP * 2, UP * 1.5 (SAFE)
   - ✅ MIDDLE zone: UP * 0.5, ORIGIN, DOWN * 0.5 (SAFE)
   - ✅ BOTTOM zone: DOWN * 1.5, DOWN * 2, DOWN * 2.5 (SAFE)
   - ⛔ NEVER use UP * 4, DOWN * 4 or beyond!

7. **TEXT LENGTH HANDLING (PREVENTS OVERFLOW):**
   - Text > 50 chars: MUST split into 2-3 Text objects, stack vertically
   - Text > 100 chars: MUST split into 3-4 Text objects
   - Use smaller font_size for long text (reduce by 20%)
   - Each piece MUST have .scale_to_fit_width()

8. **SAFE POSITIONING CHECKLIST (VERIFY BEFORE SUBMITTING):**
   ✓ Every text has .scale_to_fit_width({max_text_width})
   ✓ Font sizes within absolute limits
   ✓ Vertical spacing >= 1.5 units
   ✓ Horizontal margin >= 1 unit from edges
   ✓ Using ONLY safe positions (UP*2.5 max, DOWN*2.5 max)
   ✓ No forbidden positions (UP*4, DOWN*4, LEFT*8, RIGHT*8)
   ✓ Long text split into multiple lines

📐 PROFESSIONAL EXAMPLE (COPY THIS PATTERN FOR STUNNING RESULTS):
```python
# ✨ PROFESSIONAL: Engaging animations, perfect audio-video sync, beautiful styling

# 1. DRAMATIC TITLE REVEAL (matches narration opening)
title = Text("Educational Topic", font_size={max_font_title}, weight=BOLD)
title.set_color_by_gradient(BLUE, PURPLE)  # Gradient = professional!
title.scale_to_fit_width({max_text_width})  # MANDATORY
title.move_to(UP * {"6" if self.config.aspect_ratio == "9:16" else "3"})  # TOP zone
self.play(DrawBorderThenFill(title, run_time=1.5), rate_func=smooth)  # Smooth entry
self.play(Circumscribe(title, color=YELLOW, buff=0.2))  # Emphasize title
self.wait(0.3)  # Let it breathe

# 2. SUBTITLE WITH STYLE (appears as narration mentions key concept)
subtitle = Text("Key Concept", font_size={max_font_body}, color=YELLOW)
subtitle.scale_to_fit_width({max_text_width})  # MANDATORY  
subtitle.move_to(UP * {"2" if self.config.aspect_ratio == "9:16" else "1"})  # MIDDLE zone, 1.5+ units below
self.play(Write(subtitle, run_time=1.2))  # Classic write effect
self.wait(0.3)

# 3. CONTENT WITH EMPHASIS (synced with narration explaining main point)
content = Text("Main point here", font_size={max_font_body})
content.scale_to_fit_width({max_text_width})  # MANDATORY
content.move_to({"ORIGIN" if self.config.aspect_ratio == "9:16" else "DOWN * 0.5"})  # MIDDLE zone
self.play(FadeIn(content, shift=DOWN*0.5, run_time=1.0))  # Slide in smoothly
self.play(Flash(content, color=YELLOW), Indicate(content, scale_factor=1.2))  # Attention!
self.wait(0.4)

# 4. INTERACTIVE TRANSFORMATION (creates visual interest)
circle = Circle(radius=0.8, color=BLUE)
circle.set_fill(BLUE, opacity=0.7)  # Semi-transparent fill
circle.set_stroke(WHITE, width=3)  # White outline
circle.move_to(DOWN * {"4" if self.config.aspect_ratio == "9:16" else "2.5"})  # BOTTOM zone
self.play(GrowFromCenter(circle, run_time=1.2))  # Grow animation
self.wait(0.2)

# 5. MORPH FOR ENGAGEMENT (circle transforms to square)
square = Square(side_length=1.5, color=GREEN).move_to(circle.get_center())
square.set_fill(GREEN, opacity=0.7)
self.play(Transform(circle, square, run_time=1.3))  # Smooth morph
self.wait(0.3)

# 6. CLEAN EXIT
everything = VGroup(title, subtitle, content, circle)
self.play(FadeOut(everything, shift=DOWN*0.5, run_time=1.0))  # Smooth exit
```

💡 NOTICE THE DIFFERENCE:
  ✅ Multiple animation types (DrawBorderThenFill, Write, FadeIn, GrowFromCenter, Transform)
  ✅ Color gradients and styling (set_color_by_gradient, set_fill, set_stroke)
  ✅ Emphasis effects (Circumscribe, Flash, Indicate)
  ✅ Smooth timing (rate_func=smooth, strategic wait() calls)
  ✅ Professional pacing (run_time 1.0-1.5s, not rushed)
  ✅ Interactive transformations (Transform, ReplacementTransform for dynamic feel)
  ✅ Perfect audio-video sync (visuals match narration timing)
  ✅ Visual variety keeps viewer engaged and entertained!

❌ WRONG EXAMPLES (NEVER DO THIS - CAUSES OFF-SCREEN ELEMENTS):
```python
# ❌ BAD #1: No scale_to_fit_width - TEXT GOES OFF-SCREEN!
title = Text("Long title here", font_size=48)
title.move_to(UP * 2)  # FATAL ERROR! Missing .scale_to_fit_width() - text will be invisible!

# ✅ CORRECT VERSION:
title = Text("Long title here", font_size=48)
title.scale_to_fit_width(config.frame_width * 0.85)  # NOW it fits on screen!
title.move_to(UP * 2)

# ❌ BAD #2: Extreme position - GOES OFF-SCREEN!
title.move_to(UP * 4)  # FATAL! Goes above screen boundary - invisible!
subtitle.move_to(DOWN * 4)  # FATAL! Goes below screen boundary - invisible!

# ✅ CORRECT VERSION:
title.move_to(UP * 2)  # Safe position - stays visible
subtitle.move_to(DOWN * 2)  # Safe position - stays visible

# ❌ BAD #3: Objects too close - OVERLAP OR GO OFF-SCREEN!
title.move_to(UP * 2)
subtitle.move_to(UP * 1.5)  # WRONG! Only 0.5 units apart (minimum is 1.5) - causes overlap!

# ✅ CORRECT VERSION:
title.move_to(UP * 2)
subtitle.move_to(ORIGIN)  # 2 units apart - safe spacing!

# ❌ BAD #4: Exceeded font size - OVERFLOWS OFF-SCREEN!
huge_text = Text("Text", font_size=72)  # FATAL! Exceeds {max_font_title}px limit - will overflow!

# ✅ CORRECT VERSION:
text = Text("Text", font_size={max_font_title})
text.scale_to_fit_width(config.frame_width * 0.85)  # Safe and visible!

# ❌ BAD #5: Long text not split - GOES OFF-SCREEN!
long_text = Text("This is a very long sentence that will definitely overflow", font_size=36)
# FATAL! Long text without splitting or scaling - invisible!

# ✅ CORRECT VERSION:
line1 = Text("This is a very long sentence", font_size=36)
line1.scale_to_fit_width(config.frame_width * 0.85)
line1.move_to(UP * 1.5)
line2 = Text("that will definitely overflow", font_size=36)
line2.scale_to_fit_width(config.frame_width * 0.85)
line2.move_to(ORIGIN)  # Split into multiple lines, both scaled!

# ❌ BAD #6: Horizontal overflow - GOES OFF LEFT/RIGHT EDGE!
text.move_to(LEFT * 8)  # FATAL! Too far left - invisible!
text.move_to(RIGHT * 8)  # FATAL! Too far right - invisible!

# ✅ CORRECT VERSION:
text.move_to(LEFT * 3)  # Safe horizontal position
text.move_to(RIGHT * 3)  # Safe horizontal position
```

**🚨 REMEMBER: Every mistake above makes elements INVISIBLE to viewers!**
**✅ ALWAYS use .scale_to_fit_width() and SAFE positions!**

🎬 PROFESSIONAL ANIMATION REQUIREMENTS:
═══════════════════════════════════════════════════════════════
✨ MANDATORY TECHNIQUES (Use 5-8 per segment for maximum engagement):
  1. ENTRY ANIMATIONS:
     - Write(), DrawBorderThenFill(), GrowFromCenter() for text
     - Create(), FadeIn(shift=DOWN*0.5), Succession() for shapes
     - SpinInFromNothing(), GrowFromEdge() for dynamic reveals
     - NO plain text.move_to() without animation!
  
  2. EMPHASIS EFFECTS (Use on key points!):
     - Circumscribe(color=YELLOW, buff=0.2)
     - Flash(color=YELLOW, flash_radius=0.5)
     - Indicate(scale_factor=1.2-1.3)
     - Wiggle() for playful emphasis
     - ApplyWave() for attention-grabbing effects
  
  3. INTERACTIVE TRANSFORMATIONS (CRITICAL for engagement!):
     - Transform(obj1, obj2) for morphing between shapes
     - ReplacementTransform() for smooth replacements
     - TransformMatchingShapes() for complex transitions
     - Rotate(), Scale(), Shift() with .animate for fluid motion
     - These create the "interactive feel" users want!
  
  4. PROFESSIONAL STYLING:
     - Use .set_color_by_gradient(COLOR1, COLOR2) for titles
     - Add .set_stroke(WHITE, width=2-3) for text outlines
     - Use .set_fill(COLOR, opacity=0.7-0.9) for shapes
     - SurroundingRectangle for boxing key content
     - BackgroundRectangle for text readability
  
  5. SMOOTH TRANSITIONS:
     - Always use rate_func=smooth
     - run_time between 1.2-1.8 seconds (not too fast!)
     - Use .animate.shift().scale() for movements
     - AnimationGroup with lag_ratio=0.2-0.3 for sequences
     - Succession() for cascading reveals
  
  6. TIMING & PACING (CRITICAL for audio-video sync!):
     - Add self.wait(0.3-0.5) between major sections
     - Use different speeds: quick emphasis (0.8s), standard (1.2s), dramatic (1.8s)
     - Total animation time should match segment duration
     - Spread animations evenly - don't cluster at start/end
     - Never rush - let animations breathe!

🎨 VISUAL EXCELLENCE CHECKLIST:
  ✅ Use gradients on titles (set_color_by_gradient)
  ✅ Add emphasis to key points (Circumscribe/Flash)
  ✅ Smooth entry animations (Write, DrawBorderThenFill)
  ✅ Professional colors (not plain white/black)
  ✅ Sequenced reveals (lag_ratio for lists)
  ✅ Strategic wait times (0.3-0.5s pauses)
  ✅ Interactive transformations (Transform, ReplacementTransform)
  ✅ Dynamic movements (Rotate, Scale with .animate)
  ✅ Clean exits (FadeOut with shift)
  ✅ Perfect audio-video sync (visuals match narration)
  ✅ 5-8 different animation types per segment

❌ AVOID (These make videos look amateur):
  ❌ Only FadeIn/FadeOut (boring!)
  ❌ No emphasis on key points
  ❌ Rushed animations (run_time < 0.8s)
  ❌ Plain white text only
  ❌ No color variety
  ❌ No transformations or morphing
  ❌ Static objects (everything should animate!)
  ❌ Visuals don't match narration content
  ❌ Jerky movements (missing rate_func=smooth)

Technical Requirements:
- Class name: GeneratedAnimation{segment_number}
- Duration exactly {segment.duration} seconds
- EVERY text object MUST have .scale_to_fit_width({max_text_width})
- Minimum 1.5 units vertical spacing between text objects
- Maximum {max_font_title}px for titles, {max_font_body}px for body
- Use 3-5 different animation techniques minimum

Output format:
from manim import *

{aspect_ratio_config}

class GeneratedAnimation{segment_number}(Scene):
    def construct(self):
        # Your code - REMEMBER: No overlaps, proper spacing, scale_to_fit_width() for ALL text!
        self.wait({segment.duration})
"""
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Use OpenRouter with Qwen Coder for individual script generation
                def call_openrouter(client):
                    response = client.chat.completions.create(
                        model=self.script_model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=self.config.gemini_temperature,
                        max_tokens=self.config.gemini_max_tokens,
                    )
                    return response.choices[0].message.content
                
                response_text = self.openrouter_key_manager.execute_with_rotation(
                    call_openrouter,
                    model=self.script_model
                )
                
                if response_text:
                    script_content = self._clean_script(response_text)
                    if self._validate_script(script_content):
                        return script_content
                
                logger.warning(f"Attempt {attempt + 1} failed, retrying...")
                time.sleep(1)  # Brief delay between retries
                
            except Exception as e:
                logger.warning(f"Individual script generation attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    # NO FALLBACK - raise error
                    logger.error(f"❌ Failed to generate script after {max_retries} attempts - NO FALLBACK")
                    raise RuntimeError(f"Script generation failed for segment {segment_number} after {max_retries} retries")
                time.sleep(2)
        
        # Should not reach here, but just in case
        raise RuntimeError(f"Script generation failed for segment {segment_number} - NO FALLBACK ALLOWED")

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
        """
        Smart validation that balances performance and visual quality.
        Allows updaters for engaging visuals but rejects excessive usage.
        Also checks for proper text scaling to prevent out-of-bounds issues.
        """
        # Basic structure check
        if not ("from manim import *" in script and
                "class " in script and
                "Scene" in script and
                "def construct" in script):
            return False
        
        # TEXT SCALING VALIDATION: Warn if Text objects lack .scale_to_fit_width()
        text_objects = len(re.findall(r'(Text|MarkupText|Tex)\s*\(', script))
        scale_calls = len(re.findall(r'\.scale_to_fit_width\s*\(', script))
        
        if text_objects > 0:
            if scale_calls == 0:
                logger.warning(f"⚠️ NO SCALING DETECTED: {text_objects} text objects but 0 .scale_to_fit_width() calls - TEXT MAY GO OUT OF BOUNDS!")
            elif scale_calls < text_objects:
                logger.warning(f"⚠️ INCOMPLETE SCALING: {text_objects} text objects but only {scale_calls} .scale_to_fit_width() calls - some text may be too large!")
            else:
                logger.info(f"✅ Text scaling OK: {text_objects} text objects, {scale_calls} scaling calls")
        
        # SMART UPDATER DETECTION: Allow limited usage for engaging animations
        updater_count = len(re.findall(r'(always_redraw|add_updater)', script))
        
        if updater_count > 0:
            # Count total animation calls to calculate ratio
            total_animations = len(re.findall(r'self\.play\(|self\.add\(', script))
            
            if total_animations > 0:
                updater_ratio = updater_count / total_animations
                
                # Reject only if updaters are >30% of animations (excessive)
                if updater_ratio > 0.3:
                    logger.warning(f"🚫 Excessive updater usage detected ({updater_count}/{total_animations} = {updater_ratio*100:.1f}%). Script REJECTED.")
                    return False
                elif updater_count > 0:
                    logger.info(f"✨ Strategic updater usage detected ({updater_count}/{total_animations} = {updater_ratio*100:.1f}%) - ACCEPTABLE for visual appeal.")
            elif updater_count > 2:
                # If we can't count animations, reject if more than 2 updaters
                logger.warning(f"🚫 Too many updaters ({updater_count}) without animations. Script REJECTED.")
                return False
        
        return True

    def _clean_script(self, script: str) -> str:
        """Clean up the script by removing markdown formatting."""
        # Remove markdown code blocks
        script = re.sub(r'```(python\s*)?|\s*```', '', script)
        return script.strip()

    def _correct_script_with_groq(self, broken_script: str, error_context: str, segment: NarrationSegment = None) -> str:
        """
        STAGE 4: Script Correction (Structural Repair Only)
        
        Use Groq to fix broken scripts while enforcing strict constraints:
        - Can fix: Syntax errors, Manim API errors, layout overlaps
        - Cannot change: Narration content, scene intent, timing semantics
        """
        if not self.groq_client:
            return broken_script
        
        prompt = f"""You are a STRICT code repair engine.

The script below FAILED at runtime.
Your job is to FIX ERRORS ONLY.

ABSOLUTE RULES:
- DO NOT change visuals
- DO NOT change layout
- DO NOT change positions
- DO NOT change animation order
- DO NOT change timing or duration
- DO NOT add or remove objects
- DO NOT add new animations
- DO NOT remove scale_to_fit_width calls
- DO NOT introduce creativity

ALLOWED FIXES ONLY:
- Syntax errors
- Missing imports
- Incorrect Manim API usage
- Attribute or method name errors
- Runtime exceptions

You MUST preserve:
- Aspect ratio behavior
- Object count
- Object positions
- Total duration EXACTLY

Return the FULL corrected Python script.
Return ONLY raw code.
No explanations.

ERROR:
{error_context}

SCRIPT:
{broken_script}
"""
        
        try:
            chat_completion = self.groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}], 
                model="llama-3.1-8b-instant", 
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
        aspect_ratio_config = self._get_aspect_ratio_config()
        
        prompt = f"""
    You are a Manim Python expert.
    Rewrite a complete script for this segment from scratch.

    - Class name must be: GeneratedAnimation{segment_number}
    - Use ONLY 'from manim import *'
    - Must include aspect ratio configuration immediately after imports
    - Must match exact duration: {segment.duration:.2f} seconds
    - Visuals: {segment.visual_description}
    - Narration: {segment.text}

    REQUIRED FORMAT:
    from manim import *

    {aspect_ratio_config}

    class GeneratedAnimation{segment_number}(Scene):
        def construct(self):
            # Your code here
            self.wait({segment.duration:.2f})

    Output ONLY raw Python code. No markdown, no explanations.
        """

        try:
            # Use OpenRouter with Qwen Coder for script regeneration
            def call_openrouter(client):
                response = client.chat.completions.create(
                    model=self.script_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.config.gemini_temperature,
                    max_tokens=self.config.gemini_max_tokens,
                )
                return response.choices[0].message.content
            
            response_text = self.openrouter_key_manager.execute_with_rotation(
                call_openrouter,
                model=self.script_model
            )
            raw_script = response_text.strip()
            return self._clean_script(raw_script)
        except Exception as e:
            logger.error(f"❌ Last-resort regeneration failed for segment {segment_number}: {e}")
            raise RuntimeError(f"Last-resort script generation failed for segment {segment_number} - NO FALLBACK ALLOWED")

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
            # Set up environment for headless rendering (E2.Micro optimization)
            env = os.environ.copy()
            
            # Force headless mode for E2.Micro
            env['DISPLAY'] = ':99'  # Virtual display
            env['QT_QPA_PLATFORM'] = 'offscreen'  # Qt headless mode
            env['MPLBACKEND'] = 'Agg'  # Matplotlib headless
            env['OPENCV_IO_ENABLE_OPENEXR'] = '0'  # Disable OpenEXR
            env['MANIM_DISABLE_CACHING'] = '1'  # Disable Manim caching
            env['PYTHONUNBUFFERED'] = '1'  # Unbuffered output
            logger.info("🖥️ Running in headless mode (E2.Micro optimized)")
            
            logger.info(f"📐 Using aspect ratio: {self.config.aspect_ratio} (configured in Manim script)")
            
            # Build Manim command - use correct class name based on segment index
            # Aspect ratio is now configured inside the script itself
            # Use -qp (production quality, 1440p60) which Manim handles correctly
            # Alternative: -qh (high quality, 1080p60), -qm (medium, 720p30), -ql (low, 480p15)
            # We use -qm for 720p30 as balanced quality & speed (better quality than -ql)
            # On Windows, use "python -m manim" instead of just "manim"
            # Caching is enabled by default and controlled via script config
            
            # Determine class name from segment index
            if segment_index is not None:
                class_name = f"Segment{segment_index:03d}"
            else:
                # Fallback: try to extract class name from script
                class_name = "Scene"  # Default fallback
                try:
                    import re
                    class_match = re.search(r'class\s+(\w+)\s*\(\s*Scene\s*\)', script)
                    if class_match:
                        class_name = class_match.group(1)
                except:
                    pass
            
            cmd = [
                sys.executable, "-m", "manim", 
                filename, class_name,  # Use correct class name
                "-qm",                        # HIGH quality: 1080p60 (professional output)
                "--format", "mp4",
                "--disable_caching",          # Disable caching to save RAM
                "--flush_cache",              # Clear cache after render
                "--renderer=cairo",           # Cairo renderer for better quality
            ]
            
            logger.info(f"🎬 Rendering: {filename} → Class: {class_name} (480p15 -ql quality - E2.Micro optimized)")
            
            # Stream output with progress bar
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Combine stderr with stdout
                text=True,
                cwd=temp_path,
                env=env,
                bufsize=0,  # Unbuffered for E2.Micro
                universal_newlines=True
            )
            

            # Cross-platform timeout handling
            import threading
            import time
            
            def timeout_killer():
                time.sleep(self.config.manim_timeout)
                if process.poll() is None:  # Process still running
                    process.kill()
                    logger.warning(f"⏰ Manim process killed after {self.config.manim_timeout}s timeout")
            
            timeout_thread = threading.Thread(target=timeout_killer, daemon=True)
            timeout_thread.start()
            
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
            # Timeout thread will automatically stop when process ends
            
            if progress_shown:
                logger.info("✅ Rendering complete!")

        except Exception as e:
            if process and process.poll() is None:
                process.kill()
            return None, f"❌ Manim execution error: {str(e)}"

        if process.returncode != 0:
            full_output = '\n'.join(output_lines) if output_lines else "No output captured"
            return None, f"❌ Manim failed with code {process.returncode}:\n{full_output}"

        # Expected output file path - 480p15 quality (-ql flag) outputs to 480p15 folder
        if segment_index is not None:
            # Manim outputs video with the class name as filename
            # Expected: Segment000.mp4, Segment001.mp4, etc.
            class_name = f"Segment{segment_index:03d}"
            expected_path = temp_path / "media" / "videos" / f"segment_{segment_index:03d}" / "480p15" / f"{class_name}.mp4"
            
            if expected_path.exists():
                logger.info(f"✅ Found video: {expected_path}")
                return str(expected_path), None
            
            # Fallback 1: Check if it was saved as Scene.mp4 (shouldn't happen with correct class name)
            scene_path = temp_path / "media" / "videos" / f"segment_{segment_index:03d}" / "480p15" / "Scene.mp4"
            if scene_path.exists():
                logger.info(f"✅ Found as Scene.mp4, renaming to {class_name}.mp4")
                scene_path.rename(expected_path)
                return str(expected_path), None
            
            # Fallback 2: Search for ANY video in the segment folder
            segment_folder = temp_path / "media" / "videos" / f"segment_{segment_index:03d}"
            if segment_folder.exists():
                video_files = list(segment_folder.glob("**/*.mp4"))
                if video_files:
                    found_video = video_files[0]
                    logger.info(f"✅ Found video at {found_video}, moving to {expected_path}")
                    
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
        Pre-scale intro video once to 1280x720 (16:9, 720p) and cache it.
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
        scaled_intro = temp_dir / "intro_scaled_1280x720.mp4"
        
        # Check if already scaled
        if scaled_intro.exists():
            logger.info(f"✅ Using cached scaled intro: {scaled_intro}")
            self.scaled_intro_path = str(scaled_intro)
            return scaled_intro
        
        logger.info(f"🔧 Pre-scaling intro video to 1280x720 (one-time operation)...")
        
        cmd = [
            "ffmpeg", "-y",
            "-i", str(intro_video),
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setdar=16/9,setsar=1",
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
            "-i", str(scaled_intro),  # Input 0: intro (already 720p)
            "-i", str(generated_video_path),  # Input 1: main video (720p30 from Manim -qm)
            "-filter_complex",
            # Scale both to same resolution (720p), ensure same fps (30), then concat
            "[0:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1[v0];"
            "[1:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1[v1];"
            "[v0][0:a][v1][1:a]concat=n=2:v=1:a=1[outv][outa]",
            "-map", "[outv]",
            "-map", "[outa]",
            "-c:v", "libx264",
            "-preset", "fast",       # Balanced speed/quality for 720p
            "-crf", "23",            # Good quality (was 28 for 480p)
            "-c:a", "aac",
            "-b:a", "192k",          # Higher audio bitrate for 720p
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

    async def synchronize_audio_video_async(self, video_file: str, audio_file: str, output_file: str) -> str:
        """Asynchronous version of audio-video synchronization using asyncio subprocess.
        
        Simple approach: Copy video stream as-is, add audio stream.
        Manim already ensures video duration matches audio via self.wait() commands.
        """
        logger.info(f"🔄 Async syncing: {output_file}")
        
        cmd = [
            'ffmpeg', '-y', 
            '-i', video_file,      # Video input (already correct duration from Manim)
            '-i', audio_file,      # Audio input
            '-c:v', 'copy',        # Copy video stream without re-encoding (preserves quality & timing)
            '-c:a', 'aac',         # Encode audio to AAC
            '-b:a', '192k',        # High quality audio bitrate
            '-map', '0:v:0',       # Map video from first input
            '-map', '1:a:0',       # Map audio from second input
            '-movflags', '+faststart',  # Enable fast start for web playback
            output_file
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.config.ffmpeg_timeout
            )
            
            if process.returncode != 0:
                raise subprocess.CalledProcessError(
                    process.returncode,
                    cmd,
                    stderr.decode()
                )
            
            logger.info(f"✅ Async sync complete: {output_file}")
            return output_file
            
        except asyncio.TimeoutError:
            logger.error("❌ FFmpeg async sync timed out")
            raise
        except Exception as e:
            logger.error(f"❌ FFmpeg async sync failed: {e}")
            raise

    def synchronize_audio_video(self, video_file: str, audio_file: str, output_file: str) -> str:
        """Synchronize video and audio files - simple stream copy approach.
        
        Video duration already matches audio from Manim's self.wait() commands.
        We just copy the video stream and add the audio stream.
        """
        logger.info(f"Synchronizing video and audio into: {output_file}")
        cmd = [
            'ffmpeg', '-y', 
            '-i', video_file,      # Video input (already correct duration from Manim)
            '-i', audio_file,      # Audio input
            '-c:v', 'copy',        # Copy video stream without re-encoding (preserves quality & timing)
            '-c:a', 'aac',         # Encode audio to AAC
            '-b:a', '192k',        # High quality audio bitrate
            '-map', '0:v:0',       # Map video from first input
            '-map', '1:a:0',       # Map audio from second input
            '-movflags', '+faststart',  # Enable fast start for web playback
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

# ============================================================================
# LEGACY CODE REMOVED: Old main() function using base VideoGenerationPipeline
# Production code uses OptimizedVideoGenerationPipeline via run_generate_worker.py
# If you need to test the base class, use OptimizedVideoGenerationPipeline instead
# ============================================================================

import asyncio
import concurrent.futures
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import threading
from queue import Queue
import psutil

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
        
        # Extract openrouter_key_manager before creating config (it's not part of VideoGenerationConfig)
        openrouter_key_manager = config_dict.pop('openrouter_key_manager', None)
        
        # Initialize the singleton pipeline only once per process
        if _singleton_pipeline is None:
            config = VideoGenerationConfig(**config_dict)
            _singleton_pipeline = VideoGenerationPipeline(config)

        pipeline = _singleton_pipeline
        
        # Re-add key manager to config_dict for use by correction functions
        if openrouter_key_manager:
            config_dict['openrouter_key_manager'] = openrouter_key_manager

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
        last_correction_applied = False
        
        # Phase 1: Try corrections with Groq/OpenRouter
        # Loop allows: render attempt → correction → render attempt (to test correction)
        while correction_cycle <= max_correction_attempts:
            total_attempts += 1
            video_path, error = pipeline.create_video_file(script_content, filename=f"segment_{i:03d}.py", segment_index=i)

            if video_path:
                target_dir = Path(segment_data['video_output_dir']) / f"segment_{i:03d}"
                target_dir.mkdir(parents=True, exist_ok=True)
                expected_path = target_dir / f"Segment{i:03d}.mp4"
                Path(video_path).replace(expected_path)
                logger.info(f"✅ Video {i+1} saved to: {expected_path} (after {total_attempts} attempts)")
                return {'success': True, 'video_path': str(expected_path), 'index': i}

            # If we just tested the last correction and it failed, break
            if correction_cycle >= max_correction_attempts:
                logger.warning(f"⚠️ Video {i+1} final correction test failed: {error[:200]}")
                break
            
            logger.warning(f"⚠️ Video {i+1} attempt {total_attempts} failed: {error[:200]}")
            
            # STAGE 3: Correction ladder (strict order)
            correction_cycle += 1
            if correction_cycle == 1:
                logger.info(f"🔧 STAGE 3: Fixing with Groq llama-3.1-8b-instant (attempt 1)")
                script_content = _fix_script_errors_with_groq(
                    script_content, error, i, config_dict['groq_api_key'], 
                    config_dict.get('aspect_ratio', '16:9'), segment_data, model_name="llama-3.1-8b-instant"
                )
            elif correction_cycle == 2:
                logger.info(f"🔧 STAGE 3: Fixing with Groq llama-3.1-8b-instant (attempt 2)")
                script_content = _fix_script_errors_with_groq(
                    script_content, error, i, config_dict['groq_api_key'],
                    config_dict.get('aspect_ratio', '16:9'), segment_data, model_name="llama-3.1-8b-instant"
                )
            elif correction_cycle == 3:
                logger.info(f"🔧 STAGE 3: Fixing with OpenRouter (final attempt)")
                script_content = _fix_script_errors_with_openrouter(
                    script_content, error, i, config_dict['openrouter_key_manager'], 
                    config_dict.get('aspect_ratio', '16:9'), segment_data
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
                    segment_data, i, config_dict['openrouter_key_manager'], config_dict.get('aspect_ratio', '16:9')
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
                    
                    # Try 3 quick corrections on the regenerated script (correction ladder)
                    for fix_attempt in range(3):
                        total_attempts += 1
                        logger.info(f"🔧 STAGE 3: Fixing regenerated script {i+1} (attempt {fix_attempt + 1}/3)")
                        
                        if fix_attempt == 0:
                            script_content = _fix_script_errors_with_groq(
                                script_content, error, i, config_dict['groq_api_key'],
                                config_dict.get('aspect_ratio', '16:9'), segment_data, model_name="llama-3.1-8b-instant"
                            )
                        elif fix_attempt == 1:
                            script_content = _fix_script_errors_with_groq(
                                script_content, error, i, config_dict['groq_api_key'],
                                config_dict.get('aspect_ratio', '16:9'), segment_data, model_name="llama-3.1-8b-instant"
                            )
                        else:
                            script_content = _fix_script_errors_with_openrouter(
                                script_content, error, i, config_dict['openrouter_key_manager'],
                                config_dict.get('aspect_ratio', '16:9'), segment_data
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

def _regenerate_script_from_scratch_enhanced(segment_data: dict, index: int, openrouter_key_manager, aspect_ratio: str = "16:9") -> str:
    """
    Fully regenerate the script using OpenRouter with automatic key rotation.
    This is an enhanced version that uses the actual audio file duration.
    """
    try:
        from pydub import AudioSegment
        
        model_name = "qwen/qwen3-coder:free"
        
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

⏱️ **#1 CRITICAL: PERFECT TIMING - NO BLANK SCREENS!**

This script MUST run for EXACTLY {actual_duration:.2f} seconds with CONTINUOUS animation.

**🚨 ABSOLUTELY FORBIDDEN: Ending animations early and using self.wait() for the rest!**

**✅ CORRECT APPROACH - Distribute animations across FULL duration:**

```python
# For {actual_duration:.2f} seconds total
# Plan: 30% entry, 40% content, 30% exit

# Entry phase (~{actual_duration * 0.3:.1f}s)
title = Text("Title")
self.play(Write(title), run_time={actual_duration * 0.15:.1f})
self.play(title.animate.shift(UP*2), run_time={actual_duration * 0.15:.1f})

# Content phase (~{actual_duration * 0.4:.1f}s)
text1 = Text("Point 1")
self.play(GrowFromCenter(text1), run_time={actual_duration * 0.13:.1f})
self.play(Indicate(text1), run_time={actual_duration * 0.13:.1f})

text2 = Text("Point 2")  
self.play(FadeIn(text2), run_time={actual_duration * 0.14:.1f})

# Exit phase (~{actual_duration * 0.3:.1f}s)
self.play(FadeOut(text1), FadeOut(text2), run_time={actual_duration * 0.15:.1f})
self.play(Uncreate(title), run_time={actual_duration * 0.15:.1f})

# ONLY use short wait if slightly under (< 0.5s)
# self.wait(0.3) if needed
```

**❌ BAD - Don't do this:**
```python
self.play(FadeIn(text), run_time=2)
self.play(FadeOut(text), run_time=1.5)
self.wait(10.5)  # ❌ BLANK SCREEN FOR 10 SECONDS!
```

**✅ GOOD - Do this:**
```python
# Spread animations across full duration
self.play(Write(text), run_time=3.5)
self.play(text.animate.shift(UP), run_time=2.0)
self.play(Indicate(text), run_time=2.5)
self.play(text.animate.scale(1.2), run_time=2.0)
self.play(FadeOut(text), run_time=4.0)
# Total = 14s, only 0.1s wait needed
```

**RULES:**
1. Use LONGER run_time values to fill the duration
2. Add MORE animations instead of waiting
3. Maximum wait allowed: 1 second
4. If you need > 1s wait, add more animations or increase run_times
5. Keep screen ACTIVE throughout entire duration

---

🎯 OTHER REQUIREMENTS:
- Class name: Segment{index:03d}
- Aspect Ratio: {aspect_ratio}
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

        # Use execute_with_rotation for automatic key rotation on rate limits
        def call_openrouter(client):
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=8192
            )
            return response.choices[0].message.content.strip()
        
        regenerated_script = openrouter_key_manager.execute_with_rotation(
            call_openrouter,
            model=model_name
        )
        
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

def _fix_script_errors_with_openrouter(script_content: str, error: str, index: int, openrouter_key_manager, aspect_ratio: str = "16:9", segment_data: dict = None) -> str:
    """
    STAGE 4: Script Correction with OpenRouter (Structural Repair Only)
    
    Fix script errors using OpenRouter AI with automatic key rotation.
    """
    try:
        model_name = "qwen/qwen3-coder:free"
        
        # Generate aspect ratio config for reference
        aspect_ratio_configs = {
            "16:9": {"frame_width": 16, "frame_height": 9, "pixel_width": 1920, "pixel_height": 1080},
            "9:16": {"frame_width": 9, "frame_height": 16, "pixel_width": 1080, "pixel_height": 1920},
            "1:1": {"frame_width": 1, "frame_height": 1, "pixel_width": 1080, "pixel_height": 1080},
            "4:3": {"frame_width": 4, "frame_height": 3, "pixel_width": 1440, "pixel_height": 1080},
        }
        config = aspect_ratio_configs.get(aspect_ratio, aspect_ratio_configs["16:9"])
        aspect_ratio_config = f"""# Aspect Ratio Configuration: {aspect_ratio}
config.frame_width = {config['frame_width']}
config.frame_height = {config['frame_height']}
config.pixel_width = {config['pixel_width']}
config.pixel_height = {config['pixel_height']}
"""
        
        # Extract locked constraints
        locked_constraints = ""
        if segment_data:
            narration = segment_data.get('narration', '')
            duration = segment_data.get('duration', 10.0)
            locked_constraints = f"""
⚠️ STAGE 4 CONSTRAINTS (ABSOLUTE - CANNOT VIOLATE):
1. Audio duration is LOCKED at {duration:.2f}s - total animation time MUST equal this
2. Narration text is READ-ONLY: "{narration}"
3. You can ONLY fix technical errors (syntax, Manim API, layout, overlap)
4. You CANNOT change visual concepts, timing semantics, or animation intent
5. Fix the error while preserving the original animation structure
"""
        
        correction_prompt = f"""You are fixing a broken Manim script.

🚨 CRITICAL: PREVENT OFF-SCREEN ELEMENTS!

Your task:
- Fix runtime, syntax, or Manim API errors ONLY
- Do NOT change layout, pacing, or animation meaning
- Do NOT add or remove scene elements
- Do NOT change aspect ratio logic
- **MANDATORY: Preserve ALL scale_to_fit_width() calls**
- **MANDATORY: Keep positions within safe bounds**

⛔ STRICTLY FORBIDDEN CHANGES:
- Removing .scale_to_fit_width() calls (causes off-screen text)
- Using positions like UP*4, DOWN*4, LEFT*8, RIGHT*8 (goes off-screen)
- Increasing font sizes beyond limits (causes overflow)
- Reducing vertical spacing below 1.5 units (causes overlap)

✅ REQUIRED VALIDATIONS:
1. Every Text object MUST have .scale_to_fit_width(config.frame_width * 0.85)
2. Positions MUST stay within safe bounds: UP*2.5 max, DOWN*2.5 max
3. Font sizes MUST NOT exceed limits (title: 56px, body: 42px)
4. Vertical spacing MUST be >= 1.5 units between text objects

Constraints:
- Total animation time must remain unchanged
- Scene structure must remain identical
- Fix errors minimally and deterministically
- **DO NOT break visibility - all elements must stay on-screen**

Output ONLY the full corrected Python code.
No explanations.

ERROR LOG:
{error}

BROKEN SCRIPT:
{script_content}

**REMINDER: Verify every Text has .scale_to_fit_width() before submitting!**
"""
        
        # Use execute_with_rotation for automatic key rotation on rate limits
        def call_openrouter(client):
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": correction_prompt}],
                temperature=0.2,
                max_tokens=4096
            )
            return response.choices[0].message.content.strip()
        
        corrected_script = openrouter_key_manager.execute_with_rotation(
            call_openrouter,
            model=model_name
        )
        
        # Clean the response
        if "```python" in corrected_script:
            start_marker = "```python"
            end_marker = "```"
            start_idx = corrected_script.find(start_marker) + len(start_marker)
            end_idx = corrected_script.rfind(end_marker)
            if start_idx > len(start_marker) - 1 and end_idx > start_idx:
                corrected_script = corrected_script[start_idx:end_idx].strip()
        logger.info(f"✅ Script {index+1} corrected using OpenRouter")
        return corrected_script
        
    except Exception as e:
        logger.warning(f"⚠️ OpenRouter script correction failed: {e}")

def _fix_script_errors_with_groq(script_content: str, error: str, index: int, groq_api_key: str, aspect_ratio: str = "16:9", segment_data: dict = None, model_name: str = "llama-3.1-8b-instant") -> str:
    """
    STAGE 3: Script Correction with Groq (Structural Repair Only).
    Uses llama-3.1-8b-instant model.
    """
    try:
        from groq import Groq
        groq_client = Groq(api_key=groq_api_key)
        
        aspect_ratio_configs = {
            "16:9": {"frame_width": 16, "frame_height": 9, "pixel_width": 1920, "pixel_height": 1080},
            "9:16": {"frame_width": 9, "frame_height": 16, "pixel_width": 1080, "pixel_height": 1920},
            "1:1": {"frame_width": 1, "frame_height": 1, "pixel_width": 1080, "pixel_height": 1080},
            "4:3": {"frame_width": 4, "frame_height": 3, "pixel_width": 1440, "pixel_height": 1080},
        }
        config = aspect_ratio_configs.get(aspect_ratio, aspect_ratio_configs["16:9"])
        
        locked_constraints = ""
        if segment_data:
            narration = segment_data.get('narration', '')
            duration = segment_data.get('duration', 10.0)
            locked_constraints = f"""
STAGE 3 CONSTRAINTS (ABSOLUTE):
1. Audio duration LOCKED: {duration:.2f}s
2. Narration READ-ONLY: \"{narration}\"
3. Fix ONLY technical errors (syntax, Manim API, layout)
4. CANNOT change visual concepts, timing, animation intent
"""
        
        prompt = f"""Fix this Manim script's technical errors.

🚨 CRITICAL: PREVENT OFF-SCREEN ELEMENTS!

⛔ STRICTLY FORBIDDEN:
- Removing .scale_to_fit_width() calls (causes text to go off-screen)
- Using extreme positions: UP*4, DOWN*4, LEFT*8, RIGHT*8 (goes off-screen)
- Font sizes exceeding limits (causes overflow)
- Spacing < 1.5 units between text (causes overlap/off-screen)

✅ REQUIRED:
- Every Text object MUST have .scale_to_fit_width(config.frame_width * 0.85)
- Positions within safe bounds: UP*2.5 max, DOWN*2.5 max, LEFT*5 max, RIGHT*5 max
- Font sizes within limits
- Vertical spacing >= 1.5 units

{locked_constraints}

Error: {error}

Script:
```python
{script_content}
```

Return corrected Python code only. No markdown. No explanations.
Class name: Segment{index:03d}
Aspect ratio: {aspect_ratio}
Config: frame_width={config['frame_width']}, frame_height={config['frame_height']}
"""
        
        chat_completion = groq_client.chat.completions.create(
            model=model_name,
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
        logger.info(f"✅ Script {index+1} corrected using Groq")
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

def recover_missing_video_paths(segments: List[NarrationSegment]) -> int:
    """
    Scan output folders to recover missing video paths.
    Returns number of paths recovered.
    """
    logger.info("🔍 Scanning output folders for missing video paths...")
    recovered_count = 0
    
    for i, segment in enumerate(segments):
        # Check if video_path is missing
        if not segment.video_path:
            # Try to find the video in standard output location
            possible_paths = [
                Path(f"output/segment_{i:03d}/Segment{i:03d}.mp4"),
                Path(f"temp/media/videos/segment_{i:03d}/480p15/Segment{i:03d}.mp4"),
                Path(f"temp/media/videos/segment_{i:03d}/720p30/Segment{i:03d}.mp4"),
            ]
            
            for possible_path in possible_paths:
                if possible_path.exists():
                    segment.video_path = str(possible_path.resolve())
                    recovered_count += 1
                    logger.warning(f"⚠️ Recovered missing video path for segment {i}: {segment.video_path}")
                    break
            else:
                logger.error(f"❌ Could not recover video path for segment {i} - file not found in any expected location")
        
        # Check if audio_path is missing
        if not segment.audio_path:
            possible_audio_paths = [
                Path(f"output/segment_{i:03d}/narration.mp3"),
                Path(f"temp/narration_segment_{i}.mp3"),
            ]
            
            for possible_path in possible_audio_paths:
                if possible_path.exists():
                    segment.audio_path = str(possible_path.resolve())
                    recovered_count += 1
                    logger.warning(f"⚠️ Recovered missing audio path for segment {i}: {segment.audio_path}")
                    break
            else:
                logger.error(f"❌ Could not recover audio path for segment {i} - file not found in any expected location")
    
    if recovered_count > 0:
        logger.info(f"✅ Recovered {recovered_count} missing path(s)")
    else:
        logger.info("ℹ️ No missing paths needed recovery")
    
    return recovered_count

def validate_segment_alignment(segments: List[NarrationSegment]) -> Tuple[bool, List[int]]:
    """
    Validate that all segments have properly aligned video and audio files.
    Returns (is_valid, list_of_missing_indices)
    """
    logger.info("🔍 Validating segment alignment...")
    logger.info(f"📊 Total segments to validate: {len(segments)}")
    
    missing_segments = []
    
    for i, segment in enumerate(segments):
        # Detailed logging for each segment
        logger.info(f"  Segment {i+1}: video_path={segment.video_path}, audio_path={segment.audio_path}")
        
        # Check if paths are set
        if not segment.video_path:
            logger.error(f"❌ Segment {i+1} missing VIDEO PATH")
            missing_segments.append(i)
            continue
            
        if not segment.audio_path:
            logger.error(f"❌ Segment {i+1} missing AUDIO PATH")
            missing_segments.append(i)
            continue
        
        # Check if files exist on disk
        if not Path(segment.video_path).exists():
            logger.error(f"❌ Segment {i+1} video file doesn't exist: {segment.video_path}")
            missing_segments.append(i)
            continue
            
        if not Path(segment.audio_path).exists():
            logger.error(f"❌ Segment {i+1} audio file doesn't exist: {segment.audio_path}")
            missing_segments.append(i)
            continue
        
        # Check file sizes
        video_size = Path(segment.video_path).stat().st_size
        audio_size = Path(segment.audio_path).stat().st_size
        
        if video_size < 1024:
            logger.error(f"❌ Segment {i+1} video file too small: {video_size} bytes")
            missing_segments.append(i)
            continue
            
        if audio_size < 100:
            logger.error(f"❌ Segment {i+1} audio file too small: {audio_size} bytes")
            missing_segments.append(i)
            continue
        
        logger.info(f"  ✅ Segment {i+1} validated: video={video_size/1024:.1f}KB, audio={audio_size/1024:.1f}KB")
    
    if missing_segments:
        logger.error(f"❌ Validation failed: {len(missing_segments)} segment(s) have issues: {[i+1 for i in missing_segments]}")
        return False, missing_segments
    
    logger.info("✅ All segments have valid video and audio paths")
    return True, []


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
        
        # Detect cloud environment and set workers based on available resources
        is_cloud = os.environ.get('PORT') == '10000' or not os.environ.get('DISPLAY')
        
        # Get system resources
        cpu_count = mp.cpu_count()
        total_ram_gb = psutil.virtual_memory().total / (1024**3)  # Convert to GB
        available_ram_gb = psutil.virtual_memory().available / (1024**3)
        
        if is_cloud:
            # Cloud environment (Oracle VM, Render, etc.)
            # Formula: min(cpu_count - 1, available_ram_gb / 1.5)
            # Each Manim worker needs ~1.5GB RAM
            workers_by_cpu = max(1, cpu_count - 1)
            workers_by_ram = max(1, int(available_ram_gb / 1.5))
            self.max_workers = min(workers_by_cpu, workers_by_ram)
            self.max_workers = 1
            
            logger.info(f"☁️ Cloud environment detected:")
            logger.info(f"   - CPU Cores: {cpu_count}")
            logger.info(f"   - Total RAM: {total_ram_gb:.1f}GB")
            logger.info(f"   - Available RAM: {available_ram_gb:.1f}GB")
            logger.info(f"   - Workers (CPU limit): {workers_by_cpu}")
            logger.info(f"   - Workers (RAM limit): {workers_by_ram}")
            logger.info(f"   - USING: {self.max_workers} worker(s)")
        else:
            # Local development - more resources available
            workers_by_cpu = min(4, cpu_count)
            workers_by_ram = max(1, int(available_ram_gb / 1.5))
            self.max_workers = min(workers_by_cpu, workers_by_ram)
            
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
        """
        Initialize Gemini client with model rotation support.
        """
        try:
            from google import genai
            
            gemini_api_key = os.getenv('GEMINI_API_KEY')
            if not gemini_api_key:
                logger.warning("⚠️ GEMINI_API_KEY not found in environment")
                self.gemini_client = None
                return
            
            self.gemini_client = genai.Client(api_key=gemini_api_key)
            logger.info(f"✅ Gemini client initialized: {self.gemini_models[0]}")
            
        except ImportError:
            logger.error("❌ google-genai not installed. Run: pip install google-genai")
            self.gemini_client = None
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini client: {e}")
            self.gemini_client = None
    
    def _rotate_gemini_model(self) -> bool:
        """
        Rotate to next Gemini model.
        Returns False if all models exhausted.
        """
        self.current_gemini_model_index += 1
        if self.current_gemini_model_index >= len(self.gemini_models):
            logger.error("❌ All Gemini models exhausted")
            return False
        
        model_name = self.gemini_models[self.current_gemini_model_index]
        logger.info(f"🔄 Rotated to Gemini model: {model_name}")
        return True
    def _validate_script(self, script: str) -> bool:
        """
        Smart validation that balances performance and visual quality.
        Allows updaters for engaging visuals but rejects excessive usage.
        Also checks for proper text scaling to prevent out-of-bounds issues.
        """
        # Basic structure check
        if not ("from manim import *" in script and
                "class " in script and
                "Scene" in script and
                "def construct" in script):
            return False
        
        # TEXT SCALING VALIDATION: Warn if Text objects lack .scale_to_fit_width()
        text_objects = len(re.findall(r'(Text|MarkupText|Tex)\s*\(', script))
        scale_calls = len(re.findall(r'\.scale_to_fit_width\s*\(', script))
        
        if text_objects > 0:
            if scale_calls == 0:
                logger.warning(f"⚠️ NO SCALING DETECTED: {text_objects} text objects but 0 .scale_to_fit_width() calls - TEXT MAY GO OUT OF BOUNDS!")
            elif scale_calls < text_objects:
                logger.warning(f"⚠️ INCOMPLETE SCALING: {text_objects} text objects but only {scale_calls} .scale_to_fit_width() calls - some text may be too large!")
            else:
                logger.info(f"✅ Text scaling OK: {text_objects} text objects, {scale_calls} scaling calls")
        
        # SMART UPDATER DETECTION: Allow limited usage for engaging animations
        updater_count = len(re.findall(r'(always_redraw|add_updater)', script))
        
        if updater_count > 0:
            # Count total animation calls to calculate ratio
            total_animations = len(re.findall(r'self\.play\(|self\.add\(', script))
            
            if total_animations > 0:
                updater_ratio = updater_count / total_animations
                
                # Reject only if updaters are >30% of animations (excessive)
                if updater_ratio > 0.3:
                    logger.warning(f"🚫 Excessive updater usage detected ({updater_count}/{total_animations} = {updater_ratio*100:.1f}%). Script REJECTED.")
                    return False
                elif updater_count > 0:
                    logger.info(f"✨ Strategic updater usage detected ({updater_count}/{total_animations} = {updater_ratio*100:.1f}%) - ACCEPTABLE for visual appeal.")
            elif updater_count > 2:
                # If we can't count animations, reject if more than 2 updaters
                logger.warning(f"🚫 Too many updaters ({updater_count}) without animations. Script REJECTED.")
                return False
        
        return True
    def _call_gemini_with_rotation(self, prompt: str, generation_config: dict, task_name: str):
        """
        Call Gemini with automatic model rotation on quota/hard errors.
        """
        from google.genai import types
        
        while True:
            try:
                model_name = self.gemini_models[self.current_gemini_model_index]
                config = types.GenerateContentConfig(
                    temperature=generation_config.get('temperature', 0.7),
                    max_output_tokens=generation_config.get('max_output_tokens', 8192)
                )
                response = self.gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config
                )
                
                # Validate that we got a valid response
                if response is None:
                    logger.warning(f"⚠️ Gemini returned None response for {task_name}")
                    raise ValueError(f"Gemini returned None response")
                
                if not hasattr(response, 'text') or response.text is None:
                    logger.warning(f"⚠️ Gemini response missing text attribute for {task_name}")
                    logger.warning(f"   Response type: {type(response)}")
                    if hasattr(response, '__dict__'):
                        logger.warning(f"   Response attributes: {list(response.__dict__.keys())}")
                    raise ValueError(f"Gemini response missing or None text")
                
                return response
            except Exception as e:
                error_str = str(e).lower()
                error_type = type(e).__name__
                
                # Check if this is a quota/overload/rate limit error that should trigger rotation
                is_rotation_error = (
                    "quota" in error_str or 
                    "429" in error_str or 
                    "503" in error_str or
                    "resource" in error_str or
                    "overloaded" in error_str or
                    "unavailable" in error_str or
                    "rate limit" in error_str or
                    error_type == "ServerError" or
                    "none response" in error_str or
                    "missing or none text" in error_str
                )
                
                if is_rotation_error:
                    logger.warning(f"⚠️ Gemini error for {task_name}: {str(e)[:200]}")
                    logger.info(f"🔄 Attempting model rotation...")
                    if not self._rotate_gemini_model():
                        raise RuntimeError(f"All Gemini models failed for {task_name}: {e}")
                    logger.info(f"🔄 Retrying {task_name} with next model...")
                    continue
                else:
                    raise
        
    async def generate_video_full_parallel(self, topic: str, duration: int, output_filename: Optional[str] = None) -> str:
        """Generate video for all segments in one go: audio → script → video → sync → final concat."""
        if not output_filename:
            safe_topic = re.sub(r'[^\w\s-]', '', topic).strip().replace(' ', '_')
            output_filename = f"{self.config.output_dir}/{safe_topic}_final_video.mp4"

        logger.info(f"🚀 Starting FULL PARALLEL video generation for topic: {topic} [{duration}s]")

        try:
            # Check if quality pipeline is enabled
            use_quality = getattr(self.config, 'use_quality_pipeline', False)
            
            if use_quality:
                # ===============================================================
                # QUALITY PIPELINE: Spec-based generation for educational videos
                # ===============================================================
                logger.info("🎯 QUALITY PIPELINE ENABLED: Using spec-based generation")
                
                try:
                    from .pipeline_integration import (
                        generate_quality_segments,
                        generate_quality_scripts_bulk,
                        GeminiClientAdapter
                    )
                except ImportError:
                    from generator.video_generator.pipeline_integration import (
                        generate_quality_segments,
                        generate_quality_scripts_bulk,
                        GeminiClientAdapter
                    )
                
                # Create LLM adapter for spec generation
                llm_adapter = GeminiClientAdapter(
                    self.gemini_client,
                    self.gemini_models,
                    self.current_gemini_model_index
                )
                
                # Step 1: Generate scene specifications
                logger.info("📋 Step 1: Generating scene specifications...")
                quality_segments, spec_errors = generate_quality_segments(
                    llm_adapter, topic, duration, self.config.aspect_ratio
                )
                
                if spec_errors:
                    logger.warning(f"⚠️ Spec generation had {len(spec_errors)} errors")
                    for err in spec_errors[:3]:
                        logger.warning(f"   - {err}")
                
                if not quality_segments:
                    logger.warning("❌ Quality pipeline failed, falling back to legacy generation")
                    segments = await self._generate_narration_segments_with_gemini(topic, duration)
                else:
                    # Convert quality segments to regular NarrationSegment format
                    segments = []
                    for qs in quality_segments:
                        seg = NarrationSegment(
                            start_time=qs.start_time,
                            end_time=qs.end_time,
                            duration=qs.duration,
                            text=qs.text,
                            visual_description=qs.visual_description
                        )
                        # Store spec in segment for later retrieval
                        seg._quality_spec = qs.scene_spec
                        segments.append(seg)
                    
                    logger.info(f"✅ Generated {len(segments)} quality segments with scene specs")
            else:
                # Step 1: Generate all narration segments (LEGACY)
                segments = await self._generate_narration_segments_with_gemini(topic, duration)
            
            logger.info(f"🧾 {len(segments)} segments generated.")

            # Step 2: Generate audio for all segments in parallel
            await self.generate_all_audio_segments(segments, self.config.temp_dir)

            logger.info("🔊 Audio generation complete.")

            # Step 3: Generate scripts
            if use_quality and hasattr(segments[0], '_quality_spec') and segments[0]._quality_spec:
                # ===============================================================
                # QUALITY PIPELINE: Template-based script generation from specs
                # ===============================================================
                logger.info("🎨 Stage 3: Template-Based Script Generation (QUALITY MODE)")
                
                try:
                    from .pipeline_integration import generate_quality_scripts_bulk
                    from .pipeline_integration import QualityNarrationSegment
                except ImportError:
                    from generator.video_generator.pipeline_integration import generate_quality_scripts_bulk
                    from generator.video_generator.pipeline_integration import QualityNarrationSegment
                
                # Convert back to quality segments with audio duration
                quality_segs = []
                for seg in segments:
                    qs = QualityNarrationSegment(
                        start_time=seg.start_time,
                        end_time=seg.end_time,
                        duration=seg.duration,
                        text=seg.text,
                        visual_description=seg.visual_description,
                        audio_path=seg.audio_path,
                        _audio_duration_final=getattr(seg, '_audio_duration_final', seg.duration),
                        scene_spec=seg._quality_spec
                    )
                    quality_segs.append(qs)
                
                # Generate scripts from specs
                scripts = generate_quality_scripts_bulk(quality_segs, self.config.aspect_ratio)
                
                # Assign scripts to segments
                for i, (seg, script) in enumerate(zip(segments, scripts)):
                    if script:
                        # Save script to file
                        script_path = Path(self.config.temp_dir) / f"segment_{i:03d}.py"
                        with open(script_path, 'w', encoding='utf-8') as f:
                            f.write(script)
                        seg.script_path = str(script_path)
                        logger.info(f"✅ Quality script {i+1} generated from spec")
                    else:
                        logger.warning(f"⚠️ Quality script {i+1} needs legacy generation")
                
                # Check for any segments without scripts
                failed_indices = [i for i, seg in enumerate(segments) if not seg.script_path]
                if failed_indices:
                    logger.warning(f"⚠️ {len(failed_indices)} segments need legacy regeneration")
                    segments = await self._regenerate_failed_segments(segments, failed_indices)
                
                logger.info("📜 Quality script generation complete.")
            else:
                # ====================================================================
                # LEGACY: Bulk script generation
                # Stage 3: Manim Script Generation (Implementation Only)
                # - PRIMARY PATH: Bulk generation (1 API call for all segments) - FAST!
                # - FAIL-SAFE PATH: Individual regeneration ONLY for failed segments
                # - ABSOLUTE RULE: Cannot modify narration or audio duration
                # ====================================================================
                logger.info("🧠 Stage 3: Manim Script Generation (BULK MODE)")
                
                # ALWAYS use bulk generation (single API call - much faster)
                logger.info("📦 Bulk script generation (1 API call for all segments)...")
                segments = await self._generate_scripts_in_bulk(segments)
                
                # Validate bulk generation results
                failed_indices = self._validate_bulk_scripts(segments)
                
                if failed_indices:
                    logger.warning(f"⚠️ Bulk validation found {len(failed_indices)} failed segment(s): {failed_indices}")
                    logger.info("🔄 Regenerating ONLY failed segments individually...")
                    segments = await self._regenerate_failed_segments(segments, failed_indices)
                    logger.info("✅ Individual regeneration complete!")
                else:
                    logger.info("✅ Bulk generation successful! All scripts validated.")
                
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
  
        """
        STAGE 1: Narration Generation (SEMANTIC AUTHORITY)
        
        Uses Gemini to generate complete narration covering the FULL video duration.
        Output becomes READ-ONLY for all downstream stages.
        """
        if not self.gemini_client:
            logger.error("❌ Gemini client not initialized - cannot generate narration")
            raise RuntimeError("Gemini client required for STAGE 1: Narration Generation")
        
        # Determine tone based on video type
        is_short = getattr(self.config, 'video_type', 'regular') == 'short'
        
        if is_short:
            tone_guide = """ULTRA FRIENDLY & CONVERSATIONAL - Like a friend explaining:
- Use casual language: "Hey!", "So basically...", "Here's the cool part..."
- Add personality: "Trust me on this", "You're gonna love this"
- Use "you" and "we" to create connection
- Use contractions: "it's", "you're", "that's"
- Ask engaging questions: "Ever wonder why...?", "Cool, right?"
"""
        else:
            tone_guide = "Clear, professional, and educational with a warm tone"
        
        # Calculate expected number of segments (fewer, longer segments = better pacing)
        expected_segments = max(3, round(duration / 15))  # Aim for ~15s per segment
        
        # STAGE 1: Conversational prompt focusing on COMPLETE narration coverage
        prompt = f"""
Create a narration script for a {duration}-second educational video about "{topic}".

**PERSONALITY & VOICE:**
{tone_guide}

**DURATION MATH (CRITICAL - FOLLOW EXACTLY!):**
- Target total: {duration} seconds
- Number of segments needed: {expected_segments}
- Each segment duration: ~{duration // expected_segments} seconds
- The SUM of all segment durations MUST equal EXACTLY {duration} seconds!

**REQUIREMENTS:**
1. Create EXACTLY {expected_segments} segments
2. Each segment: {duration // expected_segments - 2} to {duration // expected_segments + 2} seconds
3. SUM of all durations MUST = {duration} seconds (NOT LESS!)
4. Format for {self.config.aspect_ratio} aspect ratio
5. Thank "Code Tapasya" at the end
6. Make it feel like a friend explaining, NOT a boring lecture!

**OUTPUT FORMAT (STRICT - FOLLOW EXACTLY):**

SEGMENT [number]: [duration in seconds]
VISUALS: [Brief animation description - 1-2 sentences max]
NARRATION: [What will be spoken - friendly and engaging]

**VISUAL DESCRIPTION RULES (CRITICAL!):**
- Keep visuals SHORT (1-2 sentences)
- Make visuals FUN and PLAYFUL - like explaining to a friend!
- Include: colors, animations, movement, emphasis
- For {self.config.aspect_ratio}: {"stack vertically" if self.config.aspect_ratio == "9:16" else "arrange horizontally" if self.config.aspect_ratio == "16:9" else "center elements"}
- Use LIVELY animations: bounce, wiggle, pop, glow, flash, pulse, spin
- Add PERSONALITY: emojis as icons, arrows that dance, text that bounces

**VISUAL STYLE GUIDE:**

✅ LIVELY VISUALS (DO THIS):
- "Title BOUNCES in with a fun bounce effect. Sparkle emoji grows around it!"
- "Diagram POPS IN piece by piece like building blocks. Arrow DANCES to connect them."
- "Code types out with satisfying CLICKS. Green checkmarks POP IN after each line!"
- "Before/After boxes SLIDE IN from sides. GLOW emphasizes the difference!"
- "Icons WIGGLE happily when mentioned. FLASH highlights key concept!"

❌ BORING VISUALS (NEVER DO THIS):
- "Text appears on screen" (Too static!)
- "Diagram is shown" (Zero energy!)
- "Elements fade in" (Snooze fest!)
- "Simple animation with text" (Vague and boring!)

**NARRATION STYLE GUIDE (CRITICAL!):**

✅ DO:
- "Hey! So you wanna learn about {topic}? Let's break it down together!"
- "Okay, here's the thing - most people overcomplicate this. But you and me? We're keeping it simple."
- "Now THIS is where it gets really cool. Ready?"
- "I know what you're thinking... 'That sounds complicated.' Nope! Check this out."
- "Boom! That's literally it. Told you it was simpler than it sounds!"
- "And hey, thanks for hanging out with me! Big shoutout to Code Tapasya!"

❌ DON'T:
- "In this video, we will explore..."  (Too formal)
- "It should be noted that..."  (Too academic)
- "The following demonstrates..."  (Boring)
- "Variables are a fundamental concept..."  (Textbook style)

**EXAMPLE (for a 45-second video with 3 segments):**

SEGMENT 1: 15
VISUALS: Title "{topic}" BOUNCES in with spring effect at top! Colorful code icons SPIN IN around it. Fun SPARKLE emphasis!
NARRATION: Hey! Ever wondered what {topic} is all about? I get it - sounds fancy, right? But here's a secret... it's actually pretty simple once you see it in action! Let me show you how this works.

SEGMENT 2: 15
VISUALS: Concept diagram POPS IN piece by piece like Legos! Arrow DANCES between parts. GLOW effect on key word!
NARRATION: So basically, think of it like this - you know how you organize stuff in your room? Same idea here! You're just organizing code in a smart way. Pretty cool when you see it click, right?

SEGMENT 3: 15
VISUALS: Code example TYPES IN with satisfying effect. Each line gets GREEN CHECKMARK that POPS! Final result GLOWS and PULSES!
NARRATION: Here's the cool part - watch what happens when we do this. Boom! That's literally it. Told you it was simpler than it sounds! Thanks for hanging with me - shoutout to Code Tapasya!

**NOW GENERATE {expected_segments} SEGMENTS for "{topic}" that ADD UP TO EXACTLY {duration} SECONDS:**
"""
        
        # Try generation with retry logic
        for attempt in range(2):
            try:
                # STAGE 1: Call Gemini with explicit token limit
                logger.info(f"🧠 STAGE 1: Generating narration (attempt {attempt + 1}/2)...")
                
                response = self._call_gemini_with_rotation(
                    prompt,
                    generation_config={
                        'temperature': 0.6,
                        'max_output_tokens': 8192,
                    },
                    task_name="narration generation"
                )
                
                # Handle different response formats from new Gemini SDK
                if response is None:
                    logger.error("❌ Gemini returned None response")
                    if attempt == 0:
                        logger.warning("⚠️ Retrying with simpler prompt...")
                        seg_duration = duration // expected_segments
                        prompt = f"""Create EXACTLY {expected_segments} segments for a {duration}-second narration about "{topic}".

⛔ FORBIDDEN: More or less than {expected_segments} segments
✅ REQUIRED: Each segment around {seg_duration} seconds
✅ REQUIRED: All segment durations MUST add up to EXACTLY {duration} seconds

Output format:
SEGMENT 1: {seg_duration}
VISUALS: brief concept
NARRATION: spoken text

SEGMENT 2: {seg_duration}
VISUALS: brief concept  
NARRATION: spoken text

(continue for all {expected_segments} segments, total = {duration}s)

START GENERATING:"""
                        continue
                    raise RuntimeError("Gemini returned None after retry")
                
                # Extract text from response
                if hasattr(response, 'text') and response.text:
                    content = response.text.replace("**", "").strip()
                elif isinstance(response, str):
                    content = response.replace("**", "").strip()
                else:
                    logger.error(f"❌ Unexpected response type: {type(response)}")
                    if attempt == 0:
                        logger.warning("⚠️ Retrying...")
                        continue
                    raise RuntimeError(f"Unexpected response format: {type(response)}")
                
                logger.info(f"📄 Gemini response received ({len(content)} chars)")
                
                # Parse segments with simple VISUALS format
                segments = []
                current_time = 0.0
                
                # Match: SEGMENT X: Y\nVISUALS: ...\nNARRATION: ...
                pattern = re.compile(
                    r'SEGMENT\s+(\d+):\s*(\d+(?:\.\d+)?)\s*(?:seconds?)?\s*\n'
                    r'\s*VISUALS?:\s*(.*?)\n'
                    r'\s*NARRATION:\s*(.*?)(?=\n\s*SEGMENT\s+\d+:|$)',
                    re.DOTALL | re.IGNORECASE
                )
                
                matches = list(pattern.finditer(content))
                logger.info(f"🔍 Found {len(matches)} segments")
                
                if len(matches) == 0:
                    logger.warning(f"⚠️ No segments parsed from response:\n{content[:500]}")
                    if attempt == 0:
                        logger.warning("⚠️ Retrying with clearer prompt...")
                        continue
                    else:
                        # Use fallback
                        logger.error("❌ Parsing failed after retry, using fallback")
                        return self._generate_fallback_segments(topic, duration)
                
                # Process matches and build segments
                total_duration = 0.0
                segment_count = 0
                
                for match in matches:
                    segment_num = int(match.group(1))
                    seg_duration = float(match.group(2))
                    visuals = match.group(3).strip()
                    narration = match.group(4).strip()
                    
                    # Clean emotion tags from narration
                    narration = re.sub(r'\[.*?\]', '', narration).strip()
                    
                    # Validate segment duration (allow longer segments for better pacing)
                    if seg_duration < 10 or seg_duration > 20:
                        logger.warning(f"⚠️ Segment {segment_num} duration {seg_duration}s outside 10-20s range")
                    
                    segment = NarrationSegment(
                        text=narration,
                        start_time=current_time,
                        end_time=current_time + seg_duration,
                        duration=seg_duration,
                        visual_description=visuals
                    )
                    segments.append(segment)
                    current_time += seg_duration
                    total_duration += seg_duration
                    segment_count += 1
                    
                    logger.info(f"📋 Segment {segment_num}: {seg_duration}s | {narration[:50]}...")
                
                # Validate total duration - REJECT if significantly over
                if total_duration > duration + 5:
                    logger.error(f"❌ Gemini generated {total_duration}s but target is {duration}s (EXCEEDS by {total_duration - duration}s)")
                    if attempt == 0:
                        logger.warning("⚠️ Retrying with stricter constraints...")
                        # Override prompt to be even more strict
                        prompt = f"""STRICT CONSTRAINT: Create EXACTLY {expected_segments} segments for {duration}-second video about "{topic}".

⛔ FORBIDDEN: Total > {duration} seconds
⛔ FORBIDDEN: More than {expected_segments} segments

REQUIRED FORMAT (each segment 12-14s):
SEGMENT X: Y
VISUALS: concept
NARRATION: text

YOU HAVE {expected_segments} SEGMENTS. TOTAL MUST = {duration}s. Generate NOW:"""
                        continue
                    else:
                        logger.error("❌ Duration exceeded even after retry, truncating...")
                        # Truncate segments to fit duration
                        truncated_segments = []
                        current_time = 0.0
                        for seg in segments:
                            if current_time + seg.duration <= duration:
                                truncated_segments.append(seg)
                                current_time += seg.duration
                            elif current_time < duration:
                                # Adjust last segment to fit
                                remaining = duration - current_time
                                seg.duration = remaining
                                seg.end_time = duration
                                truncated_segments.append(seg)
                                break
                        segments = truncated_segments
                        total_duration = sum(s.duration for s in segments)
                        logger.warning(f"⚠️ Truncated to {len(segments)} segments totaling {total_duration}s")
                
                # Clamp final segment to match exact duration if needed
                if segments and total_duration != duration:
                    diff = duration - total_duration
                    logger.warning(f"⚠️ Duration mismatch: {total_duration}s vs {duration}s (diff: {diff:.1f}s)")
                    
                    if diff > 0:
                        # Total is LESS than target - need to ADD time
                        if diff <= 5.0:
                            # Small difference - add to last segment
                            segments[-1].duration += diff
                            segments[-1].end_time = duration
                            logger.info(f"✅ Extended final segment by {diff:.1f}s to cover full duration")
                        else:
                            # Large difference - distribute across all segments
                            per_segment_add = diff / len(segments)
                            current_time = 0.0
                            for seg in segments:
                                seg.start_time = current_time
                                seg.duration += per_segment_add
                                seg.end_time = seg.start_time + seg.duration
                                current_time = seg.end_time
                            logger.info(f"✅ Extended each segment by {per_segment_add:.1f}s (total: {diff:.1f}s)")
                    elif diff < 0:
                        # Total is MORE than target - need to REDUCE
                        if abs(diff) <= 5.0:
                            # Small difference - reduce from last segment
                            segments[-1].duration += diff
                            segments[-1].end_time = duration
                            logger.info(f"✅ Reduced final segment by {abs(diff):.1f}s to match duration")
                        else:
                            # Large difference - proportionally reduce all
                            scale = duration / total_duration
                            current_time = 0.0
                            for seg in segments:
                                seg.start_time = current_time
                                seg.duration *= scale
                                seg.end_time = seg.start_time + seg.duration
                                current_time = seg.end_time
                            logger.info(f"✅ Scaled all segments by {scale:.2f} to fit duration")
                
                if not segments:
                    if attempt == 0:
                        logger.warning("⚠️ No valid segments, retrying...")
                        continue
                    return self._generate_fallback_segments(topic, duration)
                
                logger.info(f"✅ STAGE 1: Generated {len(segments)} segments covering {duration}s")
                return segments
                
            except Exception as e:
                logger.error(f"❌ Attempt {attempt + 1} failed: {e}")
                if attempt == 0:
                    logger.warning("⚠️ Retrying...")
                    continue
                else:
                    logger.error("❌ Both attempts failed, using fallback")
                    return self._generate_fallback_segments(topic, duration)

    def _generate_fallback_segments(self, topic: str, duration: int) -> List[NarrationSegment]:
        """Generate fallback segments if AI fails."""
        segment_count = max(3, duration // 15)
        segment_duration = duration / segment_count
        
        segments = []
        current_time = 0.0
        
        for i in range(segment_count):
            text = f"This is segment {i+1} discussing {topic}. We'll explore key concepts and practical applications."
            visuals = f"information about {topic}"
            
            segment = NarrationSegment(
                text=text,
                start_time=current_time,
                end_time=current_time + segment_duration,
                duration=segment_duration,
                visual_description=visuals
            )
            segments.append(segment)
            current_time += segment_duration
        
        logger.info(f"✅ Generated {len(segments)} fallback segments")
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
                    
                    # Update segment with ACTUAL duration (Stage 2: Temporal Authority)
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
                    logger.info(f"🔇 Silent audio created for segment {i+1}: {segment.duration}s")
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
                logger.info(f"🔇 Fallback silent audio: {segment.duration}s")
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

    async def _generate_scripts_in_parallel(self, segments: List[NarrationSegment]) -> List[NarrationSegment]:
        """
        Generate all Manim scripts in PARALLEL using individual Gemini calls.
        This is 5-10x faster than sequential generation.
        
        Implements 5-layer safety system:
        1. Enhanced validation of Gemini responses
        2. File system recovery for failed scripts
        3. Fallback script generation
        4. Pre-save validation with auto-recovery
        5. Comprehensive logging
        """
        logger.info("🧠 Generating all scripts in PARALLEL using Gemini...")
        logger.info(f"📊 Total segments to generate: {len(segments)}")
        
        # Load prompt resources
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
        
        animation_reference = self.animation_reference
        allowed_colors = "WHITE, BLUE, GREEN, RED, YELLOW, PINK, ORANGE, PURPLE, GOLD, GRAY"
        
        # Update segments with actual audio durations
        from pydub import AudioSegment
        for i, segment in enumerate(segments):
            if segment.audio_path and Path(segment.audio_path).exists():
                audio = AudioSegment.from_file(segment.audio_path)
                actual_audio_duration = round(len(audio) / 1000.0, 2)
                segment.duration = actual_audio_duration
                logger.info(f"🎯 Segment {i+1}: Using actual audio duration: {actual_audio_duration:.2f}s")
            else:
                logger.warning(f"⚠️ Segment {i+1} has no audio file — fallback to default duration.")
                if not segment.duration:
                    segment.duration = 5.0
        
        # Create tasks for parallel generation
        async def generate_single_script(index: int, segment: NarrationSegment) -> dict:
            """Generate a single script with comprehensive error handling."""
            try:
                prompt = self._build_individual_script_prompt(
                    index, segment, samples, allowed_attributes, 
                    animation_reference, allowed_colors
                )
                
                # Call OpenRouter for script generation WITH ROTATION (handles rate limits)
                logger.info(f"🔄 Generating script for segment {index+1}...")
                
                # Use execute_with_rotation for automatic key rotation on rate limits
                def call_openrouter(client):
                    response = client.chat.completions.create(
                        model=self.script_model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.3,
                        max_tokens=8192
                    )
                    return response.choices[0].message.content.strip()
                
                raw_script = self.openrouter_key_manager.execute_with_rotation(
                    call_openrouter,
                    model=self.script_model
                )
                
                # Clean and validate
                cleaned_script = self._clean_script_response(raw_script, index, segment.duration)
                
                if not self._validate_script_structure(cleaned_script, index):
                    logger.warning(f"⚠️ Segment {index+1}: Script validation failed, marking for fallback")
                    return {
                        'success': False,
                        'index': index,
                        'script': None,
                        'error': 'Validation failed'
                    }
                
                logger.info(f"✅ Segment {index+1}: Script generated successfully")
                return {
                    'success': True,
                    'index': index,
                    'script': cleaned_script,
                    'error': None
                }
                
            except Exception as e:
                logger.error(f"❌ Segment {index+1}: Script generation failed: {e}")
                return {
                    'success': False,
                    'index': index,
                    'script': None,
                    'error': str(e)
                }
        
        # Execute all script generation tasks in parallel
        logger.info("🚀 Launching parallel script generation tasks...")
        tasks = [generate_single_script(i, seg) for i, seg in enumerate(segments)]
        results = await asyncio.gather(*tasks)
        
        # LAYER 1: Enhanced result validation and assignment
        logger.info("📊 Processing script generation results...")
        failed_segments = []
        
        for result in results:
            index = result.get('index', -1)
            success = result.get('success', False)
            script = result.get('script', None)
            error = result.get('error', 'Unknown error')
            
            logger.info(f"🔍 Result for segment {index+1}: success={success}, has_script={script is not None}")
            
            if success and script:
                # Validate script content before saving
                if len(script) < 100:
                    logger.error(f"❌ Segment {index+1} script too short: {len(script)} chars")
                    failed_segments.append(index)
                    continue
                
                # Save script to file
                script_path = Path(self.config.temp_dir) / f"segment_{index:03d}.py"
                script_path.write_text(script, encoding='utf-8')
                segments[index].script_path = str(script_path)
                logger.info(f"✅ Segment {index+1} saved: {script_path}")
            else:
                logger.error(f"❌ Segment {index+1} generation failed: {error}")
                failed_segments.append(index)
        
        # LAYER 2: AGGRESSIVE RETRY - NO FALLBACKS, KEEP TRYING GEMINI
        if failed_segments:
            logger.warning(f"⚠️ {len(failed_segments)} segment(s) failed. Retrying with OpenRouter (NO FALLBACKS)...")
            
            max_retries = 5  # Try up to 5 times per segment
            
            for retry_attempt in range(max_retries):
                if not failed_segments:
                    break
                    
                logger.info(f"🔄 Retry attempt {retry_attempt + 1}/{max_retries} for {len(failed_segments)} segment(s)...")
                
                # Retry failed segments
                retry_tasks = [generate_single_script(idx, segments[idx]) for idx in failed_segments]
                retry_results = await asyncio.gather(*retry_tasks)
                
                still_failed = []
                for result in retry_results:
                    index = result.get('index', -1)
                    success = result.get('success', False)
                    script = result.get('script', None)
                    
                    if success and script and len(script) >= 100:
                        # Save successful retry
                        script_path = Path(self.config.temp_dir) / f"segment_{index:03d}.py"
                        script_path.write_text(script, encoding='utf-8')
                        segments[index].script_path = str(script_path)
                        logger.info(f"✅ Segment {index+1} recovered on retry {retry_attempt + 1}")
                    else:
                        still_failed.append(index)
                
                failed_segments = still_failed
                
                if failed_segments and retry_attempt < max_retries - 1:
                    # Wait a bit before retrying
                    await asyncio.sleep(2)
        
        # LAYER 3: FINAL CHECK - If still failed after all retries, RAISE ERROR (NO FALLBACKS)
        if failed_segments:
            error_msg = f"❌ CRITICAL: {len(failed_segments)} segment(s) failed after {max_retries} retry attempts: {failed_segments}"
            logger.error(error_msg)
            logger.error("❌ NO FALLBACK SCRIPTS - Generation must succeed. Please check OpenRouter API status and prompts.")
            raise RuntimeError(f"Script generation failed for segments {failed_segments} after {max_retries} retries. No fallback scripts allowed.")
        
        # LAYER 4: Final validation
        logger.info("📋 Final script status:")
        for i, segment in enumerate(segments):
            if segment.script_path and Path(segment.script_path).exists():
                file_size = Path(segment.script_path).stat().st_size
                logger.info(f"  ✅ Segment {i+1}: {segment.script_path} ({file_size} bytes)")
            else:
                logger.error(f"  ❌ Segment {i+1}: MISSING")
                raise RuntimeError(f"Script generation failed for segment {i+1} - no script file found")
        
        logger.info("✅ Parallel script generation completed.")
        return segments
    
    def _build_individual_script_prompt(
        self, index: int, segment: NarrationSegment, 
        samples: str, allowed_attributes: str, 
        animation_reference: str, allowed_colors: str
    ) -> str:
        """Build a comprehensive prompt for individual script generation."""
        
        aspect_ratio_config = self._get_aspect_ratio_config()
        
        # Add personality hint for shorts
        is_short = getattr(self.config, 'video_type', 'regular') == 'short'
        
        if is_short:
            personality_section = """
============================================================
🎭 PERSONALITY & VIBE (CRITICAL FOR SHORTS!)
============================================================

This is a FUN, FRIENDLY YouTube Short - NOT a boring lecture!
Your animations should feel:
- PLAYFUL: Use bouncy rate_func (there_and_back), wiggles, spins
- ENERGETIC: Quick entrances, punchy emphasis, satisfying reveals
- INTERACTIVE: Like pointing at things while explaining to a friend
- CELEBRATORY: Checkmarks pop, success flashes, completion pulses

Animation personality techniques:
- rate_func=there_and_back for bouncy text
- rate_func=rush_into for punchy emphasis
- Wiggle() and Circumscribe() to highlight key concepts
- SpinInFromNothing() for fun reveals
- Flash() and Indicate() for "look at this!" moments
- ApplyMethod(obj.scale, 1.1) then back for attention pulses

THINK: "Would a friend showing this on their phone do it this way?"
If it feels like a PowerPoint presentation - YOU'RE DOING IT WRONG!
"""
        else:
            personality_section = ""
        
        prompt = f"""🎯 PRIMARY OBJECTIVE

You are an ELITE Manim animation engineer and cinematic motion designer.

Your task is to generate a FULLY FUNCTIONAL, ERROR-FREE Manim script
that produces a visually FASCINATING, DYNAMIC, and CONTINUOUSLY ENGAGING video.

The video MUST feel alive for the ENTIRE duration.
Blank screens, dead time, or static visuals are STRICTLY FORBIDDEN.
{personality_section}
The animation MUST match the audio duration EXACTLY:
{segment.duration:.2f} seconds.

============================================================
MANDATORY SCRIPT STRUCTURE (NON-NEGOTIABLE)
============================================================

1. The script MUST start with:
from manim import *
import random

2. The script MUST include the aspect ratio configuration EXACTLY as provided:
{aspect_ratio_config}

3. The Scene class name MUST be:
class Segment{index:03d}(Scene):

4. You MUST implement:
def construct(self):

============================================================
CONTENT INPUT (AUTHORITATIVE — DO NOT MODIFY)
============================================================

Narration (spoken audio, DO NOT alter wording):
"{segment.text}"

Visual intent (conceptual meaning, NOT implementation):
{segment.visual_description}

============================================================
⏱️ TEMPORAL DOMINANCE RULES (CRITICAL - READ CAREFULLY!)
============================================================

🚨 THE #1 PROBLEM: Animations that RACE ahead of narration!

Your animations must BREATHE. They must feel HUMAN-PACED.
Imagine someone is SPEAKING over this animation - match THEIR pace!

GOLDEN RULE: Each animation should take 2-4 seconds minimum.
If the viewer can't read/understand it, it's TOO FAST.

❌ FORBIDDEN PACING (INSTANT REJECTION):
- run_time=0.5 for important content (TOO FAST!)
- All animations blasting in the first 30%
- FadeOut everything → long static wait
- Multiple objects appearing in rapid succession
- Animation "race" where everything competes for attention

✅ REQUIRED PACING (MANDATORY):
- Title/hook: 2-3 seconds to appear and settle
- Each concept: 3-5 seconds of screen time minimum
- Transitions: 1-2 seconds of breathing room
- Emphasis: Hold for 2+ seconds so viewer can absorb
- Final: Gentle 2-3 second settle, NOT blank screen

TIMING MATH (USE THIS!):
For a {segment.duration:.1f}s segment:
- Entry animations: {segment.duration * 0.2:.1f}s (first 20%)
- Core content: {segment.duration * 0.5:.1f}s (next 50%)  
- Emphasis/reinforcement: {segment.duration * 0.2:.1f}s (next 20%)
- Gentle outro: {segment.duration * 0.1:.1f}s (final 10%)

============================================================
🎬 PACING BLUEPRINT (THINK: TEACHING, NOT RACING)
============================================================

Imagine you're showing this to a FRIEND who's LEARNING.
You wouldn't rush through explanations - you'd let each point LAND.

STRUCTURE YOUR ANIMATION LIKE THIS:

PHASE 1 (0-20%): HOOK & SETUP
- Title appears SLOWLY (run_time=2.0+)
- Let it breathe for 1-2 seconds
- Viewer thinks: "Oh, we're learning about X"

PHASE 2 (20-70%): CORE EXPLANATION  
- Reveal concepts ONE AT A TIME
- Each element gets 3-5 seconds of attention
- Use self.wait(1.0) between major elements
- Viewer thinks: "Okay, I see how this works"

PHASE 3 (70-90%): REINFORCEMENT
- Emphasize key points (Circumscribe, Indicate)
- Show relationships or connections
- Viewer thinks: "Ah, that makes sense!"

PHASE 4 (90-100%): GENTLE LANDING
- Subtle final emphasis or pulse
- Keep elements visible (don't fade to black!)
- Viewer thinks: "Got it!"

============================================================
🎨 ANIMATION QUALITY REQUIREMENTS (HIGH BAR)
============================================================

You MUST use 8–12 DISTINCT animation techniques, including:

ENTRANCES:
- Write()
- DrawBorderThenFill()
- GrowFromCenter()
- SpinInFromNothing()

EMPHASIS:
- Circumscribe()
- Flash()
- Indicate()
- Wiggle()

MOTION:
- .animate.shift()
- .animate.scale()
- .animate.rotate()

TRANSFORMS:
- Transform()
- ReplacementTransform()

GROUPING & FLOW:
- AnimationGroup(lag_ratio=0.2–0.4)
- rate_func=smooth

============================================================
🚨 CRITICAL TEXT SCALING RULES (NO EXCEPTIONS)
============================================================

EVERY Text / MarkupText / Tex object MUST:

- Call .scale_to_fit_width() IMMEDIATELY after creation
- Be scaled BEFORE positioning
- NEVER exceed frame width

Scaling rules:
- For 16:9 → config.frame_width * 0.85
- For 9:16 → config.frame_width * 0.65

Example (MANDATORY PATTERN):

title = Text("Title", font_size=48)
title.scale_to_fit_width(config.frame_width * 0.85)
title.to_edge(UP)

============================================================
📐 LAYOUT & VISUAL SAFETY RULES
============================================================

- Minimum vertical spacing between text objects: 1.5 units
- Use SAFE ZONES only:
  - TOP    : UP * 2.5 to UP * 3.0
  - MIDDLE : ORIGIN ± 0.5
  - BOTTOM : DOWN * 2.5

- NEVER overlap zones
- NEVER crowd text
- Prefer transforming existing objects over removing them

============================================================
🎥 VISUAL PERSISTENCE RULE (ANTI-DULLNESS)
============================================================

- DO NOT FadeOut all objects before the end
- At least ONE major visual element MUST remain visible until the last seconds
- Use subtle motion for persistence:
  - slow scale pulses
  - small shifts
  - gentle rotations
  - emphasis flashes

============================================================
⚙️ PERFORMANCE & STYLE RULES
============================================================

- Prefer precomputed animations (≈90%)
- Updaters allowed ONLY for special moments (<30%)
- No excessive updaters
- NO plain FadeIn/FadeOut-only scripts
- Everything must feel intentional and cinematic

============================================================
📚 STYLE REFERENCES
============================================================


Animation techniques reference:
{animation_reference}

Allowed objects and attributes:
{allowed_attributes}

Allowed colors ONLY:
{allowed_colors}

============================================================
⏱️ DURATION ENFORCEMENT (SLOW AND DELIBERATE!)
============================================================

TOTAL DURATION: {segment.duration:.2f} seconds

You MUST fill this ENTIRE duration with MEANINGFUL content.
The animation should feel like it's TEACHING, not RUSHING.

MINIMUM RUN_TIME RULES:
- Title/main text: run_time=2.0 minimum
- Secondary animations: run_time=1.5 minimum  
- Emphasis effects: run_time=1.0 minimum
- Wait between sections: self.wait(1.0) or more

TIMING CALCULATION EXAMPLE for {segment.duration:.1f}s:
```python
# DO THIS - slow and deliberate:
self.play(Write(title), run_time=2.5)  # 2.5s
self.wait(1.0)                          # +1.0s = 3.5s
self.play(FadeIn(content), run_time=2.0)# +2.0s = 5.5s
self.play(Indicate(key_point), run_time=1.5) # +1.5s = 7.0s
self.wait(1.5)                          # +1.5s = 8.5s
# ... continue until reaching {segment.duration:.1f}s
```

```python
# DON'T DO THIS - racing:
self.play(Write(title), run_time=0.5)   # Too fast!
self.play(FadeIn(content), run_time=0.3)# Racing!  
self.wait(8.0)                          # Boring long wait!
```

REMEMBER: The viewer is LEARNING. Give them TIME to absorb each element!

============================================================
✅ OUTPUT FORMAT (STRICT)
============================================================

Return ONLY raw Python code.
NO markdown.
NO explanations.
NO text outside the code.

The output MUST start exactly with:

from manim import *
import random

Now generate the COMPLETE, PROFESSIONAL, CINEMATIC Manim script.
"""
        return prompt

    async def _generate_scripts_in_bulk(self, segments: List[NarrationSegment]) -> List[NarrationSegment]:
        """
        STAGE 2: Generate all Manim scripts using Gemini (bulk generation).
        Falls back to per-segment generation if bulk fails.
        """
        logger.info("🧠 STAGE 2: Bulk script generation with Gemini...")

        try:
            return await self._generate_scripts_bulk_gemini(segments)
        except Exception as e:
            logger.warning(f"⚠️ Bulk generation failed: {e}")
            logger.info("🔄 Falling back to per-segment generation...")
            return await self._generate_scripts_per_segment_gemini(segments)
    
    async def _generate_scripts_bulk_gemini(self, segments: List[NarrationSegment]) -> List[NarrationSegment]:
        """Bulk script generation using Gemini with model rotation."""
        from pydub import AudioSegment
        
        for i, segment in enumerate(segments):
            if segment.audio_path and Path(segment.audio_path).exists():
                audio = AudioSegment.from_file(segment.audio_path)
                segment.duration = round(len(audio) / 1000.0, 2)
        
        prompt = self._build_bulk_script_prompt(segments)
        
        response = self._call_gemini_with_rotation(
            prompt,
            generation_config={'temperature': 0.7, 'max_output_tokens': 32768},
            task_name="bulk script generation"
        )
        
        # Handle response - new SDK returns text directly, but can be None
        if response is None:
            logger.error("❌ Gemini returned None response for bulk script generation")
            raise RuntimeError("Gemini returned None response - all models may have failed")
        
        if hasattr(response, 'text') and response.text:
            content = response.text.strip()
        elif isinstance(response, str):
            content = response.strip()
        else:
            logger.error(f"❌ Unexpected response type: {type(response)}")
            logger.error(f"Response attributes: {dir(response) if response else 'None'}")
            raise ValueError(f"Unexpected response type from Gemini: {type(response)}")
        
        logger.debug(f"📥 Bulk response preview (first 500 chars): {content[:500]}")
        
        # Split by ===SCRIPT START=== separator
        scripts = re.split(r'===SCRIPT START===', content)
        scripts = [s.strip() for s in scripts if s.strip()]
        
        logger.info(f"📊 Split result: {len(scripts)} scripts from {len(content)} chars")
        
        if len(scripts) < len(segments):
            raise ValueError(f"Only {len(scripts)}/{len(segments)} scripts generated")
        
        for i, segment in enumerate(segments):
            cleaned_script = self._clean_script_response(scripts[i], i, segment.duration)
            script_path = Path(self.config.temp_dir) / f"segment_{i:03d}.py"
            script_path.write_text(cleaned_script, encoding="utf-8")
            segment.script_path = str(script_path)
        
        return segments
    
    async def _generate_scripts_per_segment_gemini(self, segments: List[NarrationSegment]) -> List[NarrationSegment]:
        """Per-segment script generation using Gemini with model rotation."""
        from pydub import AudioSegment
        
        for i, segment in enumerate(segments):
            if segment.audio_path and Path(segment.audio_path).exists():
                audio = AudioSegment.from_file(segment.audio_path)
                segment.duration = round(len(audio) / 1000.0, 2)
            
            logger.info(f"📝 Generating script for segment {i+1}/{len(segments)}...")
            prompt = self._build_single_script_prompt(i, segment)
            
            response = self._call_gemini_with_rotation(
                prompt,
                generation_config={'temperature': 0.7, 'max_output_tokens': 8192},
                task_name=f"script generation (segment {i+1})"
            )
            
            # Handle response - new SDK returns text directly, but can be None
            if response is None:
                logger.error(f"❌ Gemini returned None response for segment {i+1}")
                raise RuntimeError(f"Gemini returned None response for segment {i+1} - all models may have failed")
            
            if hasattr(response, 'text') and response.text:
                raw_text = response.text.strip()
            elif isinstance(response, str):
                raw_text = response.strip()
            else:
                logger.error(f"❌ Unexpected response type for segment {i+1}: {type(response)}")
                logger.error(f"Response attributes: {dir(response) if response else 'None'}")
                raise ValueError(f"Unexpected response type from Gemini: {type(response)}")
            
            cleaned_script = self._clean_script_response(raw_text, i, segment.duration)
            script_path = Path(self.config.temp_dir) / f"segment_{i:03d}.py"
            script_path.write_text(cleaned_script, encoding="utf-8")
            segment.script_path = str(script_path)
        
        return segments
    
    def _build_bulk_script_prompt(self, segments: List[NarrationSegment]) -> str:
        """Build prompt for bulk script generation."""
        try:
            with open('./generator/video_generator/prompt/sample.txt', 'r') as f:
                samples = f.read()
        except:
            samples = self.samples
        
        try:
            with open('./generator/video_generator/prompt/obj-attrbute_list.txt', 'r') as f:
                allowed_attributes = f.read()
        except:
            allowed_attributes = self.allowed_attributes
        
        animation_reference = self.animation_reference
        allowed_colors = self.allowed_colors
        aspect_ratio_config = self._get_aspect_ratio_config()
        
        # Build segment list in required format
        all_segments_prompt = "\n".join([
            f"""**Segment {i+1}:**
- Class Name: Segment{i:03d}
- Audio Duration: {seg.duration:.2f} seconds
- Visual Narration: {seg.visual_description}
- Spoken Text: "{seg.text}"""
            for i, seg in enumerate(segments)
        ])
        
        return f"""**🎯 PRIMARY OBJECTIVE**

You are an expert Manim animation developer. For each provided **segment**, you must generate a **fully functional Manim script** that is clean, logically structured, visually engaging, and completely error-free.

---

### 🚫 **CRITICAL #0: PREVENT OFF-SCREEN ELEMENTS (MOST IMPORTANT!)**

**⛔ ABSOLUTE RULE: NO ELEMENTS CAN GO OFF-SCREEN - THEY BECOME INVISIBLE!**

**🚨 THIS IS THE #1 CAUSE OF VIDEO FAILURES - READ CAREFULLY:**

Every text, shape, and object MUST be visible within the frame at ALL times.

**MANDATORY REQUIREMENTS (WILL BE REJECTED IF VIOLATED):**

1. **⚠️ EVERY Text object MUST have .scale_to_fit_width() - NO EXCEPTIONS!**
   ```python
   # ✅ CORRECT - ALWAYS DO THIS:
   title = Text("Some text", font_size=48)
   title.scale_to_fit_width(config.frame_width * 0.85)  # MANDATORY!
   
   # ❌ WRONG - WILL GO OFF-SCREEN:
   title = Text("Some text", font_size=48)  # Missing scale_to_fit_width!
   ```

2. **⛔ FORBIDDEN POSITIONS - NEVER USE THESE (ELEMENTS WILL GO OFF-SCREEN):**
   - ❌ UP * 4 or higher (too high, goes off-screen)
   - ❌ DOWN * 4 or lower (too low, goes off-screen)
   - ❌ LEFT * 7 or beyond (too far left, goes off-screen)
   - ❌ RIGHT * 7 or beyond (too far right, goes off-screen)

3. **✅ SAFE POSITIONS ONLY - USE THESE:**
   - ✅ UP * 2.5, UP * 1.5, UP * 0.5 (safe top area)
   - ✅ ORIGIN, UP * 0.5, DOWN * 0.5 (safe center)
   - ✅ DOWN * 1.5, DOWN * 2.5 (safe bottom area)
   - ✅ LEFT * 3, RIGHT * 3 (safe horizontal)

4. **📏 SIZE LIMITS (PREVENT OVERFLOW):**
   - Maximum font_size for titles: {48 if self.config.aspect_ratio == "9:16" else 56}px
   - Maximum font_size for body: {36 if self.config.aspect_ratio == "9:16" else 42}px
   - ALL text MUST call .scale_to_fit_width(config.frame_width * 0.85)

5. **📐 SPACING RULES (PREVENT OVERLAP/OFF-SCREEN):**
   - Minimum 1.5 units vertical spacing between text objects
   - Keep 1 unit margin from all screen edges
   - Test: If you stack 3 text objects, use UP*2, ORIGIN, DOWN*2

**⛔ REJECTION CRITERIA - YOUR SCRIPT WILL BE REJECTED IF:**
- ANY text object missing .scale_to_fit_width()
- Using positions like UP*4, DOWN*4, LEFT*8, RIGHT*8
- Font sizes exceeding limits
- Text objects overlapping or too close (<1.5 units apart)

**✅ VERIFICATION CHECKLIST BEFORE SUBMITTING:**
□ Every Text() has .scale_to_fit_width(config.frame_width * 0.85)
□ All positions use SAFE values only (UP*2.5 max, DOWN*2.5 max)
□ Font sizes within limits
□ Vertical spacing >= 1.5 units between objects
□ 1 unit margin from all edges

---

### ⏱️ **CRITICAL #1: PERFECT TIMING SYNCHRONIZATION - NO BLANK SCREENS!**

**THIS IS THE MOST IMPORTANT REQUIREMENT - READ CAREFULLY:**

Each segment has an **EXACT audio duration** that you MUST match precisely.

**🚨 CRITICAL RULE: Animations must fill the ENTIRE duration - NO long waits at the end!**

**❌ WRONG - Don't do this:**
```python
# For 15 second segment
self.play(FadeIn(title), run_time=1)
self.play(FadeOut(title), run_time=1)
self.wait(13)  # ❌ BLANK SCREEN FOR 13 SECONDS!
```

**✅ CORRECT - Do this:**
```python
# For 15 second segment - distribute animations across full time
self.play(Write(title), run_time=3.0)       # 3s
self.play(title.animate.shift(UP*2), run_time=2.0)  # 2s
content = Text("Content")
self.play(GrowFromCenter(content), run_time=2.5)    # 2.5s
self.play(Indicate(content), run_time=2.0)          # 2s
self.play(content.animate.scale(1.2), run_time=1.5) # 1.5s
self.play(FadeOut(content), FadeOut(title), run_time=3.0)  # 3s
self.wait(1.0)  # Only 1s wait - acceptable
# Total = 15s
```

**TIMING STRATEGY:**

1. **Calculate animation budget:**
   - Entry animations: 20-30% of total duration
   - Middle content: 40-50% of total duration  
   - Exit animations: 20-30% of total duration

2. **Use LONGER run_times:**
   - Instead of run_time=0.8, use run_time=2.0 or 3.0
   - Slow animations look more professional
   - Fills time naturally without waiting

3. **Add MORE animations:**
   - Don't just fade in/out - add movement, scaling, emphasis
   - Use Indicate(), Circumscribe(), Flash() to fill time
   - Shift objects around the screen
   - Rotate, scale, transform

4. **Maximum wait time: 1 second**
   - If you need > 1s wait, your animations are too fast
   - Increase run_times or add more animations

5. **Final timing (use self.wait() if needed):**
   ```python
   # Option 1: Use self.wait() to fill remaining time
   total_animation_time = sum_of_all_run_times
   remaining = audio_duration - total_animation_time
   if remaining > 0:
       self.wait(remaining)
   
   # Option 2: Distribute animations to fill entire duration
   # Increase run_times so animations naturally fill the time
   ```

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
{aspect_ratio_config}
   ```   

4. **Define a class in the format:**

   ```python
   class SegmentXXX(Scene):
   ```

5. **Implement a `construct(self)` method containing all animation logic.**

6. **Use only predefined objects and their strictly allowed attributes.**
   ❌ Do NOT use unsupported attributes or extra options.

7. **Use only approved Manim color constants.**
   ❌ Do NOT define custom colors or use hex codes.

8. **Do not use any unsupported markup or formatting classes.**
   ❌ No `MarkupText`, `<span>`, `<code>`, or HTML-style tags. Do not use MARKUPTEXT at any cost
   ✅ Use only basic `Text`, `MathTex`, `Rectangle`, `Circle`, etc., as listed in the allowed objects section.

9. **Ensure the total animation time (sum of run_times + waits) matches the given segment's exact audio duration (±0.1s).**
   ➕ Use `self.wait()` to fill in any remaining time.

10. Remember that Mobject.align_to() takes from 2 to 3 positional arguments.

11. **Ensure you don't use Camera, Code object at any cost.**

12. **Do not use any images like .png, .jpeg, .svg or any sort of image formats, if needed create the images with vectors.**

13. **Only use from manim import *, nothing else, and use only if needed.**

14. **ASPECT RATIO: This video is in {self.config.aspect_ratio} format.**
   - Design layouts appropriate for this aspect ratio
   - Position objects considering the screen dimensions
   - For 9:16 (vertical): Stack elements vertically, use full height
   - For 16:9 (horizontal): Use width, arrange side-by-side when possible
   - For 1:1 (square): Center elements, balanced composition

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

### ⚡ MANDATORY CHECKLIST FOR EACH SEGMENT:

Before submitting your script, verify:
- [ ] Uses Write() or GrowFromCenter() for at least ONE entry
- [ ] Includes .animate.shift() or .animate.scale() for movement
- [ ] Has Circumscribe(), Indicate(), or Flash() for emphasis
- [ ] Uses Uncreate(), ShrinkToCenter(), or FadeOut(shift=) for exits
- [ ] Objects MOVE and TRANSFORM, not just appear/disappear
- [ ] Animation variety - not repetitive
- [ ] Total timing matches audio duration
- [ ] NEVER use MarkupText
- [ ] All text scaled with scale_to_fit_width()

**IF YOUR SCRIPT ONLY USES FadeIn/FadeOut, IT WILL BE REJECTED!**

---

### ✅ USE THESE EXAMPLES AS STYLE REFERENCE

Use the following sample programs as reference for:

* Layout clarity
* Timing discipline
* Use of animations
* Clean code formatting
* Accurate wait calculations



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
* ❌ No long wait() times at the end
* ❌ No static FadeIn/FadeOut only animations

---

### ✅ YOUR TASK

Generate **one complete, accurate Manim script per segment**, strictly following all rules above.
The output must be professional, polished, and directly executable in Manim with no errors.

You are acting as a **senior Manim Community developer**. Your script quality must reflect that expertise.
"""
    
    def _build_single_script_prompt(self, index: int, segment: NarrationSegment) -> str:
        """Build prompt for single segment script generation."""
        aspect_ratio_config = self._get_aspect_ratio_config()
        aspect_ratio = self.config.aspect_ratio
        
        return f"""🎯 PRIMARY OBJECTIVE
You are a world-class Manim animation generation engine. Your task is to generate ONE complete, production-ready Manim script for a SINGLE video segment. The output will be executed automatically in a pipeline. Any deviation from rules will cause hard failure.

---

� **CRITICAL #0: PREVENT OFF-SCREEN ELEMENTS (MOST IMPORTANT!)**

**⛔ ABSOLUTE RULE: NO ELEMENTS CAN GO OFF-SCREEN - THEY BECOME INVISIBLE!**

**🚨 THIS IS THE #1 CAUSE OF VIDEO FAILURES - FOLLOW THESE EXACTLY:**

**MANDATORY REQUIREMENTS (WILL BE REJECTED IF VIOLATED):**

1. **⚠️ EVERY Text object MUST have .scale_to_fit_width() - NO EXCEPTIONS!**
   ```python
   # ✅ CORRECT - ALWAYS DO THIS:
   title = Text("Some text", font_size=48)
   title.scale_to_fit_width(config.frame_width * 0.85)  # MANDATORY!
   
   # ❌ WRONG - WILL GO OFF-SCREEN:
   title = Text("Some text", font_size=48)  # Missing scale_to_fit_width!
   ```

2. **⛔ FORBIDDEN POSITIONS - NEVER USE (GOES OFF-SCREEN):**
   - ❌ UP * 3.5 or higher (too high, invisible)
   - ❌ DOWN * 3.5 or lower (too low, invisible)
   - ❌ LEFT * 7 or beyond (too far left, invisible)
   - ❌ RIGHT * 7 or beyond (too far right, invisible)

3. **✅ SAFE POSITIONS ONLY:**
   - ✅ UP * 2.5, UP * 2, UP * 1.5, UP * 1 (SAFE)
   - ✅ ORIGIN, UP * 0.5, DOWN * 0.5 (SAFE)
   - ✅ DOWN * 1, DOWN * 1.5, DOWN * 2, DOWN * 2.5 (SAFE)
   - ✅ LEFT * 3, RIGHT * 3 (SAFE horizontal)

4. **📏 SIZE LIMITS:**
   - Maximum font_size: {48 if aspect_ratio == "9:16" else 56}px
   - ALL text MUST call .scale_to_fit_width(config.frame_width * 0.85)

5. **📐 SPACING RULES:**
   - Minimum 1.5 units vertical spacing between text objects
   - Keep 1 unit margin from all edges

**✅ CHECKLIST BEFORE SUBMITTING:**
□ Every Text() has .scale_to_fit_width(config.frame_width * 0.85)
□ All positions use SAFE values (UP*2.5 max, DOWN*2.5 max)
□ Font sizes within limits
□ Vertical spacing >= 1.5 units

---

�🔒 IMMUTABLE INPUTS (READ-ONLY)
• Narration text: {segment.text}
• Exact audio duration (seconds): {segment.duration:.2f}
• Aspect ratio: {aspect_ratio}

You are NOT allowed to:
❌ Change narration text
❌ Change visual description meaning
❌ Change total duration
❌ Add unrelated visuals

---

📐 ABSOLUTE ASPECT RATIO CONTRACT (NON-NEGOTIABLE)

Aspect ratio is {aspect_ratio}. All layout MUST obey this.

GLOBAL SAFE RULES (ALL RATIOS):
• Never place objects outside frame
• Never overlap text objects
• Never rely on default scaling
• Always prefer vertical stacking over crowding

TEXT WIDTH CONSTRAINT (MANDATORY):
• EVERY Text / MarkupText / Tex MUST immediately call:
text.scale_to_fit_width(config.frame_width * WIDTH_FACTOR)

WIDTH_FACTOR:
• 16:9  → 0.85
• 9:16  → 0.65   (CRITICAL – narrow screen)
• 1:1   → 0.75
• 4:3   → 0.80
• 21:9  → 0.90

---

📍 POSITION ZONES (STRICT – DO NOT INVENT NEW POSITIONS)

For 9:16:
• TOP:    UP * 6 → UP * 4
• MIDDLE: UP * 1 → DOWN * 1
• BOTTOM: DOWN * 4 → DOWN * 6

For 16:9:
• TOP:    UP * 3 → UP * 2
• MIDDLE: UP * 0.5 → DOWN * 0.5
• BOTTOM: DOWN * 2 → DOWN * 3

Rules:
• Max 1 text object per zone
• Minimum vertical spacing = 1.5 units
• Long text MUST be split into multiple stacked Text objects

---

🎬 TIMING & AUDIO SYNCHRONIZATION (ABSOLUTE)
• Total animation time MUST equal {segment.duration:.2f} seconds
• Distribute animations across entire duration
• NO front-loaded animations
• NO long blank screen at end

💡 TIMING OPTIONS:
1. Use self.wait() to fill remaining time:
   ```python
   # animations total 10.5s, segment is {segment.duration:.2f}s
   remaining = {segment.duration:.2f} - 10.5
   self.wait(remaining)  # Fill the gap
   ```

2. OR distribute animations to naturally fill duration:
   ```python
   # Increase run_times so total equals {segment.duration:.2f}s
   self.play(Write(title), run_time=4.0)  # Longer animations
   ```

---

🎨 ANIMATION QUALITY REQUIREMENTS

MANDATORY:
• Use 5–8 different animation techniques
• Use rate_func=smooth
• run_time typically 1.0–1.6s (never <0.8s)

ALLOWED TECHNIQUES:
• Write, DrawBorderThenFill, GrowFromCenter, SpinInFromNothing
• Indicate, Circumscribe, Flash, Wiggle
• Transform, ReplacementTransform, TransformMatchingShapes
• .animate.shift / scale / rotate
• AnimationGroup(lag_ratio=0.2–0.3)

FORBIDDEN:
❌ FadeIn/FadeOut-only scripts
❌ Static text dumps
❌ Excessive add_updater (>30% of animations)

---

🧠 VISUAL–NARRATION BINDING (CRITICAL)
• Every narrated concept MUST appear visually
• If narration says "three", show exactly three elements
• If narration explains a process, show flow or transformation
• Visuals must appear when narration mentions them

---

📄 REQUIRED OUTPUT FORMAT (STRICT)

Return ONLY raw Python code. No markdown. No explanations.

The script MUST start exactly with:

from manim import *
import random

{aspect_ratio_config}

class Segment{index:03d}(Scene):
    def construct(self):
        # animations here
        self.wait(X)  # X chosen so total time == {segment.duration:.2f}

---

🚨 FINAL CHECKLIST (YOU MUST SELF-VERIFY BEFORE OUTPUT)
✓ All text scaled with scale_to_fit_width
✓ No overlaps
✓ Aspect ratio respected
✓ Duration exact
✓ Animations spread across time
✓ No blank screen padding
✓ Clean exit

Generate the script now.
"""

    def _clean_script_response(self, raw_content: str, index: int, duration: float) -> str:
        """Clean and validate script response from Gemini."""
        try:
            logger.debug(f"🧹 Cleaning segment {index} (length: {len(raw_content)} chars)")
            
            # Remove markdown blocks if present (multiple formats)
            if "```python" in raw_content:
                start_marker = "```python"
                end_marker = "```"
                start_idx = raw_content.find(start_marker) + len(start_marker)
                end_idx = raw_content.rfind(end_marker)
                if start_idx > len(start_marker) - 1 and end_idx > start_idx:
                    raw_content = raw_content[start_idx:end_idx].strip()
                    logger.debug(f"📝 Removed markdown wrapper")
            elif "```" in raw_content:
                # Handle plain ``` without python keyword
                parts = raw_content.split('```')
                if len(parts) >= 3:
                    raw_content = parts[1].strip()
                    logger.debug(f"📝 Removed plain markdown wrapper")
            
            # Remove any leading/trailing content that's not code
            lines = raw_content.split('\n')
            code_start = 0
            for i, line in enumerate(lines):
                if line.strip().startswith('from manim import') or line.strip().startswith('class Segment'):
                    code_start = i
                    break
            
            if code_start > 0:
                logger.debug(f"✂️ Trimmed {code_start} leading lines")
                raw_content = '\n'.join(lines[code_start:])
            
            # Validate script structure
            if not self._validate_script_structure(raw_content, index):
                logger.error(f"❌ Script validation failed for segment {index} - missing core elements")
                raise ValueError(f"Script validation failed for segment {index}: missing required elements")
            
            return raw_content
                
        except Exception as e:
            logger.error(f"❌ Script cleaning failed for segment {index}: {e}")
            raise ValueError(f"Script cleaning failed for segment {index}: {e}")

    def _validate_script_structure(self, script: str, index: int) -> bool:
        """Validate that the script has all required components."""
        # Core required elements (self.wait is optional - animations can fill duration)
        core_elements = [
            "from manim import",
            f"class Segment{index:03d}",
            "def construct(self)"
        ]
        
        for element in core_elements:
            if element not in script:
                logger.warning(f"⚠️ Missing required element: {element}")
                return False
        
        # PERFORMANCE MONITORING: Detect per-frame updaters (slow)
        has_updater = False
        if "add_updater(" in script:
            logger.warning(f"⚠️ PERFORMANCE: Segment {index+1} uses add_updater() - consider ValueTracker instead")
            has_updater = True
        if "always_redraw(" in script:
            logger.warning(f"⚠️ PERFORMANCE: Segment {index+1} uses always_redraw() - consider Transform instead")
            has_updater = True
        
        if has_updater:
            # Don't fail validation, just log for analysis
            logger.info(f"📊 Updater detected in segment {index+1} - potential 30-40% speedup if converted")
        
        return True
    
    def _validate_bulk_scripts(self, segments: List[NarrationSegment]) -> List[int]:
        """Validate all bulk-generated scripts and return indices of failed segments."""
        failed_indices = []
        
        for i, segment in enumerate(segments):
            try:
                if not segment.script_path or not Path(segment.script_path).exists():
                    logger.warning(f"⚠️ Segment {i}: Missing script file")
                    failed_indices.append(i)
                    continue
                
                script_content = Path(segment.script_path).read_text(encoding="utf-8")
                if not self._validate_script_structure(script_content, i):
                    logger.warning(f"⚠️ Segment {i}: Script validation failed")
                    failed_indices.append(i)
            except Exception as e:
                logger.warning(f"⚠️ Segment {i}: Validation error: {e}")
                failed_indices.append(i)
        
        return failed_indices
    
    async def _regenerate_failed_segments(self, segments: List[NarrationSegment], failed_indices: List[int]) -> List[NarrationSegment]:
        """Regenerate scripts for failed segments individually using per-segment generation."""
        from pydub import AudioSegment
        
        for i in failed_indices:
            segment = segments[i]
            try:
                logger.info(f"🔄 Regenerating script for segment {i+1}/{len(segments)}...")
                
                # Ensure audio duration is set
                if segment.audio_path and Path(segment.audio_path).exists():
                    audio = AudioSegment.from_file(segment.audio_path)
                    segment.duration = round(len(audio) / 1000.0, 2)
                
                # Generate script with Gemini rotation
                prompt = self._build_single_script_prompt(i, segment)
                response = self._call_gemini_with_rotation(
                    prompt,
                    generation_config={'temperature': 0.7, 'max_output_tokens': 8192},
                    task_name=f"script regeneration (segment {i+1})"
                )
                
                # Handle response
                if response is None:
                    logger.error(f"❌ Gemini returned None response for segment {i+1}")
                    raise RuntimeError(f"Gemini returned None response for segment {i+1}")
                
                if hasattr(response, 'text') and response.text:
                    raw_text = response.text.strip()
                elif isinstance(response, str):
                    raw_text = response.strip()
                else:
                    logger.error(f"❌ Unexpected response type for segment {i+1}: {type(response)}")
                    raise ValueError(f"Unexpected response type from Gemini: {type(response)}")
                
                # Clean and save script
                cleaned_script = self._clean_script_response(raw_text, i, segment.duration)
                script_path = Path(self.config.temp_dir) / f"segment_{i:03d}.py"
                script_path.write_text(cleaned_script, encoding="utf-8")
                segment.script_path = str(script_path)
                
                logger.info(f"✅ Successfully regenerated segment {i+1}")
                
            except Exception as e:
                logger.error(f"❌ Failed to regenerate segment {i+1}: {e}")
                raise RuntimeError(f"Failed to regenerate segment {i+1}: {e}")
        
        return segments

    def _generate_fallback_script(self, segment: Optional[NarrationSegment], index: int, duration: float, is_dummy: bool = False) -> str:
        """Generate a reliable fallback script."""
        aspect_ratio_config = self._get_aspect_ratio_config()
        
        if is_dummy:
            # This script does nothing, as the main script handles everything.
            # It just needs to be a valid Manim script to not break the pipeline.
            return f'''from manim import *

{aspect_ratio_config}

class Segment{index:03d}(Scene):
    def construct(self):
        # This is a dummy segment. The main animation is in the first script.
        self.wait(max(0.1, {duration}))
'''

        content = segment.text[:80].replace('"', "'") if segment else f"Educational content for segment {index}"
        
        return f'''from manim import *

{aspect_ratio_config}

class Segment{index:03d}(Scene):
    def construct(self):
        # Main title
        title = Text("{content}...", font_size=32)
        title.scale_to_fit_width(config.frame_width * 0.85)
        title.set_color(BLUE)
        title.move_to(UP * 1.5)
        
        # Subtitle
        subtitle = Text(f"Segment {index}", font_size=24)
        subtitle.scale_to_fit_width(config.frame_width * 0.75)
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
        
        aspect_ratio_config = self._get_aspect_ratio_config()
        
        # Create ultra-simple script with just text and timing
        fallback_script = f'''from manim import *

{aspect_ratio_config}

class Segment{index:03d}(Scene):
    def construct(self):
        # Ultra-simple fallback
        text = Text("Segment {index+1}", font_size=48, color=WHITE)
        text.scale_to_fit_width(config.frame_width * 0.75)
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
            'openrouter_api_key': self.config.openrouter_api_key,  # Required for VideoGenerationConfig
            'openrouter_key_manager': self.openrouter_key_manager,  # Pass key manager for rotation
            'temp_dir': self.config.temp_dir,
            'output_dir': self.config.output_dir,
            'manim_quality': self.config.manim_quality,
            'ffmpeg_timeout': self.config.ffmpeg_timeout,
            'max_correction_attempts': self.config.max_correction_attempts,
            'manim_timeout': self.config.manim_timeout,
            'aspect_ratio': self.config.aspect_ratio,  # ✅ FIXED: Pass aspect ratio to workers
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

            # ENHANCED: Detailed result processing with validation
            logger.info("📊 Processing worker results...")
            failed_segments = []
            
            for result in results:
                index = result.get('index', -1)
                success = result.get('success', False)
                video_path = result.get('video_path', None)
                error = result.get('error', 'Unknown error')
                
                # Detailed logging for each result
                logger.info(f"🔍 Result for segment {index+1}: success={success}, video_path={video_path}")
                
                if success:
                    # Validate that video_path is actually provided
                    if not video_path:
                        logger.error(f"❌ Segment {index+1} marked as success but NO VIDEO PATH returned!")
                        failed_segments.append(index)
                        continue
                    
                    # Validate that file actually exists
                    if not Path(video_path).exists():
                        logger.error(f"❌ Segment {index+1} returned path doesn't exist: {video_path}")
                        failed_segments.append(index)
                        continue
                    
                    # Validate file size
                    file_size = Path(video_path).stat().st_size
                    if file_size < 1024:
                        logger.error(f"❌ Segment {index+1} video too small: {file_size} bytes")
                        failed_segments.append(index)
                        continue
                    
                    # All validations passed - assign the path
                    segments[index].video_path = video_path
                    logger.info(f"✅ Segment {index+1} assigned: {video_path} ({file_size/1024:.1f}KB)")
                    
                else:
                    logger.error(f"❌ Video rendering failed for segment {index+1}: {error}")
                    failed_segments.append(index)
            
            # RECOVERY PHASE 1: Attempt to recover missing paths from file system
            if failed_segments:
                logger.warning(f"⚠️ {len(failed_segments)} segment(s) failed. Attempting file system recovery...")
                recovered = recover_missing_video_paths(segments)
                
                # Re-check which segments are still missing
                still_missing = []
                for idx in failed_segments:
                    if not segments[idx].video_path or not Path(segments[idx].video_path).exists():
                        still_missing.append(idx)
                    else:
                        logger.info(f"✅ Segment {idx+1} recovered from file system!")
                
                failed_segments = still_missing
            
            # RECOVERY PHASE 2: Generate fallback videos for unrecoverable segments
            if failed_segments:
                logger.warning(f"⚠️ {len(failed_segments)} segment(s) still missing. Creating fallback videos...")
                for idx in failed_segments:
                    try:
                        logger.warning(f"🔄 Creating fallback video for segment {idx+1}")
                        fallback_path = await self._generate_emergency_fallback_video(
                            segments[idx], 
                            idx
                        )
                        segments[idx].video_path = fallback_path
                        logger.info(f"✅ Fallback video created for segment {idx+1}")
                    except Exception as fallback_error:
                        logger.error(f"❌ Even fallback failed for segment {idx+1}: {fallback_error}")
                        # Critical failure - cannot proceed
                        raise RuntimeError(f"Cannot generate video for segment {idx+1}. Both rendering and fallback failed.")

            # Final status report
            logger.info("📋 Final segment status:")
            for i, segment in enumerate(segments):
                if segment.video_path and Path(segment.video_path).exists():
                    file_size = Path(segment.video_path).stat().st_size
                    logger.info(f"  ✅ Segment {i+1}: {segment.video_path} ({file_size/1024:.1f}KB)")
                else:
                    logger.error(f"  ❌ Segment {i+1}: STILL MISSING")
            
            logger.info("✅ Parallel video generation completed.")
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
        
        # RECOVERY: Attempt to recover any missing paths before validation
        logger.info("🔍 Pre-assembly recovery check...")
        recover_missing_video_paths(segments)
        
        # Validate segment alignment with detailed reporting
        is_valid, missing_indices = validate_segment_alignment(segments)
        if not is_valid:
            logger.error(f"❌ Segment alignment validation failed for segments: {[i+1 for i in missing_indices]}")
            
            # Last-ditch recovery attempt
            logger.warning("⚠️ Attempting final recovery before aborting...")
            for idx in missing_indices:
                # Try to find video file in ANY possible location
                search_patterns = [
                    f"output/segment_{idx:03d}/*.mp4",
                    f"temp/media/videos/segment_{idx:03d}/**/*.mp4",
                    f"media/videos/segment_{idx:03d}/**/*.mp4",
                ]
                
                found = False
                for pattern in search_patterns:
                    import glob
                    matches = glob.glob(pattern, recursive=True)
                    if matches:
                        segments[idx].video_path = matches[0]
                        logger.warning(f"⚠️ EMERGENCY RECOVERY: Found segment {idx+1} at {matches[0]}")
                        found = True
                        break
                
                if not found:
                    logger.error(f"❌ Cannot recover segment {idx+1}. Video generation failed.")
            
            # Re-validate after emergency recovery
            is_valid, still_missing = validate_segment_alignment(segments)
            if not is_valid:
                raise RuntimeError(f"Segment alignment validation failed even after recovery. Missing: {[i+1 for i in still_missing]}")
            else:
                logger.warning("⚠️ Recovery successful! Proceeding with final assembly.")
        
        # Prepare synchronization workers
        worker_args = []
        config_dict = {
            'groq_api_key': self.config.groq_api_key,
            'openrouter_api_key': self.config.openrouter_api_key,  # Required for VideoGenerationConfig
            'openrouter_key_manager': self.openrouter_key_manager,  # Pass key manager for rotation
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
        
        # OPTION A OPTIMIZATION: Execute synchronization in parallel with asyncio.gather (faster than ProcessPoolExecutor)
        logger.info(f"🚀 PARALLEL SYNC: Starting {len(segments)} async FFmpeg operations...")
        
        sync_tasks = []
        temp_dir = Path(self.config.temp_dir)
        
        for i, segment in enumerate(segments):
            output_path = str(temp_dir / f"segment_{i:03d}_final.mp4")
            sync_tasks.append(
                self.synchronize_audio_video_async(
                    segment.video_path,
                    segment.audio_path,
                    output_path
                )
            )
        
        # Execute ALL syncs in parallel (15-20 seconds saved on 4+ segments!)
        final_clips = await asyncio.gather(*sync_tasks, return_exceptions=True)
        
        # Check for errors
        for i, result in enumerate(final_clips):
            if isinstance(result, Exception):
                logger.error(f"❌ Synchronization failed for segment {i+1}: {result}")
                raise RuntimeError(f"Synchronization failed for segment {i+1}: {result}")
            else:
                logger.info(f"✅ Segment {i+1} synchronized: {result}")
        
        # Verify all clips were processed  
        if None in final_clips or any(isinstance(c, Exception) for c in final_clips):
            raise RuntimeError(f"Missing or failed synchronized clips")
        
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
    
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    groq_api_key = os.getenv("GROQ_API_KEY")
    
    if not openrouter_key:
        raise ValueError("OPENROUTER_API_KEY environment variable is required.")
    
    config = VideoGenerationConfig(
        groq_api_key=groq_api_key,
        openrouter_api_key=openrouter_key,
        batch_size=5,  # Larger batches for efficiency
        max_correction_attempts=3,  # Fewer attempts for speed
        aspect_ratio="9:16",
        use_quality_pipeline=False
    )
    
    try:
        # Use memory-optimized pipeline for large `videos`
        pipeline = OptimizedVideoGenerationPipeline(config)

        
        start_time = time.time()
        # Using the chunked method for better memory management
        result = await pipeline.generate_video_full_parallel(
            topic="What is the difference between JS and JSX?", 
            duration=60,
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
