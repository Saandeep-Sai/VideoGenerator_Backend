"""
Analytics Background Worker
============================

Background worker that runs on a schedule to:
1. Ingest fresh metrics from YouTube
2. Evaluate decision rules
3. Write decisions to Firestore
4. Trigger downstream actions (series termination, topic prioritization)

Scheduler: Uses APScheduler for cron-like scheduling
Concurrency: Single worker, no parallelism needed (Firestore is fast)
"""

import logging
import os
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, timezone, timedelta
import json

# Firebase imports
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    HAS_FIREBASE = True
except ImportError:
    HAS_FIREBASE = False
    logging.warning("Firebase libraries not installed.")

# Scheduler imports
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_SCHEDULER = True
except ImportError:
    HAS_SCHEDULER = False
    logging.warning("APScheduler not installed. Manual trigger only.")

from .firestore_schema import (
    VideoDocument, SeriesDocument, TopicClusterDocument,
    AnalyticsDecision, DecisionType, VideoStatus, SeriesStatus
)
from .decision_engine import DecisionEngine, MetricsAggregator
from .youtube_metrics_ingest import (
    YouTubeAPIConfig, YouTubeMetricsFetcher, 
    MetricsTransformer, MetricsIngestionOrchestrator
)

logger = logging.getLogger(__name__)


# =============================================================================
# FIRESTORE CLIENT
# =============================================================================

