"""
Firestore Analytics Schema
==========================

Data models for decision-grade content analytics.
Optimizes for: retention, returning viewers, series intelligence.
NOT for: vanity metrics, virality.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime
from enum import Enum


# =============================================================================
# ENUMS
# =============================================================================

class VideoStatus(str, Enum):
    ACTIVE = "active"
    LOW_SIGNAL = "low_signal"
    TERMINATED = "terminated"


class SeriesStatus(str, Enum):
    TESTING = "testing"
    EXPANDING = "expanding"
    PLATEAUED = "plateaued"
    TERMINATED = "terminated"


class TopicMomentum(str, Enum):
    RISING = "rising"
    STABLE = "stable"
    DECLINING = "declining"


class DecisionType(str, Enum):
    EXPAND = "expand"
    CONTINUE = "continue"
    PAUSE = "pause"
    TERMINATE = "terminate"


# =============================================================================
# VIDEO DOCUMENT
# =============================================================================

@dataclass
class VideoMetrics:
    """Raw metrics from YouTube Analytics API."""
    views_24h: int = 0
    views_72h: int = 0
    views_7d: int = 0
    
    avg_view_duration_seconds: float = 0.0
    avg_view_percentage: float = 0.0
    
    likes: int = 0
    comments: int = 0
    shares: int = 0
    
    subscribers_gained: int = 0
    subscribers_lost: int = 0
    
    returning_viewers: int = 0
    new_viewers: int = 0


@dataclass
class DerivedMetrics:
    """Computed metrics for decision-making."""
    engagement_rate: float = 0.0      # (likes + comments + shares) / views
    retention_score: float = 0.0      # Normalized 0-1 score
    velocity_score: float = 0.0       # views_24h / hours_since_upload
    
    def compute(self, metrics: VideoMetrics, hours_since_upload: float):
        """Compute derived metrics from raw metrics."""
        total_views = metrics.views_24h or 1  # Avoid division by zero
        
        self.engagement_rate = (
            (metrics.likes + metrics.comments + metrics.shares) / total_views
        )
        
        # Retention score: 0-1 based on avg_view_percentage (100% = 1.0)
        self.retention_score = min(1.0, metrics.avg_view_percentage / 100.0)
        
        # Velocity: views per hour
        self.velocity_score = metrics.views_24h / max(1, hours_since_upload)


@dataclass
class VideoDocument:
    """Firestore document for a single video."""
    video_id: str
    platform: str = "youtube"
    upload_timestamp: str = ""  # ISO 8601
    
    topic: str = ""
    series_id: Optional[str] = None
    episode_number: Optional[int] = None
    
    duration_seconds: int = 0
    
    metrics: VideoMetrics = field(default_factory=VideoMetrics)
    derived: DerivedMetrics = field(default_factory=DerivedMetrics)
    
    status: VideoStatus = VideoStatus.ACTIVE
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "video_id": self.video_id,
            "platform": self.platform,
            "upload_timestamp": self.upload_timestamp,
            "topic": self.topic,
            "series_id": self.series_id,
            "episode_number": self.episode_number,
            "duration_seconds": self.duration_seconds,
            "metrics": asdict(self.metrics),
            "derived": asdict(self.derived),
            "status": self.status.value
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoDocument":
        metrics = VideoMetrics(**data.get("metrics", {}))
        derived = DerivedMetrics(**data.get("derived", {}))
        return cls(
            video_id=data["video_id"],
            platform=data.get("platform", "youtube"),
            upload_timestamp=data.get("upload_timestamp", ""),
            topic=data.get("topic", ""),
            series_id=data.get("series_id"),
            episode_number=data.get("episode_number"),
            duration_seconds=data.get("duration_seconds", 0),
            metrics=metrics,
            derived=derived,
            status=VideoStatus(data.get("status", "active"))
        )


# =============================================================================
# SERIES DOCUMENT
# =============================================================================

@dataclass
class SeriesAggregateMetrics:
    """Aggregate metrics across all episodes in a series."""
    avg_views_24h: float = 0.0
    avg_retention: float = 0.0
    avg_engagement_rate: float = 0.0
    
    returning_viewer_growth: float = 0.0  # % change from ep1 to latest
    subscriber_delta: int = 0             # net subscribers from series


@dataclass
class DecisionLogEntry:
    """Single decision recorded for a series."""
    timestamp: str
    decision: str
    reason: str


@dataclass
class SeriesDocument:
    """Firestore document for a content series."""
    series_id: str
    topic_cluster: str
    
    episodes: List[str] = field(default_factory=list)  # video_ids in order
    
    aggregate_metrics: SeriesAggregateMetrics = field(default_factory=SeriesAggregateMetrics)
    
    status: SeriesStatus = SeriesStatus.TESTING
    
    decision_log: List[DecisionLogEntry] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "series_id": self.series_id,
            "topic_cluster": self.topic_cluster,
            "episodes": self.episodes,
            "aggregate_metrics": asdict(self.aggregate_metrics),
            "status": self.status.value,
            "decision_log": [asdict(d) for d in self.decision_log]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SeriesDocument":
        agg = SeriesAggregateMetrics(**data.get("aggregate_metrics", {}))
        logs = [
            DecisionLogEntry(**log) 
            for log in data.get("decision_log", [])
        ]
        return cls(
            series_id=data["series_id"],
            topic_cluster=data.get("topic_cluster", ""),
            episodes=data.get("episodes", []),
            aggregate_metrics=agg,
            status=SeriesStatus(data.get("status", "testing")),
            decision_log=logs
        )


# =============================================================================
# TOPIC CLUSTER DOCUMENT
# =============================================================================

@dataclass
class ClusterMetrics:
    """Metrics aggregated across all videos in a topic cluster."""
    median_views_24h: float = 0.0
    median_retention: float = 0.0
    repeat_viewer_ratio: float = 0.0  # returning_viewers / total_viewers


@dataclass
class TopicClusterDocument:
    """Firestore document for a topic cluster."""
    topic_cluster: str
    total_videos: int = 0
    
    cluster_metrics: ClusterMetrics = field(default_factory=ClusterMetrics)
    
    momentum: TopicMomentum = TopicMomentum.STABLE
    last_updated: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic_cluster": self.topic_cluster,
            "total_videos": self.total_videos,
            "cluster_metrics": asdict(self.cluster_metrics),
            "momentum": self.momentum.value,
            "last_updated": self.last_updated
        }


# =============================================================================
# ANALYTICS DECISION DOCUMENT
# =============================================================================

@dataclass
class AnalyticsDecision:
    """System-generated decision document."""
    decision_id: str  # auto-generated
    
    entity_type: Literal["video", "series", "topic_cluster"]
    entity_id: str
    
    decision: DecisionType
    confidence: float  # 0.0 to 1.0
    
    supporting_signals: List[str] = field(default_factory=list)
    
    timestamp: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "decision": self.decision.value,
            "confidence": self.confidence,
            "supporting_signals": self.supporting_signals,
            "timestamp": self.timestamp
        }
