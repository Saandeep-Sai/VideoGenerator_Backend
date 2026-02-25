"""
YouTube Analytics using existing OAuth credentials.
Uses the same token.json as video uploads, but with expanded scopes.
"""

import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False

logger = logging.getLogger(__name__)

# Extended scopes - includes both upload AND analytics
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",        # Upload videos
    "https://www.googleapis.com/auth/youtube.readonly",      # Read video data
    "https://www.googleapis.com/auth/yt-analytics.readonly"  # Read analytics
]


def get_authenticated_services(token_path: str = "token.json", 
                                client_secret_path: str = "client_secret.json"):
    """
    Get authenticated YouTube Data API and Analytics API services.
    
    Uses the same OAuth flow as video uploads, just with expanded scopes.
    If token.json exists but doesn't have analytics scope, will prompt for re-auth.
    
    Returns:
        tuple: (youtube_data_service, youtube_analytics_service) or (None, None) if failed
    """
    if not HAS_GOOGLE_API:
        logger.error("Google API libraries not installed")
        return None, None
    
    creds = None
    
    # Load existing credentials
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    # Check if credentials need refresh or re-auth
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info("Refreshed OAuth token")
            except Exception as e:
                logger.warning(f"Token refresh failed: {e}, need re-auth")
                creds = None
        
        if not creds:
            if not os.path.exists(client_secret_path):
                logger.error(f"client_secret.json not found at {client_secret_path}")
                return None, None
            
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            try:
                creds = flow.run_local_server(port=0)
                logger.info("Completed OAuth authentication")
            except Exception as e:
                logger.error(f"OAuth flow failed: {e}")
                print("\n" + "=" * 60)
                print("To enable analytics, run on your LOCAL machine:")
                print("  python generate_youtube_token_with_analytics.py")
                print("=" * 60)
                return None, None
            
            # Save credentials
            with open(token_path, "w") as token:
                token.write(creds.to_json())
            logger.info(f"Saved new token to {token_path}")
    
    # Build services
    try:
        youtube_data = build("youtube", "v3", credentials=creds)
        youtube_analytics = build("youtubeAnalytics", "v2", credentials=creds)
        logger.info("YouTube API services initialized")
        return youtube_data, youtube_analytics
    except Exception as e:
        logger.error(f"Failed to build YouTube services: {e}")
        return None, None


