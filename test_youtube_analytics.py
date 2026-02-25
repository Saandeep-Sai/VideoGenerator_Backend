"""Test YouTube Analytics connection."""
from analytics.youtube_oauth_analytics import YouTubeAnalyticsFetcher
import logging
logging.basicConfig(level=logging.INFO)

fetcher = YouTubeAnalyticsFetcher()

if fetcher.is_connected:
    print('[OK] Connected to YouTube!')
    
    # Get channel overview
    overview = fetcher.get_channel_overview(days=7)
    if overview:
        print('Last 7 days:')
        print(f'  Views: {overview["total_views"]:,}')
        print(f'  Net subscribers: {overview["net_subscribers"]:+d}')
        print(f'  Avg retention: {overview["avg_view_percentage"]:.1f}%')
    
    # Get recent videos
    videos = fetcher.get_recent_videos(5)
    print(f'\nRecent videos: {len(videos)}')
    for v in videos[:5]:
        stats = fetcher.get_video_statistics(v["video_id"])
        views = stats["view_count"] if stats else 0
        print(f'  - {v["title"][:45]}... ({views:,} views)')
else:
    print('[X] Not connected')
