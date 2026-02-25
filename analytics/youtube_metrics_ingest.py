"""
YouTube Metrics Ingestion
=========================

Fetches analytics data from YouTube Data API and YouTube Analytics API.
Transforms raw API responses into our internal VideoMetrics format.

Required Scopes:
- youtube.readonly (for video metadata)
- yt-analytics.readonly (for detailed analytics)

Rate Limits:
- 10,000 units/day for most projects
- Batch requests when possible
"""

import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
import os

# Google API imports
try:
    from google.oauth2.credentials import Credentials
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False
    logging.warning("Google API libraries not installed. YouTube ingestion disabled.")

from .firestore_schema import VideoDocument, VideoMetrics, DerivedMetrics, VideoStatus

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class YouTubeAPIConfig:
    """Configuration for YouTube API access."""
    
    # Authentication
    service_account_file: Optional[str] = None
    oauth_credentials: Optional[Any] = None
    
    # Channel info
    channel_id: Optional[str] = None
    
    # API settings
    max_results_per_page: int = 50
    retry_count: int = 3
    
    @classmethod
    def from_env(cls) -> 'YouTubeAPIConfig':
        """Load config from environment variables."""
        return cls(
            service_account_file=os.getenv("YOUTUBE_SERVICE_ACCOUNT_FILE"),
            channel_id=os.getenv("YOUTUBE_CHANNEL_ID")
        )


# =============================================================================
# YOUTUBE DATA FETCHER
# =============================================================================