class YouTubeAnalyticsFetcher:
    """
    Fetches analytics for videos uploaded through this system.
    
    Uses OAuth2 credentials (same as upload) to access:
    - Basic video statistics (views, likes, comments)
    - Detailed analytics (retention, watch time, traffic sources)
    """
    
    def __init__(self, token_path: str = "token.json"):
        self.token_path = token_path
        self._youtube_data = None
        self._youtube_analytics = None
        self._channel_id = None
        self._initialize()
    
    def _initialize(self):
        """Initialize API clients."""
        self._youtube_data, self._youtube_analytics = get_authenticated_services(self.token_path)
        
        if self._youtube_data:
            # Get authenticated user's channel ID
            try:
                response = self._youtube_data.channels().list(
                    part="id,snippet",
                    mine=True
                ).execute()
                
                if response.get("items"):
                    self._channel_id = response["items"][0]["id"]
                    channel_title = response["items"][0]["snippet"]["title"]
                    logger.info(f"Connected to channel: {channel_title} ({self._channel_id})")
            except Exception as e:
                logger.error(f"Failed to get channel info: {e}")
    
    @property
    def is_connected(self) -> bool:
        """Check if properly connected to YouTube APIs."""
        return self._youtube_data is not None and self._channel_id is not None
    
    def get_video_statistics(self, video_id: str) -> Optional[Dict[str, Any]]:
        """
        Get basic statistics for a video.
        
        Returns:
            Dict with viewCount, likeCount, commentCount, etc.
        """
        if not self._youtube_data:
            return None
        
        try:
            response = self._youtube_data.videos().list(
                part="statistics,snippet,contentDetails",
                id=video_id
            ).execute()
            
            if response.get("items"):
                item = response["items"][0]
                return {
                    "video_id": video_id,
                    "title": item["snippet"]["title"],
                    "published_at": item["snippet"]["publishedAt"],
                    "view_count": int(item["statistics"].get("viewCount", 0)),
                    "like_count": int(item["statistics"].get("likeCount", 0)),
                    "comment_count": int(item["statistics"].get("commentCount", 0)),
                    "duration": item["contentDetails"]["duration"],
                }
            return None
            
        except HttpError as e:
            logger.error(f"Failed to get stats for {video_id}: {e}")
            return None
    
    def get_video_analytics(self, video_id: str, days: int = 7) -> Optional[Dict[str, Any]]:
        """
        Get detailed analytics for a video.
        
        Returns:
            Dict with views, averageViewDuration, averageViewPercentage, etc.
        """
        if not self._youtube_analytics or not self._channel_id:
            return None
        
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        try:
            response = self._youtube_analytics.reports().query(
                ids=f"channel=={self._channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="views,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost,shares,likes,comments",
                dimensions="video",
                filters=f"video=={video_id}"
            ).execute()
            
            if response.get("rows"):
                row = response["rows"][0]
                headers = [h["name"] for h in response["columnHeaders"]]
                data = dict(zip(headers, row))
                
                return {
                    "video_id": data.get("video", video_id),
                    "views": int(data.get("views", 0)),
                    "avg_view_duration_seconds": float(data.get("averageViewDuration", 0)),
                    "avg_view_percentage": float(data.get("averageViewPercentage", 0)),
                    "subscribers_gained": int(data.get("subscribersGained", 0)),
                    "subscribers_lost": int(data.get("subscribersLost", 0)),
                    "shares": int(data.get("shares", 0)),
                    "likes": int(data.get("likes", 0)),
                    "comments": int(data.get("comments", 0)),
                }
            return None
            
        except HttpError as e:
            logger.error(f"Failed to get analytics for {video_id}: {e}")
            return None
    
    def get_recent_videos(self, max_results: int = 20) -> List[Dict[str, Any]]:
        """
        Get list of recent videos from the channel.
        
        Returns:
            List of video metadata dicts.
        """
        if not self._youtube_data or not self._channel_id:
            return []
        
        try:
            # Get upload playlist ID
            channel_response = self._youtube_data.channels().list(
                part="contentDetails",
                id=self._channel_id
            ).execute()
            
            uploads_playlist = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
            
            # Get videos from uploads playlist
            response = self._youtube_data.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=uploads_playlist,
                maxResults=max_results
            ).execute()
            
            videos = []
            for item in response.get("items", []):
                videos.append({
                    "video_id": item["contentDetails"]["videoId"],
                    "title": item["snippet"]["title"],
                    "published_at": item["snippet"]["publishedAt"],
                    "thumbnail": item["snippet"]["thumbnails"]["default"]["url"]
                })
            
            return videos
            
        except HttpError as e:
            logger.error(f"Failed to get recent videos: {e}")
            return []
    
    def get_channel_overview(self, days: int = 28) -> Optional[Dict[str, Any]]:
        """
        Get channel-level analytics overview.
        """
        if not self._youtube_analytics or not self._channel_id:
            return None
        
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        try:
            response = self._youtube_analytics.reports().query(
                ids=f"channel=={self._channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost,averageViewDuration,averageViewPercentage"
            ).execute()
            
            if response.get("rows"):
                row = response["rows"][0]
                headers = [h["name"] for h in response["columnHeaders"]]
                data = dict(zip(headers, row))
                
                return {
                    "period_days": days,
                    "total_views": int(data.get("views", 0)),
                    "watch_time_minutes": float(data.get("estimatedMinutesWatched", 0)),
                    "subscribers_gained": int(data.get("subscribersGained", 0)),
                    "subscribers_lost": int(data.get("subscribersLost", 0)),
                    "net_subscribers": int(data.get("subscribersGained", 0)) - int(data.get("subscribersLost", 0)),
                    "avg_view_duration": float(data.get("averageViewDuration", 0)),
                    "avg_view_percentage": float(data.get("averageViewPercentage", 0))
                }
            return None
            
        except HttpError as e:
            logger.error(f"Failed to get channel overview: {e}")
            return None


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    fetcher = YouTubeAnalyticsFetcher()
    
    if fetcher.is_connected:
        print("\n=== Channel Connected ===")
        
        # Get channel overview
        overview = fetcher.get_channel_overview(days=7)
        if overview:
            print(f"\nLast 7 days:")
            print(f"  Views: {overview['total_views']:,}")
            print(f"  Watch time: {overview['watch_time_minutes']:.0f} min")
            print(f"  Net subscribers: {overview['net_subscribers']:+d}")
            print(f"  Avg retention: {overview['avg_view_percentage']:.1f}%")
        
        # Get recent videos
        print("\n=== Recent Videos ===")
        videos = fetcher.get_recent_videos(5)
        for v in videos:
            stats = fetcher.get_video_statistics(v["video_id"])
            if stats:
                print(f"  {v['title'][:40]}... - {stats['view_count']:,} views")
    else:
        print("Not connected. Run with valid token.json")
