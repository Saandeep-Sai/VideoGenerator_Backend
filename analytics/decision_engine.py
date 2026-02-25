"""
Decision Engine
================

Rule-based decision engine for content intelligence.
NO machine learning. All decisions are explainable.

Decision Flow:
1. Ingest metrics from YouTube
2. Compute derived metrics
3. Evaluate rules in order
4. Write decision to Firestore
5. Trigger downstream actions

Hard Rules (Must Be Enforced):
- Kill Video: views_24h < median AND retention < 50%
- Series Continue: ep2.retention >= ep1.retention
- Series Expand: avg_retention >= 70% AND returning_viewer_growth > 0
- Topic Priority: repeat_viewer_ratio >= 0.3
"""

import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from enum import Enum
import statistics

from .firestore_schema import (
    VideoDocument, SeriesDocument, TopicClusterDocument,
    AnalyticsDecision, DecisionType, VideoStatus, SeriesStatus,
    TopicMomentum, VideoMetrics, DerivedMetrics
)

logger = logging.getLogger(__name__)


# =============================================================================
# DECISION RULES
# =============================================================================

@dataclass
class RuleResult:
    """Result of evaluating a decision rule."""
    rule_name: str
    triggered: bool
    decision: Optional[DecisionType] = None
    confidence: float = 0.0
    signals: List[str] = None
    
    def __post_init__(self):
        if self.signals is None:
            self.signals = []


class VideoRules:
    """Rules for individual video decisions."""
    
    @staticmethod
    def kill_video_rule(
        video: VideoDocument,
        channel_median_views_24h: float
    ) -> RuleResult:
        """
        Kill Video Rule:
        IF views_24h < channel_median AND avg_view_percentage < 50%
        → mark video.status = "low_signal"
        """
        views_below_median = video.metrics.views_24h < channel_median_views_24h
        retention_below_threshold = video.metrics.avg_view_percentage < 50.0
        
        signals = []
        if views_below_median:
            signals.append(f"views_24h ({video.metrics.views_24h}) < median ({channel_median_views_24h:.0f})")
        if retention_below_threshold:
            signals.append(f"avg_view_percentage ({video.metrics.avg_view_percentage:.1f}%) < 50%")
        
        triggered = views_below_median and retention_below_threshold
        
        return RuleResult(
            rule_name="kill_video",
            triggered=triggered,
            decision=DecisionType.TERMINATE if triggered else None,
            confidence=0.9 if triggered else 0.0,
            signals=signals
        )


class SeriesRules:
    """Rules for series-level decisions."""
    
    @staticmethod
    def series_continuation_rule(
        series: SeriesDocument,
        episode_videos: List[VideoDocument]
    ) -> RuleResult:
        """
        Series Continuation Rule:
        IF episode_2.avg_retention >= episode_1.avg_retention
        → allow episode_3
        ELSE
        → series.status = "terminated"
        """
        if len(episode_videos) < 2:
            return RuleResult(
                rule_name="series_continuation",
                triggered=False,
                signals=["insufficient episodes for comparison"]
            )
        
        # Sort by episode number
        sorted_episodes = sorted(episode_videos, key=lambda v: v.episode_number or 0)
        
        ep1 = sorted_episodes[-2]  # Second to last
        ep2 = sorted_episodes[-1]  # Last (most recent)
        
        ep1_retention = ep1.metrics.avg_view_percentage
        ep2_retention = ep2.metrics.avg_view_percentage
        
        retention_maintained = ep2_retention >= ep1_retention
        
        signals = [
            f"ep{ep1.episode_number}_retention: {ep1_retention:.1f}%",
            f"ep{ep2.episode_number}_retention: {ep2_retention:.1f}%",
            "retention_maintained" if retention_maintained else "retention_declined"
        ]
        
        if retention_maintained:
            return RuleResult(
                rule_name="series_continuation",
                triggered=True,
                decision=DecisionType.CONTINUE,
                confidence=0.75,
                signals=signals
            )
        else:
            return RuleResult(
                rule_name="series_continuation",
                triggered=True,
                decision=DecisionType.TERMINATE,
                confidence=0.8,
                signals=signals + ["TERMINATING: retention declined"]
            )
    
    @staticmethod
    def series_expansion_rule(
        series: SeriesDocument
    ) -> RuleResult:
        """
        Series Expansion Rule:
        IF avg_retention >= 70% AND returning_viewer_growth > 0
        → series.status = "expanding"
        """
        avg_retention = series.aggregate_metrics.avg_retention
        returning_growth = series.aggregate_metrics.returning_viewer_growth
        
        high_retention = avg_retention >= 70.0
        positive_returning = returning_growth > 0
        
        signals = [
            f"avg_retention: {avg_retention:.1f}%",
            f"returning_viewer_growth: {returning_growth:.2%}"
        ]
        
        triggered = high_retention and positive_returning
        
        return RuleResult(
            rule_name="series_expansion",
            triggered=triggered,
            decision=DecisionType.EXPAND if triggered else None,
            confidence=0.85 if triggered else 0.0,
            signals=signals
        )


