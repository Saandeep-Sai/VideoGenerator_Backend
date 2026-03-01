"""
Visual Director — Attention-First Choreography Engine
======================================================

Converts scene specifications into timed visual event timelines.
Replaces generic animation sequencing with narration-synced,
pacing-aware visual choreography.

Pipeline position:
    SceneSpec + AudioDuration → VisualDirector → VisualTimeline → ManimCodeGenerator

Key principles:
    1. No visual gap > 1.5 seconds
    2. Animation density ≥ 0.8 events/sec
    3. New element every 3-4 seconds
    4. Scene-type-specific pacing (INTRO front-loaded, CONTENT builds, OUTRO punchy)
    5. Beat-synced animations tied to narration phrases
"""

import logging
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class EventType(Enum):
    """Types of visual events in the timeline."""
    ENTER = "enter"              # Element appears on screen
    EMPHASIZE = "emphasize"      # Draw attention to existing element
    TRANSFORM = "transform"      # Element changes visually
    MOVE = "move"                # Element repositions
    EXIT = "exit"                # Element leaves screen
    CAMERA = "camera"            # Virtual camera movement (zoom/pan)
    TRANSITION = "transition"    # Scene transition effect
    GAP_FILLER = "gap_filler"    # Micro-animation to prevent static gaps


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class TimedVisualEvent:
    """A single visual event with exact timing."""
    timestamp: float              # When this happens (seconds from segment start)
    duration: float               # How long it takes
    event_type: EventType         # ENTER, EMPHASIZE, TRANSFORM, MOVE, EXIT, etc.
    target_element: str           # Element ID
    animation_style: str          # Specific Manim animation name
    params: Dict[str, Any] = field(default_factory=dict)
    sync_phrase: Optional[str] = None  # Narration phrase this syncs with
    
    @property
    def end_time(self) -> float:
        return self.timestamp + self.duration


@dataclass
class PacingProfile:
    """Rhythm metadata for a scene type."""
    scene_type: str               # INTRO, CONTENT, OUTRO
    intensity_curve: List[float]  # Per-segment intensity 0.0-1.0
    event_density: float          # Target events per second
    max_static_gap: float         # Max seconds without visual change
    entry_style: str              # Default entry animation
    emphasis_style: str           # Default emphasis animation
    exit_style: str               # Default exit animation


@dataclass
class VisualTimeline:
    """Complete visual plan for one scene."""
    scene_id: str
    events: List[TimedVisualEvent] = field(default_factory=list)
    pacing: Optional[PacingProfile] = None
    total_duration: float = 0.0
    
    @property
    def event_count(self) -> int:
        return len(self.events)
    
    @property
    def density(self) -> float:
        if self.total_duration <= 0:
            return 0.0
        return self.event_count / self.total_duration
    
    def get_static_gaps(self, threshold: float = 1.5) -> List[Tuple[float, float]]:
        """Find gaps between events that exceed threshold."""
        if not self.events:
            return [(0.0, self.total_duration)]
        
        sorted_events = sorted(self.events, key=lambda e: e.timestamp)
        gaps = []
        
        # Check gap before first event
        if sorted_events[0].timestamp > threshold:
            gaps.append((0.0, sorted_events[0].timestamp))
        
        # Check gaps between events
        for i in range(len(sorted_events) - 1):
            gap_start = sorted_events[i].end_time
            gap_end = sorted_events[i + 1].timestamp
            if gap_end - gap_start > threshold:
                gaps.append((gap_start, gap_end))
        
        # Check gap after last event
        last_end = sorted_events[-1].end_time
        if self.total_duration - last_end > threshold:
            gaps.append((last_end, self.total_duration))
        
        return gaps


# =============================================================================
# PACING PROFILES — Scene-type-specific rhythm
# =============================================================================

PACING_PROFILES = {
    "INTRO": PacingProfile(
        scene_type="INTRO",
        intensity_curve=[1.0, 0.9, 0.8, 0.7],  # Front-loaded: grab attention FAST
        event_density=2.0,          # Cinematic: high event density from the start
        max_static_gap=0.6,         # Cinematic: never let the screen breathe too long
        entry_style="GrowFromCenter",
        emphasis_style="Flash",
        exit_style="FadeOut"
    ),
    "CONTENT": PacingProfile(
        scene_type="CONTENT",
        intensity_curve=[0.6, 0.8, 1.0, 0.9],  # Build to peak, hold strong
        event_density=1.8,          # Cinematic: was 1.3 — Grade A demands ≥1.5
        max_static_gap=0.8,         # Cinematic: was 1.2 — no dead air
        entry_style="DrawBorderThenFill",
        emphasis_style="Indicate",
        exit_style="FadeOut"
    ),
    "OUTRO": PacingProfile(
        scene_type="OUTRO",
        intensity_curve=[0.7, 0.9, 1.0, 1.0],  # End STRONG and SUSTAIN
        event_density=2.0,          # Cinematic: punchy finish
        max_static_gap=0.6,         # Cinematic: tight
        entry_style="GrowFromCenter",
        emphasis_style="Circumscribe",
        exit_style="FadeOut"
    ),
}

# Default for unknown scene types
DEFAULT_PACING = PACING_PROFILES["CONTENT"]


# =============================================================================
# ANIMATION POOLS — Variety selection per event type
# =============================================================================

ENTRY_ANIMATIONS = [
    "GrowFromCenter",
    "DrawBorderThenFill",
    "FadeIn_UP",           # FadeIn with shift=UP*0.5
    "FadeIn_RIGHT",        # FadeIn with shift=RIGHT*0.5
    "FadeIn_LEFT",         # FadeIn with shift=LEFT*0.5
    "GrowFromEdge_LEFT",   # GrowFromEdge(LEFT)
    "GrowFromEdge_DOWN",   # GrowFromEdge(DOWN)
    "SpinInFromNothing",
    "GrowFromEdge_RIGHT",  # Cinematic: variety
    "FadeIn_DOWN",         # Cinematic: top-down reveals
]

