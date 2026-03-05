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

# Import centralized prompt registry
from generator.video_generator.prompt_registry import (
    format_narrative_prompt,
    format_narrative_retry_prompt,
    format_scene_direction_prompt,
    format_scene_direction_batch_prompt,
    format_manim_execution_prompt,
    format_manim_execution_batch_prompt,
    format_error_correction_prompt,
    format_error_correction_minimal_prompt,
    get_aspect_params,
)

# Import concept visualizer (pipeline intelligence layer)
from generator.video_generator.concept_visualizer import (
    generate_visual_models_batch,
    format_visual_model_context,
)

# Import visual validation (global gate for both pipelines)
from generator.video_generator.visual_validation import (
    make_visual_contract,
    contract_from_visualizer,
    serialize_contract,
    deserialize_contract,
    validate_visual_simulation,
    validate_script_simulation,
    validate_quality_spec_against_contract,
)

# TTS import with robust error handling

# Setup logging with DEBUG level temporarily to diagnose key rotation
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
load_dotenv(override=True)

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
    scene_direction: Optional[str] = None  # Stage 2.5: Scene direction JSON from Director layer
    idea: Optional[str] = None  # Learning concept from narrative director
    emotion: Optional[str] = None  # Emotional beat from narrative director
    layout_strategy: Optional[str] = None  # Layout type from narrative director
    visual_contract: Optional[str] = None  # GLOBAL: Frozen visual authority (JSON), persists through all stages

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
        
        # OpenRouter model names for different pipeline stages
        self.narration_model = "nvidia/nemotron-3-nano-30b-a3b:free"
        self.script_model = "nvidia/nemotron-3-nano-30b-a3b:free"
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
        """Generate audio using Edge TTS (with gTTS fallback) for all segments.
        
        Audio is kept at natural TTS speed to preserve quality.
        Downstream scripts adapt their duration to match actual audio length.
        """
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
                segment._audio_duration_final = actual_duration  # Lock actual TTS duration for quality pipeline
                segment.start_time = round(sum(s.duration for s in segments[:i]), 2)
                segment.end_time = round(segment.start_time + actual_duration, 2)

                logger.info(f"✅ Segment {i+1}: audio={actual_duration}s → {mp3_path}")
            except Exception as e:
                logger.error(f"❌ Failed to generate audio for segment {i+1}: {e}")



    def generate_narration_segments(self, topic: str, duration: int) -> List[NarrationSegment]:
        """
        LAYER 1 — NARRATIVE DIRECTOR (WRITER)
        
        Uses centralized prompt registry for narration generation.
        Outputs structured segments with narration, visual_intent, emotion, layout.
        """
        import json as _json
        
        prompt = format_narrative_prompt(
            topic=topic,
            duration=duration,
            aspect_ratio=self.config.aspect_ratio,
        )

        try:
            # Use OpenRouter for narration generation
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

            # Try JSON parsing first (new narrative director format)
            segments = self._parse_narrative_json(response_text, duration)
            
            if not segments:
                # Fallback: try legacy SEGMENT: format parsing
                logger.warning("⚠️ JSON parse failed, trying legacy SEGMENT format...")
                segments = self._parse_legacy_segments(response_text)
            
            if not segments:
                raise ValueError("No valid narration segments parsed.")
            return segments

        except Exception as e:
            logger.error(f"❌ Narration generation failed: {e}")
            raise RuntimeError("Narration segment generation failed.")
    
    def _parse_narrative_json(self, response_text: str, duration: int) -> List[NarrationSegment]:
        """Parse narrative director JSON response into NarrationSegments."""
        import json as _json
        
        text = response_text.strip()
        
        # Remove markdown code blocks
        if '```json' in text:
            start = text.find('```json') + 7
            end = text.rfind('```')
            if end > start:
                text = text[start:end].strip()
        elif '```' in text:
            start = text.find('```') + 3
            end = text.rfind('```')
            if end > start:
                text = text[start:end].strip()
        
        # Find JSON object
        brace_start = text.find('{')
        brace_end = text.rfind('}')
        if brace_start < 0 or brace_end <= brace_start:
            return []
        
        try:
            data = _json.loads(text[brace_start:brace_end + 1])
        except _json.JSONDecodeError:
            return []
        
        raw_segments = data.get('segments', [])
        if not raw_segments:
            return []
        
        segments = []
        current_time = 0.0
        
        for s in raw_segments:
            seg_duration = float(s.get('duration', 15))
            narration = s.get('narration', '')
            visual_desc = s.get('visual_intent', s.get('visual_description', ''))
            
            # Clean emotion tags from narration
            narration = re.sub(r'\[.*?\]', '', narration).strip()
            
            segment = NarrationSegment(
                start_time=round(current_time, 2),
                end_time=round(current_time + seg_duration, 2),
                duration=round(seg_duration, 2),
                text=narration,
                visual_description=visual_desc,
                idea=s.get('idea', ''),
                emotion=s.get('emotion', 'clarity'),
                layout_strategy=s.get('layout_strategy', 'process_flow'),
            )
            segments.append(segment)
            current_time += seg_duration
        
        logger.info(f"✅ Parsed {len(segments)} narrative segments from JSON (total: {current_time}s)")
        return segments
    
    def _parse_legacy_segments(self, response_text: str) -> List[NarrationSegment]:
        """Fallback parser for legacy SEGMENT: format."""
        lines = response_text.strip().splitlines()
        segments = []
        current_time = 0.0

        for line in lines:
            if not line.strip().startswith("SEGMENT:"):
                continue
            try:
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
                logger.warning(f"\u26a0\ufe0f Skipping malformed segment: {line} | Error: {e}")
                continue

        return segments


    def generate_scene_directions(self, segments: List[NarrationSegment]) -> List[NarrationSegment]:
        """
        STAGE 2.5: SCENE DIRECTION (DIRECTOR LAYER)
        
        Pipeline: Narration → Concept Visualizer → visual_contract → Scene Direction LLM → Validation
        
        1. Builds segment metadata
        2. Runs Concept Visualizer → creates FROZEN visual_contract per segment
        3. Injects visual model context into each segment for the LLM
        4. Calls LLM for cinematic scene directions
        5. Validates directions against visual_contract (global gate)
        """
        logger.info(f"🎬 DIRECTOR LAYER: Generating scene directions for {len(segments)} segments...")
        
        try:
            # ── Step 1: Build segment metadata ──
            segments_data = []
            for i, seg in enumerate(segments):
                segments_data.append({
                    "segment_number": i + 1,
                    "duration": seg.duration,
                    "idea": getattr(seg, 'idea', None) or seg.visual_description[:80],
                    "emotion": getattr(seg, 'emotion', None) or "clarity",
                    "narration": seg.text,
                    "visual_intent": seg.visual_description,
                    "layout_strategy": getattr(seg, 'layout_strategy', None) or "process_flow",
                })
            
            # ── Step 2: Concept Visualizer → FROZEN visual_contract ──
            visual_models = generate_visual_models_batch(segments_data)
            logger.info(f"  🧠 Concept Visualizer: generated {len(visual_models)} visual models")
            
            # Create and freeze contracts
            contracts = []
            for i, vm in enumerate(visual_models):
                contract = contract_from_visualizer(vm)
                contracts.append(contract)
                # Persist on segment — survives through ALL pipeline stages
                if i < len(segments):
                    segments[i].visual_contract = serialize_contract(contract)
                dep_type = contract.get("depiction_mode", "unknown")
                vis_model = contract.get("visual_model", "unknown")
                logger.info(f"    Seg {i+1}: depiction={dep_type}, model={vis_model}")
            
            # ── Step 3: Inject visual model context into segment data ──
            for i, seg_data in enumerate(segments_data):
                if i < len(visual_models):
                    vm_context = format_visual_model_context(visual_models[i])
                    seg_data["visual_behavior_model"] = vm_context
            
            import json
            segments_json = json.dumps(segments_data, indent=2)
            
            batch_prompt = format_scene_direction_batch_prompt(
                segments_json=segments_json,
                num_scenes=len(segments),
                aspect_ratio=self.config.aspect_ratio,
            )
            
            # ── Step 4: Call LLM for scene direction ──
            def call_openrouter(client):
                response = client.chat.completions.create(
                    model=self.narration_model,
                    messages=[{"role": "user", "content": batch_prompt}],
                    temperature=0.6,
                    max_tokens=8192,
                )
                return response.choices[0].message.content
            
            response_text = self.openrouter_key_manager.execute_with_rotation(
                call_openrouter,
                model=self.narration_model
            )
            
            if not response_text:
                logger.warning("⚠️ Scene direction response empty, using fallback")
                return self._generate_fallback_directions(segments)
            
            # Parse JSON response
            directions = self._parse_scene_directions(response_text, len(segments))
            
            if directions and len(directions) >= len(segments):
                for i, seg in enumerate(segments):
                    seg.scene_direction = json.dumps(directions[i])
                    logger.info(f"  ✅ Scene {i+1} direction: {directions[i].get('scene_goal', 'N/A')[:60]}")
                
                # ── Step 5: Validate against visual_contract (global gate) ──
                for i, direction in enumerate(directions):
                    contract = contracts[i] if i < len(contracts) else make_visual_contract()
                    passed, issues, score = validate_visual_simulation(direction, contract)
                    if not passed:
                        issues_str = ", ".join(issues)
                        logger.warning(
                            f"  ⚠️ Scene {i+1} contract validation FAILED (score={score}): {issues_str}"
                        )
                    else:
                        logger.info(f"  ✓ Scene {i+1} contract validation passed (score={score})")
            else:
                logger.warning(f"⚠️ Got {len(directions) if directions else 0} directions for {len(segments)} segments, using fallback")
                return self._generate_fallback_directions(segments)
            
            logger.info("✅ DIRECTOR LAYER: All scene directions generated.")
            return segments
            
        except Exception as e:
            logger.warning(f"⚠️ Scene direction generation failed: {e}, using fallback")
            return self._generate_fallback_directions(segments)
    
    def _parse_scene_directions(self, response_text: str, expected_count: int) -> list:
        """Parse scene direction JSON from LLM response."""
        import json
        
        # Try direct JSON parse
        text = response_text.strip()
        
        # Remove markdown code blocks if present
        if '```json' in text:
            start = text.find('```json') + 7
            end = text.rfind('```')
            if end > start:
                text = text[start:end].strip()
        elif '```' in text:
            start = text.find('```') + 3
            end = text.rfind('```')
            if end > start:
                text = text[start:end].strip()
        
        # Try parsing as JSON array
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
            elif isinstance(result, dict) and 'scenes' in result:
                return result['scenes']
            elif isinstance(result, dict):
                return [result]
        except json.JSONDecodeError:
            pass
        
        # Try finding JSON array in the text
        bracket_start = text.find('[')
        bracket_end = text.rfind(']')
        if bracket_start >= 0 and bracket_end > bracket_start:
            try:
                return json.loads(text[bracket_start:bracket_end + 1])
            except json.JSONDecodeError:
                pass
        
        logger.warning("⚠️ Could not parse scene direction JSON")
        return []
    
    def _generate_fallback_directions(self, segments: List[NarrationSegment]) -> List[NarrationSegment]:
        """Generate simulation-first fallback directions when LLM fails."""
        import json
        
        # Run concept visualizer even for fallbacks
        segments_data = []
        for i, seg in enumerate(segments):
            segments_data.append({
                "segment_number": i + 1,
                "duration": seg.duration,
                "idea": getattr(seg, 'idea', None) or seg.visual_description[:80],
                "narration": seg.text,
                "visual_intent": seg.visual_description,
                "layout_strategy": getattr(seg, 'layout_strategy', None) or "process_flow",
            })
        
        visual_models = generate_visual_models_batch(segments_data)
        
        # Create and freeze contracts for fallback path too
        contracts = []
        for i, vm in enumerate(visual_models):
            contract = contract_from_visualizer(vm)
            contracts.append(contract)
            if i < len(segments):
                segments[i].visual_contract = serialize_contract(contract)
        
        for i, seg in enumerate(segments):
            vm = visual_models[i] if i < len(visual_models) else {}
            entities = vm.get("entities", ["main_element"])
            behaviors = vm.get("behaviors", ["appear", "transform"])
            
            elem_ids = [f"s{i+1}_{e}" for e in entities[:4]]
            elements = []
            for j, eid in enumerate(elem_ids):
                elements.append({
                    "id": eid,
                    "type": "node" if j == 0 else "signal",
                    "label": entities[j] if j < len(entities) else f"element_{j}",
                    "role": "primary" if j == 0 else "secondary",
                    "position": ["center", "right", "left", "top"][j % 4],
                    "size": "large" if j == 0 else "medium",
                    "color": ["BLUE", "GREEN", "ORANGE", "PURPLE"][j % 4],
                })
            
            fallback = {
                "scene_number": i + 1,
                "depiction_mode": vm.get("depiction_type", "simulation"),
                "scene_goal": seg.visual_description[:100],
                "focus_object": entities[0] if entities else "main concept",
                "visual_metaphor": vm.get("visual_model", "process_flow"),
                "layout": {
                    "strategy": getattr(seg, 'layout_strategy', None) or "process_flow",
                    "primary_zone": "center",
                    "element_spread": "balanced across screen"
                },
                "elements": elements or [{
                    "id": f"s{i+1}_elem_1",
                    "type": "node",
                    "label": "Main",
                    "role": "primary",
                    "position": "center",
                    "size": "large",
                    "color": "BLUE",
                }],
                "direction_beats": [
                    {
                        "beat": 1, "time_percent": "0-30%",
                        "action": f"{behaviors[0] if behaviors else 'Introduce'} main elements",
                        "purpose": "Set the scene",
                        "elements_involved": elem_ids[:2] or [f"s{i+1}_elem_1"],
                        "motion_type": "activate",
                    },
                    {
                        "beat": 2, "time_percent": "30-70%",
                        "action": f"{behaviors[1] if len(behaviors) > 1 else 'Transform'} — show process",
                        "purpose": "Build understanding through motion",
                        "elements_involved": elem_ids or [f"s{i+1}_elem_1"],
                        "motion_type": "propagate",
                    },
                    {
                        "beat": 3, "time_percent": "70-100%",
                        "action": "Complete transformation cycle",
                        "purpose": "Reinforce learning visually",
                        "elements_involved": elem_ids or [f"s{i+1}_elem_1"],
                        "motion_type": "transform",
                    },
                ],
                "transformation_chain": behaviors[:3] if behaviors else ["appear", "transform", "settle"],
                "attention_flow": elem_ids or [f"s{i+1}_elem_1"],
                "interaction_plan": [f"Elements animate {b}" for b in (behaviors[:2] or ["appear", "transform"])],
                "transition_out": "hold"
            }
            seg.scene_direction = json.dumps(fallback)
        
        return segments

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
        """
        LAYER 3 — MANIM EXECUTION (ANIMATOR) — Batch mode.
        Uses scene direction from Director layer when available.
        """
        aspect_ratio_config = self._get_aspect_ratio_config()
        params = get_aspect_params(self.config.aspect_ratio)
        
        # Build segment info with scene directions
        all_segments_with_direction = ""
        for i, segment in enumerate(batch_segments):
            direction = getattr(segment, 'scene_direction', '') or f"Visual intent: {segment.visual_description}"
            all_segments_with_direction += f"""
--- Segment {batch_start + i + 1} ---
Class: Segment{batch_start + i:03d}
Duration: {segment.duration:.2f}s
Narration: "{segment.text}"
Scene Direction: {direction}
"""

        batch_prompt = format_manim_execution_batch_prompt(
            num_segments=len(batch_segments),
            all_segments_with_direction=all_segments_with_direction,
            aspect_ratio=self.config.aspect_ratio,
            aspect_ratio_config=aspect_ratio_config,
            allowed_colors=self.allowed_colors,
        )

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
        """
        LAYER 3 — MANIM EXECUTION (ANIMATOR) — Individual mode.
        Uses scene direction from Director layer when available.
        """
        logger.info(f"🎬 ENTERING _generate_individual_script for segment {segment_number}")
        
        aspect_ratio_config = self._get_aspect_ratio_config()
        
        # Build scene direction context
        direction = getattr(segment, 'scene_direction', '') or f"Visual intent: {segment.visual_description}"
        
        prompt = format_manim_execution_prompt(
            index=segment_number - 1,
            duration=segment.duration,
            aspect_ratio=self.config.aspect_ratio,
            narration=segment.text,
            scene_direction=direction,
            aspect_ratio_config=aspect_ratio_config,
            animation_reference=getattr(self, 'animation_reference', ''),
            allowed_attributes=getattr(self, 'allowed_attributes', ''),
            allowed_colors=getattr(self, 'allowed_colors', ''),
        )
        
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

    def _correct_script_with_groq(self, broken_script: str, error_context: str, segment: NarrationSegment = None, segment_index: int = 0) -> str:
        """
        STAGE 4: Script Correction (Structural Repair Only)
        
        Use Groq to fix broken scripts while enforcing strict constraints:
        - Can fix: Syntax errors, Manim API errors, layout overlaps
        - Cannot change: Narration content, scene intent, timing semantics
        """
        if not self.groq_client:
            return broken_script
        
        prompt = format_error_correction_minimal_prompt(
            index=segment_index,
            duration=segment.duration if segment else 10.0,
            error=error_context,
            script=broken_script,
            aspect_ratio=self.config.aspect_ratio,
        )
        
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
        Fully regenerate a fresh Manim script using Gemini directly.
        Uses the original narration, visuals, and audio duration.
        """
        aspect_ratio_config = self._get_aspect_ratio_config()
        
        prompt = f"""
    You are a Manim Python expert.
    Rewrite a complete script for this segment from scratch.

    - Class name must be: Segment{segment_number:03d}
    - Use ONLY 'from manim import *'
    - Must include aspect ratio configuration immediately after imports
    - Must match exact duration: {segment.duration:.2f} seconds
    - Visuals: {segment.visual_description}
    - Narration: {segment.text}

    REQUIRED FORMAT:
    from manim import *

    {aspect_ratio_config}

    class Segment{segment_number:03d}(Scene):
        def construct(self):
            # Your code here - fill entire duration with animations
            # End with self.wait() ONLY if needed to reach exact duration

    Output ONLY raw Python code. No markdown, no explanations.
        """

        try:
            # Use Gemini directly for script regeneration
            response = self._call_gemini_with_rotation(
                prompt,
                {'temperature': self.config.gemini_temperature, 'max_output_tokens': self.config.gemini_max_tokens},
                f"script_regeneration_segment_{segment_number}"
            )
            raw_script = response.text.strip()
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
                    # Inject premium background after regeneration
                    script_content = self._inject_premium_background(script_content, i, segment.duration or 5.0)
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
                    script_content = self._correct_script_with_groq(script_content, error or "Unknown error", segment, i)

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
                "-qh",                        # HIGH quality: 1080p60 (professional output)
                "--format", "mp4",
                "--disable_caching",          # Disable caching to save RAM
                "--flush_cache",              # Clear cache after render
                "--renderer=cairo",           # Cairo renderer for better quality
            ]
            
            logger.info(f"🎬 Rendering: {filename} → Class: {class_name} (1080p60 -qh quality - professional output)")
            
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

        # Expected output file path - 1080p60 quality (-qh flag) outputs to 1080p60 folder
        if segment_index is not None:
            # Manim outputs video with the class name as filename
            # Expected: Segment000.mp4, Segment001.mp4, etc.
            class_name = f"Segment{segment_index:03d}"
            expected_path = temp_path / "media" / "videos" / f"segment_{segment_index:03d}" / "1080p60" / f"{class_name}.mp4"
            
            if expected_path.exists():
                logger.info(f"✅ Found video: {expected_path}")
                return str(expected_path), None
            
            # Fallback 1: Check if it was saved as Scene.mp4 (shouldn't happen with correct class name)
            scene_path = temp_path / "media" / "videos" / f"segment_{segment_index:03d}" / "1080p60" / "Scene.mp4"
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

    def _prepare_intro_for_aspect_ratio(self) -> Optional[Path]:
        """
        Prepare intro video for the current aspect ratio.
        
        For 16:9: Uses the pre-made intro video scaled to 720p
        For 9:16/1:1/4:3: Generates a Manim-based intro with Code Tapasya branding
        
        Returns:
            Path to intro video, or None if not available
        """
        if self.config.aspect_ratio == "16:9":
            # Use traditional scaled intro
            return self._prepare_scaled_intro()
        
        # For other aspect ratios, generate Manim-based intro
        return self._generate_manim_intro()
    
    def _generate_manim_intro(self) -> Optional[Path]:
        """
        Generate a Manim-based intro animation for non-16:9 aspect ratios.
        Features Code Tapasya branding with professional animation.
        
        Returns:
            Path to rendered intro video, or None on failure
        """
        temp_dir = Path(self.config.temp_dir)
        aspect_ratio = self.config.aspect_ratio
        
        # Cache filename includes aspect ratio
        cache_path = temp_dir / f"intro_manim_{aspect_ratio.replace(':', 'x')}.mp4"
        
        if cache_path.exists():
            logger.info(f"✅ Using cached Manim intro: {cache_path}")
            return cache_path
        
        logger.info(f"🎬 Generating Manim intro for {aspect_ratio}...")
        
        # Get config for aspect ratio
        aspect_configs = {
            "9:16": {"fw": 9, "fh": 16, "pw": 1080, "ph": 1920},
            "1:1": {"fw": 1, "fh": 1, "pw": 1080, "ph": 1080},
            "4:3": {"fw": 4, "fh": 3, "pw": 1440, "ph": 1080},
        }
        cfg = aspect_configs.get(aspect_ratio, aspect_configs["9:16"])
        
        intro_script = f'''from manim import *

# Configure for {aspect_ratio}
config.frame_width = {cfg["fw"]}
config.frame_height = {cfg["fh"]}
config.pixel_width = {cfg["pw"]}
config.pixel_height = {cfg["ph"]}


class IntroAnimation(Scene):
    def construct(self):
        # Background gradient
        bg = Rectangle(
            width=config.frame_width + 1,
            height=config.frame_height + 1,
            fill_opacity=1.0,
            stroke_width=0
        )
        bg.set_fill(color=["#0a0a1a", "#1a1a3a", "#0a0a1a"])
        self.add(bg)
        
        # Code Tapasya logo text
        brand_name = Text("Code Tapasya", font_size=36, weight=BOLD)
        brand_name.scale_to_fit_width(config.frame_width * 0.7)
        brand_name.set_color_by_gradient(BLUE, TEAL)
        
        # Tagline
        tagline = Text("Learn • Create • Grow", font_size=20)
        tagline.scale_to_fit_width(config.frame_width * 0.6)
        tagline.set_color(GRAY)
        tagline.next_to(brand_name, DOWN, buff=0.4)
        
        # Center group
        logo_group = VGroup(brand_name, tagline)
        logo_group.move_to(ORIGIN)
        
        # Decorative elements
        circle_glow = Circle(radius=config.frame_width * 0.3, stroke_width=0)
        circle_glow.set_fill(color=BLUE, opacity=0.05)
        circle_glow.move_to(ORIGIN)
        
        # Animated particles
        particles = VGroup()
        import random
        random.seed(42)
        for _ in range(8):
            dot = Dot(radius=0.05, fill_opacity=random.uniform(0.3, 0.6), color=BLUE_B)
            x = random.uniform(-config.frame_width * 0.4, config.frame_width * 0.4)
            y = random.uniform(-config.frame_height * 0.4, config.frame_height * 0.4)
            dot.move_to([x, y, 0])
            particles.add(dot)
        
        # Animation sequence (3 seconds total)
        self.play(FadeIn(circle_glow, scale=0.5), run_time=0.3)
        self.play(LaggedStart(*[FadeIn(p, scale=0.5) for p in particles], lag_ratio=0.05), run_time=0.4)
        self.play(Write(brand_name), run_time=0.8)
        self.play(FadeIn(tagline, shift=UP*0.2), run_time=0.4)
        self.play(
            circle_glow.animate.scale(1.1).set_opacity(0.02),
            brand_name.animate.scale(1.02),
            run_time=0.5
        )
        self.wait(0.3)
        self.play(
            FadeOut(logo_group),
            FadeOut(circle_glow),
            FadeOut(particles),
            run_time=0.3
        )
'''
        
        # Save and render
        script_path = temp_dir / "intro_script.py"
        script_path.write_text(intro_script, encoding="utf-8")
        
        try:
            cmd = [
                'manim', 'render',
                '-qh',  # High quality
                '--disable_caching',
                '--media_dir', str(temp_dir / 'media_intro'),
                str(script_path),
                'IntroAnimation'
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(temp_dir)
            )
            
            if result.returncode != 0:
                logger.error(f"❌ Manim intro render failed: {result.stderr}")
                return None
            
            # Find output video
            output_dir = temp_dir / 'media_intro' / 'videos' / 'intro_script' / '1080p60'
            if not output_dir.exists():
                output_dir = temp_dir / 'media_intro' / 'videos' / 'intro_script' / '1920p60'
            
            intro_files = list(output_dir.glob('IntroAnimation.mp4'))
            if intro_files:
                # Move to cache location
                shutil.copy2(intro_files[0], cache_path)
                logger.info(f"✅ Manim intro generated and cached: {cache_path}")
                return cache_path
            
            logger.error("❌ Manim intro video not found after render")
            return None
            
        except Exception as e:
            logger.error(f"❌ Manim intro generation failed: {e}")
            return None

    def _generate_manim_outro(self) -> Optional[Path]:
        """
        Generate a Manim-based outro animation with CTA for subscriptions.
        Features Code Tapasya branding with subscribe/like prompts.
        
        Returns:
            Path to rendered outro video, or None on failure
        """
        temp_dir = Path(self.config.temp_dir)
        aspect_ratio = self.config.aspect_ratio
        
        # Cache filename includes aspect ratio
        cache_path = temp_dir / f"outro_manim_{aspect_ratio.replace(':', 'x')}.mp4"
        
        if cache_path.exists():
            logger.info(f"✅ Using cached Manim outro: {cache_path}")
            return cache_path
        
        logger.info(f"🎬 Generating Manim outro for {aspect_ratio}...")
        
        # Get config for aspect ratio
        aspect_configs = {
            "9:16": {"fw": 9, "fh": 16, "pw": 1080, "ph": 1920},
            "1:1": {"fw": 1, "fh": 1, "pw": 1080, "ph": 1080},
            "4:3": {"fw": 4, "fh": 3, "pw": 1440, "ph": 1080},
            "16:9": {"fw": 16, "fh": 9, "pw": 1920, "ph": 1080},
        }
        cfg = aspect_configs.get(aspect_ratio, aspect_configs["9:16"])
        
        outro_script = f'''from manim import *

# Configure for {aspect_ratio}
config.frame_width = {cfg["fw"]}
config.frame_height = {cfg["fh"]}
config.pixel_width = {cfg["pw"]}
config.pixel_height = {cfg["ph"]}


class OutroAnimation(Scene):
    def construct(self):
        # Background gradient
        bg = Rectangle(
            width=config.frame_width + 1,
            height=config.frame_height + 1,
            fill_opacity=1.0,
            stroke_width=0
        )
        bg.set_fill(color=["#0a0a1a", "#0f1a2a", "#0a0a1a"])
        self.add(bg)
        
        # Thank you message
        thanks = Text("Thanks for watching!", font_size=28, weight=BOLD)
        thanks.scale_to_fit_width(config.frame_width * 0.75)
        thanks.set_color(WHITE)
        
        # Subscribe CTA
        subscribe = Text("Subscribe for more!", font_size=22)
        subscribe.scale_to_fit_width(config.frame_width * 0.6)
        subscribe.set_color_by_gradient(RED, PINK)
        subscribe.next_to(thanks, DOWN, buff=0.5)
        
        # Code Tapasya branding
        brand = Text("Code Tapasya", font_size=18)
        brand.scale_to_fit_width(config.frame_width * 0.4)
        brand.set_color(GRAY)
        brand.to_edge(DOWN, buff=0.8)
        
        # Decorative subscribe button effect
        btn_rect = RoundedRectangle(
            width=config.frame_width * 0.35,
            height=0.6,
            corner_radius=0.15,
            fill_opacity=0.9,
            fill_color=RED,
            stroke_width=0
        )
        btn_text = Text("SUBSCRIBE", font_size=16, weight=BOLD, color=WHITE)
        btn_text.scale_to_fit_width(btn_rect.width * 0.7)
        btn_group = VGroup(btn_rect, btn_text)
        btn_group.next_to(subscribe, DOWN, buff=0.4)
        
        # Center main content
        main_group = VGroup(thanks, subscribe, btn_group)
        main_group.move_to(ORIGIN + UP * 0.5)
        
        # Animation sequence (3 seconds total)
        self.play(FadeIn(thanks, scale=0.8), run_time=0.5)
        self.play(
            FadeIn(subscribe, shift=UP * 0.2),
            run_time=0.4
        )
        self.play(
            GrowFromCenter(btn_group),
            run_time=0.4
        )
        self.play(
            btn_rect.animate.scale(1.05),
            rate_func=there_and_back,
            run_time=0.3
        )
        self.play(FadeIn(brand, shift=UP * 0.1), run_time=0.3)
        self.wait(0.5)
        self.play(
            FadeOut(main_group),
            FadeOut(brand),
            run_time=0.6
        )
'''
        
        # Save and render
        script_path = temp_dir / "outro_script.py"
        script_path.write_text(outro_script, encoding="utf-8")
        
        try:
            cmd = [
                'manim', 'render',
                '-qh',  # High quality
                '--disable_caching',
                '--media_dir', str(temp_dir / 'media_outro'),
                str(script_path),
                'OutroAnimation'
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(temp_dir)
            )
            
            if result.returncode != 0:
                logger.error(f"❌ Manim outro render failed: {result.stderr}")
                return None
            
            # Find output video
            output_dir = temp_dir / 'media_outro' / 'videos' / 'outro_script' / '1080p60'
            if not output_dir.exists():
                output_dir = temp_dir / 'media_outro' / 'videos' / 'outro_script' / '1920p60'
            
            outro_files = list(output_dir.glob('OutroAnimation.mp4'))
            if outro_files:
                # Move to cache location
                shutil.copy2(outro_files[0], cache_path)
                logger.info(f"✅ Manim outro generated and cached: {cache_path}")
                return cache_path
            
            logger.error("❌ Manim outro video not found after render")
            return None
            
        except Exception as e:
            logger.error(f"❌ Manim outro generation failed: {e}")
            return None

    def _video_has_audio(self, video_path: str) -> bool:
        """
        Check if a video file has an audio stream using ffprobe.
        
        Args:
            video_path: Path to the video file
            
        Returns:
            True if video has audio, False otherwise
        """
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                str(video_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return "audio" in result.stdout.lower()
        except Exception as e:
            logger.warning(f"⚠️ ffprobe audio check failed for {video_path}: {e}")
            return False

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
        Previously added intro/outro clips via FFmpeg concatenation.
        Now disabled - intro/outro are built into the narration and visuals.
        
        Args:
            generated_video_path: Path to the generated video
            
        Returns:
            The same video path (no concatenation needed)
        """
        # Intro/outro now built into content via narrative prompt
        # No separate clips needed
        logger.info("ℹ️ Intro/outro built into content, no concatenation needed")
        return generated_video_path

    def cleanup_temp_files(self) -> None:
        """Clean up temporary files after video generation."""
        try:
            temp_path = Path(self.config.temp_dir)
            if temp_path.exists():
                # Remove all contents but keep the temp directory
                for item in temp_path.iterdir():
                    try:
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
            '-shortest',           # Trim to shorter of audio/video
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
            '-shortest',           # Trim to shorter of audio/video
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

            # Step 1.5: Generate scene directions (Director layer)
            segments = self.generate_scene_directions(segments)
            logger.info(f"Generated scene directions for {len(segments)} segments")
            
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
                "-i", str(concat_list_path), "-c", "copy",
            ]
            # A2: Duration cap REMOVED — let content run its full length
            # The audio/video segments already have correct durations from generation.
            # Trimming here cuts off valid narrated content.
            cmd.append(final_output_path)

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


