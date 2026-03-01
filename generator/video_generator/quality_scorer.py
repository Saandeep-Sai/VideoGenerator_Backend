"""
Quality Scorer — Pre-Upload Engagement Prediction
==================================================

Analyzes VisualTimeline metadata to predict viewer engagement quality.
No ML model needed — uses measurable structural metrics.

Scoring dimensions:
    1. Animation density (events/second)
    2. Static gap detection (gaps > 1.5s)
    3. Animation variety (unique types / total)
    4. Beat sync accuracy (% with matching animation)
    5. Timing accuracy (animation vs audio duration)

Thresholds:
    >= 0.8 → Ship ✅
    0.6-0.8 → Auto-enhance (insert gap fillers, increase emphasis)
    < 0.6 → Re-generate with higher intensity profile
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# SCORING DATA
# =============================================================================

@dataclass
class EngagementScore:
    """Composite engagement quality score for a single segment."""
    animation_density: float = 0.0      # Events per second (target: >= 1.2)
    static_gap_count: int = 0           # Count of gaps > threshold (target: 0)
    max_static_gap: float = 0.0         # Longest gap in seconds (target: < 1.0)
    animation_variety: float = 0.0      # Unique animation types / total events
    beat_sync_accuracy: float = 0.0     # % of beats with matching animation ±0.5s
    timing_accuracy: float = 1.0        # Closeness of animation total to audio duration
    element_utilization: float = 0.0    # % of elements that received at least one animation
    cinematic_depth: float = 0.0        # Bonus for MOVE/TRANSFORM/CAMERA events (cinematic interactions)
    momentum_score: float = 0.0         # Solution A: No element inactive > 2s
    rhythm_score: float = 0.0           # Solution D: Energy peaks at regular intervals
    variety_enforcement: float = 0.0    # Solution G: No consecutive identical patterns
    spatial_clarity: float = 0.0        # Spatial safety: element count vs scale, overflow risk
    overall: float = 0.0               # Weighted composite 0.0-1.0
    
    @property
    def grade(self) -> str:
        """Human-readable grade."""
        if self.overall >= 0.8:
            return "A"
        elif self.overall >= 0.6:
            return "B"
        elif self.overall >= 0.4:
            return "C"
        else:
            return "D"
    
    @property
    def action(self) -> str:
        """Recommended action based on score."""
        if self.overall >= 0.8:
            return "SHIP"
        elif self.overall >= 0.6:
            return "ENHANCE"
        else:
            return "REGENERATE"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "animation_density": round(self.animation_density, 3),
            "static_gap_count": self.static_gap_count,
            "max_static_gap": round(self.max_static_gap, 2),
            "animation_variety": round(self.animation_variety, 3),
            "beat_sync_accuracy": round(self.beat_sync_accuracy, 3),
            "timing_accuracy": round(self.timing_accuracy, 3),
            "element_utilization": round(self.element_utilization, 3),
            "cinematic_depth": round(self.cinematic_depth, 3),
            "momentum_score": round(self.momentum_score, 3),
            "rhythm_score": round(self.rhythm_score, 3),
            "variety_enforcement": round(self.variety_enforcement, 3),
            "spatial_clarity": round(self.spatial_clarity, 3),
            "overall": round(self.overall, 3),
            "grade": self.grade,
            "action": self.action,
        }


@dataclass
class VideoScore:
    """Aggregate score for entire video (all segments)."""
    segment_scores: List[EngagementScore] = field(default_factory=list)
    overall: float = 0.0
    worst_segment_index: int = -1
    
    @property
    def action(self) -> str:
        if self.overall >= 0.8:
            return "SHIP"
        elif self.overall >= 0.6:
            return "ENHANCE"
        else:
            return "REGENERATE"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "segment_scores": [s.to_dict() for s in self.segment_scores],
            "overall": round(self.overall, 3),
            "worst_segment_index": self.worst_segment_index,
            "action": self.action,
        }


# =============================================================================
# QUALITY SCORER
# =============================================================================

class QualityScorer:
    """
    Analyzes VisualTimelines to predict engagement quality.
    
    Uses only generated metadata — no video frame analysis needed.
    """
    
    # Scoring weights (sum to 1.0)+ spatial clarity
    WEIGHTS = {
        "density": 0.13,
        "gaps": 0.13,
        "variety": 0.09,
        "beat_sync": 0.09,
        "timing": 0.04,
        "utilization": 0.07,
        "cinematic": 0.09,       # MOVE/TRANSFORM/CAMERA events
        "momentum": 0.11,        # Solution A: continuous activity per element
        "rhythm": 0.07,          # Solution D: energy peaks at intervals
        "variety_enforcement": 0.06,  # Solution G: no consecutive identical patterns
        "spatial_clarity": 0.12, # Spatial safety: element density, overflow risk
        "variety_enforcement": 0.07,  # Solution G: no consecutive identical patterns
    }
    
    # Cinematic targets — tighter than before for Grade A
    TARGET_DENSITY = 1.2       # events per second (was 0.8)
    TARGET_MAX_GAP = 1.0       # seconds (was 1.5)
    MAX_ELEMENT_INACTIVE = 2.0 # Solution A: max seconds idle per element
    PEAK_INTERVAL = 6.0        # Solution D: expected energy peak interval
    
    def score_timeline(
        self,
        timeline,  # VisualTimeline
        audio_duration: float,
        total_elements: int = 0,
        total_beats: int = 0,
    ) -> EngagementScore:
        """
        Score a single segment's timeline for engagement quality.
        
        Args:
            timeline: VisualTimeline from VisualDirector
            audio_duration: Actual audio duration in seconds
            total_elements: Total number of visual elements in the spec
            total_beats: Total number of semantic beats
            
        Returns:
            EngagementScore with dimensional scores and composite
        """
        from generator.video_generator.visual_director import EventType
        
        events = timeline.events if timeline else []
        
        # 1. Animation density
        density = len(events) / max(0.1, audio_duration)
        density_score = min(1.0, density / self.TARGET_DENSITY)
        
        # 2. Static gaps
        gaps = timeline.get_static_gaps(self.TARGET_MAX_GAP) if timeline else []
        max_gap = max((end - start for start, end in gaps), default=0.0)
        gap_score = max(0.0, 1.0 - len(gaps) * 0.25)  # -0.25 per gap
        
        # 3. Animation variety
        if events:
            unique_styles = len(set(e.animation_style for e in events))
            variety_score = min(1.0, unique_styles / max(3, len(events) * 0.4))
        else:
            variety_score = 0.0
        
        # 4. Beat sync accuracy
        if total_beats > 0 and events:
            synced_events = sum(1 for e in events if e.sync_phrase)
            beat_sync_score = min(1.0, synced_events / total_beats)
        else:
            beat_sync_score = 0.5  # Neutral if no beats
        
        # 5. Timing accuracy
        if events and audio_duration > 0:
            total_event_time = sum(e.duration for e in events)
            timing_ratio = total_event_time / audio_duration
            # Perfect = 0.7-1.0 coverage (some waits are fine)
            if 0.6 <= timing_ratio <= 1.1:
                timing_score = 1.0
            else:
                timing_score = max(0.0, 1.0 - abs(timing_ratio - 0.85) * 2)
        else:
            timing_score = 0.0
        
        # 6. Element utilization
        if total_elements > 0 and events:
            animated_elements = len(set(e.target_element for e in events))
            utilization_score = animated_elements / total_elements
        else:
            utilization_score = 0.0
        
        # 7. Cinematic depth — rewards MOVE, TRANSFORM, CAMERA events
        # These event types create the "story through motion" cinematic feel
        cinematic_types = {"move", "transform", "camera"}
        if events:
            cinematic_events = sum(
                1 for e in events
                if e.event_type.value in cinematic_types
            )
            # Target: at least 3 cinematic events per segment for full score
            cinematic_score = min(1.0, cinematic_events / 3.0)
        else:
            cinematic_score = 0.0
        
        # 8. Momentum score (Solution A) — no element inactive > 2s
        # Measures how well continuous activity is maintained per element
        if events and total_elements > 0 and audio_duration > 2:
            momentum_score = self._score_momentum(events, audio_duration)
        else:
            momentum_score = 0.0
        
        # 9. Rhythm score (Solution D) — energy peaks at regular intervals
        if events and audio_duration > 5:
            rhythm_score = self._score_rhythm(events, audio_duration)
        else:
            rhythm_score = 0.5  # Neutral for very short segments
        
        # 10. Variety enforcement score (Solution G) — no consecutive identical patterns
        if events and len(events) >= 3:
            variety_enforcement_score = self._score_variety_enforcement(events)
        else:
            variety_enforcement_score = 0.5  # Neutral for very few events
        
        # 11. Spatial clarity score — element density, overflow risk, hierarchy compliance
        spatial_clarity_score = self._score_spatial_clarity(events, total_elements, audio_duration)
        
        # Composite score
        overall = (
            self.WEIGHTS["density"] * density_score +
            self.WEIGHTS["gaps"] * gap_score +
            self.WEIGHTS["variety"] * variety_score +
            self.WEIGHTS["beat_sync"] * beat_sync_score +
            self.WEIGHTS["timing"] * timing_score +
            self.WEIGHTS["utilization"] * utilization_score +
            self.WEIGHTS["cinematic"] * cinematic_score +
            self.WEIGHTS["momentum"] * momentum_score +
            self.WEIGHTS["rhythm"] * rhythm_score +
            self.WEIGHTS["variety_enforcement"] * variety_enforcement_score +
            self.WEIGHTS["spatial_clarity"] * spatial_clarity_score
        )
        
        score = EngagementScore(
            animation_density=density,
            static_gap_count=len(gaps),
            max_static_gap=max_gap,
            animation_variety=variety_score,
            beat_sync_accuracy=beat_sync_score,
            timing_accuracy=timing_score,
            element_utilization=utilization_score,
            cinematic_depth=cinematic_score,
            momentum_score=momentum_score,
            rhythm_score=rhythm_score,
            variety_enforcement=variety_enforcement_score,
            spatial_clarity=spatial_clarity_score,
            overall=overall
        )
        
        logger.info(
            f"📊 Score: {score.overall:.2f} ({score.grade}) "
            f"[density={density:.2f}, gaps={len(gaps)}, variety={variety_score:.2f}, "
            f"cinematic={cinematic_score:.2f}, momentum={momentum_score:.2f}, "
            f"rhythm={rhythm_score:.2f}, variety_enf={variety_enforcement_score:.2f}, "
            f"spatial={spatial_clarity_score:.2f}] "
            f"→ {score.action}"
        )
        
        return score
    
    def _score_momentum(self, events: list, audio_duration: float) -> float:
        """Solution A scoring: Measure continuous activity per element.
        
        For each unique element, check that it never goes more than 2s
        without an event. Score = fraction of elements with good momentum.
        """
        from generator.video_generator.visual_director import EventType
        
        # Group events by element
        element_events = {}
        for e in events:
            if e.target_element not in element_events:
                element_events[e.target_element] = []
            element_events[e.target_element].append(e.timestamp)
        
        if not element_events:
            return 0.0
        
        good_momentum = 0
        for elem_id, timestamps in element_events.items():
            timestamps.sort()
            max_gap = 0.0
            
            for i in range(len(timestamps) - 1):
                gap = timestamps[i + 1] - timestamps[i]
                max_gap = max(max_gap, gap)
            
            # Check gap from last event to end of audio
            if timestamps:
                trailing_gap = audio_duration - timestamps[-1]
                max_gap = max(max_gap, trailing_gap)
            
            if max_gap <= self.MAX_ELEMENT_INACTIVE:
                good_momentum += 1
        
        return good_momentum / len(element_events)
    
    def _score_rhythm(self, events: list, audio_duration: float) -> float:
        """Solution D scoring: Check for energy peaks at regular intervals.
        
        Looks for clusters of 2+ events within 0.3s windows at ~6s intervals.
        """
        # Build event density histogram (1s bins)
        bins = int(audio_duration) + 1
        density_map = [0] * bins
        
        for e in events:
            bin_idx = min(int(e.timestamp), bins - 1)
            density_map[bin_idx] += 1
        
        # Look for peaks (bins with 3+ events)
        peaks = [i for i, d in enumerate(density_map) if d >= 3]
        
        if not peaks:
            return 0.3  # No clear peaks — low score
        
        # Expected peaks: audio_duration / 6
        expected_peaks = max(1, int(audio_duration / self.PEAK_INTERVAL))
        peak_ratio = min(1.0, len(peaks) / expected_peaks)
        
        # Check peak spacing regularity (bonus for even spacing)
        if len(peaks) >= 2:
            spacings = [peaks[i+1] - peaks[i] for i in range(len(peaks) - 1)]
            avg_spacing = sum(spacings) / len(spacings)
            spacing_variance = sum((s - avg_spacing) ** 2 for s in spacings) / len(spacings)
            regularity_bonus = max(0.0, 1.0 - spacing_variance / 25.0)  # Normalize
        else:
            regularity_bonus = 0.5
        
        return 0.6 * peak_ratio + 0.4 * regularity_bonus
    
    def _score_variety_enforcement(self, events: list) -> float:
        """Solution G scoring: Penalize consecutive identical animation patterns.
        
        Checks sequential events of the same type for duplicate styles.
        Returns 1.0 if no consecutive duplicates, lower for more repeats.
        """
        sorted_events = sorted(events, key=lambda e: e.timestamp)
        
        consecutive_dupes = 0
        comparisons = 0
        
        for i in range(1, len(sorted_events)):
            prev = sorted_events[i - 1]
            curr = sorted_events[i]
            
            if prev.event_type == curr.event_type:
                comparisons += 1
                if prev.animation_style == curr.animation_style:
                    consecutive_dupes += 1
        
        if comparisons == 0:
            return 1.0
        
        dupe_ratio = consecutive_dupes / comparisons
        return max(0.0, 1.0 - dupe_ratio * 2.0)  # Heavy penalty for dupes
    
    def _score_spatial_clarity(self, events: list, total_elements: int, audio_duration: float) -> float:
        """Spatial safety scoring: penalize overflow risk & missing density awareness.
        
        Dimensions scored:
        1. Element count sanity: 1-5 = full score, 6-7 = minor penalty, 8+ = heavy penalty
        2. Scale hierarchy: check if ENTER events have scale_rank params
        3. Camera zoom safety: penalize zoom events with scale_factor > 1.20
        4. Element density: more elements need proportionally smaller scale factors
        """
        if total_elements == 0:
            return 0.5  # Neutral
        
        from generator.video_generator.visual_director import EventType
        
        # 1. Element count sanity (40% weight)
        if total_elements <= 5:
            count_score = 1.0
        elif total_elements <= 7:
            count_score = 0.7
        else:
            count_score = max(0.3, 1.0 - (total_elements - 5) * 0.1)
        
        # 2. Scale hierarchy compliance (30% weight)
        # Check that ENTER events carry scale_rank params with density awareness
        enter_events = [e for e in events if e.event_type == EventType.ENTER] if events else []
        if enter_events:
            has_hierarchy = sum(
                1 for e in enter_events
                if e.params.get("scale_rank") and e.params.get("element_count")
            )
            hierarchy_score = min(1.0, has_hierarchy / max(1, len(enter_events)))
        else:
            hierarchy_score = 0.5
        
        # 3. Camera zoom safety (20% weight)
        # Penalize any zoom events with excessive scale factors
        camera_events = [e for e in events if e.event_type == EventType.CAMERA] if events else []
        if camera_events:
            unsafe_zooms = sum(
                1 for e in camera_events
                if e.params.get("scale_factor", 1.0) > 1.20
            )
            zoom_score = max(0.0, 1.0 - unsafe_zooms * 0.3)
        else:
            zoom_score = 1.0  # No camera events = safe
        
        # 4. Density factor present (10% weight)
        # Did the director pass element_count context?
        if enter_events and any(e.params.get("element_count") for e in enter_events):
            density_awareness_score = 1.0
        else:
            density_awareness_score = 0.3
        
        return (
            0.40 * count_score +
            0.30 * hierarchy_score +
            0.20 * zoom_score +
            0.10 * density_awareness_score
        )
    
    def score_video(
        self,
        timelines: list,
        audio_durations: List[float],
        element_counts: List[int] = None,
        beat_counts: List[int] = None,
    ) -> VideoScore:
        """
        Score an entire video (all segments).
        
        Args:
            timelines: List of VisualTimelines
            audio_durations: List of audio durations per segment
            element_counts: Optional list of element counts per segment
            beat_counts: Optional list of beat counts per segment
            
        Returns:
            VideoScore with per-segment and aggregate scores
        """
        if element_counts is None:
            element_counts = [0] * len(timelines)
        if beat_counts is None:
            beat_counts = [0] * len(timelines)
        
        segment_scores = []
        
        for i, (tl, dur) in enumerate(zip(timelines, audio_durations)):
            elem_count = element_counts[i] if i < len(element_counts) else 0
            beat_count = beat_counts[i] if i < len(beat_counts) else 0
            
            score = self.score_timeline(tl, dur, elem_count, beat_count)
            segment_scores.append(score)
        
        # Aggregate
        if segment_scores:
            overall = sum(s.overall for s in segment_scores) / len(segment_scores)
            worst_idx = min(range(len(segment_scores)), key=lambda i: segment_scores[i].overall)
        else:
            overall = 0.0
            worst_idx = -1
        
        video_score = VideoScore(
            segment_scores=segment_scores,
            overall=overall,
            worst_segment_index=worst_idx
        )
        
        logger.info(
            f"🎬 Video Score: {overall:.2f} ({video_score.action}) "
            f"| Worst segment: #{worst_idx + 1}"
        )
        
        return video_score


# =============================================================================
# PIPELINE HEALTH CHECK
# =============================================================================

class PipelineHealthCheck:
    """Post-generation health check for the pipeline."""
    
    def check(self, video_score: VideoScore) -> List[str]:
        """
        Run health checks and return alerts.
        
        Returns:
            List of alert messages (empty = healthy)
        """
        alerts = []
        
        for i, score in enumerate(video_score.segment_scores):
            if score.overall < 0.4:
                alerts.append(
                    f"🔴 CRITICAL: Segment {i+1} scored {score.overall:.2f} "
                    f"(density={score.animation_density:.2f}, gaps={score.static_gap_count})"
                )
            
            if score.max_static_gap > 3.0:
                alerts.append(
                    f"🟡 WARNING: Segment {i+1} has {score.max_static_gap:.1f}s static gap"
                )
            
            if score.element_utilization < 0.5:
                alerts.append(
                    f"🟡 WARNING: Segment {i+1} uses only "
                    f"{score.element_utilization:.0%} of elements"
                )
            
            if score.cinematic_depth < 0.3:
                alerts.append(
                    f"🟡 WARNING: Segment {i+1} has low cinematic depth "
                    f"({score.cinematic_depth:.2f}) — missing MOVE/TRANSFORM/CAMERA events"
                )
            
            if score.momentum_score < 0.5:
                alerts.append(
                    f"🟡 WARNING: Segment {i+1} has low momentum "
                    f"({score.momentum_score:.2f}) — elements inactive too long (Solution A)"
                )
            
            if score.rhythm_score < 0.4:
                alerts.append(
                    f"🟡 WARNING: Segment {i+1} has flat energy curve "
                    f"({score.rhythm_score:.2f}) — missing energy peaks (Solution D)"
                )
            
            if score.variety_enforcement < 0.5:
                alerts.append(
                    f"🟡 WARNING: Segment {i+1} has repetitive patterns "
                    f"({score.variety_enforcement:.2f}) — consecutive identical animations (Solution G)"
                )
            
            if score.spatial_clarity < 0.5:
                alerts.append(
                    f"🟡 WARNING: Segment {i+1} has spatial clarity issues "
                    f"({score.spatial_clarity:.2f}) — possible overflow/crowding risk"
                )
        
        total_gaps = sum(s.static_gap_count for s in video_score.segment_scores)
        if total_gaps > len(video_score.segment_scores):
            alerts.append(
                f"🟠 WARNING: {total_gaps} total static gaps across all segments"
            )
        
        if video_score.overall < 0.6:
            alerts.append(
                f"🔴 CRITICAL: Overall video score {video_score.overall:.2f} "
                f"below shipping threshold (0.6)"
            )
        
        if alerts:
            for alert in alerts:
                logger.warning(alert)
        else:
            logger.info("✅ Pipeline health check passed — no issues detected")
        
        return alerts
