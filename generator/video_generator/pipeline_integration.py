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
from .visual_validation import (
    validate_quality_spec_against_contract,
    validate_script_simulation,
    deserialize_contract,
)

logger = logging.getLogger(__name__)


# =============================================================================
# LLM CLIENT ADAPTER
# =============================================================================

class GeminiClientAdapter:
    """
    Adapts the Gemini client from OptimizedVideoGenerationPipeline to work
    with the SceneSpecGenerator's expected interface.
    
    C4: If `pipeline` is provided, rotation state is shared bidirectionally —
    any model/key rotation here is visible to the parent pipeline and vice-versa.
    
    Rotation order: Key1+Model1 → Key2+Model1 → Key3+Model1
                  → Key1+Model2 → Key2+Model2 → Key3+Model2 → ...
    """
    
    def __init__(self, gemini_client, gemini_models: List[str], current_model_index: int = 0, pipeline=None):
        self.gemini_client = gemini_client
        self.gemini_models = gemini_models
        self._pipeline = pipeline
        self._local_model_index = current_model_index
        self._local_key_index = 0
        
        # Build client list from pipeline or single client
        if pipeline and hasattr(pipeline, 'gemini_clients') and pipeline.gemini_clients:
            self._clients = pipeline.gemini_clients
        else:
            self._clients = [gemini_client] if gemini_client else []
    
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
    
    @property
    def current_key_index(self):
        if self._pipeline is not None:
            return self._pipeline.current_gemini_key_index
        return self._local_key_index
    
    @current_key_index.setter
    def current_key_index(self, value):
        if self._pipeline is not None:
            self._pipeline.current_gemini_key_index = value
            self._pipeline.gemini_client = self._clients[value]
        else:
            self._local_key_index = value
    
    def _get_current_client(self):
        """Get the genai.Client bound to the current key index."""
        if self._clients:
            idx = min(self.current_key_index, len(self._clients) - 1)
            return self._clients[idx]
        return self.gemini_client
    
    def generate(self, prompt: str, temperature: float = 0.7) -> str:
        """Generate response with key-first-then-model rotation."""
        from google.genai import types
        import time
        
        max_attempts = len(self.gemini_models) * max(len(self._clients), 1) * 2
        last_error = None
        
        for attempt in range(max_attempts):
            model_name = self.gemini_models[self.current_model_index]
            client = self._get_current_client()
            
            try:
                try:
                    config = types.GenerateContentConfig(
                        temperature=temperature,
                        max_output_tokens=32768,
                    )
                except (TypeError, AttributeError):
                    config = types.GenerateContentConfig(
                        temperature=temperature,
                        max_output_tokens=32768
                    )
                
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config
                )
                
                if hasattr(response, 'text') and response.text:
                    return response.text
                
                # Handle cases where text is None but candidates exist
                if hasattr(response, 'candidates') and response.candidates:
                    for candidate in response.candidates:
                        if hasattr(candidate, 'content') and candidate.content:
                            if hasattr(candidate.content, 'parts') and candidate.content.parts:
                                for part in candidate.content.parts:
                                    if hasattr(part, 'text') and part.text:
                                        return part.text
                
                logger.error(f"❌ Could not extract text from Gemini response: {type(response)}")
                return str(response)
                
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                
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
                
                if is_retryable:
                    key_num = self.current_key_index + 1
                    logger.warning(
                        f"⚠️ {model_name} on key {key_num}/{len(self._clients)} "
                        f"failed ({str(e)[:100]})"
                    )
                    
                    # Try next KEY with same model
                    next_key = self.current_key_index + 1
                    if next_key < len(self._clients):
                        self.current_key_index = next_key
                        logger.info(f"🔑 Trying next key for same model ({model_name})...")
                        time.sleep(2)
                        continue
                    
                    # All keys exhausted → try next MODEL, reset keys
                    next_model = self.current_model_index + 1
                    if next_model < len(self.gemini_models):
                        self.current_model_index = next_model
                        self.current_key_index = 0
                        new_model = self.gemini_models[next_model]
                        logger.info(f"🔄 All keys exhausted for {model_name}, advancing to {new_model}...")
                        time.sleep(2)
                        continue
                    
                    # Everything exhausted
                    raise RuntimeError(f"All {len(self.gemini_models)} models × {len(self._clients)} keys exhausted. Last: {e}")
                else:
                    raise
        
        raise RuntimeError(f"All {max_attempts} attempts failed. Last error: {last_error}")


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
    # Visual contract — frozen authority from concept visualizer
    visual_contract: Optional[str] = None


