"""
Manim Correction Engine — Main Orchestrator
=============================================

Ties together:
  - Error Classifier (deterministic classification + regex auto-fix)
  - Pre-Render Validator (3-stage validation gate)
  - Correction Memory (SQLite + ChromaDB dual storage)
  - Ollama Client (Qwen 3.5 primary + Gemma 4 fallback)
  - Correction Prompt Builder (7-section structured prompts)

Pipeline flow:
  1. Classify error + generate failure hash
  2. Check hash cache for known fix
  3. Try deterministic regex auto-fix
  4. Static validation gate
  5. Retrieve similar fixes from ChromaDB
  6. Qwen 3.5 correction (with retrieval context)
  7. Static validation gate
  8. If Qwen fails → Gemma 4 fallback
  9. Store ALL results (success + failure) to memory

Creative Preservation: ONLY technical failures are corrected.
Animation intent, scene composition, and cinematic pacing are preserved.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, List

try:
    from .error_classifier import (
        classify_error,
        auto_fix_common_errors,
        ErrorClassification,
        AutoFixResult,
    )
    from .pre_render_validator import validate_static, validate_structural, validate_semantic
    from .correction_memory import (
        CorrectionMemory,
        CorrectionEntry,
        generate_code_diff,
        generate_retrieval_text,
    )
    from .ollama_client import OllamaCorrectionClient
    from .correction_prompt_builder import (
        build_correction_prompt,
        extract_script_context,
        clean_correction_response,
    )
except ImportError:
    # Fallback for worker processes (spawned via ProcessPoolExecutor)
    from error_classifier import (
        classify_error,
        auto_fix_common_errors,
        ErrorClassification,
        AutoFixResult,
    )
    from pre_render_validator import validate_static, validate_structural, validate_semantic
    from correction_memory import (
        CorrectionMemory,
        CorrectionEntry,
        generate_code_diff,
        generate_retrieval_text,
    )
    from ollama_client import OllamaCorrectionClient
    from correction_prompt_builder import (
        build_correction_prompt,
        extract_script_context,
        clean_correction_response,
    )

logger = logging.getLogger(__name__)


@dataclass
class CorrectionResult:
    """Result of a correction attempt."""
    corrected_script: str
    success: bool
    model_used: str = ""          # "regex_autofix" | "qwen3.5" | "gemma4" | "hash_cache" | "unchanged"
    error_type: str = ""
    method: str = ""              # Human-readable correction method
    attempts: int = 0
    retrieval_hits: int = 0
    fixes_applied: List[str] = field(default_factory=list)


class ManimCorrectionEngine:
    """
    Main orchestrator for the retrieval-augmented correction pipeline.
    
    Combines deterministic repair, semantic retrieval, and LLM correction
    to fix Manim render failures with minimal changes and maximal reliability.
    """

    def __init__(
        self,
        memory: CorrectionMemory,
        ollama: OllamaCorrectionClient,
    ):
        self.memory = memory
        self.ollama = ollama
        self._catastrophic_threshold = 4  # Score threshold for catastrophic bailout
        logger.info("✅ ManimCorrectionEngine initialized")

    def correct_script(
        self,
        script: str,
        error: str,
        segment_index: int,
        segment_data: dict,
        aspect_ratio: str = "9:16",
    ) -> CorrectionResult:
        """
        Full correction pipeline.
        
        Args:
            script: The failing Manim script.
            error: The error traceback from the failed render.
            segment_index: Segment number (0-indexed).
            segment_data: Dict with narration, duration, etc.
            aspect_ratio: Video aspect ratio.
        
        Returns:
            CorrectionResult with corrected script and metadata.
        """
        duration = segment_data.get("duration", 10.0)
        scene_id = f"segment_{segment_index:03d}"
        attempts = 0

        # ── STEP 1: CLASSIFY ERROR ──
        classification = classify_error(error)
        logger.info(
            f"🏷️ Correction Engine: {classification.error_type} "
            f"(hash={classification.failure_hash[:12]}...)"
        )

        # ── STEP 1.5: CATASTROPHIC DETECTION ──
        catastrophic_score = self._catastrophic_score(script, error)
        if catastrophic_score >= self._catastrophic_threshold:
            logger.warning(
                f"🚨 Catastrophic instability detected (score={catastrophic_score}) "
                f"— skipping correction, signal regeneration"
            )
            self._store_result(
                original=script, corrected="", error=error,
                classification=classification, model_used="catastrophic_bailout",
                scene_id=scene_id,
                fix_summary=f"Catastrophic: score={catastrophic_score}, regenerate",
                validation_passed=False, render_success=False, retry_count=0,
            )
            return CorrectionResult(
                corrected_script=script,
                success=False,
                model_used="catastrophic_bailout",
                error_type=classification.error_type,
                method=f"Catastrophic instability (score={catastrophic_score}) — regenerate",
                attempts=0,
            )

        # ── STEP 2: HASH CACHE LOOKUP ──
        cached_fix = self.memory.lookup_by_hash(classification.failure_hash)
        if cached_fix and cached_fix.corrected_script:
            logger.info(f"⚡ Hash cache HIT — applying known fix")
            # Validate the cached fix still works statically
            val = validate_static(cached_fix.corrected_script, segment_index)
            if val.is_valid:
                return CorrectionResult(
                    corrected_script=cached_fix.corrected_script,
                    success=True,
                    model_used="hash_cache",
                    error_type=classification.error_type,
                    method="Hash cache — known successful fix reapplied",
                    attempts=0,
                    retrieval_hits=1,
                )
            else:
                logger.warning(f"⚠️ Cached fix failed static validation, proceeding to repair")

        # ── STEP 3: DETERMINISTIC PRE-REPAIR (Escalation Level 1) ──
        auto_result = auto_fix_common_errors(script, error, segment_index)
        attempts += 1

        if auto_result.was_fixed:
            # Run structural validation on auto-fixed script
            struct_val = validate_structural(auto_result.script, segment_index)
            if struct_val.auto_fixed_script:
                auto_result = AutoFixResult(
                    script=struct_val.auto_fixed_script,
                    was_fixed=True,
                    fixes_applied=auto_result.fixes_applied + ["structural_autofix"],
                )
                logger.info("🔧 Structural validator applied auto-fixes")
            
            # Validate the auto-fix
            val = validate_static(auto_result.script, segment_index)
            if val.is_valid:
                logger.info(
                    f"🔧 Deterministic auto-fix succeeded: {auto_result.fixes_applied}"
                )
                # Store success
                self._store_result(
                    original=script,
                    corrected=auto_result.script,
                    error=error,
                    classification=classification,
                    model_used="regex_autofix",
                    scene_id=scene_id,
                    fix_summary=f"Regex auto-fix: {', '.join(auto_result.fixes_applied)}",
                    validation_passed=True,
                    render_success=False,  # Not yet rendered
                    retry_count=attempts,
                )
                return CorrectionResult(
                    corrected_script=auto_result.script,
                    success=True,
                    model_used="regex_autofix",
                    error_type=classification.error_type,
                    method=f"Deterministic auto-fix: {', '.join(auto_result.fixes_applied)}",
                    attempts=attempts,
                    fixes_applied=auto_result.fixes_applied,
                )
            else:
                logger.warning(
                    f"⚠️ Auto-fix applied but failed static validation: {val.errors}"
                )
                # Use auto-fixed version as base for LLM correction
                script = auto_result.script

        # Also apply static validation auto-fixes
        val = validate_static(script, segment_index)
        if val.auto_fixed_script:
            script = val.auto_fixed_script
            logger.info("🔧 Static validator applied auto-fixes")

        # ── STEP 4: CHECK OLLAMA AVAILABILITY ──
        if not self.ollama.is_available:
            logger.warning("⚠️ Ollama not available — returning best auto-fix attempt")
            return CorrectionResult(
                corrected_script=script,
                success=auto_result.was_fixed,
                model_used="regex_autofix_only",
                error_type=classification.error_type,
                method="Regex auto-fix only (Ollama unavailable)",
                attempts=attempts,
                fixes_applied=auto_result.fixes_applied if auto_result.was_fixed else [],
            )

        # ── STEP 5: RETRIEVE SIMILAR FIXES ──
        tb_summary = error[-500:] if len(error) > 500 else error
        retrieved = self.memory.retrieve_similar_fixes(
            classification.error_type, tb_summary
        )
        retrieval_hits = len(retrieved)

        # Convert to dicts for prompt builder
        retrieved_dicts = []
        for entry in retrieved:
            retrieved_dicts.append({
                "error_type": entry.error_type,
                "fix_summary": entry.fix_summary,
                "code_diff": entry.code_diff,
            })

        if retrieval_hits:
            logger.info(f"🔍 Retrieved {retrieval_hits} similar fixes from memory")

        # ── STEP 6: PRIMARY LLM CORRECTION (Escalation Level 2) ──
        script_context = extract_script_context(
            script, classification.failing_line_number
        )

        prompt = build_correction_prompt(
            error_type=classification.error_type,
            traceback=error,
            failing_line=classification.failing_line,
            script_context=script_context,
            segment_index=segment_index,
            duration=duration,
            aspect_ratio=aspect_ratio,
            retrieved_fixes=retrieved_dicts if retrieved_dicts else None,
        )

        attempts += 1
        corrected = self.ollama.correct(prompt, model="primary")

        if corrected:
            corrected = clean_correction_response(corrected)
            # Run structural + static validation
            struct_val = validate_structural(corrected, segment_index)
            if struct_val.auto_fixed_script:
                corrected = struct_val.auto_fixed_script
                logger.info("🔧 Structural auto-fixes applied to primary LLM output")
            val = validate_static(corrected, segment_index)

            if val.is_valid:
                logger.info("✅ Primary LLM correction passed validation")
                self._store_result(
                    original=script,
                    corrected=corrected,
                    error=error,
                    classification=classification,
                    model_used=self.ollama.MODELS.get('primary', 'primary'),
                    scene_id=scene_id,
                    fix_summary=f"Primary LLM correction for {classification.error_type}",
                    validation_passed=True,
                    render_success=False,
                    retry_count=attempts,
                )
                return CorrectionResult(
                    corrected_script=val.auto_fixed_script or corrected,
                    success=True,
                    model_used=self.ollama.MODELS.get('primary', 'primary'),
                    error_type=classification.error_type,
                    method=f"Primary LLM correction ({classification.error_type})",
                    attempts=attempts,
                    retrieval_hits=retrieval_hits,
                )
            else:
                logger.warning(
                    f"⚠️ Primary LLM correction failed validation: {val.errors}"
                )

        # ── STEP 7: SECONDARY LLM FALLBACK (Escalation Level 3) ──
        logger.info("🔄 Primary failed, falling back to secondary LLM...")
        attempts += 1
        corrected = self.ollama.correct(prompt, model="secondary")

        if corrected:
            corrected = clean_correction_response(corrected)
            val = validate_static(corrected, segment_index)

            if val.is_valid:
                logger.info("✅ Secondary LLM fallback passed validation")
                self._store_result(
                    original=script,
                    corrected=corrected,
                    error=error,
                    classification=classification,
                    model_used=self.ollama.MODELS.get('secondary', 'secondary'),
                    scene_id=scene_id,
                    fix_summary=f"Secondary LLM fallback for {classification.error_type}",
                    validation_passed=True,
                    render_success=False,
                    retry_count=attempts,
                )
                return CorrectionResult(
                    corrected_script=val.auto_fixed_script or corrected,
                    success=True,
                    model_used=self.ollama.MODELS.get('secondary', 'secondary'),
                    error_type=classification.error_type,
                    method=f"Secondary LLM fallback ({classification.error_type})",
                    attempts=attempts,
                    retrieval_hits=retrieval_hits,
                )
            else:
                logger.warning(
                    f"❌ Secondary LLM correction also failed validation: {val.errors}"
                )

        # ── STEP 8: ALL CORRECTIONS FAILED (Escalation Level 4: Regenerate) ──
        logger.error(
            f"❌ Correction engine exhausted for segment {segment_index} "
            f"({classification.error_type}) after {attempts} attempts"
        )

        # Store failure
        self._store_result(
            original=script,
            corrected="",
            error=error,
            classification=classification,
            model_used="all_failed",
            scene_id=scene_id,
            fix_summary=f"All correction methods failed for {classification.error_type}",
            validation_passed=False,
            render_success=False,
            retry_count=attempts,
        )

        return CorrectionResult(
            corrected_script=script,  # Return original
            success=False,
            model_used="all_failed",
            error_type=classification.error_type,
            method="All correction methods exhausted",
            attempts=attempts,
            retrieval_hits=retrieval_hits,
        )

    def mark_render_success(
        self,
        script: str,
        segment_index: int,
        error: str,
        model_used: str,
    ):
        """
        Called after a corrected script renders successfully.
        Updates the correction memory with render_success=True.
        """
        classification = classify_error(error)
        self._store_result(
            original="",  # We don't have the original at this point
            corrected=script,
            error=error,
            classification=classification,
            model_used=model_used,
            scene_id=f"segment_{segment_index:03d}",
            fix_summary=f"Render-verified fix for {classification.error_type}",
            validation_passed=True,
            render_success=True,
            retry_count=0,
        )

    def _store_result(
        self,
        original: str,
        corrected: str,
        error: str,
        classification: ErrorClassification,
        model_used: str,
        scene_id: str,
        fix_summary: str,
        validation_passed: bool,
        render_success: bool,
        retry_count: int,
    ):
        """Store a correction result into dual memory."""
        try:
            entry = CorrectionEntry(
                model_used=model_used,
                scene_id=scene_id,
                original_script=original,
                error_traceback=error,
                error_type=classification.error_type,
                failing_line=classification.failing_line or "",
                corrected_script=corrected,
                validation_passed=validation_passed,
                render_success=render_success,
                retry_count=retry_count,
                fix_summary=fix_summary,
                failure_hash=classification.failure_hash,
                code_diff=generate_code_diff(original, corrected) if original and corrected else "",
            )
            entry.retrieval_text = generate_retrieval_text(entry)
            self.memory.store_correction(entry)
        except Exception as e:
            logger.warning(f"⚠️ Failed to store correction result: {e}")

    def get_stats(self) -> dict:
        """Get correction memory statistics."""
        return self.memory.get_stats()

    def _catastrophic_score(self, script: str, error: str) -> int:
        """
        Score a script's structural instability.
        
        High scores indicate the script needs regeneration, not repair.
        Threshold is self._catastrophic_threshold (default 4).
        
        Scoring:
          +3: Missing class/construct structure
          +2: Excessive .add() ownership corruption (>5)
          +2: Deep chained .animate mutations (>2 chains)
          +2: Multiple NameErrors in traceback
          +1: No self.play() calls at all
          +1: Multiple SyntaxErrors
        """
        import re
        score = 0
        
        # Missing basic structure
        if "class" not in script or "def construct" not in script:
            score += 3
        
        # Ownership corruption (.add() overuse)
        add_count = len(re.findall(r'\.add\s*\(', script))
        if add_count > 5:
            score += 2
        
        # Deep chained .animate mutations (safe string scan)
        chain_count = 0
        for line in script.split('\n'):
            if '.animate.' in line:
                anim_pos = line.find('.animate.')
                after = line[anim_pos + len('.animate'):]
                dots = 0
                ci = 0
                while ci < len(after):
                    if after[ci] == '.':
                        dots += 1
                        ci += 1
                        while ci < len(after) and after[ci] != '(':
                            ci += 1
                        if ci < len(after) and after[ci] == '(':
                            d = 1
                            ci += 1
                            while ci < len(after) and d > 0:
                                if after[ci] == '(':
                                    d += 1
                                elif after[ci] == ')':
                                    d -= 1
                                ci += 1
                    else:
                        break
                if dots >= 3:
                    chain_count += 1
        if chain_count > 2:
            score += 2
        
        # Multiple NameErrors = too many undefined references
        if error.count("NameError") > 2:
            score += 2
        
        # No animations at all
        if not re.search(r'self\.play\s*\(', script):
            score += 1
        
        # Multiple distinct syntax errors
        if error.count("SyntaxError") > 1:
            score += 1
        
        if score >= self._catastrophic_threshold:
            logger.debug(
                f"🔍 Catastrophic score: {score} "
                f"(add={add_count}, chains={len(deep_chains)})"
            )
        
        return score