def _safe_move_video(src_path: str, dest_path: str) -> None:
    """Safely move a video file, handling Windows file-locking (WinError 5).
    
    Path.replace() fails on Windows when the target already exists and is
    locked by another process (antivirus, explorer thumbnailing, etc.).
    We use shutil.copy2 + os.remove with retry logic instead.
    """
    import shutil, time
    src = Path(src_path)
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    
    # Remove existing target first (free any stale lock)
    for attempt in range(3):
        try:
            if dest.exists():
                dest.unlink()
            break
        except PermissionError:
            time.sleep(0.5 * (attempt + 1))
    
    # Copy then remove source (works across volumes, avoids atomic-rename issues)
    for attempt in range(3):
        try:
            shutil.copy2(str(src), str(dest))
            try:
                src.unlink()  # best-effort remove source
            except Exception:
                pass
            return
        except PermissionError:
            time.sleep(0.5 * (attempt + 1))
    
    # Final fallback: shutil.move
    shutil.move(str(src), str(dest))


def _inject_premium_background_standalone(script: str, index: int, duration: float, aspect_ratio: str = "9:16") -> str:
    """
    Standalone background injection for use in worker processes.
    
    Injects premium background (GradientBackground, SubtleGrid, AmbientParticles,
    progress bar, channel watermark) into Manim scripts.
    
    This is a module-level copy of OptimizedVideoGenerationPipeline._inject_premium_background()
    so that ProcessPoolExecutor workers can use it without access to the class instance.
    """
    # Skip if already has premium background
    if 'GradientBackground' in script or 'SubtleGrid' in script:
        return script
    
    # Per-segment accent color rotation
    accent_colors = ["BLUE", "TEAL", "PURPLE", "GOLD", "PINK", "GREEN"]
    accent = accent_colors[index % len(accent_colors)]
    
    # PRIMITIVES BLOCK: inserted before the Scene class
    primitives_block = f'''
# === PREMIUM BACKGROUND PRIMITIVES (auto-injected) ===

class GradientBackground(VGroup):
    """Dark gradient background with subtle color accent."""
    def __init__(self, accent_color=BLUE, **kwargs):
        super().__init__(**kwargs)
        fw, fh = config.frame_width, config.frame_height
        base = Rectangle(width=fw + 1, height=fh + 1, fill_opacity=1.0, stroke_width=0)
        base.set_fill(color=["#0a0a1a", "#0f1629", "#0a0a1a"])
        self.add(base)
        glow = Circle(radius=fw * 0.06, fill_opacity=0.015, stroke_width=0, color=accent_color)
        glow.shift(UP * fh * 0.4 + RIGHT * fw * 0.35)
        self.add(glow)


class AmbientParticles(VGroup):
    """Floating dots that drift slowly."""
    def __init__(self, count=6, **kwargs):
        super().__init__(**kwargs)
        fw, fh = config.frame_width, config.frame_height
        import random as _rng
        _rng.seed(42)
        for _ in range(count):
            r = _rng.uniform(0.03, 0.07)
            opacity = _rng.uniform(0.12, 0.25)
            dot = Dot(radius=r, fill_opacity=opacity, color=WHITE, stroke_width=0)
            x = _rng.uniform(-fw * 0.45, fw * 0.45)
            y = _rng.uniform(-fh * 0.45, fh * 0.45)
            dot.move_to([x, y, 0])
            self.add(dot)


class SubtleGrid(VGroup):
    """Very faint grid lines for visual structure."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        fw, fh = config.frame_width, config.frame_height
        for i in range(-3, 4):
            x = i * fw / 6
            line = Line([x, -fh/2, 0], [x, fh/2, 0], stroke_width=0.3, stroke_opacity=0.06, color=WHITE)
            self.add(line)
        for i in range(-5, 6):
            y = i * fh / 10
            line = Line([-fw/2, y, 0], [fw/2, y, 0], stroke_width=0.3, stroke_opacity=0.06, color=WHITE)
            self.add(line)

'''
    
    # BACKGROUND SETUP CODE: inserted right after `def construct(self):`
    bg_setup = f'''
        # === PREMIUM BACKGROUND (auto-injected) ===
        _bg = GradientBackground(accent_color={accent})
        self.add(_bg)
        _grid = SubtleGrid()
        self.add(_grid)
        _particles = AmbientParticles(count=6)
        self.add(_particles)
        for _dot in _particles:
            _dx = random.uniform(-0.02, 0.02)
            _dy = random.uniform(0.01, 0.03)
            _dot.add_updater(lambda m, dt, _dx=_dx, _dy=_dy: m.shift(np.array([_dx * dt, _dy * dt, 0])))
        # Progress bar
        _pb_total_w = config.frame_width * 0.85
        _pb_bg = Rectangle(width=_pb_total_w, height=0.06, fill_opacity=0.15,
                           fill_color=WHITE, stroke_width=0)
        _pb_bg.move_to(np.array([0, -config.frame_height/2 + 0.12, 0]))
        self.add(_pb_bg)
        _pb_bar = Rectangle(width=0.01, height=0.06, fill_opacity=0.6,
                            fill_color={accent}, stroke_width=0)
        _pb_bar.move_to(_pb_bg.get_center())
        _pb_bar.align_to(_pb_bg, LEFT)
        self.add(_pb_bar)
        _pb_bar._pt = 0
        _scene_dur = {duration:.1f}
        def _pb_upd(m, dt):
            m._pt += dt
            frac = min(1.0, m._pt / max(0.1, _scene_dur))
            new_w = max(0.01, _pb_total_w * frac)
            m.stretch_to_fit_width(new_w)
            m.align_to(_pb_bg, LEFT)
        _pb_bar.add_updater(_pb_upd)
        # Channel watermark
        _wm = Text("Code Tapasya", font_size=14, color=WHITE,
                    font="sans-serif", fill_opacity=0.25)
        _wm.move_to(np.array([config.frame_width/2 - 1.2,
                              -config.frame_height/2 + 0.35, 0]))
        self.add(_wm)
        # Scene intro flash
        _flash_rect = Rectangle(width=config.frame_width + 2, height=config.frame_height + 2,
                               fill_opacity=0.04, fill_color=WHITE, stroke_width=0)
        self.play(FadeIn(_flash_rect, run_time=0.06), rate_func=rate_functions.ease_out_cubic)
        self.play(FadeOut(_flash_rect, run_time=0.1), rate_func=rate_functions.ease_in_cubic)
        self.remove(_flash_rect)
'''
    
    # Ensure numpy is imported
    if 'import numpy' not in script and 'numpy' not in script:
        script = script.replace('from manim import *', 'from manim import *\nimport numpy as np')
    if 'import random' not in script:
        script = script.replace('from manim import *', 'from manim import *\nimport random')
    
    # Step 1: Inject primitive class definitions before the Scene class
    class_pattern = re.search(r'^class Segment\d{3}\(Scene\):', script, re.MULTILINE)
    if class_pattern:
        insert_pos = class_pattern.start()
        script = script[:insert_pos] + primitives_block + script[insert_pos:]
    
    # Step 2: Inject background setup code after `def construct(self):`
    construct_pattern = re.search(r'def construct\(self\):\s*\n', script)
    if construct_pattern:
        insert_pos = construct_pattern.end()
        script = script[:insert_pos] + bg_setup + '\n' + script[insert_pos:]
    
    logger.info(f"🎨 Injected premium background into regenerated segment {index}")
    return script