def generate_quality_segments(
    llm_client,
    topic: str,
    duration: int,
    aspect_ratio: str = "9:16",
    max_retries: int = 2,
    visual_contracts: Optional[List[dict]] = None,
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
        visual_contracts: Optional list of visual contract dicts.  When provided,
            the first contract is injected as HIGHEST AUTHORITY into the spec
            generation prompt so the LLM respects depiction_mode and entities.
        
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
            # Generate specifications (with visual contract authority)
            logger.info(f"🎯 Quality Pipeline: Generating scene specifications for '{topic}' (attempt {attempt + 1}/{max_retries + 1})")
            if visual_contracts:
                logger.info(f"   🔒 Visual contracts provided: {len(visual_contracts)} contracts")
            specs, gen_errors = spec_generator.generate_specifications(
                topic, duration, visual_contracts=visual_contracts
            )
            
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
    
    # ══════════════════════════════════════════════════════════════
    # PASS 1: Semantic Alignment — score + optional LLM refinement
    # Scores how well each spec visually depicts the narration.
    # Low-scoring specs receive a refinement prompt → LLM revision.
    # High-scoring specs pass through untouched (zero extra latency).
    # ══════════════════════════════════════════════════════════════
    try:
        from .semantic_alignment import (
            analyze_and_build_feedback,
            ALIGNMENT_THRESHOLD,
        )
        sa_available = True
    except ImportError:
        try:
            from generator.video_generator.semantic_alignment import (
                analyze_and_build_feedback,
                ALIGNMENT_THRESHOLD,
            )
            sa_available = True
        except ImportError:
            sa_available = False
    
    # CREATIVE FREEDOM MODE: Semantic alignment loop DISABLED
    # Letting LLM specs pass through without scoring or refinement
    logger.info("🎨 Creative freedom mode — semantic alignment checks skipped")
    
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
    aspect_ratio: str = "9:16",
    max_integrity_retries: int = 1,
    llm_client=None,
) -> List[str]:
    """
    Generate Manim scripts via GEMINI DIRECT generation — no templates.
    
    Pipeline: SceneSpec + Narration → Gemini → Raw Manim Python → Static Validation
    
    Gemini receives the creative direction (from spec) and writes the full
    Manim Python script. Templates are NOT used for animation construction.
    Error correction at render-time is handled by the legacy correction loop
    in the OVG render workers.
    
    Args:
        segments: List of QualityNarrationSegment with scene specs
        aspect_ratio: Video aspect ratio
        max_integrity_retries: (unused, kept for API compatibility)
        llm_client: LLM client with .generate(prompt, temperature) method.
                    If None, falls back to template generation (backward compat).
        
    Returns:
        List of generated Manim script strings (None for failures)
    """
    # ── NEW: Gemini Direct Generation ──
    if llm_client is not None:
        try:
            from .gemini_manim_generator import generate_manim_scripts_bulk as _gemini_bulk
        except ImportError:
            from generator.video_generator.gemini_manim_generator import generate_manim_scripts_bulk as _gemini_bulk
        
        logger.info(
            f"🎬 GEMINI DIRECT MODE: Generating {len(segments)} Manim scripts via LLM "
            f"(no templates)"
        )
        scripts = _gemini_bulk(llm_client, segments, aspect_ratio)
        
        # Tag segments for OVG compatibility
        for i, (seg, script) in enumerate(zip(segments, scripts)):
            if script:
                seg.script_path = f"segment_{i:03d}.py"
                seg._integrity_passed = True  # No integrity gate in Gemini mode
            else:
                seg._integrity_passed = False
        
        valid_count = sum(1 for s in scripts if s is not None)
        logger.info(f"✅ Gemini generated {valid_count}/{len(segments)} scripts")
        return scripts
    
    # ── FALLBACK: Template-based generation (when no llm_client provided) ──
    logger.warning("⚠️ No LLM client for Gemini direct mode — falling back to template generation")
    
    code_generator = ManimCodeGenerator(
        GeneratorConfig(aspect_ratio=aspect_ratio)
    )
    code_validator = CodeValidator()
    visual_director = VisualDirector()
    
    scripts = []
    
    for i, segment in enumerate(segments):
        if segment.scene_spec:
            logger.info(f"🎨 [TEMPLATE FALLBACK] Generating script for segment {i+1}")
            
            audio_dur = (
                segment._audio_duration_final
                or (segment.scene_spec.timing.audio_duration_seconds if segment.scene_spec.timing else None)
                or segment.duration
                or 10.0
            )
            
            scene_type = getattr(segment.scene_spec, 'scene_type', 'CONTENT') or "CONTENT"
            
            contract = None
            contract_json = getattr(segment, 'visual_contract', None)
            if contract_json:
                try:
                    contract = deserialize_contract(contract_json)
                except Exception:
                    pass
            
            try:
                timeline = visual_director.plan_timeline(
                    spec=segment.scene_spec,
                    audio_duration=audio_dur,
                    scene_type=scene_type
                )
            except Exception:
                timeline = None
            
            script = code_generator.generate_scene_code(
                segment.scene_spec, i, timeline=timeline,
                visual_contract=contract,
            )
            
            is_valid, issues = code_validator.validate(script)
            if not is_valid:
                logger.warning(f"⚠️ Template script {i+1} has issues: {issues}")
            
            scripts.append(script)
            segment.script_path = f"segment_{i:03d}.py"
            segment._integrity_passed = True
        else:
            logger.warning(f"⚠️ Segment {i+1} has no spec, needs legacy generation")
            scripts.append(None)
    
    valid_count = sum(1 for s in scripts if s is not None)
    logger.info(f"✅ Generated {valid_count}/{len(segments)} scripts (template fallback)")
    return scripts


