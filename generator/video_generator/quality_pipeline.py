"""
Quality Video Generation Pipeline
==================================

Orchestrates the new spec-based video generation flow:

1. Topic → Scene Specification Generation (LLM)
2. Specification Validation (Gate 1)
3. Manim Code Generation (Template-based)
4. Code Validation (Gate 2)
5. Audio Generation (TTS)
6. Video Rendering (Manim)
7. Quality Validation (Gate 3 - optional mute test)

This replaces the old narration-driven approach with a concept-first,
specification-constrained pipeline.
"""

import os
import json
import logging
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from .scene_specification import SceneSpecification, Timing
from .scene_spec_generator import SceneSpecGenerator, GenerationConfig, SpecificationValidator
from .manim_code_generator import ManimCodeGenerator, GeneratorConfig, CodeValidator
from .visual_validation import (
    validate_quality_spec_against_contract,
    validate_script_simulation,
    contract_from_visualizer,
    serialize_contract,
    deserialize_contract,
)

logger = logging.getLogger(__name__)


# =============================================================================
# PIPELINE CONFIGURATION
# =============================================================================

@dataclass
class QualityPipelineConfig:
    """Configuration for the quality video generation pipeline."""
    
    # API Keys
    openrouter_api_key: str = ""
    
    # Output settings
    output_dir: str = "output"
    temp_dir: str = "temp"
    
    # Video settings
    aspect_ratio: str = "9:16"
    manim_quality: str = "medium_quality"  # low_quality, medium_quality, high_quality
    video_type: str = "short"  # "short" = casual/friendly, "regular" = professional
    
    # Quality thresholds
    min_quality_score: float = 0.7
    max_regeneration_attempts: int = 3
    strict_validation: bool = True
    
    # Scene settings
    max_scenes: int = 5
    target_scene_duration: float = 12.0
    
    # TTS settings
    tts_voice: str = "en-US-AndrewNeural"
    
    def __post_init__(self):
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)


# =============================================================================
# LLM CLIENT WRAPPER
# =============================================================================

class LLMClient:
    """
    Wrapper for LLM API calls.
    Compatible with OpenRouter, OpenAI, or similar APIs.
    """
    
    def __init__(self, api_key: str, model: str = "anthropic/claude-3-haiku"):
        self.api_key = api_key
        self.model = model
        self._client = None
    
    def _get_client(self):
        """Lazy initialization of OpenAI-compatible client."""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self.api_key,
                    base_url="https://openrouter.ai/api/v1"
                )
            except ImportError:
                logger.warning("OpenAI package not available, using mock client")
                return None
        return self._client
    
    def generate(self, prompt: str, temperature: float = 0.7) -> str:
        """Generate response from LLM."""
        client = self._get_client()
        
        if client is None:
            # Return mock response for testing
            return self._mock_response(prompt)
        
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert educational animation architect."},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=4096
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise
    
    def _mock_response(self, prompt: str) -> str:
        """Return mock response for testing."""
        return '''[
            {
                "scene_id": "scene_001",
                "concept": {
                    "idea": "The concept being explained",
                    "pedagogical_goal": "What viewer learns"
                },
                "visual_metaphor": {
                    "abstract_concept": "abstract idea",
                    "concrete_representation": "visual representation",
                    "metaphor_type": "process_flow",
                    "visual_elements": [
                        {"id": "elem1", "element_type": "boundary_box", "label": "Main", "color": "BLUE", "position": "center", "size": "large"}
                    ]
                },
                "transformation": {
                    "type": "demo",
                    "sequence": [
                        {"action": "appear", "target": "elem1"}
                    ]
                },
                "narration": {
                    "text": "This explains the concept clearly.",
                    "semantic_beats": [
                        {"beat_phrase": "explains the concept", "visual_sync": "element appears", "target_elements": ["elem1"]}
                    ]
                },
                "timing": {"cognitive_duration_estimate_seconds": 10}
            }
        ]'''


# =============================================================================
# PIPELINE STAGES
# =============================================================================