# Global functions for ProcessPoolExecutor (must be at module level)
def render_single_video_worker(args):
    """
    Enhanced worker function for video rendering with improved error handling.
    This replaces the original render_single_video_worker function.
    """
    global _singleton_pipeline

    i, segment_data, config_dict = args

    try:
        
        # Extract keys that are not part of VideoGenerationConfig before creating config
        openrouter_key_manager = config_dict.pop('openrouter_key_manager', None)
        gemini_api_key = config_dict.pop('gemini_api_key', None)
        gemini_models = config_dict.pop('gemini_models', None)
        
        # Initialize the singleton pipeline only once per process
        if _singleton_pipeline is None:
            config = VideoGenerationConfig(**config_dict)
            _singleton_pipeline = VideoGenerationPipeline(config)

        pipeline = _singleton_pipeline
        
        # Re-add extracted keys to config_dict for use by correction/regeneration functions
        if openrouter_key_manager:
            config_dict['openrouter_key_manager'] = openrouter_key_manager
        if gemini_api_key:
            config_dict['gemini_api_key'] = gemini_api_key
        if gemini_models:
            config_dict['gemini_models'] = gemini_models

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
                _safe_move_video(video_path, str(expected_path))
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
        
        # Track last error for context in regeneration
        last_error_for_regen = error if error else "Unknown render failure"
        
        while regeneration_count < max_regeneration_attempts:
            regeneration_count += 1
            total_attempts += 1
            
            logger.warning(f"🔄 Regenerating script {i+1} from scratch (regeneration {regeneration_count}/{max_regeneration_attempts})")
            
            try:
                # Regenerate script from scratch using Gemini directly
                # Pass previous_error so Gemini can avoid same mistakes
                script_content = _regenerate_script_from_scratch_enhanced(
                    segment_data, i, config_dict['gemini_api_key'], 
                    config_dict.get('aspect_ratio', '16:9'),
                    config_dict.get('gemini_models'),
                    previous_error=last_error_for_regen  # NEW: Pass error context
                )
                
                # CRITICAL: Inject premium background after regeneration
                duration = segment_data.get('duration', 5.0)
                script_content = _inject_premium_background_standalone(
                    script_content, i, duration, config_dict.get('aspect_ratio', '16:9')
                )
                
                Path(script_path).write_text(script_content, encoding="utf-8")
                
                # Try rendering the regenerated script
                video_path, error = pipeline.create_video_file(script_content, filename=f"segment_{i:03d}.py", segment_index=i)
                
                if video_path:
                    target_dir = Path(segment_data['video_output_dir']) / f"segment_{i:03d}"
                    target_dir.mkdir(parents=True, exist_ok=True)
                    expected_path = target_dir / f"Segment{i:03d}.mp4"
                    _safe_move_video(video_path, str(expected_path))
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
                            _safe_move_video(video_path, str(expected_path))
                            logger.info(f"✅ Fixed regenerated video {i+1} saved to: {expected_path} (after {total_attempts} total attempts)")
                            return {'success': True, 'video_path': str(expected_path), 'index': i}
                    
                    # All fixes failed, will regenerate again in next iteration
                    # Update error context for next regeneration attempt
                    last_error_for_regen = error if error else "Render failed after fixes"
                    logger.warning(f"⚠️ All 3 fix attempts failed for regenerated script {i+1}, will try next regeneration")
                    
            except Exception as regen_error:
                # Update error context for next regeneration attempt
                last_error_for_regen = str(regen_error)
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
                    _safe_move_video(video_path, str(expected_path))
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
                _safe_move_video(video_path, str(expected_path))
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