class YouTubeMetricsFetcher:
    """
    Fetches video metrics from YouTube APIs.
    
    Uses two APIs:
    1. YouTube Data API v3 - for video metadata and basic statistics
    2. YouTube Analytics API - for detailed retention/engagement data
    """
    
    def __init__(self, config: YouTubeAPIConfig):
        self.config = config
        self._youtube_data = None
        self._youtube_analytics = None
        
        if not HAS_GOOGLE_API:
            logger.error("Google API libraries not available")
            return
        
        self._initialize_clients()
    
    def _initialize_clients(self):
        """Initialize YouTube API clients."""
        try:
            if self.config.service_account_file:
                credentials = service_account.Credentials.from_service_account_file(
                    self.config.service_account_file,
                    scopes=[
                        'https://www.googleapis.com/auth/youtube.readonly',
                        'https://www.googleapis.com/auth/yt-analytics.readonly'
                    ]
                )
            elif self.config.oauth_credentials:
                credentials = self.config.oauth_credentials
            else:
                logger.warning("No credentials provided, running in mock mode")
                return
            
            self._youtube_data = build('youtube', 'v3', credentials=credentials)
            self._youtube_analytics = build('youtubeAnalytics', 'v2', credentials=credentials)
            
            logger.info("YouTube API clients initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize YouTube clients: {e}")
    
    def fetch_video_statistics(self, video_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch basic statistics for a video.
        
        API Cost: 1 unit per video (can batch up to 50)
        
        Returns:
            Dict with viewCount, likeCount, commentCount, etc.
        """
        if not self._youtube_data:
            return self._mock_video_statistics(video_id)
        
        try:
            response = self._youtube_data.videos().list(
                part='statistics,snippet,contentDetails',
                id=video_id
            ).execute()
            
            if response.get('items'):
                item = response['items'][0]
                return {
                    'video_id': video_id,
                    'title': item['snippet']['title'],
                    'published_at': item['snippet']['publishedAt'],
                    'duration_seconds': self._parse_duration(item['contentDetails']['duration']),
                    'view_count': int(item['statistics'].get('viewCount', 0)),
                    'like_count': int(item['statistics'].get('likeCount', 0)),
                    'comment_count': int(item['statistics'].get('commentCount', 0)),
                }
            
            return None
            
        except HttpError as e:
            logger.error(f"YouTube Data API error for {video_id}: {e}")
            return None
    
    def fetch_video_analytics(
        self, 
        video_id: str,
        start_date: str,
        end_date: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch detailed analytics for a video.
        
        API Cost: Higher, use sparingly
        
        Returns:
            Dict with averageViewDuration, averageViewPercentage, 
            subscribersGained, subscribersLost, etc.
        """
        if not self._youtube_analytics:
            return self._mock_video_analytics(video_id)
        
        try:
            response = self._youtube_analytics.reports().query(
                ids=f'channel=={self.config.channel_id}',
                startDate=start_date,
                endDate=end_date,
                metrics='views,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost,shares',
                dimensions='video',
                filters=f'video=={video_id}'
            ).execute()
            
            if response.get('rows'):
                row = response['rows'][0]
                # Map metrics to our format
                headers = [h['name'] for h in response['columnHeaders']]
                data = dict(zip(headers, row))
                
                return {
                    'video_id': video_id,
                    'views': int(data.get('views', 0)),
                    'avg_view_duration': float(data.get('averageViewDuration', 0)),
                    'avg_view_percentage': float(data.get('averageViewPercentage', 0)),
                    'subscribers_gained': int(data.get('subscribersGained', 0)),
                    'subscribers_lost': int(data.get('subscribersLost', 0)),
                    'shares': int(data.get('shares', 0)),
                }
            
            return None
            
        except HttpError as e:
            logger.error(f"YouTube Analytics API error for {video_id}: {e}")
            return None
    
    def fetch_audience_retention(self, video_id: str) -> Optional[List[float]]:
        """
        Fetch audience retention curve for a video.
        
        Returns list of retention percentages at each percentage of video duration.
        e.g., [95.0, 92.0, 88.0, ...] means 95% retained at 0-1%, 92% at 1-2%, etc.
        """
        if not self._youtube_analytics:
            return self._mock_retention_curve(video_id)
        
        try:
            # This requires specific API access
            response = self._youtube_analytics.reports().query(
                ids=f'channel=={self.config.channel_id}',
                startDate='2020-01-01',
                endDate=datetime.now().strftime('%Y-%m-%d'),
                metrics='audienceWatchRatio',
                dimensions='elapsedVideoTimeRatio',
                filters=f'video=={video_id}'
            ).execute()
            
            if response.get('rows'):
                # Extract retention values
                retention = [float(row[1]) * 100 for row in response['rows']]
                return retention
            
            return None
            
        except HttpError as e:
            logger.error(f"Retention API error for {video_id}: {e}")
            return None
    
    def fetch_viewer_types(self, video_id: str) -> Optional[Dict[str, int]]:
        """
        Fetch viewer type breakdown (new vs returning).
        
        Note: This specific breakdown may require creator studio access
        """
        if not self._youtube_analytics:
            return self._mock_viewer_types(video_id)
        
        try:
            # Viewer type dimension (if available)
            response = self._youtube_analytics.reports().query(
                ids=f'channel=={self.config.channel_id}',
                startDate='2020-01-01',
                endDate=datetime.now().strftime('%Y-%m-%d'),
                metrics='views',
                dimensions='subscribedStatus',
                filters=f'video=={video_id}'
            ).execute()
            
            result = {'new_viewers': 0, 'returning_viewers': 0}
            
            if response.get('rows'):
                for row in response['rows']:
                    status = row[0]  # SUBSCRIBED or UNSUBSCRIBED
                    views = int(row[1])
                    
                    if status == 'SUBSCRIBED':
                        result['returning_viewers'] = views
                    else:
                        result['new_viewers'] = views
            
            return result
            
        except HttpError as e:
            logger.error(f"Viewer types API error for {video_id}: {e}")
            return None
    
    def fetch_all_channel_videos(self, limit: int = 100) -> List[str]:
        """
        Fetch all video IDs from the channel.
        
        Returns list of video IDs ordered by publish date (newest first)
        """
        if not self._youtube_data:
            return self._mock_channel_videos(limit)
        
        try:
            video_ids = []
            next_page_token = None
            
            while len(video_ids) < limit:
                response = self._youtube_data.search().list(
                    part='id',
                    channelId=self.config.channel_id,
                    type='video',
                    order='date',
                    maxResults=min(50, limit - len(video_ids)),
                    pageToken=next_page_token
                ).execute()
                
                for item in response.get('items', []):
                    video_ids.append(item['id']['videoId'])
                
                next_page_token = response.get('nextPageToken')
                if not next_page_token:
                    break
            
            return video_ids
            
        except HttpError as e:
            logger.error(f"Channel videos API error: {e}")
            return []
    
    # =========================================================================
    # MOCK DATA (for testing without API access)
    # =========================================================================
    
    def _mock_video_statistics(self, video_id: str) -> Dict[str, Any]:
        """Generate mock statistics for testing."""
        import random
        return {
            'video_id': video_id,
            'title': f'Mock Video {video_id}',
            'published_at': (datetime.now() - timedelta(days=random.randint(1, 30))).isoformat(),
            'duration_seconds': random.randint(30, 60),
            'view_count': random.randint(500, 5000),
            'like_count': random.randint(20, 200),
            'comment_count': random.randint(5, 50),
        }
    
    def _mock_video_analytics(self, video_id: str) -> Dict[str, Any]:
        """Generate mock analytics for testing."""
        import random
        return {
            'video_id': video_id,
            'views': random.randint(500, 5000),
            'avg_view_duration': random.uniform(20, 50),
            'avg_view_percentage': random.uniform(40, 90),
            'subscribers_gained': random.randint(0, 20),
            'subscribers_lost': random.randint(0, 5),
            'shares': random.randint(0, 30),
        }
    
    def _mock_retention_curve(self, video_id: str) -> List[float]:
        """Generate mock retention curve."""
        import random
        # Typical retention curve: starts high, drops quickly, then stabilizes
        retention = [100.0]
        for i in range(99):
            drop = random.uniform(0.5, 2.0)
            retention.append(max(10.0, retention[-1] - drop))
        return retention
    
    def _mock_viewer_types(self, video_id: str) -> Dict[str, int]:
        """Generate mock viewer types."""
        import random
        total = random.randint(500, 5000)
        returning = int(total * random.uniform(0.2, 0.4))
        return {
            'new_viewers': total - returning,
            'returning_viewers': returning
        }
    
    def _mock_channel_videos(self, limit: int) -> List[str]:
        """Generate mock video IDs."""
        return [f'mock_video_{i}' for i in range(limit)]
    
    # =========================================================================
    # UTILITIES
    # =========================================================================
    
    def _parse_duration(self, duration_str: str) -> int:
        """Parse ISO 8601 duration (PT1M30S) to seconds."""
        import re
        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
        if not match:
            return 0
        
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        
        return hours * 3600 + minutes * 60 + seconds


# =============================================================================
# DATA TRANSFORMER
# =============================================================================

class MetricsTransformer:
    """
    Transforms raw YouTube API data into our internal VideoDocument format.
    """
    
    @staticmethod
    def transform_to_video_document(
        video_id: str,
        statistics: Dict[str, Any],
        analytics: Dict[str, Any],
        viewer_types: Dict[str, int],
        series_id: Optional[str] = None,
        episode_number: Optional[int] = None,
        topic_cluster: Optional[str] = None
    ) -> VideoDocument:
        """
        Transform API responses into a VideoDocument.
        
        Computes derived metrics automatically.
        """
        # Build raw metrics
        metrics = VideoMetrics(
            views_total=statistics.get('view_count', 0),
            views_24h=analytics.get('views', 0),  # May need time-based query
            views_48h=analytics.get('views', 0),  # Placeholder
            avg_view_percentage=analytics.get('avg_view_percentage', 0.0),
            likes=statistics.get('like_count', 0),
            comments=statistics.get('comment_count', 0),
            shares=analytics.get('shares', 0),
            subscribers_gained=analytics.get('subscribers_gained', 0),
            subscribers_lost=analytics.get('subscribers_lost', 0),
            returning_viewers=viewer_types.get('returning_viewers', 0),
            new_viewers=viewer_types.get('new_viewers', 0)
        )
        
        # Compute derived metrics
        total_viewers = metrics.returning_viewers + metrics.new_viewers
        engagement = (metrics.likes + metrics.comments + metrics.shares) / max(1, metrics.views_total)
        
        derived = DerivedMetrics(
            engagement_rate=min(engagement * 100, 100.0),  # As percentage
            repeat_viewer_ratio=metrics.returning_viewers / max(1, total_viewers)
        )
        
        # Determine status
        if analytics.get('avg_view_percentage', 0) < 50 and analytics.get('views', 0) < 100:
            status = VideoStatus.LOW_SIGNAL
        else:
            status = VideoStatus.ACTIVE
        
        return VideoDocument(
            video_id=video_id,
            youtube_video_id=video_id,
            series_id=series_id,
            topic_cluster=topic_cluster,
            episode_number=episode_number,
            title=statistics.get('title', ''),
            published_at=statistics.get('published_at', datetime.now().isoformat()),
            duration_seconds=statistics.get('duration_seconds', 0),
            status=status,
            metrics=metrics,
            derived=derived,
            last_updated=datetime.now(timezone.utc).isoformat()
        )


# =============================================================================
# INGESTION ORCHESTRATOR
# =============================================================================

class MetricsIngestionOrchestrator:
    """
    Orchestrates the full ingestion process.
    
    1. Fetches video list from channel
    2. For each video, fetches all metrics
    3. Transforms to internal format
    4. Returns documents ready for Firestore
    """
    
    def __init__(self, config: YouTubeAPIConfig):
        self.fetcher = YouTubeMetricsFetcher(config)
        self.transformer = MetricsTransformer()
    
    def ingest_video(
        self,
        video_id: str,
        series_id: Optional[str] = None,
        episode_number: Optional[int] = None,
        topic_cluster: Optional[str] = None
    ) -> Optional[VideoDocument]:
        """Ingest a single video's metrics."""
        
        # Fetch all data
        stats = self.fetcher.fetch_video_statistics(video_id)
        if not stats:
            logger.error(f"Failed to fetch statistics for {video_id}")
            return None
        
        # Analytics for last 7 days
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        
        analytics = self.fetcher.fetch_video_analytics(video_id, start_date, end_date)
        analytics = analytics or {}
        
        viewer_types = self.fetcher.fetch_viewer_types(video_id)
        viewer_types = viewer_types or {'new_viewers': 0, 'returning_viewers': 0}
        
        # Transform
        return self.transformer.transform_to_video_document(
            video_id=video_id,
            statistics=stats,
            analytics=analytics,
            viewer_types=viewer_types,
            series_id=series_id,
            episode_number=episode_number,
            topic_cluster=topic_cluster
        )
    
    def ingest_channel_videos(
        self,
        limit: int = 50,
        series_mapping: Optional[Dict[str, Tuple[str, int]]] = None
    ) -> List[VideoDocument]:
        """
        Ingest metrics for all recent channel videos.
        
        Args:
            limit: Max videos to ingest
            series_mapping: Dict mapping video_id to (series_id, episode_number)
        
        Returns:
            List of VideoDocument objects
        """
        series_mapping = series_mapping or {}
        
        video_ids = self.fetcher.fetch_all_channel_videos(limit)
        documents = []
        
        for video_id in video_ids:
            series_info = series_mapping.get(video_id, (None, None))
            
            doc = self.ingest_video(
                video_id=video_id,
                series_id=series_info[0],
                episode_number=series_info[1]
            )
            
            if doc:
                documents.append(doc)
                logger.info(f"Ingested video {video_id}: {doc.metrics.views_total} views")
        
        logger.info(f"Ingested {len(documents)} videos from channel")
        return documents
