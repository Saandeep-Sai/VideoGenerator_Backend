"""
Integrated Analytics Service
=============================

Connects YouTube analytics with video generation and Firestore.
Uses the same OAuth token.json as video uploads.

Integration Points:
1. After video upload → Save video ID to Firestore for tracking
2. Periodic sync → Fetch analytics for all tracked videos
3. Decision engine → Evaluate series/video performance
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

# Load environment variables from .env
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass  # dotenv not installed, assume env vars are set

# Local imports
try:
    from .youtube_oauth_analytics import YouTubeAnalyticsFetcher
    from .firestore_schema import (
        VideoDocument, SeriesDocument, VideoMetrics, DerivedMetrics,
        VideoStatus, SeriesStatus, DecisionType
    )
    from .decision_engine import DecisionEngine, MetricsAggregator
except ImportError:
    from analytics.youtube_oauth_analytics import YouTubeAnalyticsFetcher
    from analytics.firestore_schema import (
        VideoDocument, SeriesDocument, VideoMetrics, DerivedMetrics,
        VideoStatus, SeriesStatus, DecisionType
    )
    from analytics.decision_engine import DecisionEngine, MetricsAggregator

# Firebase
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    HAS_FIREBASE = True
except ImportError:
    HAS_FIREBASE = False
    logging.warning("Firebase libraries not installed")

logger = logging.getLogger(__name__)


# =============================================================================
# INTEGRATED ANALYTICS SERVICE
# =============================================================================

@dataclass
class AnalyticsServiceConfig:
    """Configuration for the analytics service."""
    token_path: str = "token.json"
    firebase_project_id: Optional[str] = None
    collection_name: str = "video_analytics"  # Firestore collection
    sync_interval_hours: int = 6
    
    def __post_init__(self):
        if self.firebase_project_id is None:
            self.firebase_project_id = os.getenv("FIREBASE_PROJECT_ID")


class IntegratedAnalyticsService:
    """
    Main analytics service that integrates with the video generation pipeline.
    
    Usage:
        # After uploading a video
        analytics.track_video(youtube_video_id, topic, series_id)
        
        # Periodic sync (run every few hours)
        analytics.sync_all_videos()
        
        # Get performance report
        report = analytics.get_performance_report()
    """
    
    def __init__(self, config: Optional[AnalyticsServiceConfig] = None):
        self.config = config or AnalyticsServiceConfig()
        self._db = None
        self._youtube = None
        self._decision_engine = DecisionEngine()
        
        self._initialize()
    
    def _initialize(self):
        """Initialize Firebase and YouTube connections."""
        # Initialize YouTube
        self._youtube = YouTubeAnalyticsFetcher(self.config.token_path)
        if self._youtube.is_connected:
            logger.info("YouTube Analytics connected")
        else:
            logger.warning("YouTube Analytics not connected - using limited mode")
        
        # Initialize Firebase
        if HAS_FIREBASE:
            try:
                try:
                    firebase_admin.get_app()
                except ValueError:
                    cred_b64 = os.getenv("FIREBASE_CREDENTIALS_BASE64")
                    if cred_b64:
                        import base64
                        import json
                        cred_json = base64.b64decode(cred_b64).decode('utf-8')
                        cred_dict = json.loads(cred_json)
                        cred = credentials.Certificate(cred_dict)
                        firebase_admin.initialize_app(cred, {
                            'projectId': self.config.firebase_project_id
                        })
                    else:
                        firebase_admin.initialize_app(options={
                            'projectId': self.config.firebase_project_id
                        })
                
                self._db = firestore.client()
                logger.info(f"Firestore connected: {self.config.firebase_project_id}")
            except Exception as e:
                logger.error(f"Firebase init failed: {e}")
    
    # =========================================================================
    # TRACKING - Call after video upload
    # =========================================================================
    
    def track_video(
        self,
        youtube_video_id: str,
        topic: str,
        series_id: Optional[str] = None,
        episode_number: Optional[int] = None,
        topic_cluster: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Track a newly uploaded video for analytics.
        
        Call this immediately after upload_video_to_youtube() succeeds.
        
        Args:
            youtube_video_id: The YouTube video ID (e.g., "dQw4w9WgXcQ")
            topic: The video topic
            series_id: Optional series ID for series tracking
            episode_number: Episode number in series
            topic_cluster: Topic category for clustering
            metadata: Additional metadata (title, description, etc.)
        
        Returns:
            True if successfully saved to Firestore
        """
        if not self._db:
            logger.warning(f"[MOCK] Would track video: {youtube_video_id}")
            return True
        
        try:
            doc = {
                "youtube_video_id": youtube_video_id,
                "topic": topic,
                "series_id": series_id,
                "episode_number": episode_number,
                "topic_cluster": topic_cluster or self._infer_topic_cluster(topic),
                "title": metadata.get("title", topic) if metadata else topic,
                "status": VideoStatus.ACTIVE.value,
                "published_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_synced": None,
                "metrics": {
                    "views_total": 0,
                    "views_24h": 0,
                    "avg_view_percentage": 0.0,
                    "likes": 0,
                    "comments": 0,
                    "shares": 0,
                    "subscribers_gained": 0,
                    "subscribers_lost": 0,
                },
                "metadata": metadata or {}
            }
            
            self._db.collection(self.config.collection_name).document(youtube_video_id).set(doc)
            logger.info(f"Tracked video: {youtube_video_id} - {topic}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to track video {youtube_video_id}: {e}")
            return False
    
    def _infer_topic_cluster(self, topic: str) -> str:
        """Infer topic cluster from topic text."""
        topic_lower = topic.lower()
        
        clusters = {
            "python": ["python", "django", "flask", "pandas", "numpy"],
            "javascript": ["javascript", "js", "react", "node", "typescript", "vue"],
            "web": ["html", "css", "web", "frontend", "backend", "api"],
            "devops": ["docker", "kubernetes", "aws", "cloud", "devops", "ci/cd"],
            "database": ["sql", "database", "mongodb", "postgres", "mysql"],
            "algorithms": ["algorithm", "data structure", "leetcode", "sort", "search"],
            "general": []  # Default
        }
        
        for cluster, keywords in clusters.items():
            if any(kw in topic_lower for kw in keywords):
                return cluster
        
        return "general"
    
    # =========================================================================
    # SYNC - Fetch latest analytics from YouTube
    # =========================================================================
    
    def sync_video(self, youtube_video_id: str) -> Optional[Dict[str, Any]]:
        """
        Sync analytics for a single video.
        
        Returns updated metrics dict or None if failed.
        """
        if not self._youtube or not self._youtube.is_connected:
            logger.warning("YouTube not connected, skipping sync")
            return None
        
        # Get basic stats
        stats = self._youtube.get_video_statistics(youtube_video_id)
        if not stats:
            logger.warning(f"Could not fetch stats for {youtube_video_id}")
            return None
        
        # Get detailed analytics (if API is enabled)
        analytics = self._youtube.get_video_analytics(youtube_video_id, days=7)
        
        # Build metrics
        metrics = {
            "views_total": stats.get("view_count", 0),
            "views_24h": analytics.get("views", 0) if analytics else 0,
            "avg_view_percentage": analytics.get("avg_view_percentage", 0.0) if analytics else 0.0,
            "likes": stats.get("like_count", 0),
            "comments": stats.get("comment_count", 0),
            "shares": analytics.get("shares", 0) if analytics else 0,
            "subscribers_gained": analytics.get("subscribers_gained", 0) if analytics else 0,
            "subscribers_lost": analytics.get("subscribers_lost", 0) if analytics else 0,
        }
        
        # Update Firestore
        if self._db:
            try:
                self._db.collection(self.config.collection_name).document(youtube_video_id).update({
                    "metrics": metrics,
                    "last_synced": datetime.now(timezone.utc).isoformat(),
                    "title": stats.get("title", "")
                })
                logger.info(f"Synced {youtube_video_id}: {metrics['views_total']} views, {metrics['avg_view_percentage']:.1f}% retention")
            except Exception as e:
                logger.error(f"Failed to update Firestore for {youtube_video_id}: {e}")
        
        return metrics
    
    def sync_all_videos(self, limit: int = 50) -> Dict[str, Any]:
        """
        Sync analytics for all tracked videos.
        
        Returns summary of sync operation.
        """
        if not self._db:
            logger.warning("No Firestore connection, using YouTube channel videos")
            return self._sync_from_youtube_channel(limit)
        
        # Get tracked videos from Firestore
        try:
            docs = (
                self._db.collection(self.config.collection_name)
                .where("status", "==", VideoStatus.ACTIVE.value)
                .limit(limit)
                .get()
            )
            
            synced = 0
            failed = 0
            
            for doc in docs:
                video_id = doc.id
                if self.sync_video(video_id):
                    synced += 1
                else:
                    failed += 1
            
            return {
                "synced": synced,
                "failed": failed,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Sync failed: {e}")
            return {"error": str(e)}
    
    def _sync_from_youtube_channel(self, limit: int) -> Dict[str, Any]:
        """Sync videos directly from YouTube channel (no Firestore tracking)."""
        if not self._youtube or not self._youtube.is_connected:
            return {"error": "YouTube not connected"}
        
        videos = self._youtube.get_recent_videos(limit)
        
        results = []
        for v in videos:
            stats = self._youtube.get_video_statistics(v["video_id"])
            if stats:
                results.append({
                    "video_id": v["video_id"],
                    "title": v["title"],
                    "views": stats["view_count"],
                    "likes": stats["like_count"]
                })
        
        return {
            "synced": len(results),
            "videos": results,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    # =========================================================================
    # REPORTING
    # =========================================================================
    
    def get_performance_report(self, days: int = 7) -> Dict[str, Any]:
        """
        Get a performance report for recent videos.
        """
        if not self._youtube or not self._youtube.is_connected:
            return {"error": "YouTube not connected"}
        
        # Channel overview
        overview = self._youtube.get_channel_overview(days)
        
        # Recent videos with stats
        videos = self._youtube.get_recent_videos(10)
        video_stats = []
        
        for v in videos:
            stats = self._youtube.get_video_statistics(v["video_id"])
            if stats:
                video_stats.append({
                    "video_id": v["video_id"],
                    "title": v["title"][:50],
                    "published": v["published_at"],
                    "views": stats["view_count"],
                    "likes": stats["like_count"],
                    "comments": stats["comment_count"]
                })
        
        return {
            "period_days": days,
            "channel": overview,
            "recent_videos": video_stats,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
    
    def get_video_decision(self, youtube_video_id: str) -> Optional[Dict[str, Any]]:
        """
        Get decision recommendation for a video based on its metrics.
        """
        metrics = self.sync_video(youtube_video_id)
        if not metrics:
            return None
        
        # Create a VideoDocument for decision engine
        video = VideoDocument(
            video_id=youtube_video_id,
            youtube_video_id=youtube_video_id,
            title="",
            published_at=datetime.now(timezone.utc).isoformat(),
            status=VideoStatus.ACTIVE,
            metrics=VideoMetrics(
                views_total=metrics["views_total"],
                views_24h=metrics["views_24h"],
                avg_view_percentage=metrics["avg_view_percentage"],
                likes=metrics["likes"],
                comments=metrics["comments"],
                shares=metrics["shares"],
                subscribers_gained=metrics["subscribers_gained"],
                subscribers_lost=metrics["subscribers_lost"],
            ),
            derived=DerivedMetrics()
        )
        
        # Evaluate
        decision = self._decision_engine.evaluate_video(video)
        
        return {
            "video_id": youtube_video_id,
            "decision": decision.decision.value,
            "confidence": decision.confidence,
            "signals": decision.supporting_signals,
            "metrics": metrics
        }


# =============================================================================
# FACTORY & GLOBAL INSTANCE
# =============================================================================

_analytics_service: Optional[IntegratedAnalyticsService] = None


def get_analytics_service() -> IntegratedAnalyticsService:
    """Get or create the global analytics service instance."""
    global _analytics_service
    if _analytics_service is None:
        _analytics_service = IntegratedAnalyticsService()
    return _analytics_service


def track_uploaded_video(
    youtube_video_id: str,
    topic: str,
    series_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Convenience function to track a newly uploaded video.
    
    Call this in run_generate_worker.py after successful YouTube upload.
    """
    service = get_analytics_service()
    return service.track_video(
        youtube_video_id=youtube_video_id,
        topic=topic,
        series_id=series_id,
        metadata=metadata
    )


# =============================================================================
# CLI TESTING
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    service = IntegratedAnalyticsService()
    
    print("\n=== Performance Report ===")
    report = service.get_performance_report(days=7)
    
    if "error" not in report:
        if report.get("channel"):
            ch = report["channel"]
            print(f"\nChannel (last 7 days):")
            print(f"  Views: {ch['total_views']:,}")
            print(f"  Net subs: {ch['net_subscribers']:+d}")
            print(f"  Avg retention: {ch['avg_view_percentage']:.1f}%")
        
        print(f"\nRecent Videos:")
        for v in report.get("recent_videos", [])[:5]:
            print(f"  {v['title']}... - {v['views']:,} views")
    else:
        print(f"Error: {report['error']}")