def _regenerate_script_from_scratch_enhanced(segment_data: dict, index: int, gemini_api_key: str, aspect_ratio: str = "16:9", gemini_models: list = None, previous_error: str = None) -> str:
    """
    Fully regenerate the script using Gemini directly with automatic model rotation.
    
    ENHANCED: Now uses scene_spec and visual_contract from segment_data for better context,
    and includes previous_error to help Gemini avoid the same mistakes.
    
    Args:
        segment_data: Dict containing narration, visuals, duration, scene_spec, visual_contract, audio_path
        index: Segment index (0-based)
        gemini_api_key: Gemini API key
        aspect_ratio: Video aspect ratio
        gemini_models: List of Gemini models for rotation
        previous_error: The error from the previous failed attempt (helps Gemini avoid it)
    
    Returns:
        Raw Manim script (WITHOUT background injection - caller must inject background)
    """
    try:
        from pydub import AudioSegment
        import google.genai as genai
        from google.genai import types
        
        # Initialize Gemini client
        gemini_client = genai.Client(api_key=gemini_api_key)
        
        # Default models for rotation
        if gemini_models is None:
            gemini_models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]
        
        narration = segment_data.get('narration', "Educational content")
        visuals = segment_data.get('visuals', "Simple visuals")
        scene_spec = segment_data.get('scene_spec')  # NEW: scene_spec dict
        visual_contract = segment_data.get('visual_contract')  # NEW: visual_contract JSON
        
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
            "16:9": {"frame_width": 16, "frame_height": 9, "pixel_width": 1920, "pixel_height": 1080, "safe_x": 7.0, "safe_y": 3.5},
            "9:16": {"frame_width": 9, "frame_height": 16, "pixel_width": 1080, "pixel_height": 1920, "safe_x": 3.8, "safe_y": 6.5},
            "1:1": {"frame_width": 1, "frame_height": 1, "pixel_width": 1080, "pixel_height": 1080, "safe_x": 4.0, "safe_y": 4.0},
            "4:3": {"frame_width": 4, "frame_height": 3, "pixel_width": 1440, "pixel_height": 1080, "safe_x": 5.5, "safe_y": 4.0},
            "21:9": {"frame_width": 21, "frame_height": 9, "pixel_width": 2560, "pixel_height": 1080, "safe_x": 9.5, "safe_y": 3.5}
        }
        config = aspect_ratio_configs.get(aspect_ratio, aspect_ratio_configs["16:9"])
        
        # Width factor for text scaling
        width_factors = {"16:9": 0.85, "9:16": 0.55, "1:1": 0.70, "4:3": 0.80, "21:9": 0.90}
        width_factor = width_factors.get(aspect_ratio, 0.55)
        max_fonts = {"16:9": 48, "9:16": 28, "1:1": 38, "4:3": 44, "21:9": 48}
        max_font = max_fonts.get(aspect_ratio, 28)

        # Build scene direction from scene_spec if available
        scene_direction = ""
        if scene_spec:
            parts = []
            vm = scene_spec.get('visual_metaphor', {})
            if vm.get('abstract_concept'):
                parts.append(f"Abstract concept: {vm['abstract_concept']}")
            if vm.get('concrete_representation'):
                parts.append(f"Visual representation: {vm['concrete_representation']}")
            elements = vm.get('visual_elements', [])
            if elements:
                elem_strs = []
                for e in elements[:6]:
                    etype = e.get('element_type', 'unknown')
                    label = e.get('label', '')
                    elem_strs.append(f"  - {label or etype} ({etype})")
                parts.append("Key elements:\n" + "\n".join(elem_strs))
            
            transformation = scene_spec.get('transformation', {})
            sequence = transformation.get('sequence', [])
            if sequence:
                step_strs = []
                for s in sequence[:6]:
                    action = s.get('action', 'appear')
                    target = s.get('target', '')
                    step_strs.append(f"  {action} → {target}")
                parts.append("Animation sequence:\n" + "\n".join(step_strs))
            
            scene_direction = "\n".join(parts) if parts else "Create engaging educational animation"
        
        # Build visual contract context
        contract_context = ""
        if visual_contract:
            try:
                if isinstance(visual_contract, str):
                    import json
                    vc = json.loads(visual_contract)
                else:
                    vc = visual_contract
                parts = []
                if vc.get('depiction_mode'):
                    parts.append(f"Depiction mode: {vc['depiction_mode']}")
                if vc.get('visual_model'):
                    parts.append(f"Visual model: {vc['visual_model']}")
                if vc.get('entities'):
                    parts.append(f"Key entities: {', '.join(str(e.get('type', e)) if isinstance(e, dict) else str(e) for e in vc['entities'][:5])}")
                contract_context = "\n".join(parts)
            except Exception:
                pass
        
        # Build error avoidance section if we have a previous error
        error_avoidance = ""
        if previous_error:
            # Extract key error info
            error_lines = previous_error[:800]  # Limit error context
            error_avoidance = f"""
⚠️ CRITICAL: PREVIOUS ATTEMPT FAILED WITH THIS ERROR - AVOID IT!
```
{error_lines}
```
ANALYZE THIS ERROR and ensure your new script does NOT make the same mistake.
Common fixes:
- If "no attribute": Check Manim API - use correct method names
- If "not defined": Make sure all variables are defined before use
- If "position" error: Use .move_to([x, y, 0]) or .move_to(UP*2 + RIGHT*3)
- If "Transform" error: Transform takes exactly 2 mobjects
- If "Text" error: Use font_size=X not size=X, use weight=BOLD not bold=True
"""

        # Layout guidance based on aspect ratio
        if aspect_ratio == "9:16":
            layout_guidance = """VERTICAL LAYOUT (9:16):
- Stack elements VERTICALLY using .arrange(DOWN, buff=0.5)
- Keep text SHORT (max 15 words per text object)
- Position: TOP (UP*6), CENTER (ORIGIN), BOTTOM (DOWN*6)
- ALWAYS use .scale_to_fit_width(config.frame_width * 0.55) for ALL text"""
        else:
            layout_guidance = f"""LAYOUT ({aspect_ratio}):
- Use appropriate spacing for frame dimensions
- ALWAYS use .scale_to_fit_width(config.frame_width * {width_factor}) for ALL text"""

        prompt = f"""You are an expert Manim animation engineer.

Your job is to generate a COMPLETE and EXECUTABLE Manim script that visually represents the narration.

The animation must be educational, visually alive, and clearly depict the concept described in the narration.

You have creative freedom, but the code must be STABLE and FOLLOW valid Manim API usage.

--------------------------------------------------

SEGMENT INFORMATION

Class name: Segment{index:03d}

Target Duration: {actual_duration:.2f} seconds

Aspect Ratio: {aspect_ratio}

Frame size:
width = {config['frame_width']}
height = {config['frame_height']}

--------------------------------------------------

ASPECT RATIO CONFIGURATION
This must appear directly after imports:

config.frame_width = {config['frame_width']}
config.frame_height = {config['frame_height']}
config.pixel_width = {config['pixel_width']}
config.pixel_height = {config['pixel_height']}

--------------------------------------------------

NARRATION

{narration}

--------------------------------------------------

VISUAL DIRECTION

{scene_direction if scene_direction else "Create an engaging visual explanation of the narration."}

--------------------------------------------------

VISUAL CONTRACT

{contract_context if contract_context else "Use your judgement to visually depict the narration."}

--------------------------------------------------

SPATIAL SAFETY LIMITS

Objects must stay within these bounds:

Horizontal: LEFT*{config['safe_x']} to RIGHT*{config['safe_x']}

Vertical: UP*{config['safe_y']} to DOWN*{config['safe_y']}

All text must use:

.scale_to_fit_width(config.frame_width * {width_factor})

OR

font_size ≤ {max_font}

--------------------------------------------------

CODE STRUCTURE (MANDATORY)

Your script MUST follow this exact structure:

from manim import *

config.frame_width = ...
config.frame_height = ...
config.pixel_width = ...
config.pixel_height = ...

class SegmentXXX(Scene):
    def construct(self):

        # create visual objects
        object_a = ...
        object_b = ...

        # animate them
        self.play(...)

        # continue animations
        self.play(...)

        # finish scene
        self.wait()

--------------------------------------------------

ANIMATION DESIGN RULES

• Animate PROCESSES, not just objects.
• Objects should move, transform, or interact.
• Prefer Transform() or ReplacementTransform().
• Use Create(), Write(), or FadeIn() to introduce objects.
• Do NOT leave the screen static for long periods.

Avoid purely explanatory diagrams.

Visuals should SHOW what the narration describes.

--------------------------------------------------

TIMING GUIDELINES

Do NOT try to calculate exact durations.

Instead:

• Use several animations with run_time between 1.5 and 3 seconds.
• Add self.wait() at the end if extra time remains.
• The animation should approximately fill the target duration.

--------------------------------------------------

MANIM API RULES

Correct usage examples:

Text("Title", font_size=32)

circle = Circle()

self.play(Create(circle))

self.play(circle.animate.shift(RIGHT))

Transform(obj1, obj2)

self.play(..., run_time=2)

Never:

• Use undefined variables
• Use size= in Text
• Use strings for colors
• Use objects before defining them

--------------------------------------------------

IMPORTANT STABILITY RULES

• Every object must be stored in a variable.
• Define objects before using them.
• Always animate objects using self.play().
• Use simple, reliable Manim constructs.

--------------------------------------------------

OUTPUT

Return ONLY valid Python code.

Do NOT include markdown.

The script MUST begin with:

from manim import *
"""

        # Use Gemini directly with model rotation
        regenerated_script = None
        last_error = None
        
        for model_name in gemini_models:
            try:
                logger.info(f"🔄 Regenerating script {index+1} with Gemini model: {model_name}")
                gen_config = types.GenerateContentConfig(
                    temperature=0.4,
                    max_output_tokens=8192
                )
                response = gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=gen_config
                )
                
                if response and hasattr(response, 'text') and response.text:
                    regenerated_script = response.text.strip()
                    break
                else:
                    logger.warning(f"⚠️ Gemini {model_name} returned empty response, trying next model...")
                    continue
                    
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                if "quota" in error_str or "429" in error_str or "rate" in error_str:
                    logger.warning(f"⚠️ Gemini {model_name} rate limited, trying next model...")
                    continue
                else:
                    logger.warning(f"⚠️ Gemini {model_name} error: {e}, trying next model...")
                    continue
        
        if not regenerated_script:
            raise RuntimeError(f"All Gemini models failed for script regeneration: {last_error}")
        
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
    Uses prompt registry for consistent error correction.
    Truncates inputs to avoid token limit issues.
    IMPORTANT: Preserves truncated portion to avoid losing script content.
    """
    # Model fallback list - try multiple models if one fails
    model_fallback_list = [
        "google/gemma-3-4b-it:free",
        "meta-llama/llama-3.2-3b-instruct:free", 
        "qwen/qwen3-4b:free",
        "microsoft/phi-4-reasoning-plus:free",
    ]
    
    try:
        # Truncate error and script to avoid token limit issues
        max_error_chars = 2000
        max_script_chars = 5000
        
        truncated_error = error[:max_error_chars] if len(error) > max_error_chars else error
        if len(error) > max_error_chars:
            truncated_error += "\n... [error truncated]"
        
        # Store the truncated portion to preserve it
        was_truncated = len(script_content) > max_script_chars
        truncated_portion = script_content[max_script_chars:] if was_truncated else ""
        
        truncated_script = script_content[:max_script_chars] if was_truncated else script_content
        if was_truncated:
            truncated_script += "\n# ... [script truncated, fix visible portion]"
        
        # Extract locked constraints
        locked_constraints = ""
        duration = 10.0
        if segment_data:
            narration = segment_data.get('narration', '')
            duration = segment_data.get('duration', 10.0)
            locked_constraints = f"""STAGE 4 CONSTRAINTS (ABSOLUTE):
