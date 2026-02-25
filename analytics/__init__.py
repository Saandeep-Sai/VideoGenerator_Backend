"""
Analytics Intelligence Module
==============================

Decision-grade analytics for YouTube Shorts automation.

This module provides:
1. Firestore data models for videos, series, and topic clusters
2. YouTube metrics ingestion from Data API and Analytics API
3. Rule-based decision engine (no ML, fully explainable)
4. Background worker for scheduled analytics processing

Design Principles:
- Retention over views: Focus on audience retention and returning viewers
- Explainable decisions: All decisions have clear supporting signals
- Series intelligence: Track performance across episode sequences
- Self-correcting: Automatic termination of underperforming content

Key Metrics:
- avg_view_percentage: Primary retention metric
- returning_viewers: Audience loyalty indicator
- repeat_viewer_ratio: Topic cluster strength
- engagement_rate: Derived from likes + comments + shares

Decision Rules:
- Kill Video: views < median AND retention < 50%
- Series Continue: ep2.retention >= ep1.retention
- Series Expand: avg_retention >= 70% AND returning_growth > 0
- Topic Priority: repeat_viewer_ratio >= 0.3

Usage:
    from analytics import AnalyticsWorker, create_worker_from_env
    
    # Create worker
    worker = create_worker_from_env()
    
    # Run single cycle
    result = worker.run_single_cycle()
    
    # Or start scheduled background processing
    worker.start()
"""

from .firestore_schema import (
    VideoDocument,
    SeriesDocument,
    TopicClusterDocument,
    AnalyticsDecision,
    VideoMetrics,
    DerivedMetrics,
    SeriesAggregateMetrics,
    ClusterMetrics,
    VideoStatus,
    SeriesStatus,
    TopicMomentum,
    DecisionType
)

from .decision_engine import (
    DecisionEngine,
    VideoRules,
    SeriesRules,
    TopicRules,
    RuleResult,
    MetricsAggregator
)

from .youtube_metrics_ingest import (
    YouTubeAPIConfig,
    YouTubeMetricsFetcher,
    MetricsTransformer,
    MetricsIngestionOrchestrator
)

from .analytics_worker import (
    AnalyticsWorker,
    FirestoreClient,
    WorkerConfig,
    create_worker_from_env
)

# OAuth-based YouTube analytics (uses same token.json as uploads)
from .youtube_oauth_analytics import (
    YouTubeAnalyticsFetcher,
    get_authenticated_services
)

# Integrated service (main entry point for pipeline integration)
from .integrated_analytics import (
    IntegratedAnalyticsService,
    AnalyticsServiceConfig,
    get_analytics_service,
    track_uploaded_video
)

# Smart topic selector (analytics-driven topic selection)
from .smart_topic_selector import (
    SmartTopicSelector,
    TopicClusterAnalyzer,
    ClusterPerformance,
    get_smart_topic,
    get_prioritized_cluster
)

__all__ = [
    # Schema
    'VideoDocument',
    'SeriesDocument', 
    'TopicClusterDocument',
    'AnalyticsDecision',
    'VideoMetrics',
    'DerivedMetrics',
    'SeriesAggregateMetrics',
    'ClusterMetrics',
    'VideoStatus',
    'SeriesStatus',
    'TopicMomentum',
    'DecisionType',
    
    # Decision Engine
    'DecisionEngine',
    'VideoRules',
    'SeriesRules',
    'TopicRules',
    'RuleResult',
    'MetricsAggregator',
    
    # Ingestion (legacy service account method)
    'YouTubeAPIConfig',
    'YouTubeMetricsFetcher',
    'MetricsTransformer',
    'MetricsIngestionOrchestrator',
    
    # Worker
    'AnalyticsWorker',
    'FirestoreClient',
    'WorkerConfig',
    'create_worker_from_env',
    
    # OAuth-based analytics (recommended)
    'YouTubeAnalyticsFetcher',
    'get_authenticated_services',
    
    # Integrated service (main entry point)
    'IntegratedAnalyticsService',
    'AnalyticsServiceConfig',
    'get_analytics_service',
    'track_uploaded_video',
    
    # Smart topic selector (analytics-driven)
    'SmartTopicSelector',
    'TopicClusterAnalyzer',
    'ClusterPerformance',
    'get_smart_topic',
    'get_prioritized_cluster'
]