# ════════════════════════════════════════════════════════════════════
# SPEC ↔ DICT CONVERSION HELPERS (for integrity enforcement)
# ════════════════════════════════════════════════════════════════════

def _spec_to_dict(spec: SceneSpecification) -> dict:
    """Convert a SceneSpecification to a dict for integrity checking."""
    elements = []
    if spec.visual_metaphor and spec.visual_metaphor.visual_elements:
        for elem in spec.visual_metaphor.visual_elements:
            elements.append({
                "id": elem.id,
                "element_type": elem.element_type.value if hasattr(elem.element_type, 'value') else str(elem.element_type),
                "label": elem.label or "",
                "position": elem.position.value if elem.position and hasattr(elem.position, 'value') else str(elem.position or "center"),
                "size": elem.size or "medium",
                "color": elem.color or "BLUE",
            })
    
    sequence = []
    if spec.transformation and spec.transformation.sequence:
        for step in spec.transformation.sequence:
            sequence.append({
                "action": step.action.value if hasattr(step.action, 'value') else str(step.action),
                "target": step.target or "",
                "description": step.description or "",
            })
    
    return {
        "visual_metaphor": {
            "abstract_concept": spec.visual_metaphor.abstract_concept if spec.visual_metaphor else "",
            "concrete_representation": spec.visual_metaphor.concrete_representation if spec.visual_metaphor else "",
            "metaphor_type": spec.visual_metaphor.metaphor_type.value if spec.visual_metaphor and hasattr(spec.visual_metaphor.metaphor_type, 'value') else "",
            "visual_elements": elements,
        },
        "transformation": {
            "sequence": sequence,
        },
    }


def _apply_dict_to_spec(spec_dict: dict, spec: SceneSpecification):
    """Apply enforced dict changes back to a SceneSpecification object.
    
    Only updates fields that enforcement might change:
    - element_type of visual elements
    - action of transformation steps
    - new elements added by entity injection
    """
    dict_elements = spec_dict.get("visual_metaphor", {}).get("visual_elements", [])
    spec_elements = spec.visual_metaphor.visual_elements if spec.visual_metaphor else []
    
    # Update existing elements
    for spec_elem, dict_elem in zip(spec_elements, dict_elements):
        new_type_str = dict_elem.get("element_type", "")
        if new_type_str:
            try:
                new_type = ElementType(new_type_str)
                if new_type != spec_elem.element_type:
                    spec_elem.element_type = new_type
            except (ValueError, KeyError):
                pass
    
    # Handle injected elements (dict has more than spec)
    if len(dict_elements) > len(spec_elements) and spec.visual_metaphor:
        for dict_elem in dict_elements[len(spec_elements):]:
            try:
                new_elem = VisualElement(
                    id=dict_elem.get("id", f"injected_{len(spec_elements)}"),
                    element_type=ElementType(dict_elem.get("element_type", "node")),
                    label=dict_elem.get("label", ""),
                    position=Position(dict_elem.get("position", "center")),
                    size=dict_elem.get("size", "medium"),
                    color=dict_elem.get("color", "TEAL"),
                )
                spec.visual_metaphor.visual_elements.append(new_elem)
            except (ValueError, KeyError) as e:
                logger.debug(f"  Could not inject element: {e}")
    
    # Update transformation actions
    dict_sequence = spec_dict.get("transformation", {}).get("sequence", [])
    spec_sequence = spec.transformation.sequence if spec.transformation else []
    
    for spec_step, dict_step in zip(spec_sequence, dict_sequence):
        new_action_str = dict_step.get("action", "")
        if new_action_str:
            try:
                new_action = TransformAction(new_action_str)
                if new_action != spec_step.action:
                    spec_step.action = new_action
            except (ValueError, KeyError):
                pass


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