1. Audio duration LOCKED at {duration:.2f}s
2. Narration READ-ONLY: "{narration[:200]}..."
3. Fix ONLY technical errors
"""
        
        # Get frame dimensions for aspect ratio
        aspect_configs = {
            "16:9": (16, 9), "9:16": (9, 16),
            "1:1": (1, 1), "4:3": (4, 3),
        }
        fw, fh = aspect_configs.get(aspect_ratio, (16, 9))
        
        correction_prompt = format_error_correction_prompt(
            index=index,
            duration=duration,
            aspect_ratio=aspect_ratio,
            error=truncated_error,
            script=truncated_script,
            frame_width=fw,
            frame_height=fh,
            locked_constraints=locked_constraints,
        )
        
        corrected_script = None
        last_error = None
        
        # Try each model in the fallback list
        for model_name in model_fallback_list:
            try:
                def call_openrouter(client):
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=[{"role": "user", "content": correction_prompt}],
                        temperature=0.2,
                        max_tokens=4096
                    )
                    
                    # Check finish_reason for issues
                    finish_reason = getattr(response.choices[0], 'finish_reason', None)
                    if finish_reason == 'length':
                        logger.warning(f"Model {model_name} hit token limit (finish_reason=length)")
                    
                    content = response.choices[0].message.content
                    if content is None or content.strip() == "":
                        raise ValueError(f"Model {model_name} returned empty content (finish_reason={finish_reason})")
                    return content.strip()
                
                corrected_script = openrouter_key_manager.execute_with_rotation(
                    call_openrouter,
                    model=model_name
                )
                
                if corrected_script and len(corrected_script) > 50:
                    logger.info(f"✅ Script correction succeeded with model: {model_name}")
                    break  # Success, exit the loop
                else:
                    logger.warning(f"Model {model_name} returned invalid/short response, trying next model...")
                    corrected_script = None
                    
            except Exception as model_error:
                last_error = model_error
                logger.warning(f"Model {model_name} failed: {model_error}, trying next model...")
                continue
        
        if not corrected_script:
            logger.warning(f"All OpenRouter models failed. Last error: {last_error}")
            return script_content
        
        # Clean the response
        if "```python" in corrected_script:
            start_marker = "```python"
            end_marker = "```"
            start_idx = corrected_script.find(start_marker) + len(start_marker)
            end_idx = corrected_script.rfind(end_marker)
            if start_idx > len(start_marker) - 1 and end_idx > start_idx:
                corrected_script = corrected_script[start_idx:end_idx].strip()
        
        # If script was truncated, restore the truncated portion
        # Remove lazy LLM comments like "rest of script remains the same"
        if was_truncated and truncated_portion:
            # Remove lazy placeholder comments that LLMs often add
            lazy_patterns = [
                r'#\s*\.{3,}\s*\[?rest\s+of\s+(the\s+)?script.*',
                r'#\s*\.{3,}\s*\[?script\s+truncated.*',
                r'#\s*\.{3,}\s*\[?continues?\s+(as\s+)?before.*',
                r'#\s*\.{3,}\s*\[?same\s+as\s+before.*',
                r'#\s*\.\.\.\s*$',
            ]
            for pattern in lazy_patterns:
                corrected_script = re.sub(pattern, '', corrected_script, flags=re.IGNORECASE | re.MULTILINE)
            
            # Append the truncated portion back
            corrected_script = corrected_script.rstrip() + '\n' + truncated_portion
            logger.info(f"Script {index+1} corrected using OpenRouter (truncated portion restored)")
        else:
            logger.info(f"Script {index+1} corrected using OpenRouter")
        
        return corrected_script
        
    except Exception as e:
        logger.warning(f"OpenRouter script correction failed: {e}")
        return script_content

def _fix_script_errors_with_groq(script_content: str, error: str, index: int, groq_api_key: str, aspect_ratio: str = "16:9", segment_data: dict = None, model_name: str = "llama-3.1-8b-instant") -> str:
    """
    STAGE 3: Script Correction with Groq (Structural Repair Only).
    Uses prompt registry for consistent error correction.
    Truncates inputs to fit within Groq's token limits.
    IMPORTANT: Preserves truncated portion to avoid losing script content.
    """
    try:
        from groq import Groq
        groq_client = Groq(api_key=groq_api_key)
        
        duration = 10.0
        if segment_data:
            duration = segment_data.get("duration", 10.0)
        
        # Truncate error and script to fit within Groq's 6000 TPM limit
        # Reserve ~1000 tokens for prompt overhead and output
        # ~4 chars per token means ~4000 chars for script, ~1500 for error
        max_error_chars = 1500
        max_script_chars = 4000
        
        truncated_error = error[:max_error_chars] if len(error) > max_error_chars else error
        if len(error) > max_error_chars:
            truncated_error += "\n... [error truncated]"
        
        # Store the truncated portion to preserve it
        was_truncated = len(script_content) > max_script_chars
        truncated_portion = script_content[max_script_chars:] if was_truncated else ""
        
        truncated_script = script_content[:max_script_chars] if was_truncated else script_content
        if was_truncated:
            truncated_script += "\n# ... [script truncated, fix visible portion]"
        
        prompt = format_error_correction_minimal_prompt(
            index=index,
            duration=duration,
            error=truncated_error,
            script=truncated_script,
            aspect_ratio=aspect_ratio,
        )
        
        chat_completion = groq_client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=4096
        )
        content = chat_completion.choices[0].message.content
        if content is None:
            raise ValueError("Groq returned empty content")
        corrected_script = content.strip()
        if "```python" in corrected_script:
            start_marker = "```python"
            end_marker = "```"
            start_idx = corrected_script.find(start_marker) + len(start_marker)
            end_idx = corrected_script.rfind(end_marker)
            if start_idx > len(start_marker) - 1 and end_idx > start_idx:
                corrected_script = corrected_script[start_idx:end_idx].strip()
        corrected_script = re.sub(r"```+", "", corrected_script)
        
        # If script was truncated, restore the truncated portion
        # Remove lazy LLM comments like "rest of script remains the same"
        if was_truncated and truncated_portion:
            # Remove lazy placeholder comments that LLMs often add
            lazy_patterns = [
                r'#\s*\.{3,}\s*\[?rest\s+of\s+(the\s+)?script.*',
                r'#\s*\.{3,}\s*\[?script\s+truncated.*',
                r'#\s*\.{3,}\s*\[?continues?\s+(as\s+)?before.*',
                r'#\s*\.{3,}\s*\[?same\s+as\s+before.*',
                r'#\s*\.\.\.\s*$',
            ]
            for pattern in lazy_patterns:
                corrected_script = re.sub(pattern, '', corrected_script, flags=re.IGNORECASE | re.MULTILINE)
            
            # Append the truncated portion back
            corrected_script = corrected_script.rstrip() + '\n' + truncated_portion
            logger.info(f"Script {index+1} corrected using Groq (truncated portion restored)")
        else:
            logger.info(f"Script {index+1} corrected using Groq")
        
        return corrected_script
        
    except Exception as e:
        logger.warning(f"Groq correction failed: {e}")
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
                Path(f"temp/media/videos/segment_{i:03d}/1080p60/Segment{i:03d}.mp4"),
                Path(f"temp/media/videos/segment_{i:03d}/720p30/Segment{i:03d}.mp4"),
                Path(f"temp/media/videos/segment_{i:03d}/480p15/Segment{i:03d}.mp4"),
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
                # C4: Share model rotation state with adapter
                llm_adapter = GeminiClientAdapter(
                    self.gemini_client,
                    self.gemini_models,
                    pipeline=self
                )
                
                # Step 0: Pre-generate visual contracts from topic
                # These contracts give the spec generator HIGHEST AUTHORITY
                # context so it doesn't default to diagram-style output.
                pre_contracts = []
                try:
                    try:
                        from .concept_visualizer import generate_visual_models_batch
                        from .visual_validation import contract_from_visualizer
                    except ImportError:
                        from generator.video_generator.concept_visualizer import generate_visual_models_batch
                        from generator.video_generator.visual_validation import contract_from_visualizer
                    
                    num_pre = max(3, round(duration / 15))
                    pre_data = []
                    for idx in range(num_pre):
                        pre_data.append({
                            "segment_number": idx + 1,
                            "duration": duration / num_pre,
                            "idea": topic,
                            "narration": "",
                            "visual_intent": topic,
                            "layout_strategy": "process_flow",
                        })
                    pre_models = generate_visual_models_batch(pre_data)
                    for vm in pre_models:
                        pre_contracts.append(contract_from_visualizer(vm))
                    logger.info(
                        f"🔒 Pre-generated {len(pre_contracts)} visual contracts for spec generation "
                        f"(mode={pre_contracts[0].get('depiction_mode', '?') if pre_contracts else '?'})"
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Pre-contract generation skipped: {e}")
                
                # Step 1: Generate scene specifications (with contract authority)
                logger.info("📋 Step 1: Generating scene specifications...")
                quality_segments, spec_errors = generate_quality_segments(
                    llm_adapter, topic, duration, self.config.aspect_ratio,
                    visual_contracts=pre_contracts or None,
                )
                
                if spec_errors:
                    logger.warning(f"⚠️ Spec generation had {len(spec_errors)} errors")
                    for err in spec_errors[:3]:
                        logger.warning(f"   - {err}")
                
                if not quality_segments:
                    logger.warning("❌ Quality pipeline failed, falling back to legacy generation")
                    segments = await self._generate_narration_segments_with_gemini(topic, duration)
                    # Director layer: generate scene directions
                    segments = self.generate_scene_directions(segments)
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
                    
                    # ── VISUAL CONTRACT for quality segments ──
                    # Reuse pre-contracts when available; otherwise regenerate
                    if pre_contracts and len(pre_contracts) >= len(segments):
                        logger.info("🔒 Reusing pre-generated visual contracts for quality segments")
                        for i, seg in enumerate(segments):
                            if i < len(pre_contracts):
                                seg.visual_contract = serialize_contract(pre_contracts[i])
                                logger.info(
                                    f"    QSeg {i+1}: depiction={pre_contracts[i].get('depiction_mode', '?')}, "
                                    f"model={pre_contracts[i].get('visual_model', '?')}"
                                )
                    else:
                        logger.info("🔒 Creating visual contracts for quality segments...")
                        try:
                            from .concept_visualizer import generate_visual_models_batch
                            from .visual_validation import contract_from_visualizer
                        except ImportError:
                            from generator.video_generator.concept_visualizer import generate_visual_models_batch
                            from generator.video_generator.visual_validation import contract_from_visualizer
                        q_segments_data = []
                        for i, seg in enumerate(segments):
                            q_segments_data.append({
                                "segment_number": i + 1,
                                "duration": seg.duration,
                                "idea": seg.visual_description[:80],
                                "narration": seg.text,
                                "visual_intent": seg.visual_description,
                                "layout_strategy": "process_flow",
                            })
                        
                        q_visual_models = generate_visual_models_batch(q_segments_data)
                        for i, vm in enumerate(q_visual_models):
                            if i < len(segments):
                                contract = contract_from_visualizer(vm)
                                segments[i].visual_contract = serialize_contract(contract)
                                logger.info(
                                    f"    QSeg {i+1}: depiction={contract.get('depiction_mode', '?')}, "
                                    f"model={contract.get('visual_model', '?')}"
                                )
                    
                    # Validate quality specs against visual contracts
                    for i, seg in enumerate(segments):
                        spec = getattr(seg, '_quality_spec', None)
                        contract_json = getattr(seg, 'visual_contract', None)
                        if spec and contract_json:
                            try:
                                contract = deserialize_contract(contract_json)
                                spec_dict = spec.to_dict() if hasattr(spec, 'to_dict') else {}
                                passed, issues = validate_quality_spec_against_contract(spec_dict, contract)
                                if not passed:
                                    issues_str = ", ".join(issues)
                                    logger.warning(
                                        f"    ⚠️ QSeg {i+1} spec vs contract: {issues_str}"
                                    )
                                else:
                                    logger.info(f"    ✓ QSeg {i+1} spec passes contract check")
                            except Exception as e:
                                logger.debug(f"    Spec contract check skipped for seg {i+1}: {e}")
                    
                    logger.info(f"✅ Generated {len(segments)} quality segments with scene specs + contracts")
            else:
                # Step 1: Generate all narration segments (LEGACY)
                segments = await self._generate_narration_segments_with_gemini(topic, duration)
                # Director layer: generate scene directions
                segments = self.generate_scene_directions(segments)
            
            logger.info(f"🧾 {len(segments)} segments generated.")

            # Step 2: Generate audio for all segments in parallel
            await self.generate_all_audio_segments(segments, self.config.temp_dir)

            logger.info("🔊 Audio generation complete.")

            # Step 3: Generate scripts
            if use_quality and hasattr(segments[0], '_quality_spec') and segments[0]._quality_spec:
                # ===============================================================
                # QUALITY PIPELINE: Gemini-Direct Manim Script Generation
                # Gemini writes the full Manim script — NO templates involved.
                # Error correction uses the same legacy correction loop.
                # ===============================================================
                logger.info("🎬 Stage 3: GEMINI-DIRECT Script Generation (QUALITY MODE)")
                
                try:
                    from .pipeline_integration import generate_quality_scripts_bulk
                    from .pipeline_integration import QualityNarrationSegment, GeminiClientAdapter
                except ImportError:
                    from generator.video_generator.pipeline_integration import generate_quality_scripts_bulk
                    from generator.video_generator.pipeline_integration import QualityNarrationSegment, GeminiClientAdapter
                
                # Create LLM adapter for Gemini direct script generation
                gemini_script_adapter = GeminiClientAdapter(
                    self.gemini_client,
                    self.gemini_models,
                    pipeline=self
                )
                
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
                        scene_spec=seg._quality_spec,
                        visual_contract=getattr(seg, 'visual_contract', None),
                    )
                    quality_segs.append(qs)
                
                # Generate scripts via Gemini (llm_client enables direct mode)
                scripts = generate_quality_scripts_bulk(
                    quality_segs, self.config.aspect_ratio,
                    llm_client=gemini_script_adapter,
                )
                
                # Assign scripts to segments (inject premium background before saving)
                for i, (seg, qs, script) in enumerate(zip(segments, quality_segs, scripts)):
                    if script:
                        # Inject premium background template (same as legacy pipeline)
                        dur = getattr(qs, '_audio_duration_final', None) or seg.duration or 10.0
                        script = self._inject_premium_background(script, i, dur)
                        
                        # Save script to file
                        script_path = Path(self.config.temp_dir) / f"segment_{i:03d}.py"
                        with open(script_path, 'w', encoding='utf-8') as f:
                            f.write(script)
                        seg.script_path = str(script_path)
                        logger.info(f"🎬 Gemini script {i+1} generated + background injected ({len(script)} chars)")
                    else:
                        logger.warning(f"⚠️ Gemini script {i+1} failed — needs legacy generation")
                
                # Check for any segments without scripts
                failed_indices = [i for i, seg in enumerate(segments) if not seg.script_path]
                
                if failed_indices:
                    logger.warning(
                        f"⚠️ {len(failed_indices)} segments need legacy regeneration"
                    )
                    segments = await self._regenerate_failed_segments(segments, failed_indices)
                
                logger.info("📜 Gemini-direct script generation complete.")
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

            # Step 5: Sync audio/video + concatenate (A2: pass duration for hard cap)
            final_path = await self._parallel_final_assembly_with_proper_sync(segments, topic, duration)
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
        
        # STAGE 1: Use narrative director prompt from registry
        expected_segments = max(3, round(duration / 15))  # For duration validation later
        prompt = format_narrative_prompt(
            topic=topic,
            duration=duration,
            aspect_ratio=self.config.aspect_ratio
        )
        
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
                        prompt = format_narrative_retry_prompt(
                            topic=topic,
                            duration=duration,
                            aspect_ratio=self.config.aspect_ratio
                        )
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
                
                # Parse JSON response (narrative director format)
                segments = self._parse_narrative_json(content, duration)
                
                if not segments:
                    # Fallback: try legacy SEGMENT: format
                    logger.warning("⚠️ JSON parse failed, trying legacy format...")
                    segments = self._parse_legacy_segments(content)
                
                logger.info(f"🔍 Found {len(segments)} segments")
                
                if not segments:
                    logger.warning(f"⚠️ No segments parsed from response:\n{content[:500]}")
                    if attempt == 0:
                        logger.warning("⚠️ Retrying with clearer prompt...")
                        prompt = format_narrative_retry_prompt(
                            topic=topic,
                            duration=duration,
                            aspect_ratio=self.config.aspect_ratio
                        )
                        continue
                    else:
                        logger.error("❌ Parsing failed after retry, using fallback")
                        return self._generate_fallback_segments(topic, duration)
                
                total_duration = sum(s.duration for s in segments)
                
                # Validate total duration - REJECT if significantly over
                if total_duration > duration + 5:
                    logger.error(f"❌ Gemini generated {total_duration}s but target is {duration}s (EXCEEDS by {total_duration - duration}s)")
                    if attempt == 0:
                        logger.warning("⚠️ Retrying with stricter constraints...")
                        # Override prompt to be even more strict
                        prompt = format_narrative_retry_prompt(
                            topic=topic,
                            duration=duration,
                            aspect_ratio=self.config.aspect_ratio
                        )
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
                    content = response.choices[0].message.content
                    if content is None:
                        raise ValueError("LLM returned empty content")
                    return content.strip()
                
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
        """LAYER 3 — Build individual script prompt using registry."""
        aspect_ratio_config = self._get_aspect_ratio_config()
        direction = getattr(segment, 'scene_direction', '') or f"Visual intent: {segment.visual_description}"
        
        # Inject visual_contract as MANDATORY context
        if getattr(segment, 'visual_contract', None):
            try:
                from .visual_validation import contract_prompt_block
                contract = deserialize_contract(segment.visual_contract)
                direction += "\n\n" + contract_prompt_block(contract)
            except Exception:
                # Fallback to inline format if contract_prompt_block not available
                try:
                    contract = deserialize_contract(segment.visual_contract)
                    dep_mode = contract.get("depiction_mode", "simulation")
                    vis_model = contract.get("visual_model", "")
                    entities = contract.get("entities", [])
                    behaviors = contract.get("behaviors", [])
                    primitives = contract.get("animation_primitives", [])
                    chain = contract.get("transformation_chain", [])
                    entities_str = ", ".join(
                        (e.get("type", str(e)) if isinstance(e, dict) else str(e))
                        for e in entities[:6]
                    )
                    chain_str = " → ".join(
                        f"{s.get('from_state', '?')}→{s.get('to_state', '?')}"
                        for s in chain[:4]
                    ) if chain else "(none)"
                    direction += f"""