EMPHASIS_ANIMATIONS = [
    "Indicate",
    "Flash",
    "Circumscribe",
    "Wiggle",
    "ScalePulse",          # scale(1.2) then scale(1/1.2)
    "Circumscribe_GOLD",   # Circumscribe with GOLD color
    "Flash_BLUE",          # Flash with blue color
    "Indicate_WHITE",      # Indicate with WHITE for contrast
    "FocusZoom",           # Scale up briefly to draw eye
]

EXIT_ANIMATIONS = [
    "FadeOut_DOWN",     # FadeOut with shift=DOWN*0.3
    "FadeOut",
    "FadeOut_LEFT",     # FadeOut with shift=LEFT*0.3
    "ShrinkToCenter",   # Cinematic: variety for exits
]

# Cinematic MOVE animations — element repositioning for diagram building
MOVE_ANIMATIONS = [
    "SlideToPosition",     # Smooth move to new grid position
    "ArcToPosition",       # Curved arc movement (more cinematic)
    "DriftToPosition",     # Slow drift with ease-in-out
]

# Cinematic TRANSFORM animations — element evolution
TRANSFORM_ANIMATIONS = [
    "MorphTransform",      # Shape morphs into new form
    "ScaleTransform",      # Size changes to show emphasis shift
    "ColorTransform",      # Color shifts to show state change
]

# Cinematic CAMERA animations — virtual camera focus
CAMERA_ANIMATIONS = [
    "ZoomIn",              # Zoom into key element
    "ZoomOut",             # Zoom out to reveal full diagram
    "FocusPulse",          # Brief zoom in + out on element
]

GAP_FILLER_ANIMATIONS = [
    "subtle_pulse",     # Gentle scale pulse
    "color_shift",      # Slight color change
    "position_drift",   # Small drift
    "glow_pulse",       # Soft glow
    "gentle_rotate",    # Slight rotation wobble
    "micro_bounce",     # Cinematic: tiny bounce to keep alive
    "opacity_breathe",  # Cinematic: subtle opacity wave
]

# === Solution D: Energy bursts — simultaneous animation clusters every 5-7s ===
ENERGY_BURST_ANIMATIONS = [
    "ScalePulse",
    "Flash",
    "Wiggle",
    "Circumscribe",
    "FocusZoom",
    "Flash_BLUE",
    "Indicate_WHITE",
]

# === Solution A: Continuous activity — keep elements alive between major events ===
CONTINUOUS_ACTIVITY_ANIMATIONS = [
    "subtle_pulse",
    "micro_bounce",
    "gentle_rotate",
    "position_drift",
    "opacity_breathe",
    "glow_pulse",
]

# === Solution B: Lateral camera movements for attention guidance ===
LATERAL_CAMERA_ANIMATIONS = [
    "PanLeft",          # Lateral shift left to follow flow
    "PanRight",         # Lateral shift right to follow flow
    "FocusIsolate",     # Zoom in + dim others
    "RackFocus",        # Shift focus between two elements
]


# =============================================================================
# VISUAL DIRECTOR
# =============================================================================