class TopicRules:
    """Rules for topic cluster decisions."""
    
    @staticmethod
    def topic_priority_rule(
        cluster: TopicClusterDocument
    ) -> RuleResult:
        """
        Topic Priority Rule:
        IF repeat_viewer_ratio >= 0.3
        → prioritize this topic_cluster for new series
        """
        ratio = cluster.cluster_metrics.repeat_viewer_ratio
        
        triggered = ratio >= 0.3
        
        signals = [
            f"repeat_viewer_ratio: {ratio:.2%}",
            "HIGH_PRIORITY" if triggered else "NORMAL_PRIORITY"
        ]
        
        return RuleResult(
            rule_name="topic_priority",
            triggered=triggered,
            decision=DecisionType.EXPAND if triggered else None,
            confidence=0.7 if triggered else 0.0,
            signals=signals
        )


# =============================================================================
# DECISION ENGINE
# =============================================================================

class DecisionEngine:
    """
    Orchestrates rule evaluation and decision generation.
    
    Responsibilities:
    1. Accept metrics input
    2. Run all applicable rules
    3. Aggregate signals
    4. Generate final decision
    5. Return decision for persistence
    """
    
    def __init__(self, channel_median_views_24h: float = 1000.0):
        self.channel_median_views_24h = channel_median_views_24h
    
    def evaluate_video(
        self,
        video: VideoDocument
    ) -> AnalyticsDecision:
        """Evaluate all rules for a single video."""
        
        # Run kill rule
        kill_result = VideoRules.kill_video_rule(video, self.channel_median_views_24h)
        
        if kill_result.triggered and kill_result.decision == DecisionType.TERMINATE:
            return AnalyticsDecision(
                decision_id=f"decision_{video.video_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                entity_type="video",
                entity_id=video.video_id,
                decision=DecisionType.TERMINATE,
                confidence=kill_result.confidence,
                supporting_signals=kill_result.signals,
                timestamp=datetime.now(timezone.utc).isoformat()
            )
        
        # Video is healthy
        return AnalyticsDecision(
            decision_id=f"decision_{video.video_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            entity_type="video",
            entity_id=video.video_id,
            decision=DecisionType.CONTINUE,
            confidence=0.6,
            supporting_signals=["video_healthy", "no_termination_rules_triggered"],
            timestamp=datetime.now(timezone.utc).isoformat()
        )
    
    def evaluate_series(
        self,
        series: SeriesDocument,
        episode_videos: List[VideoDocument]
    ) -> AnalyticsDecision:
        """Evaluate all rules for a series."""
        
        all_signals = []
        final_decision = DecisionType.CONTINUE
        final_confidence = 0.5
        
        # 1. Check expansion rule first (positive outcome)
        expansion_result = SeriesRules.series_expansion_rule(series)
        all_signals.extend(expansion_result.signals)
        
        if expansion_result.triggered:
            final_decision = DecisionType.EXPAND
            final_confidence = expansion_result.confidence
        
        # 2. Check continuation rule (can override with termination)
        if len(episode_videos) >= 2:
            continuation_result = SeriesRules.series_continuation_rule(series, episode_videos)
            all_signals.extend(continuation_result.signals)
            
            if continuation_result.decision == DecisionType.TERMINATE:
                final_decision = DecisionType.TERMINATE
                final_confidence = continuation_result.confidence
        
        return AnalyticsDecision(
            decision_id=f"decision_{series.series_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            entity_type="series",
            entity_id=series.series_id,
            decision=final_decision,
            confidence=final_confidence,
            supporting_signals=all_signals,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
    
    def evaluate_topic_cluster(
        self,
        cluster: TopicClusterDocument
    ) -> AnalyticsDecision:
        """Evaluate rules for a topic cluster."""
        
        priority_result = TopicRules.topic_priority_rule(cluster)
        
        return AnalyticsDecision(
            decision_id=f"decision_{cluster.topic_cluster}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            entity_type="topic_cluster",
            entity_id=cluster.topic_cluster,
            decision=priority_result.decision or DecisionType.CONTINUE,
            confidence=priority_result.confidence,
            supporting_signals=priority_result.signals,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
    
    def compute_channel_median(self, all_videos: List[VideoDocument]) -> float:
        """Compute channel median views_24h from all videos."""
        if not all_videos:
            return 1000.0  # Default fallback
        
        views = [v.metrics.views_24h for v in all_videos if v.metrics.views_24h > 0]
        
        if not views:
            return 1000.0
        
        return statistics.median(views)


# =============================================================================
# AGGREGATION UTILITIES
# =============================================================================

class MetricsAggregator:
    """Utilities for computing aggregate metrics."""
    
    @staticmethod
    def compute_series_aggregates(
        episodes: List[VideoDocument]
    ) -> Dict[str, Any]:
        """Compute aggregate metrics for a series from its episodes."""
        if not episodes:
            return {
                "avg_views_24h": 0.0,
                "avg_retention": 0.0,
                "avg_engagement_rate": 0.0,
                "returning_viewer_growth": 0.0,
                "subscriber_delta": 0
            }
        
        avg_views_24h = statistics.mean([e.metrics.views_24h for e in episodes])
        avg_retention = statistics.mean([e.metrics.avg_view_percentage for e in episodes])
        avg_engagement = statistics.mean([e.derived.engagement_rate for e in episodes])
        
        # Returning viewer growth: compare first and last episode
        sorted_eps = sorted(episodes, key=lambda e: e.episode_number or 0)
        first_returning = sorted_eps[0].metrics.returning_viewers or 1
        last_returning = sorted_eps[-1].metrics.returning_viewers
        returning_growth = (last_returning - first_returning) / first_returning
        
        # Subscriber delta: sum across all episodes
        sub_delta = sum(
            e.metrics.subscribers_gained - e.metrics.subscribers_lost 
            for e in episodes
        )
        
        return {
            "avg_views_24h": avg_views_24h,
            "avg_retention": avg_retention,
            "avg_engagement_rate": avg_engagement,
            "returning_viewer_growth": returning_growth,
            "subscriber_delta": sub_delta
        }
    
    @staticmethod
    def compute_cluster_metrics(
        videos: List[VideoDocument]
    ) -> Dict[str, Any]:
        """Compute metrics for a topic cluster."""
        if not videos:
            return {
                "median_views_24h": 0.0,
                "median_retention": 0.0,
                "repeat_viewer_ratio": 0.0
            }
        
        median_views = statistics.median([v.metrics.views_24h for v in videos])
        median_retention = statistics.median([v.metrics.avg_view_percentage for v in videos])
        
        total_returning = sum(v.metrics.returning_viewers for v in videos)
        total_viewers = sum(v.metrics.returning_viewers + v.metrics.new_viewers for v in videos)
        
        repeat_ratio = total_returning / max(1, total_viewers)
        
        return {
            "median_views_24h": median_views,
            "median_retention": median_retention,
            "repeat_viewer_ratio": repeat_ratio
        }