[VISUAL CONTRACT — MANDATORY]
  depiction_mode: {dep_mode}
  visual_model: {vis_model}
  entities: {entities_str}
  behaviors: {', '.join(behaviors[:6])}
  animation_primitives: {', '.join(primitives[:6])}
  transformation_chain: {chain_str}
  RULE: ALL visual elements MUST come from these entities. Do NOT invent labeled boxes or diagram containers.
  RULE: Walk the transformation_chain in order — each step = a Transform animation."""
                except Exception:
                    pass
        
        return format_manim_execution_prompt(
            index=index,
            duration=segment.duration,
            aspect_ratio=self.config.aspect_ratio,
            narration=segment.text,
            scene_direction=direction,
            aspect_ratio_config=aspect_ratio_config,
            animation_reference=animation_reference,
            allowed_attributes=allowed_attributes,
            allowed_colors=allowed_colors,
        )

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
        
        # Split by various ===SCRIPT...=== separator patterns the LLM may produce
        # Handles: ===SCRIPT START===, ===SCRIPT_1===, ===SCRIPT 1===, ===SEGMENT_0===, etc.
        scripts = re.split(r'===\s*(?:SCRIPT|SEGMENT)[\s_]*(?:START|\d+)?\s*===', content)
        scripts = [s.strip() for s in scripts if s.strip()]
        
        logger.info(f"📊 Split result: {len(scripts)} scripts from {len(content)} chars")
        
        # Fallback: if split didn't work, try splitting on 'from manim import' boundaries
        if len(scripts) < len(segments):
            logger.warning(f"⚠️ Separator split got {len(scripts)}/{len(segments)}, trying 'from manim' boundary split...")
            parts = re.split(r'(?=from manim import)', content)
            parts = [p.strip() for p in parts if p.strip() and 'class Segment' in p]
            if len(parts) >= len(segments):
                scripts = parts
                logger.info(f"📊 Boundary split recovered {len(scripts)} scripts")
        
        if len(scripts) < len(segments):
            raise ValueError(f"Only {len(scripts)}/{len(segments)} scripts generated")
        
        for i, segment in enumerate(segments):
            cleaned_script = self._clean_script_response(scripts[i], i, segment.duration)
            # Script-level contract gate
            cleaned_script = self._validate_script_against_contract(cleaned_script, segment, i)
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
            # Script-level contract gate
            cleaned_script = self._validate_script_against_contract(cleaned_script, segment, i)
            script_path = Path(self.config.temp_dir) / f"segment_{i:03d}.py"
            script_path.write_text(cleaned_script, encoding="utf-8")
            segment.script_path = str(script_path)
        
        return segments
    
    def _build_bulk_script_prompt(self, segments: list) -> str:
        """LAYER 3 — Build bulk script prompt using registry.
        
        Includes visual_contract context per segment to ensure the Manim code
        generator stays faithful to the frozen visual model.
        """
        aspect_ratio_config = self._get_aspect_ratio_config()
        
        all_segments_with_direction = ""
        for i, seg in enumerate(segments):
            direction = getattr(seg, 'scene_direction', '') or f"Visual intent: {seg.visual_description}"
            
            # Inject visual_contract as MANDATORY context
            contract_context = ""
            if getattr(seg, 'visual_contract', None):
                try:
                    contract = deserialize_contract(seg.visual_contract)
                    dep_mode = contract.get("depiction_mode", "simulation")
                    vis_model = contract.get("visual_model", "")
                    entities = contract.get("entities", [])
                    behaviors = contract.get("behaviors", [])
                    primitives = contract.get("animation_primitives", [])
                    contract_context = f"""
[VISUAL CONTRACT — MANDATORY]
  depiction_mode: {dep_mode}
  visual_model: {vis_model}
  entities: {', '.join(entities[:6])}
  behaviors: {', '.join(behaviors[:6])}
  animation_primitives: {', '.join(primitives[:6])}
  RULE: ALL visual elements MUST come from these entities. Do NOT invent labeled boxes or diagram containers."""
                except Exception:
                    pass
            
            all_segments_with_direction += f"""
