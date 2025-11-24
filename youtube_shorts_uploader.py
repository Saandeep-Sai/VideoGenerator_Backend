import logging
from pathlib import Path
from youtube_upload import upload_short

logger = logging.getLogger(__name__)

def upload_video_to_youtube(video_path, topic, duration):
    """Upload generated video to YouTube as Short"""
    try:
        if not Path(video_path).exists():
            logger.error(f"❌ Video file not found: {video_path}")
            return None
        
        # Create YouTube Short title and description
        title = f"{topic} in {duration} Seconds! #Shorts"
        description = f"""Quick tutorial on {topic}!

🔥 Learn programming concepts in bite-sized videos
💡 Perfect for developers on the go
📚 More tutorials coming daily

Thanks to Code Tapasya for the amazing content!

#Programming #Coding #Tutorial #LearnToCode #Developer #TechTips"""
        
        logger.info(f"📤 Uploading to YouTube: {title}")
        response = upload_short(video_path, title, description)
        
        video_id = response.get('id')
        if video_id:
            logger.info(f"✅ YouTube upload successful: {video_id}")
            logger.info(f"🔗 URL: https://youtube.com/watch?v={video_id}")
            return video_id
        else:
            logger.error("❌ YouTube upload failed - no video ID returned")
            return None
            
    except Exception as e:
        logger.error(f"❌ YouTube upload failed: {e}")
        return None