class FirestoreClient:
    """
    Wrapper for Firestore operations.
    
    Collections:
    - videos: Individual video documents
    - series: Series documents  
    - topic_clusters: Topic cluster documents
    - decisions: Decision log
    """
    
    def __init__(self, project_id: Optional[str] = None):
        self._db = None
        self.project_id = project_id or os.getenv("FIREBASE_PROJECT_ID")
        
        if not HAS_FIREBASE:
            logger.warning("Firebase not available, using mock mode")
            return
        
        self._initialize()
    
    def _initialize(self):
        """Initialize Firebase connection."""
        try:
            # Check if already initialized
            try:
                firebase_admin.get_app()
            except ValueError:
                # Not initialized, initialize now
                cred = None
                
                # Option 1: Base64 encoded credentials (used in your .env)
                cred_base64 = os.getenv("FIREBASE_CREDENTIALS_BASE64")
                if cred_base64:
                    import base64
                    import json as json_module
                    try:
                        cred_json = base64.b64decode(cred_base64).decode('utf-8')
                        cred_dict = json_module.loads(cred_json)
                        cred = credentials.Certificate(cred_dict)
                        logger.info("Using FIREBASE_CREDENTIALS_BASE64 for auth")
                    except Exception as e:
                        logger.warning(f"Failed to decode base64 credentials: {e}")
                
                # Option 2: File path to credentials
                if not cred:
                    cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
                    if cred_path and os.path.exists(cred_path):
                        cred = credentials.Certificate(cred_path)
                        logger.info("Using FIREBASE_CREDENTIALS_PATH for auth")
                
                # Initialize with credentials or default
                if cred:
                    firebase_admin.initialize_app(cred, {
                        'projectId': self.project_id
                    })
                else:
                    # Use default credentials (for Cloud Run, etc.)
                    firebase_admin.initialize_app(options={
                        'projectId': self.project_id
                    })
                    logger.info("Using default credentials for auth")
            
            self._db = firestore.client()
            logger.info(f"Firestore connected to project: {self.project_id}")
            
        except Exception as e:
            logger.error(f"Failed to initialize Firestore: {e}")
    
    # =========================================================================
    # VIDEO OPERATIONS
    # =========================================================================
    
    def get_video(self, video_id: str) -> Optional[VideoDocument]:
        """Get a single video document."""
        if not self._db:
            return None
        
        doc = self._db.collection('videos').document(video_id).get()
        if doc.exists:
            return VideoDocument.from_dict(doc.to_dict())
        return None
    
    def save_video(self, video: VideoDocument) -> bool:
        """Save or update a video document."""
        if not self._db:
            logger.info(f"[MOCK] Would save video: {video.video_id}")
            return True
        
        try:
            self._db.collection('videos').document(video.video_id).set(
                video.to_dict(),
                merge=True
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save video {video.video_id}: {e}")
            return False
    
    def get_all_videos(self, limit: int = 100) -> List[VideoDocument]:
        """Get all videos, ordered by publish date."""
        if not self._db:
            return []
        
        docs = (
            self._db.collection('videos')
            .order_by('published_at', direction=firestore.Query.DESCENDING)
            .limit(limit)
            .get()
        )
        
        return [VideoDocument.from_dict(d.to_dict()) for d in docs]
    
    def get_videos_by_series(self, series_id: str) -> List[VideoDocument]:
        """Get all videos in a series."""
        if not self._db:
            return []
        
        docs = (
            self._db.collection('videos')
            .where('series_id', '==', series_id)
            .order_by('episode_number')
            .get()
        )
        
        return [VideoDocument.from_dict(d.to_dict()) for d in docs]
    
    def get_videos_by_topic(self, topic_cluster: str) -> List[VideoDocument]:
        """Get all videos in a topic cluster."""
        if not self._db:
            return []
        
        docs = (
            self._db.collection('videos')
            .where('topic_cluster', '==', topic_cluster)
            .get()
        )
        
        return [VideoDocument.from_dict(d.to_dict()) for d in docs]
    
    # =========================================================================
    # SERIES OPERATIONS
    # =========================================================================
    
    def get_series(self, series_id: str) -> Optional[SeriesDocument]:
        """Get a series document."""
        if not self._db:
            return None
        
        doc = self._db.collection('series').document(series_id).get()
        if doc.exists:
            return SeriesDocument.from_dict(doc.to_dict())
        return None
    
    def save_series(self, series: SeriesDocument) -> bool:
        """Save or update a series document."""
        if not self._db:
            logger.info(f"[MOCK] Would save series: {series.series_id}")
            return True
        
        try:
            self._db.collection('series').document(series.series_id).set(
                series.to_dict(),
                merge=True
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save series {series.series_id}: {e}")
            return False
    
    def get_all_series(self, status: Optional[SeriesStatus] = None) -> List[SeriesDocument]:
        """Get all series, optionally filtered by status."""
        if not self._db:
            return []
        
        query = self._db.collection('series')
        
        if status:
            query = query.where('status', '==', status.value)
        
        docs = query.get()
        return [SeriesDocument.from_dict(d.to_dict()) for d in docs]
    
    # =========================================================================
    # TOPIC CLUSTER OPERATIONS
    # =========================================================================
    
    def get_topic_cluster(self, topic_cluster: str) -> Optional[TopicClusterDocument]:
        """Get a topic cluster document."""
        if not self._db:
            return None
        
        doc = self._db.collection('topic_clusters').document(topic_cluster).get()
        if doc.exists:
            return TopicClusterDocument.from_dict(doc.to_dict())
        return None
    
    def save_topic_cluster(self, cluster: TopicClusterDocument) -> bool:
        """Save or update a topic cluster document."""
        if not self._db:
            logger.info(f"[MOCK] Would save topic cluster: {cluster.topic_cluster}")
            return True
        
        try:
            self._db.collection('topic_clusters').document(cluster.topic_cluster).set(
                cluster.to_dict(),
                merge=True
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save topic cluster {cluster.topic_cluster}: {e}")
            return False
    
    def get_all_topic_clusters(self) -> List[TopicClusterDocument]:
        """Get all topic clusters."""
        if not self._db:
            return []
        
        docs = self._db.collection('topic_clusters').get()
        return [TopicClusterDocument.from_dict(d.to_dict()) for d in docs]
    
    # =========================================================================
    # DECISION OPERATIONS
    # =========================================================================
    
    def save_decision(self, decision: AnalyticsDecision) -> bool:
        """Save a decision to the decision log."""
        if not self._db:
            logger.info(f"[MOCK] Would save decision: {decision.decision_id}")
            return True
        
        try:
            self._db.collection('decisions').document(decision.decision_id).set(
                decision.to_dict()
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save decision {decision.decision_id}: {e}")
            return False
    
    def get_recent_decisions(
        self, 
        entity_type: Optional[str] = None,
        limit: int = 50
    ) -> List[AnalyticsDecision]:
        """Get recent decisions, optionally filtered by entity type."""
        if not self._db:
            return []
        
        query = self._db.collection('decisions')
        
        if entity_type:
            query = query.where('entity_type', '==', entity_type)
        
        query = query.order_by('timestamp', direction=firestore.Query.DESCENDING)
        query = query.limit(limit)
        
        docs = query.get()
        return [AnalyticsDecision.from_dict(d.to_dict()) for d in docs]


# =============================================================================
# ANALYTICS WORKER
# =============================================================================

@dataclass
class WorkerConfig:
    """Configuration for the analytics worker."""
    
    # YouTube API config
    youtube_config: YouTubeAPIConfig = None
    
    # Firestore config
    firebase_project_id: Optional[str] = None
    
    # Scheduling
    ingest_cron: str = "0 */6 * * *"  # Every 6 hours
    evaluate_cron: str = "30 */6 * * *"  # 30 min after ingest
    
    # Limits
    max_videos_per_run: int = 50
    
    def __post_init__(self):
        if self.youtube_config is None:
            self.youtube_config = YouTubeAPIConfig.from_env()
        if self.firebase_project_id is None:
            self.firebase_project_id = os.getenv("FIREBASE_PROJECT_ID")


class AnalyticsWorker:
    """
    Background worker for analytics processing.
    
    Main jobs:
    1. ingest_metrics: Fetch fresh data from YouTube
    2. evaluate_decisions: Run decision rules on all entities
    3. apply_decisions: Execute termination/expansion actions
    """
    
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.firestore = FirestoreClient(config.firebase_project_id)
        self.ingestion = MetricsIngestionOrchestrator(config.youtube_config)
        self.decision_engine = DecisionEngine()
        self.scheduler = None
        
        if HAS_SCHEDULER:
            self.scheduler = BackgroundScheduler()
    
    def start(self):
        """Start the background worker with scheduled jobs."""
        if not self.scheduler:
            logger.warning("Scheduler not available, worker will not auto-run")
            return
        
        # Schedule ingestion job
        self.scheduler.add_job(
            self.ingest_metrics,
            CronTrigger.from_crontab(self.config.ingest_cron),
            id='ingest_metrics',
            name='Ingest YouTube Metrics'
        )
        
        # Schedule evaluation job
        self.scheduler.add_job(
            self.evaluate_all_decisions,
            CronTrigger.from_crontab(self.config.evaluate_cron),
            id='evaluate_decisions',
            name='Evaluate Decision Rules'
        )
        
        self.scheduler.start()
        logger.info("Analytics worker started with scheduled jobs")
    
    def stop(self):
        """Stop the background worker."""
        if self.scheduler:
            self.scheduler.shutdown()
            logger.info("Analytics worker stopped")
    
    # =========================================================================
    # MAIN JOBS
    # =========================================================================
    
    def ingest_metrics(self) -> int:
        """
        Job 1: Ingest fresh metrics from YouTube.
        
        Returns number of videos ingested.
        """
        logger.info("Starting metrics ingestion...")
        
        # Get current series mapping from Firestore
        series_mapping = self._build_series_mapping()
        
        # Ingest videos
        videos = self.ingestion.ingest_channel_videos(
            limit=self.config.max_videos_per_run,
            series_mapping=series_mapping
        )
        
        # Save to Firestore
        saved_count = 0
        for video in videos:
            if self.firestore.save_video(video):
                saved_count += 1
        
        logger.info(f"Ingested and saved {saved_count}/{len(videos)} videos")
        return saved_count
    
    def evaluate_all_decisions(self) -> Dict[str, int]:
        """
        Job 2: Evaluate decision rules on all entities.
        
        Returns dict with counts of each decision type.
        """
        logger.info("Starting decision evaluation...")
        
        results = {
            'videos_evaluated': 0,
            'videos_terminated': 0,
            'series_evaluated': 0,
            'series_expanded': 0,
            'series_terminated': 0,
            'clusters_evaluated': 0,
            'clusters_prioritized': 0
        }
        
        # Update channel median
        all_videos = self.firestore.get_all_videos(limit=100)
        self.decision_engine.channel_median_views_24h = \
            self.decision_engine.compute_channel_median(all_videos)
        
        # Evaluate videos
        for video in all_videos:
            decision = self.decision_engine.evaluate_video(video)
            self.firestore.save_decision(decision)
            results['videos_evaluated'] += 1
            
            if decision.decision == DecisionType.TERMINATE:
                results['videos_terminated'] += 1
                # Apply termination
                video.status = VideoStatus.LOW_SIGNAL
                self.firestore.save_video(video)
        
        # Evaluate series
        all_series = self.firestore.get_all_series(status=SeriesStatus.ACTIVE)
        for series in all_series:
            episodes = self.firestore.get_videos_by_series(series.series_id)
            
            # Update aggregate metrics
            aggregates = MetricsAggregator.compute_series_aggregates(episodes)
            series.aggregate_metrics.avg_retention = aggregates['avg_retention']
            series.aggregate_metrics.returning_viewer_growth = aggregates['returning_viewer_growth']
            self.firestore.save_series(series)
            
            decision = self.decision_engine.evaluate_series(series, episodes)
            self.firestore.save_decision(decision)
            results['series_evaluated'] += 1
            
            if decision.decision == DecisionType.EXPAND:
                results['series_expanded'] += 1
                series.status = SeriesStatus.EXPANDING
                self.firestore.save_series(series)
            elif decision.decision == DecisionType.TERMINATE:
                results['series_terminated'] += 1
                series.status = SeriesStatus.TERMINATED
                self.firestore.save_series(series)
        
        # Evaluate topic clusters
        all_clusters = self.firestore.get_all_topic_clusters()
        for cluster in all_clusters:
            cluster_videos = self.firestore.get_videos_by_topic(cluster.topic_cluster)
            
            # Update cluster metrics
            cluster_metrics = MetricsAggregator.compute_cluster_metrics(cluster_videos)
            cluster.cluster_metrics.repeat_viewer_ratio = cluster_metrics['repeat_viewer_ratio']
            self.firestore.save_topic_cluster(cluster)
            
            decision = self.decision_engine.evaluate_topic_cluster(cluster)
            self.firestore.save_decision(decision)
            results['clusters_evaluated'] += 1
            
            if decision.decision == DecisionType.EXPAND:
                results['clusters_prioritized'] += 1
        
        logger.info(f"Evaluation complete: {results}")
        return results
    
    # =========================================================================
    # UTILITIES
    # =========================================================================
    
    def _build_series_mapping(self) -> Dict[str, tuple]:
        """Build a mapping from video_id to (series_id, episode_number)."""
        mapping = {}
        
        all_series = self.firestore.get_all_series()
        for series in all_series:
            for vid in series.video_ids:
                # Try to infer episode number from position
                try:
                    ep_num = series.video_ids.index(vid) + 1
                except:
                    ep_num = None
                mapping[vid] = (series.series_id, ep_num)
        
        return mapping
    
    def run_single_cycle(self) -> Dict[str, Any]:
        """
        Run a single ingestion + evaluation cycle.
        
        Useful for testing or manual triggers.
        """
        ingested = self.ingest_metrics()
        decisions = self.evaluate_all_decisions()
        
        return {
            'ingested_count': ingested,
            'decisions': decisions,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    def get_dashboard_summary(self) -> Dict[str, Any]:
        """
        Get a summary for dashboard display.
        """
        all_videos = self.firestore.get_all_videos(limit=100)
        all_series = self.firestore.get_all_series()
        recent_decisions = self.firestore.get_recent_decisions(limit=10)
        
        return {
            'total_videos': len(all_videos),
            'active_series': len([s for s in all_series if s.status == SeriesStatus.ACTIVE]),
            'terminated_series': len([s for s in all_series if s.status == SeriesStatus.TERMINATED]),
            'expanding_series': len([s for s in all_series if s.status == SeriesStatus.EXPANDING]),
            'low_signal_videos': len([v for v in all_videos if v.status == VideoStatus.LOW_SIGNAL]),
            'recent_decisions': [
                {
                    'id': d.decision_id,
                    'entity': d.entity_id,
                    'decision': d.decision.value,
                    'signals': d.supporting_signals[:2]  # First 2 signals
                }
                for d in recent_decisions
            ],
            'channel_median_views': self.decision_engine.compute_channel_median(all_videos)
        }


# =============================================================================
# ENTRY POINT
# =============================================================================

def create_worker_from_env() -> AnalyticsWorker:
    """Factory function to create worker from environment variables."""
    config = WorkerConfig()
    return AnalyticsWorker(config)


if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create and run worker
    worker = create_worker_from_env()
    
    # Run single cycle for testing
    print("Running single analytics cycle...")
    result = worker.run_single_cycle()
    print(f"Result: {json.dumps(result, indent=2, default=str)}")
    
    # Print dashboard summary
    print("\nDashboard Summary:")
    summary = worker.get_dashboard_summary()
    print(json.dumps(summary, indent=2, default=str))