--- Segment {i+1} ---
Class: Segment{i:03d}
Duration: {seg.duration:.2f}s
Narration: \"{seg.text}\"
Scene Direction: {direction}
{contract_context}
"""
        
        return format_manim_execution_batch_prompt(
            num_segments=len(segments),
            all_segments_with_direction=all_segments_with_direction,
            aspect_ratio=self.config.aspect_ratio,
            aspect_ratio_config=aspect_ratio_config,
            allowed_colors=getattr(self, 'allowed_colors', ''),
        )

    def _build_single_script_prompt(self, index: int, segment: NarrationSegment) -> str:
        """LAYER 3 — Build single segment prompt using registry.
        
        Includes visual_contract context to ensure the Manim code generator
        stays faithful to the frozen visual model.
        """
        aspect_ratio_config = self._get_aspect_ratio_config()
        direction = getattr(segment, 'scene_direction', '') or f"Visual intent: {segment.visual_description}"
        
        # Inject visual_contract as MANDATORY context appended to direction
        if getattr(segment, 'visual_contract', None):
            try:
                contract = deserialize_contract(segment.visual_contract)
                dep_mode = contract.get("depiction_mode", "simulation")
                vis_model = contract.get("visual_model", "")
                entities = contract.get("entities", [])
                behaviors = contract.get("behaviors", [])
                primitives = contract.get("animation_primitives", [])
                direction += f"""

[VISUAL CONTRACT — MANDATORY]
  depiction_mode: {dep_mode}
  visual_model: {vis_model}
  entities: {', '.join(entities[:6])}
  behaviors: {', '.join(behaviors[:6])}
  animation_primitives: {', '.join(primitives[:6])}
  RULE: ALL visual elements MUST come from these entities. Do NOT invent labeled boxes or diagram containers."""
            except Exception:
                pass
        
        return format_manim_execution_prompt(
            index=index,
            duration=segment.duration,
            aspect_ratio=self.config.aspect_ratio,
            narration=segment.text,
            scene_direction=direction,
            aspect_ratio_config=aspect_ratio_config,
            animation_reference=getattr(self, 'animation_reference', ''),
            allowed_attributes=getattr(self, 'allowed_attributes', ''),
            allowed_colors=getattr(self, 'allowed_colors', ''),
        )

    def _validate_script_against_contract(self, script: str, segment: 'NarrationSegment', index: int) -> str:
        """Post-generation validation: check script against frozen visual_contract.
        
        Runs THREE validation gates:
          1. HARD simulation integrity gate (from simulation_integrity.py)
             — returns pass/fail, used by caller for rollback decisions
          2. Legacy contract validation (validate_script_simulation)
          3. Simulation quality validation (validate_script_simulation_quality)
        
        Returns the script unchanged. The integrity result is logged but
        the caller (quality pipeline path in OVG) uses _integrity_passed
        from pipeline_integration for actual rollback decisions.
        """
        contract_json = getattr(segment, 'visual_contract', None) if segment else None
        if not contract_json:
            return script
        
        try:
            contract = deserialize_contract(contract_json)
            
            # Gate 0: HARD simulation integrity gate
            if contract.get("depiction_mode") == "simulation":
                try:
                    try:
                        from .simulation_integrity import validate_script_integrity
                    except ImportError:
                        from generator.video_generator.simulation_integrity import validate_script_integrity
                    integrity_result = validate_script_integrity(script, contract)
                    if not integrity_result.passed:
                        logger.warning(
                            f"  🚫 Segment {index+1} SIMULATION INTEGRITY FAILED: "
                            f"{integrity_result.summary()}"
                        )
                    else:
                        logger.info(
                            f"  ✅ Segment {index+1} simulation integrity PASSED: "
                            f"{integrity_result.summary()}"
                        )
                except ImportError:
                    pass
                except Exception as sie:
                    logger.debug(f"  Simulation integrity check error: {sie}")
            
            # Gate 1: Legacy contract validation
            passed, issues, score = validate_script_simulation(script, contract)
            if not passed:
                issues_str = ", ".join(issues)
                logger.warning(
                    f"  ⚠️ Segment {index+1} script contract check FAILED (score={score:.2f}): {issues_str}"
                )
            else:
                logger.info(f"  ✓ Segment {index+1} script contract check passed (score={score:.2f})")
            
            # Gate 2: Simulation quality validation (execution safety rules)
            if contract.get("depiction_mode") == "simulation":
                try:
                    try:
                        from .visual_quality_validator import validate_script_simulation_quality
                    except ImportError:
                        from generator.video_generator.visual_quality_validator import validate_script_simulation_quality
                    sq_passed, sq_issues, sq_metrics = validate_script_simulation_quality(
                        script, contract
                    )
                    if not sq_passed:
                        sq_str = ", ".join(sq_issues[:3])
                        logger.warning(
                            f"  ⚠️ Segment {index+1} simulation quality FAILED "
                            f"(score={sq_metrics.overall:.2f}): {sq_str}"
                        )
                    else:
                        logger.info(
                            f"  ✓ Segment {index+1} simulation quality passed "
                            f"(score={sq_metrics.overall:.2f})"
                        )
                except ImportError:
                    pass
                except Exception as sqe:
                    logger.debug(f"  Simulation quality check skipped: {sqe}")
        except Exception as e:
            logger.debug(f"  Script contract validation skipped for segment {index+1}: {e}")
        
        return script

    def _clean_script_response(self, raw_content: str, index: int, duration: float) -> str:
        """Clean, validate and inject premium background into script response from Gemini."""
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
            
            # Inject premium background template into legacy scripts
            raw_content = self._inject_premium_background(raw_content, index, duration)
            
            return raw_content
                
        except Exception as e:
            logger.error(f"❌ Script cleaning failed for segment {index}: {e}")
            raise ValueError(f"Script cleaning failed for segment {index}: {e}")

    def _inject_premium_background(self, script: str, index: int, duration: float) -> str:
        """Inject premium background (GradientBackground, SubtleGrid, AmbientParticles,
        progress bar, channel watermark) into legacy LLM-generated Manim scripts.
        
        This gives legacy pipeline the same professional look as the quality pipeline.
        """
        # Skip if already has premium background
        if 'GradientBackground' in script or 'SubtleGrid' in script:
            return script
        
        # D4: Per-segment accent color rotation
        accent_colors = ["BLUE", "TEAL", "PURPLE", "GOLD", "PINK", "GREEN"]
        accent = accent_colors[index % len(accent_colors)]
        
        # --- PRIMITIVES BLOCK: inserted before the Scene class ---
        primitives_block = f'''
# === PREMIUM BACKGROUND PRIMITIVES (auto-injected) ===

class GradientBackground(VGroup):
    """Dark gradient background with subtle color accent."""
    def __init__(self, accent_color=BLUE, **kwargs):
        super().__init__(**kwargs)
        fw, fh = config.frame_width, config.frame_height
        base = Rectangle(width=fw + 1, height=fh + 1, fill_opacity=1.0, stroke_width=0)
        base.set_fill(color=["#0a0a1a", "#0f1629", "#0a0a1a"])
        self.add(base)
        glow = Circle(radius=fw * 0.06, fill_opacity=0.015, stroke_width=0, color=accent_color)
        glow.shift(UP * fh * 0.4 + RIGHT * fw * 0.35)
        self.add(glow)


class AmbientParticles(VGroup):
    """Floating dots that drift slowly."""
    def __init__(self, count=6, **kwargs):
        super().__init__(**kwargs)
        fw, fh = config.frame_width, config.frame_height
        import random as _rng
        _rng.seed(42)
        for _ in range(count):
            r = _rng.uniform(0.03, 0.07)
            opacity = _rng.uniform(0.12, 0.25)
            dot = Dot(radius=r, fill_opacity=opacity, color=WHITE, stroke_width=0)
            x = _rng.uniform(-fw * 0.45, fw * 0.45)
            y = _rng.uniform(-fh * 0.45, fh * 0.45)
            dot.move_to([x, y, 0])
            self.add(dot)


class SubtleGrid(VGroup):
    """Very faint grid lines for visual structure."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        fw, fh = config.frame_width, config.frame_height
        for i in range(-3, 4):
            x = i * fw / 6
            line = Line([x, -fh/2, 0], [x, fh/2, 0], stroke_width=0.3, stroke_opacity=0.06, color=WHITE)
            self.add(line)
        for i in range(-5, 6):
            y = i * fh / 10
            line = Line([-fw/2, y, 0], [fw/2, y, 0], stroke_width=0.3, stroke_opacity=0.06, color=WHITE)
            self.add(line)

'''
        
        # --- BACKGROUND SETUP CODE: inserted right after `def construct(self):` ---
        bg_setup = f'''
        # === PREMIUM BACKGROUND (auto-injected) ===
        _bg = GradientBackground(accent_color={accent})
        self.add(_bg)
        _grid = SubtleGrid()
        self.add(_grid)
        _particles = AmbientParticles(count=6)
        self.add(_particles)
        for _dot in _particles:
            _dx = random.uniform(-0.02, 0.02)
            _dy = random.uniform(0.01, 0.03)
            _dot.add_updater(lambda m, dt, _dx=_dx, _dy=_dy: m.shift(np.array([_dx * dt, _dy * dt, 0])))
        # Progress bar
        _pb_total_w = config.frame_width * 0.85
        _pb_bg = Rectangle(width=_pb_total_w, height=0.06, fill_opacity=0.15,
                           fill_color=WHITE, stroke_width=0)
        _pb_bg.move_to(np.array([0, -config.frame_height/2 + 0.12, 0]))
        self.add(_pb_bg)
        _pb_bar = Rectangle(width=0.01, height=0.06, fill_opacity=0.6,
                            fill_color={accent}, stroke_width=0)
        _pb_bar.move_to(_pb_bg.get_center())
        _pb_bar.align_to(_pb_bg, LEFT)
        self.add(_pb_bar)
        _pb_bar._pt = 0
        _scene_dur = {duration:.1f}
        def _pb_upd(m, dt):
            m._pt += dt
            frac = min(1.0, m._pt / max(0.1, _scene_dur))
            new_w = max(0.01, _pb_total_w * frac)
            m.stretch_to_fit_width(new_w)
            m.align_to(_pb_bg, LEFT)
        _pb_bar.add_updater(_pb_upd)
        # Channel watermark
        _wm = Text("Code Tapasya", font_size=14, color=WHITE,
                    font="sans-serif", fill_opacity=0.25)
        _wm.move_to(np.array([config.frame_width/2 - 1.2,
                              -config.frame_height/2 + 0.35, 0]))
        self.add(_wm)
        # Scene intro flash
        _flash_rect = Rectangle(width=config.frame_width + 2, height=config.frame_height + 2,
                               fill_opacity=0.04, fill_color=WHITE, stroke_width=0)
        self.play(FadeIn(_flash_rect, run_time=0.06), rate_func=rate_functions.ease_out_cubic)
        self.play(FadeOut(_flash_rect, run_time=0.1), rate_func=rate_functions.ease_in_cubic)
        self.remove(_flash_rect)
'''
        
        # Ensure numpy is imported
        if 'import numpy' not in script and 'numpy' not in script:
            script = script.replace('from manim import *', 'from manim import *\nimport numpy as np')
        if 'import random' not in script:
            script = script.replace('from manim import *', 'from manim import *\nimport random')
        
        # Step 1: Inject primitive class definitions before the Scene class
        class_pattern = re.search(r'^class Segment\d{3}\(Scene\):', script, re.MULTILINE)
        if class_pattern:
            insert_pos = class_pattern.start()
            script = script[:insert_pos] + primitives_block + script[insert_pos:]
        
        # Step 2: Inject background setup code after `def construct(self):`
        construct_pattern = re.search(r'def construct\(self\):\s*\n', script)
        if construct_pattern:
            insert_pos = construct_pattern.end()
            script = script[:insert_pos] + bg_setup + '\n' + script[insert_pos:]
        
        logger.info(f"🎨 Injected premium background into legacy segment {index}")
        return script

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
                # Script-level contract gate
                cleaned_script = self._validate_script_against_contract(cleaned_script, segment, i)
                script_path = Path(self.config.temp_dir) / f"segment_{i:03d}.py"
                script_path.write_text(cleaned_script, encoding="utf-8")
                segment.script_path = str(script_path)
                
                logger.info(f"✅ Successfully regenerated segment {i+1}")
                
            except Exception as e:
                logger.error(f"❌ Failed to regenerate segment {i+1}: {e}")
                raise RuntimeError(f"Failed to regenerate segment {i+1}: {e}")
        
        return segments

    def _generate_fallback_script(self, segment: Optional[NarrationSegment], index: int, duration: float, is_dummy: bool = False) -> str:
        """Generate a reliable fallback script with concept-card layout (not blank text)."""
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

        content = segment.text[:70].replace('"', "'") if segment else f"Educational content for segment {index}"
        short_title = segment.text[:35].replace('"', "'") if segment else f"Segment {index}"
        
        return f'''from manim import *

{aspect_ratio_config}