class VisualDirector:
    """
    Converts scene specifications into timed visual event timelines.
    
    This is the choreography engine that ensures:
    - Animations sync with narration beats
    - No static gaps exceed pacing thresholds
    - Scene type dictates rhythm and intensity
    - Animation variety prevents repetition
    """
    
    def __init__(self):
        self._last_entry_idx = 0
        self._last_emphasis_idx = 0
        self._last_exit_idx = 0
        self._last_move_idx = 0
        self._last_camera_idx = 0
        self._recent_styles = []       # Solution G: track last N styles for variety
        self._max_recent = 4           # Don't repeat same style within last 4 events
    
    def plan_timeline(
        self,
        spec,  # SceneSpecification
        audio_duration: float,
        scene_type: str = "CONTENT"
    ) -> VisualTimeline:
        """
        Create a complete visual timeline for one scene.
        
        Args:
            spec: SceneSpecification with elements, beats, transformations
            audio_duration: Exact audio duration in seconds
            scene_type: INTRO, CONTENT, or OUTRO
            
        Returns:
            VisualTimeline with timed events
        """
        pacing = PACING_PROFILES.get(scene_type.upper(), DEFAULT_PACING)
        
        timeline = VisualTimeline(
            scene_id=getattr(spec, 'scene_id', 'scene_000') if hasattr(spec, 'scene_id') else 'scene_000',
            pacing=pacing,
            total_duration=audio_duration
        )
        
        # Extract data from spec
        elements = spec.visual_metaphor.visual_elements if spec.visual_metaphor else []
        beats = spec.narration.semantic_beats if spec.narration else []
        narration_text = spec.narration.text if spec.narration else ""
        
        if not elements:
            logger.warning("⚠️ No visual elements in spec — generating minimal timeline")
            return timeline
        
        element_ids = [e.id for e in elements]
        
        # Spatial safety: element count drives density awareness
        self._element_count = len(element_ids)
        
        # =====================================================
        # STEP 1: Estimate beat timing from narration
        # =====================================================
        beat_timings = self._estimate_beat_timings(
            narration=narration_text,
            beats=beats,
            total_duration=audio_duration
        )
        
        # =====================================================
        # STEP 2: Schedule element entries (with scaling hierarchy — Solution F)
        # =====================================================
        self._schedule_entries(
            timeline=timeline,
            element_ids=element_ids,
            beat_timings=beat_timings,
            pacing=pacing,
            audio_duration=audio_duration
        )
        
        # =====================================================
        # STEP 3: Schedule beat-synced emphasis (interaction-first — Solution E)
        # =====================================================
        self._schedule_beat_emphasis(
            timeline=timeline,
            beat_timings=beat_timings,
            element_ids=element_ids,
            pacing=pacing
        )
        
        # =====================================================
        # STEP 4: Schedule interactions (MOVE/TRANSFORM)
        # =====================================================
        self._schedule_interactions(
            timeline=timeline,
            element_ids=element_ids,
            beat_timings=beat_timings,
            pacing=pacing,
            audio_duration=audio_duration
        )
        
        # =====================================================
        # STEP 4b: Schedule causal transforms (Solution C)
        # =====================================================
        self._schedule_causal_transforms(
            timeline=timeline,
            element_ids=element_ids,
            beat_timings=beat_timings,
            audio_duration=audio_duration
        )
        
        # =====================================================
        # STEP 5: Schedule camera events (expanded — Solution B)
        # =====================================================
        self._schedule_camera_events(
            timeline=timeline,
            element_ids=element_ids,
            beat_timings=beat_timings,
            pacing=pacing,
            audio_duration=audio_duration
        )
        
        # =====================================================
        # STEP 5b: Schedule continuous activity (Solution A)
        # =====================================================
        self._schedule_continuous_activity(
            timeline=timeline,
            element_ids=element_ids,
            audio_duration=audio_duration
        )
        
        # =====================================================
        # STEP 5c: Schedule energy peaks (Solution D)
        # =====================================================
        self._schedule_energy_peaks(
            timeline=timeline,
            element_ids=element_ids,
            audio_duration=audio_duration
        )
        
        # =====================================================
        # STEP 6: Schedule exits
        # =====================================================
        self._schedule_exits(
            timeline=timeline,
            element_ids=element_ids,
            audio_duration=audio_duration,
            pacing=pacing
        )
        
        # =====================================================
        # STEP 7: Fill static gaps
        # =====================================================
        self._fill_gaps(
            timeline=timeline,
            element_ids=element_ids,
            pacing=pacing
        )
        
        # =====================================================
        # STEP 8: Enforce animation variety (Solution G)
        # =====================================================
        self._enforce_variety(timeline)
        
        # Sort events by timestamp
        timeline.events.sort(key=lambda e: e.timestamp)
        
        logger.info(
            f"📐 VisualDirector: {timeline.event_count} events, "
            f"density={timeline.density:.2f}/s, "
            f"gaps={len(timeline.get_static_gaps(pacing.max_static_gap))}"
        )
        
        return timeline
    
    # =========================================================================
    # BEAT TIMING ESTIMATION
    # =========================================================================
    
    def _estimate_beat_timings(
        self,
        narration: str,
        beats: list,
        total_duration: float
    ) -> List[Tuple[Any, float, float]]:
        """
        Estimate when each semantic beat occurs in the narration.
        Returns list of (beat, start_time, duration) tuples.
        """
        if not narration or not beats:
            return []
        
        words = narration.split()
        total_words = len(words)
        if total_words == 0:
            return []
        
        words_per_second = total_words / total_duration
        beat_timings = []
        
        for beat in beats:
            beat_phrase = beat.beat_phrase.lower().strip()
            narration_lower = narration.lower()
            
            phrase_start = narration_lower.find(beat_phrase)
            
            if phrase_start == -1:
                # Phrase not found — estimate from beat order
                beat_index = beats.index(beat)
                fraction = (beat_index + 0.5) / max(1, len(beats))
                start_time = fraction * total_duration
            else:
                words_before = narration[:phrase_start].split()
                start_time = len(words_before) / words_per_second
            
            start_time = max(0.0, min(start_time, total_duration - 1.0))
            
            phrase_words = len(beat_phrase.split())
            duration = max(0.6, min(1.5, phrase_words / words_per_second))
            
            beat_timings.append((beat, start_time, duration))
        
        beat_timings.sort(key=lambda x: x[1])
        return beat_timings
    
    # =========================================================================
    # ENTRY SCHEDULING
    # =========================================================================
    
    def _schedule_entries(
        self,
        timeline: VisualTimeline,
        element_ids: List[str],
        beat_timings: list,
        pacing: PacingProfile,
        audio_duration: float
    ):
        """Schedule element entries — some immediate, some beat-synced."""
        
        if not element_ids:
            return
        
        # Build map: element_id → first beat that targets it
        elem_to_beat = {}
        for beat, start_time, duration in beat_timings:
            for target_id in getattr(beat, 'target_elements', []):
                if target_id not in elem_to_beat and target_id in element_ids:
                    elem_to_beat[target_id] = (start_time, duration, beat)
        
        # Cinematic: 2 elements appear immediately for ALL scene types
        # (builds visual density from the start — no empty screen)
        immediate_count = 2
        immediate_elements = element_ids[:immediate_count]
        deferred_elements = element_ids[immediate_count:]
        
        # Schedule immediate entries
        entry_time = 0.1
        for idx, elem_id in enumerate(immediate_elements):
            anim = self._next_entry_animation()
            # Solution F: Scaling hierarchy — first element is primary (largest)
            # Density-aware: reduce all scales when many elements present
            density_factor = self._density_scale_factor()
            scale_rank = "primary" if idx == 0 else "secondary"
            scale_factor = (1.0 if idx == 0 else 0.85) * density_factor
            timeline.events.append(TimedVisualEvent(
                timestamp=entry_time,
                duration=min(1.8, audio_duration * 0.12),
                event_type=EventType.ENTER,
                target_element=elem_id,
                animation_style=anim,
                params={
                    "shift": "UP*0.5" if "FadeIn" in anim else "",
                    "scale_rank": scale_rank,
                    "scale_factor": scale_factor,
                    "element_count": getattr(self, '_element_count', 3),
                }
            ))
            entry_time += 0.4  # Stagger immediate entries
        
        # Schedule deferred entries — synced to beats or evenly spaced
        if deferred_elements:
            # Calculate spacing for elements not tied to beats
            available_window = audio_duration * 0.7  # Use first 70% for entries
            spacing = available_window / (len(deferred_elements) + 1)
            
            for idx, elem_id in enumerate(deferred_elements):
                if elem_id in elem_to_beat:
                    # This element has a beat — enter just before the beat
                    beat_start = elem_to_beat[elem_id][0]
                    entry_ts = max(0.5, beat_start - 0.3)
                    beat_obj = elem_to_beat[elem_id][2]
                    sync_phrase = getattr(beat_obj, 'beat_phrase', None)
                else:
                    # No beat — space evenly
                    entry_ts = spacing * (idx + 1) + entry_time
                    sync_phrase = None
                # Density-aware: reduce all scales when many elements present
                density_factor = self._density_scale_factor()
                overall_idx = immediate_count + idx
                if overall_idx <= 1:
                    scale_rank = "secondary"
                    scale_factor = 0.85 * density_factor
                else:
                    scale_rank = "supporting"
                    scale_factor = 0.75 * density_factor
                timeline.events.append(TimedVisualEvent(
                    timestamp=min(entry_ts, audio_duration * 0.75),
                    duration=min(1.5, audio_duration * 0.10),
                    event_type=EventType.ENTER,
                    target_element=elem_id,
                    animation_style=anim,
                    params={
                        "shift": "UP*0.5" if "FadeIn" in anim else "",
                        "scale_rank": scale_rank,
                        "scale_factor": scale_factor,
                        "element_count": getattr(self, '_element_count', 3)
                    },
                    sync_phrase=sync_phrase
                ))
    
    # =========================================================================
    # BEAT-SYNCED EMPHASIS
    # =========================================================================
    
    def _schedule_beat_emphasis(
        self,
        timeline: VisualTimeline,
        beat_timings: list,
        element_ids: List[str],
        pacing: PacingProfile
    ):
        """Schedule beat-synced events — interaction-first rule (Solution E).
        
        Every beat MUST trigger at least one of: interaction (MOVE/TRANSFORM),
        emphasis, or spatial change. Not just passive emphasis — at least 40%
        of beats trigger a MOVE or TRANSFORM to create causal feel.
        """
        
        if not beat_timings:
            return
        
        # Solution E: Force at least 40% of beats to be MOVE or TRANSFORM
        total_beats = len(beat_timings)
        interaction_quota = max(1, int(total_beats * 0.4))
        interaction_count = 0
        
        for beat_idx, (beat, start_time, duration) in enumerate(beat_timings):
            targets = getattr(beat, 'target_elements', [])
            
            if not targets:
                entered = self._get_entered_elements_at(timeline, start_time)
                if entered:
                    targets = [entered[-1]]
                else:
                    continue
            
            for elem_id in targets:
                if elem_id not in element_ids:
                    continue
                
                entered = self._get_entered_elements_at(timeline, start_time)
                if elem_id not in entered:
                    continue
                
                # Solution E: Decide event type — interaction or emphasis
                # Alternate: every other beat gets MOVE/TRANSFORM until quota met
                if interaction_count < interaction_quota and beat_idx % 2 == 1:
                    # MOVE or TRANSFORM event instead of just emphasis
                    if len(entered) >= 2 and random.random() < 0.5:
                        # MOVE: shift toward another element
                        other = [e for e in entered if e != elem_id]
                        if other:
                            move_target = random.choice(other)
                            timeline.events.append(TimedVisualEvent(
                                timestamp=start_time,
                                duration=min(duration, 1.5),
                                event_type=EventType.MOVE,
                                target_element=elem_id,
                                animation_style=random.choice(MOVE_ANIMATIONS),
                                params={"toward": move_target, "fraction": 0.15},
                                sync_phrase=getattr(beat, 'beat_phrase', None)
                            ))
                            interaction_count += 1
                            continue
                    
                    # TRANSFORM: visual evolution
                    timeline.events.append(TimedVisualEvent(
                        timestamp=start_time,
                        duration=min(duration, 1.2),
                        event_type=EventType.TRANSFORM,
                        target_element=elem_id,
                        animation_style=random.choice(TRANSFORM_ANIMATIONS),
                        params={"scale_factor": 1.12, "color": "GOLD"},
                        sync_phrase=getattr(beat, 'beat_phrase', None)
                    ))
                    interaction_count += 1
                else:
                    # Standard emphasis (but with variety)
                    anim = self._next_emphasis_animation()
                    timeline.events.append(TimedVisualEvent(
                        timestamp=start_time,
                        duration=min(duration, 1.2),
                        event_type=EventType.EMPHASIZE,
                        target_element=elem_id,
                        animation_style=anim,
                        params={"color": "GOLD", "scale_factor": 1.15},
                        sync_phrase=getattr(beat, 'beat_phrase', None)
                    ))
    
    # =========================================================================
    # INTERACTION SCHEDULING (MOVE / TRANSFORM — Progressive Diagram Building)
    # =========================================================================
    
    def _schedule_interactions(
        self,
        timeline: VisualTimeline,
        element_ids: List[str],
        beat_timings: list,
        pacing: PacingProfile,
        audio_duration: float
    ):
        """Schedule MOVE and TRANSFORM events for progressive diagram construction.
        
        Cinematic principle: Elements don't just appear and sit — they REPOSITION
        to form relationships, TRANSFORM to show state changes, and DRIFT to
        guide attention through the visual narrative.
        """
        if len(element_ids) < 2:
            return  # Need at least 2 elements for interactions
        
        # --- MOVE events: Reposition elements to build spatial relationships ---
        # After 40% of duration, shift an early element toward a later element
        # (simulates "these concepts connect")
        move_time = audio_duration * 0.40
        entered_at_move = self._get_entered_elements_at(timeline, move_time)
        
        if len(entered_at_move) >= 2:
            # Move the first entered element slightly toward the second (closing the gap)
            mover = entered_at_move[0]
            target = entered_at_move[1]
            move_anim = random.choice(MOVE_ANIMATIONS)
            timeline.events.append(TimedVisualEvent(
                timestamp=move_time,
                duration=min(1.2, audio_duration * 0.08),
                event_type=EventType.MOVE,
                target_element=mover,
                animation_style=move_anim,
                params={"toward": target, "fraction": 0.25},
                sync_phrase=None
            ))
        
        # --- TRANSFORM events: Shape/color evolution at beat moments ---
        # Pick 1-2 beats in the middle of the scene for TRANSFORM events
        mid_beats = [
            (beat, t, d) for beat, t, d in beat_timings
            if 0.3 * audio_duration < t < 0.7 * audio_duration
        ]
        
        transform_count = 0
        for beat, beat_time, beat_dur in mid_beats[:2]:
            targets = getattr(beat, 'target_elements', [])
            if not targets:
                continue
            
            elem_id = targets[0]
            if elem_id not in element_ids:
                continue
            
            entered = self._get_entered_elements_at(timeline, beat_time)
            if elem_id not in entered:
                continue
            
            transform_anim = random.choice(TRANSFORM_ANIMATIONS)
            timeline.events.append(TimedVisualEvent(
                timestamp=beat_time + beat_dur * 0.5,  # Mid-beat transform
                duration=min(0.8, beat_dur),
                event_type=EventType.TRANSFORM,
                target_element=elem_id,
                animation_style=transform_anim,
                params={"scale_factor": 1.15, "color": "GOLD"},
                sync_phrase=getattr(beat, 'beat_phrase', None)
            ))
            transform_count += 1
        
        # --- Second MOVE: Late-scene convergence (elements tighten into final diagram) ---
        if len(element_ids) >= 3 and audio_duration > 8:
            converge_time = audio_duration * 0.65
            entered_late = self._get_entered_elements_at(timeline, converge_time)
            if len(entered_late) >= 3:
                # Move the third element slightly toward center (convergence)
                timeline.events.append(TimedVisualEvent(
                    timestamp=converge_time,
                    duration=min(1.0, audio_duration * 0.07),
                    event_type=EventType.MOVE,
                    target_element=entered_late[2],
                    animation_style=random.choice(MOVE_ANIMATIONS),
                    params={"toward": "center", "fraction": 0.2},
                    sync_phrase=None
                ))
        
        if transform_count > 0:
            logger.debug(f"🔄 Scheduled {transform_count} TRANSFORM events")
    
    # =========================================================================
    # CAMERA EVENT SCHEDULING (Virtual Zoom / Focus)
    # =========================================================================
    
    def _schedule_camera_events(
        self,
        timeline: VisualTimeline,
        element_ids: List[str],
        beat_timings: list,
        pacing: PacingProfile,
        audio_duration: float
    ):
        """Schedule CAMERA events — Solution B: Camera as Attention Guide.
        
        The camera ACTIVELY guides attention through zoom, lateral shifts,
        focus isolation, and rack focus. Not a passive tripod — a director's eye.
        
        Target: 4-6 camera events per scene (was 2-3).
        """
        if not element_ids:
            return
        
        camera_events_added = 0
        
        # --- 1. FOCUS PULSE on first element right after entry ---
        if element_ids and audio_duration > 4:
            first_entry_time = None
            for ev in timeline.events:
                if ev.event_type == EventType.ENTER and ev.target_element == element_ids[0]:
                    first_entry_time = ev.end_time
                    break
            
            if first_entry_time and first_entry_time + 0.5 < audio_duration:
                timeline.events.append(TimedVisualEvent(
                    timestamp=first_entry_time + 0.2,
                    duration=0.9,
                    event_type=EventType.CAMERA,
                    target_element=element_ids[0],
                    animation_style="FocusPulse",
                    params={"scale_factor": 1.15},
                    sync_phrase=None
                ))
                camera_events_added += 1
        
        # --- 2. LATERAL PAN at 30% — guide eye across layout ---
        if len(element_ids) >= 2 and audio_duration > 6:
            pan_time = audio_duration * 0.30
            entered = self._get_entered_elements_at(timeline, pan_time)
            if len(entered) >= 2:
                timeline.events.append(TimedVisualEvent(
                    timestamp=pan_time,
                    duration=1.0,
                    event_type=EventType.CAMERA,
                    target_element=entered[1],
                    animation_style="PanRight",
                    params={"shift": "RIGHT*0.4"},
                    sync_phrase=None
                ))
                camera_events_added += 1
        
        # --- 3. ZOOM IN at narrative climax (60%) ---
        climax_time = audio_duration * 0.60
        best_beat = None
        best_dist = float('inf')
        
        for beat, t, d in beat_timings:
            dist = abs(t - climax_time)
            if dist < best_dist:
                best_dist = dist
                best_beat = (beat, t, d)
        
        if best_beat and element_ids:
            beat, beat_time, beat_dur = best_beat
            focus_elem = element_ids[0]
            # Density-aware camera zoom: reduce when many elements
            zoom_scale = 1.15 if getattr(self, '_element_count', 3) <= 4 else 1.08
            
            timeline.events.append(TimedVisualEvent(
                timestamp=beat_time,
                duration=min(1.2, beat_dur * 0.7),
                event_type=EventType.CAMERA,
                target_element=focus_elem,
                animation_style="ZoomIn",
                params={"scale_factor": zoom_scale},
                sync_phrase=getattr(beat, 'beat_phrase', None)
            ))
            camera_events_added += 1
            
            # Follow with ZOOM OUT to reveal full picture
            zoom_out_time = beat_time + beat_dur
            if zoom_out_time < audio_duration - 1.5:
                timeline.events.append(TimedVisualEvent(
                    timestamp=zoom_out_time,
                    duration=1.0,
                    event_type=EventType.CAMERA,
                    target_element=focus_elem,
                    animation_style="ZoomOut",
                    params={"scale_factor": 1.0},
                    sync_phrase=None
                ))
                camera_events_added += 1
        
        # --- 4. FOCUS ISOLATE at 45% — zoom into a secondary element ---
        if len(element_ids) >= 3 and audio_duration > 8:
            isolate_time = audio_duration * 0.45
            entered = self._get_entered_elements_at(timeline, isolate_time)
            if len(entered) >= 2:
                # Pick a secondary element (not the first)
                iso_target = entered[min(1, len(entered) - 1)]
                timeline.events.append(TimedVisualEvent(
                    timestamp=isolate_time,
                    duration=1.0,
                    event_type=EventType.CAMERA,
                    target_element=iso_target,
                    animation_style="FocusIsolate",
                    params={"scale_factor": 1.2, "dim_others": True},
                    sync_phrase=None
                ))
                camera_events_added += 1
        
        # --- 5. RACK FOCUS at 75% — shift attention between two elements ---
        if len(element_ids) >= 2 and audio_duration > 10:
            rack_time = audio_duration * 0.75
            entered = self._get_entered_elements_at(timeline, rack_time)
            if len(entered) >= 2:
                timeline.events.append(TimedVisualEvent(
                    timestamp=rack_time,
                    duration=1.0,
                    event_type=EventType.CAMERA,
                    target_element=entered[0],
                    animation_style="RackFocus",
                    params={"from_elem": entered[0], "to_elem": entered[-1]},
                    sync_phrase=None
                ))
                camera_events_added += 1
        
        # --- 6. Final LATERAL PAN at 85% — guide eye to conclusion ---
        if audio_duration > 6:
            final_pan_time = audio_duration * 0.85
            last_elem = element_ids[-1]
            timeline.events.append(TimedVisualEvent(
                timestamp=final_pan_time,
                duration=0.9,
                event_type=EventType.CAMERA,
                target_element=last_elem,
                animation_style="PanLeft",
                params={"shift": "LEFT*0.3"},
                sync_phrase=None
            ))
            camera_events_added += 1
        
        if camera_events_added > 0:
            logger.debug(f"🎥 Scheduled {camera_events_added} CAMERA events (Solution B)")
    
    # =========================================================================
    # EXIT SCHEDULING
    # =========================================================================
    
    def _schedule_exits(
        self,
        timeline: VisualTimeline,
        element_ids: List[str],
        audio_duration: float,
        pacing: PacingProfile
    ):
        """Schedule element exits — KEEP most elements visible, only exit early ones.
        
        KEY PRINCIPLE: Do NOT FadeOut all elements at the end. This creates
        blank frames between segments. Instead, only exit the first 1-2
        elements (to show progression) and keep the rest visible.
        """
        
        if not element_ids:
            return
        
        # Only exit the first 1-2 early-introduced elements (not all)
        # This prevents blank frames at segment end
        max_exits = min(2, len(element_ids) - 1)  # Always keep at least 1 element
        if max_exits <= 0:
            return  # Single element — keep it visible
        
        exit_elements = element_ids[:max_exits]
        
        # Exit window: last 10% of duration (smaller window — subtle exits)
        exit_start = audio_duration * 0.85
        exit_spacing = (audio_duration * 0.10) / max(1, len(exit_elements))
        exit_duration = min(0.8, exit_spacing * 0.7)
        
        for idx, elem_id in enumerate(exit_elements):
            anim = self._next_exit_animation()
            timestamp = exit_start + (idx * exit_spacing)
            
            timeline.events.append(TimedVisualEvent(
                timestamp=max(0, timestamp),
                duration=exit_duration,
                event_type=EventType.EXIT,
                target_element=elem_id,
                animation_style=anim,
                params={"shift": "DOWN*0.2"} if "FadeOut" in anim else {}
            ))
        
        # Add a final emphasis on the last remaining element instead of exit
        if len(element_ids) > max_exits:
            last_elem = element_ids[-1]
            timeline.events.append(TimedVisualEvent(
                timestamp=audio_duration - 1.0,
                duration=0.8,
                event_type=EventType.EMPHASIZE,
                target_element=last_elem,
                animation_style="Circumscribe",
                params={"color": "WHITE", "buff": 0.1}
            ))
    
    # =========================================================================
    # GAP FILLING
    # =========================================================================
    
    def _fill_gaps(
        self,
        timeline: VisualTimeline,
        element_ids: List[str],
        pacing: PacingProfile
    ):
        """Fill static gaps with micro-animations to maintain engagement."""
        
        if not element_ids:
            return
        
        gaps = timeline.get_static_gaps(pacing.max_static_gap)
        
        for gap_start, gap_end in gaps:
            gap_duration = gap_end - gap_start
            
            # Find elements visible during this gap
            visible = self._get_entered_elements_at(timeline, gap_start + gap_duration / 2)
            if not visible:
                visible = element_ids[:1]  # Fallback to first element
            
            # Insert 1-2 micro-animations per gap
            num_fillers = min(2, max(1, int(gap_duration / 1.5)))
            filler_spacing = gap_duration / (num_fillers + 1)
            
            for i in range(num_fillers):
                target = visible[i % len(visible)]
                filler_style = random.choice(GAP_FILLER_ANIMATIONS)
                filler_ts = gap_start + filler_spacing * (i + 1)
                
                timeline.events.append(TimedVisualEvent(
                    timestamp=filler_ts,
                    duration=min(0.9, filler_spacing * 0.7),
                    event_type=EventType.GAP_FILLER,
                    target_element=target,
                    animation_style=filler_style,
                    params={}
                ))
        
        if gaps:
            logger.info(f"🔧 Filled {len(gaps)} static gaps with micro-animations")
    
    # =========================================================================
    # CONTINUOUS ACTIVITY SCHEDULING (Solution A)
    # =========================================================================
    
    def _schedule_continuous_activity(
        self,
        timeline: VisualTimeline,
        element_ids: List[str],
        audio_duration: float
    ):
        """Solution A: No element inactive > 2 seconds.
        
        After an element enters, ensure it receives at least one event
        every 2 seconds. If a gap exists, insert a micro-activity
        (subtle pulse, micro bounce, drift) to maintain visual momentum.
        """
        if not element_ids:
            return
        
        MAX_INACTIVE = 2.0  # No element silent for more than 2 seconds
        activity_added = 0
        
        for elem_id in element_ids:
            # Find when this element enters
            entry_time = None
            exit_time = audio_duration
            
            for ev in timeline.events:
                if ev.target_element == elem_id:
                    if ev.event_type == EventType.ENTER:
                        entry_time = ev.end_time
                    elif ev.event_type == EventType.EXIT:
                        exit_time = ev.timestamp
            
            if entry_time is None:
                continue
            
            # Collect all events for this element after entry
            elem_events = sorted(
                [ev for ev in timeline.events
                 if ev.target_element == elem_id and ev.timestamp >= entry_time],
                key=lambda e: e.timestamp
            )
            
            # Walk through the element's visible window and find inactivity gaps
            check_time = entry_time + 0.5
            event_idx = 0
            
            while check_time < exit_time - 0.5:
                # Find next event for this element after check_time
                next_event_time = exit_time
                while event_idx < len(elem_events):
                    if elem_events[event_idx].timestamp > check_time:
                        next_event_time = elem_events[event_idx].timestamp
                        break
                    event_idx += 1
                else:
                    next_event_time = exit_time
                
                inactive_gap = next_event_time - check_time
                
                if inactive_gap > MAX_INACTIVE:
                    # Insert micro-activity at midpoint of gap
                    activity_time = check_time + MAX_INACTIVE * 0.8
                    activity_style = random.choice(CONTINUOUS_ACTIVITY_ANIMATIONS)
                    
                    timeline.events.append(TimedVisualEvent(
                        timestamp=activity_time,
                        duration=0.8,
                        event_type=EventType.GAP_FILLER,
                        target_element=elem_id,
                        animation_style=activity_style,
                        params={"source": "continuous_activity"}
                    ))
                    activity_added += 1
                    check_time = activity_time + 0.9
                else:
                    check_time = next_event_time + 0.3
        
        if activity_added > 0:
            logger.debug(f"🔄 Solution A: Added {activity_added} continuous activity events")
    
    # =========================================================================
    # CAUSAL TRANSFORM SCHEDULING (Solution C)
    # =========================================================================
    
    def _schedule_causal_transforms(
        self,
        timeline: VisualTimeline,
        element_ids: List[str],
        beat_timings: list,
        audio_duration: float
    ):
        """Solution C: Causal animation logic.
        
        When beats reference multiple elements, schedule TRANSFORMS that
        connect them causally — morphs over replacements, progressive building,
        arrow-draw simulation between concepts.
        """
        if len(element_ids) < 2 or not beat_timings:
            return
        
        causal_added = 0
        
        for beat, start_time, duration in beat_timings:
            targets = getattr(beat, 'target_elements', [])
            
            if len(targets) < 2:
                continue
            
            # Multiple elements in same beat → causal relationship
            entered = self._get_entered_elements_at(timeline, start_time)
            active_targets = [t for t in targets if t in entered and t in element_ids]
            
            if len(active_targets) < 2:
                continue
            
            # Schedule a TRANSFORM on the first element (cause)
            # and a MOVE on the second element (effect — pulled toward cause)
            cause_elem = active_targets[0]
            effect_elem = active_targets[1]
            
            # Cause: visual transformation (color shift/morph)
            timeline.events.append(TimedVisualEvent(
                timestamp=start_time,
                duration=min(1.0, duration * 0.6),
                event_type=EventType.TRANSFORM,
                target_element=cause_elem,
                animation_style="ColorTransform",
                params={"color": "GOLD", "causal": True},
                sync_phrase=getattr(beat, 'beat_phrase', None)
            ))
            causal_added += 1
            
            # Effect: move toward cause (pulled by relationship)
            timeline.events.append(TimedVisualEvent(
                timestamp=start_time + duration * 0.3,
                duration=min(0.9, duration * 0.5),
                event_type=EventType.MOVE,
                target_element=effect_elem,
                animation_style="ArcToPosition",
                params={"toward": cause_elem, "fraction": 0.15, "causal": True},
                sync_phrase=None
            ))
            causal_added += 1
            
            # Limit to 3 causal pairs per scene (increased from 2)
            if causal_added >= 6:
                break
        
        if causal_added > 0:
            logger.debug(f"🔗 Solution C: Added {causal_added} causal transform events")
    
    # =========================================================================
    # ENERGY RHYTHM CONTROL (Solution D)
    # =========================================================================
    
    def _schedule_energy_peaks(
        self,
        timeline: VisualTimeline,
        element_ids: List[str],
        audio_duration: float
    ):
        """Solution D: Energy peaks every 5-7 seconds.
        
        Insert energy bursts — clusters of 2-3 simultaneous animations —
        at regular intervals to create peaks/valleys in the energy curve.
        Prevents flat, constant-intensity viewing experience.
        """
        if not element_ids or audio_duration < 5:
            return
        
        PEAK_INTERVAL = 6.0  # Peak every 6 seconds
        peaks_added = 0
        
        # Calculate peak positions
        peak_time = 3.0  # First peak at 3s
        while peak_time < audio_duration - 2.0:
            visible = self._get_entered_elements_at(timeline, peak_time)
            if not visible:
                peak_time += PEAK_INTERVAL
                continue
            
            # Create an energy burst: 2-3 simultaneous emphasis events
            burst_count = min(len(visible), random.choice([2, 2, 3]))
            burst_elements = random.sample(visible, burst_count)
            
            for i, elem_id in enumerate(burst_elements):
                burst_style = ENERGY_BURST_ANIMATIONS[
                    (peaks_added * 3 + i) % len(ENERGY_BURST_ANIMATIONS)
                ]
                timeline.events.append(TimedVisualEvent(
                    timestamp=peak_time + i * 0.15,  # Slight stagger for visual cascade
                    duration=0.9,
                    event_type=EventType.EMPHASIZE,
                    target_element=elem_id,
                    animation_style=burst_style,
                    params={"energy_peak": True, "color": "GOLD"}
                ))
            
            peaks_added += 1
            peak_time += PEAK_INTERVAL
        
        if peaks_added > 0:
            logger.debug(f"⚡ Solution D: Added {peaks_added} energy peaks ({peaks_added * 2}-{peaks_added * 3} burst events)")
    
    # =========================================================================
    # VARIETY ENFORCEMENT (Solution G)
    # =========================================================================
    
    def _enforce_variety(self, timeline: VisualTimeline):
        """Solution G: No consecutive identical animation patterns.
        
        Post-process the timeline to detect consecutive events using the
        same animation_style and replace duplicates with alternatives.
        Ensures the viewer never sees the same pattern twice in a row.
        """
        if len(timeline.events) < 3:
            return
        
        sorted_events = sorted(timeline.events, key=lambda e: e.timestamp)
        replacements = 0
        
        for i in range(1, len(sorted_events)):
            prev = sorted_events[i - 1]
            curr = sorted_events[i]
            
            # Skip if different event types — variety within same type matters most
            if prev.event_type != curr.event_type:
                continue
            
            if prev.animation_style == curr.animation_style:
                # Replace current with an alternative
                new_style = self._get_alternative_style(
                    curr.event_type, curr.animation_style
                )
                if new_style != curr.animation_style:
                    curr.animation_style = new_style
                    replacements += 1
        
        if replacements > 0:
            logger.debug(f"🎨 Solution G: Replaced {replacements} consecutive duplicate animations")
    
    # =========================================================================
    # HELPERS
    # =========================================================================
    
    def _get_entered_elements_at(self, timeline: VisualTimeline, time: float) -> List[str]:
        """Get element IDs that have entered but not exited by a given time."""
        entered = set()
        exited = set()
        
        for event in timeline.events:
            if event.timestamp <= time:
                if event.event_type == EventType.ENTER:
                    entered.add(event.target_element)
                elif event.event_type == EventType.EXIT:
                    exited.add(event.target_element)
        
        return [e for e in entered if e not in exited]
    
    def _next_entry_animation(self) -> str:
        """Rotate through entry animations for variety."""
        anim = ENTRY_ANIMATIONS[self._last_entry_idx % len(ENTRY_ANIMATIONS)]
        self._last_entry_idx += 1
        return anim
    
    def _next_emphasis_animation(self) -> str:
        """Rotate through emphasis animations for variety."""
        anim = EMPHASIS_ANIMATIONS[self._last_emphasis_idx % len(EMPHASIS_ANIMATIONS)]
        self._last_emphasis_idx += 1
        return anim
    
    def _next_exit_animation(self) -> str:
        """Rotate through exit animations for variety."""
        anim = EXIT_ANIMATIONS[self._last_exit_idx % len(EXIT_ANIMATIONS)]
        self._last_exit_idx += 1
        return anim
    
    def _get_alternative_style(self, event_type: 'EventType', current_style: str) -> str:
        """Get an alternative animation style for variety enforcement (Solution G)."""
        pool_map = {
            EventType.ENTER: ENTRY_ANIMATIONS,
            EventType.EMPHASIZE: EMPHASIS_ANIMATIONS,
            EventType.EXIT: EXIT_ANIMATIONS,
            EventType.GAP_FILLER: GAP_FILLER_ANIMATIONS + CONTINUOUS_ACTIVITY_ANIMATIONS,
            EventType.MOVE: MOVE_ANIMATIONS,
            EventType.TRANSFORM: TRANSFORM_ANIMATIONS,
            EventType.CAMERA: CAMERA_ANIMATIONS + LATERAL_CAMERA_ANIMATIONS,
        }
        
    
    def _density_scale_factor(self) -> float:
        """Compute density-aware scale reduction based on element count.
        
        1-3 elements: 1.0 (full size)
        4-5 elements: 0.85 (15% reduction)
        6+  elements: 0.72 (28% reduction)
        """
        count = getattr(self, '_element_count', 3)
        if count <= 3:
            return 1.0
        elif count <= 5:
            return 0.85
        else:
            return 0.72
        pool = pool_map.get(event_type, EMPHASIS_ANIMATIONS)
        alternatives = [a for a in pool if a != current_style]
        
        if alternatives:
            return random.choice(alternatives)
        return current_style
