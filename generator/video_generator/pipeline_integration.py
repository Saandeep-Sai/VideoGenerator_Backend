"""
Quality Pipeline Integration Module
====================================

This module provides functions to integrate the new spec-based quality pipeline
into the existing OptimizedVideoGenerationPipeline.

Usage:
    from generator.video_generator.pipeline_integration import (
        generate_quality_segments,
        generate_quality_scripts_bulk
    )
    
    # In OptimizedVideoGenerationPipeline, replace:
    # - _generate_narration_segments_with_gemini -> generate_quality_segments
    # - _generate_scripts_in_bulk -> generate_quality_scripts_bulk
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from .scene_specification import (
    SceneSpecification, Concept, VisualMetaphor, Transformation,
    Constraints, Narration, Timing, VisualElement, TransformationStep,
    SemanticBeat, MetaphorType, ElementType, TransformAction, Position, TextRole
)
from .scene_spec_generator import SceneSpecGenerator, GenerationConfig, SpecificationValidator
from .manim_code_generator import ManimCodeGenerator, GeneratorConfig, CodeValidator
from .visual_director import VisualDirector, VisualTimeline
from .quality_scorer import QualityScorer, VideoScore, PipelineHealthCheck

logger = logging.getLogger(__name__)


# =============================================================================
# LLM CLIENT ADAPTER
# =============================================================================

class GeminiClientAdapter:
    """
    Adapts the Gemini client from OptimizedVideoGenerationPipeline to work
    with the SceneSpecGenerator's expected interface.
    
    C4: If `pipeline` is provided, rotation state is shared bidirectionally —
    any model rotation here is visible to the parent pipeline and vice-versa.
    """
    
    def __init__(self, gemini_client, gemini_models: List[str], current_model_index: int = 0, pipeline=None):
        self.gemini_client = gemini_client
        self.gemini_models = gemini_models
        self._pipeline = pipeline
        self._local_model_index = current_model_index
    
    @property
    def current_model_index(self):
        if self._pipeline is not None:
            return self._pipeline.current_gemini_model_index
        return self._local_model_index
    
    @current_model_index.setter
    def current_model_index(self, value):
        if self._pipeline is not None:
            self._pipeline.current_gemini_model_index = value
        else:
            self._local_model_index = value
    
    def generate(self, prompt: str, temperature: float = 0.7) -> str:
        """Generate response using Gemini client with JSON mode and automatic model rotation on 503."""
        from google.genai import types
        import time
        
        # Try each model in rotation before giving up
        attempts = len(self.gemini_models)
        last_error = None
        
        for attempt in range(attempts):
            model_name = self.gemini_models[self.current_model_index]
            
            try:
                # Try to use JSON response format for better parsing
                try:
                    config = types.GenerateContentConfig(
                        temperature=temperature,
                        max_output_tokens=8192,
                        response_mime_type="application/json"  # Request JSON output
                    )
                except (TypeError, AttributeError):
                    logger.warning("⚠️ JSON mode not available, using standard generation")
                    config = types.GenerateContentConfig(
                        temperature=temperature,
                        max_output_tokens=8192
                    )
                
                response = self.gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config
                )
                
                if hasattr(response, 'text') and response.text:
                    logger.debug(f"✅ Gemini response length: {len(response.text)} chars")
                    return response.text
                
                # Handle cases where text is None but candidates exist
                if hasattr(response, 'candidates') and response.candidates:
                    for candidate in response.candidates:
                        if hasattr(candidate, 'content') and candidate.content:
                            if hasattr(candidate.content, 'parts') and candidate.content.parts:
                                for part in candidate.content.parts:
                                    if hasattr(part, 'text') and part.text:
                                        logger.debug(f"✅ Extracted from candidate: {len(part.text)} chars")
                                        return part.text
                
                logger.error(f"❌ Could not extract text from Gemini response: {type(response)}")
                return str(response)
                
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                
                # Check if this is a retryable error (503, quota, rate limit, etc.)
                is_retryable = (
                    "503" in error_str or
                    "unavailable" in error_str or
                    "quota" in error_str or
                    "429" in error_str or
                    "overloaded" in error_str or
                    "resource" in error_str or
                    "rate limit" in error_str or
                    "capacity" in error_str or
                    "high demand" in error_str
                )
                
                if is_retryable and attempt < attempts - 1:
                    old_model = model_name
                    self.current_model_index = (self.current_model_index + 1) % len(self.gemini_models)
                    new_model = self.gemini_models[self.current_model_index]
                    logger.warning(f"⚠️ {old_model} failed ({str(e)[:100]}), cycling to {new_model}")
                    time.sleep(3)  # Brief pause before retrying
                    continue
                else:
                    raise
        
        raise RuntimeError(f"All {attempts} Gemini models failed. Last error: {last_error}")


class OpenRouterAdapter:
    """
    Adapts OpenRouter key manager to work with SceneSpecGenerator.
    """
    
    def __init__(self, openrouter_key_manager, model: str = "anthropic/claude-3-sonnet"):
        self.key_manager = openrouter_key_manager
        self.model = model
    
    def generate(self, prompt: str, temperature: float = 0.7) -> str:
        """Generate response using OpenRouter."""
        def call_api(client):
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert educational animation architect."},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=8192
            )
            return response.choices[0].message.content
        
        return self.key_manager.execute_with_rotation(call_api, model=self.model)


# =============================================================================
# INTEGRATION FUNCTIONS
# =============================================================================

@dataclass
class QualityNarrationSegment:
    """
    Enhanced NarrationSegment with scene specification.
    Compatible with existing NarrationSegment but adds spec field.
    """
    start_time: float
    end_time: float
    duration: float
    text: str
    visual_description: str
    audio_path: Optional[str] = None
    script_path: Optional[str] = None
    video_path: Optional[str] = None
    _audio_duration_final: Optional[float] = None
    # New field for quality pipeline
    scene_spec: Optional[SceneSpecification] = None


def generate_quality_segments(
    llm_client,
    topic: str,
    duration: int,
    aspect_ratio: str = "9:16",
    max_retries: int = 2
) -> Tuple[List[QualityNarrationSegment], List[str]]:
    """
    Generate narration segments using the new spec-based approach.
    
    This function replaces _generate_narration_segments_with_gemini.
    
    Args:
        llm_client: Adapted LLM client (GeminiClientAdapter or OpenRouterAdapter)
        topic: The educational topic
        duration: Total video duration in seconds
        aspect_ratio: Video aspect ratio
        max_retries: Number of retry attempts on failure
        
    Returns:
        Tuple of (list of QualityNarrationSegment, list of errors)
    """
    # Configure spec generator
    # A3: Align with legacy formula (~15s per segment)
    config = GenerationConfig(
        max_scenes=max(3, round(duration / 15)),
        target_scene_duration=15.0,
        aspect_ratio=aspect_ratio
    )
    
    spec_generator = SceneSpecGenerator(llm_client, config)
    validator = SpecificationValidator(strict_mode=False)
    
    all_errors = []
    
    # Retry loop for robustness
    for attempt in range(max_retries + 1):
        try:
            # Generate specifications
            logger.info(f"🎯 Quality Pipeline: Generating scene specifications for '{topic}' (attempt {attempt + 1}/{max_retries + 1})")
            specs, gen_errors = spec_generator.generate_specifications(topic, duration)
            
            if gen_errors:
                all_errors.extend(gen_errors)
                logger.warning(f"⚠️ Generation had {len(gen_errors)} errors: {gen_errors[:2]}")
            
            if specs:
                logger.info(f"✅ Successfully generated {len(specs)} specifications")
                break  # Success!
            else:
                logger.warning(f"⚠️ No specs generated on attempt {attempt + 1}")
                if attempt < max_retries:
                    import time
                    time.sleep(1)  # Brief pause before retry
                    
        except Exception as e:
            logger.error(f"❌ Attempt {attempt + 1} failed with exception: {e}")
            all_errors.append(f"Attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries:
                import time
                time.sleep(1)
    
    if not specs:
        logger.error("❌ No specifications generated after all retries")
        return [], all_errors
    
    # Validate specifications
    valid_specs, val_errors = validator.validate_all(specs)
    all_errors = gen_errors + val_errors
    
    if not valid_specs:
        logger.error("❌ No valid specifications after validation")
        return [], all_errors
    
    # Convert to QualityNarrationSegment format
    segments = []
    current_time = 0.0
    
    for spec in valid_specs:
        seg_duration = spec.timing.cognitive_duration_estimate_seconds
        
        segment = QualityNarrationSegment(
            start_time=current_time,
            end_time=current_time + seg_duration,
            duration=seg_duration,
            text=spec.narration.text,
            visual_description=_spec_to_visual_description(spec),
            scene_spec=spec
        )
        segments.append(segment)
        current_time += seg_duration
    
    logger.info(f"✅ Generated {len(segments)} quality segments with specs")
    
    # Log quality scores
    for i, spec in enumerate(valid_specs):
        score = validator.get_quality_score(spec)
        logger.info(f"   Scene {i+1}: Quality Score = {score:.2f}")
    
    return segments, all_errors


def _spec_to_visual_description(spec: SceneSpecification) -> str:
    """
    Convert a scene specification to a visual description string.
    This provides backwards compatibility with existing code expecting
    freeform visual descriptions.
    """
    elements = spec.visual_metaphor.visual_elements
    element_descs = []
    
    for elem in elements:
        desc = f"{elem.element_type.value}"
        if elem.label:
            desc += f" labeled '{elem.label}'"
        if elem.color:
            desc += f" in {elem.color}"
        if elem.position:
            desc += f" at {elem.position.value}"
        element_descs.append(desc)
    
    # Build transformation description
    transform_desc = []
    for step in spec.transformation.sequence[:4]:  # First 4 steps
        transform_desc.append(f"{step.action.value} {step.target}")
    
    visual = f"Metaphor: {spec.visual_metaphor.concrete_representation}. "
    visual += f"Elements: {', '.join(element_descs)}. "
    visual += f"Animation: {', '.join(transform_desc)}."
    
    return visual


def generate_quality_scripts_bulk(
    segments: List[QualityNarrationSegment],
    aspect_ratio: str = "9:16"
) -> List[str]:
    """
    Generate Manim scripts from segments using the Visual Director + template approach.
    
    Pipeline: SceneSpec + AudioDuration → VisualDirector → VisualTimeline → ManimCodeGenerator
    
    Args:
        segments: List of QualityNarrationSegment with scene specs
        aspect_ratio: Video aspect ratio
        
    Returns:
        List of generated Manim script strings
    """
    code_generator = ManimCodeGenerator(
        GeneratorConfig(aspect_ratio=aspect_ratio)
    )
    code_validator = CodeValidator()
    visual_director = VisualDirector()
    
    scripts = []
    
    for i, segment in enumerate(segments):
        if segment.scene_spec:
            logger.info(f"🎨 Generating script from spec for segment {i+1}")
            
            # Update spec timing with actual audio duration if available
            if segment._audio_duration_final:
                segment.scene_spec.timing.audio_duration_seconds = segment._audio_duration_final
            
            audio_dur = (
                segment._audio_duration_final
                or segment.scene_spec.timing.audio_duration_seconds
                or segment.duration
                or 10.0
            )
            
            # Determine scene type from spec
            scene_type = getattr(segment.scene_spec, 'scene_type', 'CONTENT')
            if not scene_type:
                scene_type = "CONTENT"
            
            # === VISUAL DIRECTOR: Plan the timeline ===
            try:
                timeline = visual_director.plan_timeline(
                    spec=segment.scene_spec,
                    audio_duration=audio_dur,
                    scene_type=scene_type
                )
                logger.info(
                    f"📐 Visual Director: {timeline.event_count} events, "
                    f"density={timeline.density:.2f}/s for segment {i+1}"
                )
            except Exception as e:
                logger.warning(f"⚠️ VisualDirector failed for segment {i+1}: {e}. Using legacy path.")
                timeline = None
            
            # === MANIM CODE GENERATION (timeline-driven or legacy) ===
            script = code_generator.generate_scene_code(
                segment.scene_spec, i, timeline=timeline
            )
            
            # Validate generated code
            is_valid, issues = code_validator.validate(script)
            
            if not is_valid:
                logger.warning(f"⚠️ Script {i+1} has issues: {issues}")
            
            scripts.append(script)
            segment.script_path = f"segment_{i:03d}.py"
        else:
            logger.warning(f"⚠️ Segment {i+1} has no spec, needs legacy generation")
            scripts.append(None)
    
    valid_count = sum(1 for s in scripts if s is not None)
    logger.info(f"✅ Generated {valid_count}/{len(segments)} scripts from specs")
    
    return scripts


def score_video_quality(
    segments: List[QualityNarrationSegment],
    timelines: List[Optional[VisualTimeline]],
) -> VideoScore:
    """
    Score all segments for engagement quality.
    
    Call after generate_quality_scripts_bulk to get quality metrics.
    
    Returns:
        VideoScore with per-segment and aggregate scores
    """
    scorer = QualityScorer()
    
    audio_durations = []
    element_counts = []
    beat_counts = []
    
    for seg in segments:
        dur = (
            seg._audio_duration_final
            or (seg.scene_spec.timing.audio_duration_seconds if seg.scene_spec else None)
            or seg.duration
            or 10.0
        )
        audio_durations.append(dur)
        
        if seg.scene_spec:
            element_counts.append(len(seg.scene_spec.visual_metaphor.visual_elements))
            beats = seg.scene_spec.narration.semantic_beats if seg.scene_spec.narration else []
            beat_counts.append(len(beats))
        else:
            element_counts.append(0)
            beat_counts.append(0)
    
    video_score = scorer.score_video(
        timelines=timelines,
        audio_durations=audio_durations,
        element_counts=element_counts,
        beat_counts=beat_counts,
    )
    
    # Run health checks
    health = PipelineHealthCheck()
    alerts = health.check(video_score)
    
    return video_score


# =============================================================================
# PIPELINE MIXIN: Add quality methods to existing pipeline
# =============================================================================

class QualityPipelineMixin:
    """
    Mixin class that adds quality pipeline methods to OptimizedVideoGenerationPipeline.
    
    Usage:
        class EnhancedPipeline(QualityPipelineMixin, OptimizedVideoGenerationPipeline):
            pass
    """
    
    def _should_use_quality_pipeline(self) -> bool:
        """Check if quality pipeline should be used."""
        return getattr(self.config, 'use_quality_pipeline', False)
    
    async def _generate_segments_quality_mode(
        self,
        topic: str,
        duration: int
    ) -> List[QualityNarrationSegment]:
        """Generate segments using quality pipeline."""
        # Create LLM adapter
        if hasattr(self, 'gemini_client') and self.gemini_client:
            llm_client = GeminiClientAdapter(
                self.gemini_client,
                self.gemini_models,
                self.current_gemini_model_index
            )
        else:
            # Fallback to OpenRouter
            from ..openrouter_key_manager import get_openrouter_key_manager
            key_manager = get_openrouter_key_manager()
            llm_client = OpenRouterAdapter(key_manager)
        
        segments, errors = generate_quality_segments(
            llm_client,
            topic,
            duration,
            self.config.aspect_ratio
        )
        
        if errors:
            logger.warning(f"Quality generation had errors: {errors}")
        
        return segments
    
    def _generate_scripts_quality_mode(
        self,
        segments: List[QualityNarrationSegment]
    ) -> List[str]:
        """Generate scripts using quality pipeline."""
        return generate_quality_scripts_bulk(
            segments,
            self.config.aspect_ratio
        )


# =============================================================================
# ENHANCED CONFIG
# =============================================================================

def patch_video_generation_config():
    """
    Patch VideoGenerationConfig to add quality pipeline option.
    Call this at module load time.
    """
    try:
        from . import optimized_video_generator
        
        original_config = optimized_video_generator.VideoGenerationConfig
        
        # Add new field
        if not hasattr(original_config, 'use_quality_pipeline'):
            original_config.use_quality_pipeline = False
            logger.info("✅ Patched VideoGenerationConfig with use_quality_pipeline option")
    except Exception as e:
        logger.warning(f"Could not patch VideoGenerationConfig: {e}")


# =============================================================================
# EXAMPLE: How to use in existing code
# =============================================================================

INTEGRATION_EXAMPLE = '''
# ==========================================
# INTEGRATION GUIDE
# ==========================================

# Option 1: Direct replacement in OptimizedVideoGenerationPipeline
# ----------------------------------------------------------------
# In optimized_video_generator.py, modify generate_video_full_parallel:

async def generate_video_full_parallel(self, topic: str, duration: int, ...):
    # BEFORE (old approach):
    # segments = await self._generate_narration_segments_with_gemini(topic, duration)
    
    # AFTER (quality approach):
    from .pipeline_integration import generate_quality_segments, GeminiClientAdapter
    
    llm_adapter = GeminiClientAdapter(
        self.gemini_client,
        self.gemini_models,
        self.current_gemini_model_index
    )
    segments, errors = generate_quality_segments(llm_adapter, topic, duration, self.config.aspect_ratio)
    
    # Convert to regular NarrationSegment if needed for compatibility
    # ... rest of pipeline ...


# Option 2: Use QualityPipelineMixin
# ----------------------------------
from .pipeline_integration import QualityPipelineMixin

class EnhancedVideoGenerationPipeline(QualityPipelineMixin, OptimizedVideoGenerationPipeline):
    async def generate_video_full_parallel(self, topic: str, duration: int, ...):
        if self._should_use_quality_pipeline():
            segments = await self._generate_segments_quality_mode(topic, duration)
            scripts = self._generate_scripts_quality_mode(segments)
        else:
            # Fall back to original implementation
            segments = await self._generate_narration_segments_with_gemini(topic, duration)
            # ...


# Option 3: Full replacement with QualityVideoPipeline
# ----------------------------------------------------
from .quality_pipeline import QualityVideoPipeline, QualityPipelineConfig

pipeline = QualityVideoPipeline(QualityPipelineConfig(
    openrouter_api_key=os.environ["OPENROUTER_API_KEY"],
    aspect_ratio="9:16"
))
result = pipeline.generate_video(topic, duration)
'''


if __name__ == "__main__":
    print("Pipeline Integration Module")
    print("=" * 50)
    print(INTEGRATION_EXAMPLE)