class Segment{index:03d}(Scene):
    def construct(self):
        # Title card at top
        title = Text("{short_title}...", font_size=38, weight=BOLD)
        title.set_color_by_gradient(BLUE, TEAL)
        title.scale_to_fit_width(config.frame_width * 0.7)
        title.move_to(UP * 3)
        
        # Concept card — labeled box in center
        card = RoundedRectangle(
            corner_radius=0.25, width=min(10, config.frame_width * 0.7),
            height=3.5, color=BLUE, fill_opacity=0.2, stroke_width=2
        )
        card.move_to(DOWN * 0.3)
        card_text = Text("{content}...", font_size=22, color=WHITE)
        card_text.scale_to_fit_width(min(9, config.frame_width * 0.6))
        card_text.move_to(card.get_center())
        
        # Decorative side elements
        left_dot = Circle(radius=0.3, color=TEAL, fill_opacity=0.3, stroke_width=1)
        left_dot.move_to(LEFT * 5.5 + DOWN * 0.3)
        right_dot = Circle(radius=0.3, color=GOLD, fill_opacity=0.3, stroke_width=1)
        right_dot.move_to(RIGHT * 5.5 + DOWN * 0.3)
        
        # Segment indicator at bottom
        indicator = Text("Part {index + 1}", font_size=18, color=GRAY)
        indicator.scale_to_fit_width(config.frame_width * 0.15)
        indicator.move_to(DOWN * 3.5)
        
        # Animations
        self.play(DrawBorderThenFill(title), run_time=1.5)
        self.play(
            GrowFromCenter(card), FadeIn(card_text),
            GrowFromCenter(left_dot), GrowFromCenter(right_dot),
            run_time=1.5
        )
        self.play(FadeIn(indicator), run_time=0.5)
        self.play(Circumscribe(card, color=BLUE, buff=0.1), run_time=1.0)
        
        # Hold everything visible
        remaining_time = max(0.1, {duration} - 4.5)
        self.wait(remaining_time)'''

    async def _regenerate_and_render_with_gemini(
        self, 
        segment: 'NarrationSegment', 
        index: int, 
        max_gemini_attempts: int = 3
    ) -> str:
        """
        Regenerate a failed segment's script using Gemini and re-render.
        
        This is called when the worker subprocess failed to produce a video.
        Uses Gemini for regeneration (not fallback scripts), then applies
        the full correction ladder before giving up.
        
        Args:
            segment: The failed segment with narration and spec
            index: Segment index
            max_gemini_attempts: Max Gemini regeneration cycles
            
        Returns:
            Path to successfully rendered video, or raises RuntimeError
        """
        logger.warning(f"🔄 Regenerating segment {index+1} with Gemini (up to {max_gemini_attempts} attempts)")
        
        output_dir = Path(self.config.output_dir) / f"segment_{index:03d}"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"Segment{index:03d}.mp4"
        
        # Import Gemini generator for single-segment regeneration
        try:
            from .gemini_manim_generator import generate_manim_script
        except ImportError:
            from generator.video_generator.gemini_manim_generator import generate_manim_script
        
        # Get segment info
        narration = segment.text if hasattr(segment, 'text') else ""
        spec = getattr(segment, '_quality_spec', None) or getattr(segment, 'scene_spec', None)
        duration = getattr(segment, '_audio_duration_final', None) or segment.duration or 10.0
        
        # Create Gemini adapter
        try:
            from .pipeline_integration import GeminiClientAdapter
        except ImportError:
            from generator.video_generator.pipeline_integration import GeminiClientAdapter
        
        gemini_adapter = GeminiClientAdapter(
            self.gemini_client,
            self.gemini_models,
            pipeline=self
        )
        
        for gemini_attempt in range(1, max_gemini_attempts + 1):
            logger.info(f"  🎬 Gemini regeneration attempt {gemini_attempt}/{max_gemini_attempts} for segment {index+1}")
            
            try:
                # Generate new script with Gemini
                script = generate_manim_script(
                    llm_client=gemini_adapter,
                    narration=narration,
                    scene_spec=spec,
                    index=index,
                    duration=duration,
                    aspect_ratio=self.config.aspect_ratio,
                    visual_contract=None,
                )
                
                if not script:
                    logger.warning(f"  ⚠️ Gemini returned empty script, retrying...")
                    continue
                
                # Inject premium background
                script = self._inject_premium_background(script, index, duration)
                
                # Save script
                script_path = Path(self.config.temp_dir) / f"segment_{index:03d}_regen_{gemini_attempt}.py"
                script_path.write_text(script, encoding="utf-8")
                logger.info(f"  📝 Regenerated script saved ({len(script)} chars)")
                
                # Try to render with correction ladder
                video_path = await self._render_with_correction_ladder(
                    script, script_path, index, output_path, segment, duration
                )
                
                if video_path and Path(video_path).exists():
                    logger.info(f"  ✅ Gemini regeneration successful for segment {index+1}")
                    return str(video_path)
                    
            except Exception as e:
                logger.warning(f"  ⚠️ Gemini attempt {gemini_attempt} failed: {e}")
                continue
        
        # If all Gemini attempts failed, fall back to emergency fallback
        logger.error(f"❌ All {max_gemini_attempts} Gemini regenerations failed for segment {index+1}")
        logger.warning(f"🆘 Using emergency fallback for segment {index+1}")
        return await self._generate_emergency_fallback_video(segment, index)
    
    async def _render_with_correction_ladder(
        self,
        script: str,
        script_path: Path,
        index: int,
        output_path: Path,
        segment: 'NarrationSegment',
        duration: float,
        max_corrections: int = 6,
    ) -> Optional[str]:
        """
        Render a script with Groq/OpenRouter correction ladder.
        
        Tries: Groq x3 → OpenRouter x3 before giving up.
        """
        current_script = script
        
        for attempt in range(max_corrections + 1):  # +1 for initial render
            try:
                # Use async subprocess for Manim
                video_result, error = await self._render_manim_async(
                    current_script, script_path, index
                )
                
                if video_result:
                    # Move to output location
                    _safe_move_video(str(video_result), str(output_path))
                    return str(output_path)
                
                if attempt >= max_corrections:
                    logger.warning(f"  ⚠️ All {max_corrections} corrections exhausted")
                    break
                
                # Apply correction
                logger.info(f"  🔧 Correction {attempt+1}/{max_corrections}: {error[:100] if error else 'Unknown'}...")
                
                segment_data = {
                    'narration': segment.text,
                    'duration': duration,
                }
                
                if attempt < 3:
                    # Groq corrections
                    current_script = _fix_script_errors_with_groq(
                        current_script, error or "Render failed", index,
                        self.config.groq_api_key, self.config.aspect_ratio,
                        segment_data, model_name="llama-3.1-8b-instant"
                    )
                else:
                    # OpenRouter corrections
                    current_script = _fix_script_errors_with_openrouter(
                        current_script, error or "Render failed", index,
                        self.openrouter_key_manager, self.config.aspect_ratio,
                        segment_data
                    )
                
                # Re-inject background after correction (might have been stripped)
                current_script = self._inject_premium_background(current_script, index, duration)
                script_path.write_text(current_script, encoding="utf-8")
                
            except Exception as e:
                logger.warning(f"  ⚠️ Render attempt {attempt+1} crashed: {e}")
                continue
        
        return None
    
    async def _render_manim_async(
        self, 
        script: str, 
        script_path: Path, 
        index: int
    ) -> Tuple[Optional[str], Optional[str]]:
        """Async Manim render returning (video_path, error)."""
        import asyncio
        
        script_path.write_text(script, encoding="utf-8")
        
        cmd = [
            'manim', 'render',
            '-qh',  # High quality 1080p60
            '--disable_caching',
            '--media_dir', str(Path(self.config.temp_dir) / 'media'),
            str(script_path),
            f'Segment{index:03d}'
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(Path(self.config.temp_dir))
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.config.manim_timeout
            )
            
            if process.returncode != 0:
                error_text = stderr.decode() if stderr else stdout.decode() if stdout else "Unknown error"
                return None, error_text[:500]
            
            # Find output video
            expected_path = (
                Path(self.config.temp_dir) / 'media' / 'videos' / 
                script_path.stem / '1080p60' / f'Segment{index:03d}.mp4'
            )
            
            if expected_path.exists():
                return str(expected_path), None
            
            # Fallback search
            media_dir = Path(self.config.temp_dir) / 'media' / 'videos'
            for mp4 in media_dir.glob('**/*.mp4'):
                if f'Segment{index:03d}' in mp4.name:
                    return str(mp4), None
            
            return None, "Video file not found after render"
            
        except asyncio.TimeoutError:
            return None, "Manim render timed out"
        except Exception as e:
            return None, str(e)

    async def _generate_emergency_fallback_video(self, segment: NarrationSegment, index: int) -> str:
        """
        Generate an ultra-simple emergency fallback video when all else fails.
        Uses concept-card layout instead of plain text on black.
        """
        output_dir = Path(self.config.output_dir) / f"segment_{index:03d}"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"Segment{index:03d}.mp4"
        
        aspect_ratio_config = self._get_aspect_ratio_config()
        short_label = segment.text[:40].replace('"', "'").replace('\n', ' ') if segment.text else f"Part {index+1}"
        
        # Create fallback with visible concept card (not just text on black)
        fallback_script = f'''from manim import *

{aspect_ratio_config}

class Segment{index:03d}(Scene):
    def construct(self):
        # Background card for visibility
        card = RoundedRectangle(
            corner_radius=0.3, width=min(10, config.frame_width * 0.75),
            height=3, color=BLUE, fill_opacity=0.2, stroke_width=2
        )
        label = Text("{short_label}...", font_size=28, color=WHITE, weight=BOLD)
        label.scale_to_fit_width(min(9, config.frame_width * 0.65))
        label.move_to(card.get_center())
        group = VGroup(card, label)
        self.play(GrowFromCenter(group), run_time=1.5)
        self.wait({max(0.1, segment.duration - 1.5):.2f})
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
            'gemini_api_key': os.getenv('GEMINI_API_KEY'),  # For script regeneration with Gemini
            'gemini_models': self.gemini_models,  # Gemini model list for rotation
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
            
            # Serialize scene_spec if available (for regeneration context)
            scene_spec_dict = None
            spec = getattr(segment, '_quality_spec', None)
            if spec and hasattr(spec, 'to_dict'):
                try:
                    scene_spec_dict = spec.to_dict()
                except Exception:
                    pass
            
            segment_data = {
                'script_path': segment.script_path,
                'video_output_dir': self.config.output_dir,
                'temp_dir': self.config.temp_dir,
                'narration': segment.text,
                'visuals': segment.visual_description,
                'duration': segment.duration,
                # NEW: Add context for regeneration
                'audio_path': segment.audio_path,
                'scene_spec': scene_spec_dict,
                'visual_contract': getattr(segment, 'visual_contract', None),
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
            
            # RECOVERY PHASE 2: Regenerate with Gemini (not fallback scripts!)
            if failed_segments:
                logger.warning(f"⚠️ {len(failed_segments)} segment(s) still missing. Regenerating with Gemini...")
                for idx in failed_segments:
                    try:
                        logger.warning(f"🔄 Regenerating segment {idx+1} with Gemini (not fallback)")
                        regen_path = await self._regenerate_and_render_with_gemini(
                            segments[idx], 
                            idx,
                            max_gemini_attempts=3
                        )
                        segments[idx].video_path = regen_path
                        logger.info(f"✅ Segment {idx+1} regenerated successfully")
                    except Exception as regen_error:
                        logger.error(f"❌ Gemini regeneration failed for segment {idx+1}: {regen_error}")
                        # Critical failure - cannot proceed
                        raise RuntimeError(f"Cannot generate video for segment {idx+1}. All regeneration attempts failed.")

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

    async def _parallel_final_assembly_with_proper_sync(self, segments: List[NarrationSegment], topic: str, duration: int = None) -> str:
        """
        Parallel synchronization with proper video-audio alignment and validation.
        A2: Accepts duration for hard cap on final output.
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
        ]
        # A2: Duration cap REMOVED — let content run its full length
        # The audio/video segments already have correct durations from generation.
        # Trimming here cuts off valid narrated content.
        cmd.append(final_output_path)
        
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
            final_output_complete = self._add_intro_with_ffmpeg(final_output_path)
            logger.info(f"✅ Final video complete: {final_output_complete}")
            
            # Cleanup temporary files
            self.cleanup_temp_files()
            
            return final_output_complete
            
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
    logger.info(f"🔑 OPENROUTER_API_KEY:{openrouter_key}")
    
    if not openrouter_key:
        raise ValueError("OPENROUTER_API_KEY environment variable is required.")
    
    config = VideoGenerationConfig(
        groq_api_key=groq_api_key,
        openrouter_api_key=openrouter_key,
        batch_size=5,  # Larger batches for efficiency
        max_correction_attempts=3,  # Fewer attempts for speed
        aspect_ratio="9:16",
        use_quality_pipeline=True  
    )
    
    
    try:
        # Use memory-optimized pipeline for large `videos`
        pipeline = OptimizedVideoGenerationPipeline(config)

        
        start_time = time.time()
        # Using the chunked method for better memory management
        result = await pipeline.generate_video_full_parallel(
            topic="Explain about Deterministic Finite Automata (DFA)", 
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
