import logging
from pathlib import Path
from youtube_upload import upload_short_with_metadata

logger = logging.getLogger(__name__)

def upload_video_to_youtube(video_path, topic, duration, metadata=None):
    """Upload generated video to YouTube as Short with dynamic metadata"""
    try:
        if not Path(video_path).exists():
            logger.error(f"❌ Video file not found: {video_path}")
            return None
        
        # Use provided metadata or create fallback
        if metadata:
            title = metadata.get('title', f"{topic} in {duration} Seconds! #Shorts")
            description = metadata.get('description', f"Quick tutorial on {topic}! Thanks to Code Tapasya!")
            tags = metadata.get('tags', ['programming', 'coding', 'tutorial', 'shorts'])
        else:
            # Fallback metadata
            title = f"{topic} in {duration} Seconds! #Shorts"
            description = f"""Quick tutorial on {topic}!

🔥 Learn programming concepts in bite-sized videos
💡 Perfect for developers on the go
📚 More tutorials coming daily

Thanks to Code Tapasya for the amazing content!

#Programming #Coding #Tutorial #LearnToCode #Developer #TechTips"""
            tags = ['Programming', 'Coding', 'Tutorial', 'Shorts', 'Education', 'TechTips']
        
        logger.info(f"📤 Uploading to YouTube: {title[:50]}...")
        response = upload_short_with_metadata(video_path, title, description, tags)
        
        video_id = response.get('id')
        if video_id:
            logger.info(f"✅ YouTube upload successful: {video_id}")
            logger.info(f"📈 Title: {title}")
            logger.info(f"🔗 URL: https://youtube.com/watch?v={video_id}")
            return video_id
        else:
            logger.error("❌ YouTube upload failed - no video ID returned")
            return None
            
    except Exception as e:
        logger.error(f"❌ YouTube upload failed: {e}")
        return None