@dataclass
class PipelineStage:
    """Represents a stage in the pipeline with its result."""
    name: str
    success: bool = False
    result: Any = None
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class QualityVideoPipeline:
    """
    The main pipeline orchestrator for quality video generation.
    
    This implements the new architecture:
    - Concepts precede narration
    - Structured scene specifications
    - Template-based code generation
    - Multiple validation gates
    """
    
    def __init__(self, config: QualityPipelineConfig):
        self.config = config
        
        # Initialize components
        self.llm_client = LLMClient(config.openrouter_api_key)
        
        self.spec_generator = SceneSpecGenerator(
            self.llm_client,
            GenerationConfig(
                max_scenes=config.max_scenes,
                target_scene_duration=config.target_scene_duration,
                aspect_ratio=config.aspect_ratio,
                video_type=config.video_type
            )
        )
        
        self.code_generator = ManimCodeGenerator(
            GeneratorConfig(
                aspect_ratio=config.aspect_ratio
            )
        )
        
        self.spec_validator = SpecificationValidator(strict_mode=config.strict_validation)
        self.code_validator = CodeValidator()
        
        # Pipeline state
        self.stages: List[PipelineStage] = []
    
    def generate_video(
        self,
        topic: str,
        duration: int = 60
    ) -> Dict[str, Any]:
        """
        Generate a high-quality educational video.
        
        Args:
            topic: The educational topic to explain
            duration: Target video duration in seconds
            
        Returns:
            Dictionary with generation results and metadata
        """
        import time
        start_time = time.time()
        
        self.stages = []
        result = {
            "success": False,
            "topic": topic,
            "duration": duration,
            "video_path": None,
            "errors": [],
            "stages": [],
            "specifications": [],
            "quality_scores": []
        }
        
        try:
            # Stage 1: Generate Scene Specifications
            stage1 = self._stage_generate_specifications(topic, duration)
            self.stages.append(stage1)
            
            if not stage1.success:
                result["errors"].extend(stage1.errors)
                return self._finalize_result(result, start_time)
            
            specs: List[SceneSpecification] = stage1.result
            result["specifications"] = [s.to_dict() for s in specs]
            
            # Stage 2: Validate Specifications
            stage2 = self._stage_validate_specifications(specs)
            self.stages.append(stage2)
            
            if not stage2.success and self.config.strict_validation:
                result["errors"].extend(stage2.errors)
                return self._finalize_result(result, start_time)
            
            valid_specs = stage2.result["valid_specs"]
            result["quality_scores"] = stage2.result["quality_scores"]
            
            # Stage 2.5: Create visual contracts from concept visualizer
            # The contract FREEZES the visual model so code generation can't downgrade it
            visual_contracts = []
            try:
                from .concept_visualizer import generate_visual_models_batch
                specs_data = []
                for i, spec in enumerate(valid_specs):
                    specs_data.append({
                        "segment_number": i + 1,
                        "duration": spec.timing.cognitive_duration_estimate_seconds,
                        "idea": spec.concept.idea if spec.concept else "main concept",
                        "narration": spec.narration.text if spec.narration else "",
                        "visual_intent": spec.visual_metaphor.concrete_representation if spec.visual_metaphor else "",
                        "layout_strategy": "process_flow",
                    })
                vm_models = generate_visual_models_batch(specs_data)
                for i, vm in enumerate(vm_models):
                    contract = contract_from_visualizer(vm)
                    visual_contracts.append(contract)
                    spec_dict = valid_specs[i].to_dict() if hasattr(valid_specs[i], 'to_dict') else {}
                    passed, issues = validate_quality_spec_against_contract(spec_dict, contract)
                    if not passed:
                        logger.warning(f"  ⚠️ Spec {i+1} vs visual contract: {', '.join(issues)}")
                    else:
                        logger.info(f"  ✓ Spec {i+1} passes visual contract check")
            except Exception as e:
                logger.warning(f"⚠️ Visual contract creation skipped: {e}")
            
            # Stage 3: Generate Manim Code
            stage3 = self._stage_generate_code(valid_specs)
            self.stages.append(stage3)
            
            if not stage3.success:
                result["errors"].extend(stage3.errors)
                return self._finalize_result(result, start_time)
            
            scripts = stage3.result
            
            # Stage 4: Validate Generated Code
            stage4 = self._stage_validate_code(scripts)
            self.stages.append(stage4)
            
            # Stage 4.5: Validate scripts against visual contracts
            if visual_contracts and stage4.result:
                for i, script in enumerate(stage4.result):
                    if i < len(visual_contracts) and script:
                        try:
                            passed, issues, score = validate_script_simulation(script, visual_contracts[i])
                            if not passed:
                                logger.warning(
                                    f"  ⚠️ Quality script {i+1} contract check FAILED "
                                    f"(score={score:.2f}): {', '.join(issues)}"
                                )
                            else:
                                logger.info(f"  ✓ Quality script {i+1} contract check passed (score={score:.2f})")
                        except Exception as e:
                            logger.debug(f"  Script contract validation skipped for {i+1}: {e}")
            
            if not stage4.success and self.config.strict_validation:
                result["errors"].extend(stage4.errors)
                return self._finalize_result(result, start_time)
            
            valid_scripts = stage4.result
            
            # Stage 5: Generate Audio (TTS)
            stage5 = self._stage_generate_audio(valid_specs)
            self.stages.append(stage5)
            
            # Stage 6: Render Videos
            stage6 = self._stage_render_videos(valid_scripts, valid_specs)
            self.stages.append(stage6)
            
            if stage6.success:
                result["success"] = True
                result["video_path"] = stage6.result.get("final_video")
            
            return self._finalize_result(result, start_time)
            
        except Exception as e:
            logger.exception("Pipeline failed")
            result["errors"].append(f"Pipeline error: {str(e)}")
            return self._finalize_result(result, start_time)
    
    def _stage_generate_specifications(
        self,
        topic: str,
        duration: int
    ) -> PipelineStage:
        """Stage 1: Generate scene specifications."""
        import time
        start = time.time()
        
        stage = PipelineStage(name="generate_specifications")
        
        try:
            specs, errors = self.spec_generator.generate_specifications(topic, duration)
            
            if specs:
                stage.success = True
                stage.result = specs
            else:
                stage.errors = errors or ["No specifications generated"]
                
        except Exception as e:
            stage.errors = [f"Specification generation failed: {str(e)}"]
        
        stage.duration_seconds = time.time() - start
        return stage
    
    def _stage_validate_specifications(
        self,
        specs: List[SceneSpecification]
    ) -> PipelineStage:
        """Stage 2: Validate specifications."""
        import time
        start = time.time()
        
        stage = PipelineStage(name="validate_specifications")
        
        try:
            valid_specs, errors = self.spec_validator.validate_all(specs)
            
            # Calculate quality scores
            quality_scores = [
                self.spec_validator.get_quality_score(spec)
                for spec in valid_specs
            ]
            
            avg_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0
            
            stage.result = {
                "valid_specs": valid_specs,
                "quality_scores": quality_scores,
                "average_score": avg_score
            }
            
            if avg_score >= self.config.min_quality_score:
                stage.success = True
            else:
                stage.errors = [f"Average quality score {avg_score:.2f} below threshold {self.config.min_quality_score}"]
            
            if errors:
                stage.errors.extend(errors)
                
        except Exception as e:
            stage.errors = [f"Validation failed: {str(e)}"]
        
        stage.duration_seconds = time.time() - start
        return stage
    
    def _stage_generate_code(
        self,
        specs: List[SceneSpecification]
    ) -> PipelineStage:
        """Stage 3: Generate Manim code."""
        import time
        start = time.time()
        
        stage = PipelineStage(name="generate_code")
        
        try:
            scripts = self.code_generator.generate_all_scenes(specs)
            stage.result = scripts
            stage.success = True
            
        except Exception as e:
            stage.errors = [f"Code generation failed: {str(e)}"]
        
        stage.duration_seconds = time.time() - start
        return stage
    
    def _stage_validate_code(
        self,
        scripts: List[str]
    ) -> PipelineStage:
        """Stage 4: Validate generated code."""
        import time
        start = time.time()
        
        stage = PipelineStage(name="validate_code")
        valid_scripts = []
        
        try:
            for i, script in enumerate(scripts):
                is_valid, issues = self.code_validator.validate(script)
                
                if is_valid:
                    valid_scripts.append(script)
                else:
                    stage.errors.extend([f"Script {i}: {issue}" for issue in issues])
                    # Include anyway if not strict
                    if not self.config.strict_validation:
                        valid_scripts.append(script)
            
            stage.result = valid_scripts
            stage.success = len(valid_scripts) > 0
            
        except Exception as e:
            stage.errors = [f"Code validation failed: {str(e)}"]
        
        stage.duration_seconds = time.time() - start
        return stage
    
    def _stage_generate_audio(
        self,
        specs: List[SceneSpecification]
    ) -> PipelineStage:
        """Stage 5: Generate audio for narrations."""
        import time
        start = time.time()
        
        stage = PipelineStage(name="generate_audio")
        audio_files = []
        
        try:
            for i, spec in enumerate(specs):
                audio_path = Path(self.config.temp_dir) / f"audio_{i:03d}.mp3"
                
                # Use Edge TTS
                success = self._generate_tts(spec.narration.text, str(audio_path))
                
                if success:
                    audio_files.append(str(audio_path))
                    
                    # Update timing with actual audio duration
                    duration = self._get_audio_duration(str(audio_path))
                    if duration:
                        spec.timing.audio_duration_seconds = duration
                else:
                    stage.errors.append(f"TTS failed for scene {i}")
            
            stage.result = audio_files
            stage.success = len(audio_files) == len(specs)
            
        except Exception as e:
            stage.errors = [f"Audio generation failed: {str(e)}"]
        
        stage.duration_seconds = time.time() - start
        return stage
    
    def _stage_render_videos(
        self,
        scripts: List[str],
        specs: List[SceneSpecification]
    ) -> PipelineStage:
        """Stage 6: Render videos using Manim."""
        import time
        start = time.time()
        
        stage = PipelineStage(name="render_videos")
        video_files = []
        
        try:
            for i, script in enumerate(scripts):
                script_path = Path(self.config.temp_dir) / f"scene_{i:03d}.py"
                video_path = Path(self.config.temp_dir) / f"scene_{i:03d}.mp4"
                
                # Save script
                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(script)
                
                # Render with Manim
                success = self._render_manim(str(script_path), str(video_path), f"Segment{i:03d}")
                
                if success and video_path.exists():
                    video_files.append(str(video_path))
                else:
                    stage.errors.append(f"Render failed for scene {i}")
            
            # Combine videos if we have multiple
            if len(video_files) > 1:
                final_path = Path(self.config.output_dir) / "final_video.mp4"
                self._combine_videos(video_files, str(final_path))
                stage.result = {"video_files": video_files, "final_video": str(final_path)}
            elif len(video_files) == 1:
                stage.result = {"video_files": video_files, "final_video": video_files[0]}
            else:
                stage.result = {"video_files": [], "final_video": None}
            
            stage.success = len(video_files) > 0
            
        except Exception as e:
            stage.errors = [f"Rendering failed: {str(e)}"]
        
        stage.duration_seconds = time.time() - start
        return stage
    
    def _generate_tts(self, text: str, output_path: str) -> bool:
        """Generate TTS audio using Edge TTS."""
        try:
            import edge_tts
            import asyncio
            
            async def generate():
                communicate = edge_tts.Communicate(text, self.config.tts_voice)
                await communicate.save(output_path)
            
            asyncio.run(generate())
            return Path(output_path).exists()
            
        except Exception as e:
            logger.error(f"TTS generation failed: {e}")
            return False
    
    def _get_audio_duration(self, audio_path: str) -> Optional[float]:
        """Get duration of audio file."""
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(audio_path)
            return len(audio) / 1000.0
        except:
            return None
    
    def _render_manim(
        self,
        script_path: str,
        output_path: str,
        scene_name: str
    ) -> bool:
        """Render a Manim scene."""
        import subprocess
        
        try:
            cmd = [
                "manim",
                "-q", self.config.manim_quality[0],  # l, m, or h
                script_path,
                scene_name,
                "-o", output_path
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            return result.returncode == 0
            
        except Exception as e:
            logger.error(f"Manim render failed: {e}")
            return False
    
    def _combine_videos(self, video_files: List[str], output_path: str) -> bool:
        """Combine multiple video files."""
        try:
            from moviepy.editor import VideoFileClip, concatenate_videoclips
            
            clips = [VideoFileClip(f) for f in video_files]
            final = concatenate_videoclips(clips)
            final.write_videofile(output_path, codec="libx264", audio_codec="aac")
            
            for clip in clips:
                clip.close()
            
            return True
            
        except Exception as e:
            logger.error(f"Video combination failed: {e}")
            return False
    
    def _finalize_result(
        self,
        result: Dict[str, Any],
        start_time: float
    ) -> Dict[str, Any]:
        """Finalize result with stage information."""
        import time
        
        result["total_duration_seconds"] = time.time() - start_time
        result["stages"] = [
            {
                "name": s.name,
                "success": s.success,
                "duration_seconds": s.duration_seconds,
                "error_count": len(s.errors)
            }
            for s in self.stages
        ]
        
        return result
    
    def get_pipeline_summary(self) -> str:
        """Get a summary of the pipeline execution."""
        lines = ["Pipeline Execution Summary", "=" * 40]
        
        for stage in self.stages:
            status = "✓" if stage.success else "✗"
            lines.append(f"{status} {stage.name}: {stage.duration_seconds:.2f}s")
            
            if stage.errors:
                for error in stage.errors[:3]:  # Show first 3 errors
                    lines.append(f"    - {error}")
        
        return "\n".join(lines)


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

def example_usage():
    """Example of how to use the quality pipeline."""
    
    config = QualityPipelineConfig(
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        aspect_ratio="9:16",
        strict_validation=False  # Allow imperfect specs for demo
    )
    
    pipeline = QualityVideoPipeline(config)
    
    result = pipeline.generate_video(
        topic="How Zero Trust Security Works",
        duration=45
    )
    
    print(pipeline.get_pipeline_summary())
    print(f"\nSuccess: {result['success']}")
    
    if result['video_path']:
        print(f"Video: {result['video_path']}")
    
    if result['errors']:
        print(f"Errors: {len(result['errors'])}")


if __name__ == "__main__":
    example_usage()
