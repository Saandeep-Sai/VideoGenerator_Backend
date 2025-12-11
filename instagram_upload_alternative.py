#!/usr/bin/env python3
"""
Alternative Instagram Upload using instabot library
More reliable for automation but requires manual verification first
"""

import os
import logging
from pathlib import Path
from typing import Optional, Dict
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

def upload_using_instabot(video_path: str, topic: str, metadata: Dict = None) -> Optional[str]:
    """
    Alternative upload method using instabot library
    Requires: pip install instabot
    """
    try:
        from instabot import Bot
        
        bot = Bot()
        username = os.getenv("INSTAGRAM_USERNAME")
        password = os.getenv("INSTAGRAM_PASSWORD")
        
        # Login
        bot.login(username=username, password=password)
        
        # Generate caption
        caption = f"{topic}\n\n"
        caption += "#programming #coding #developer #tech #shorts"
        
        # Upload video as IGTV (Reels alternative)
        # Note: instabot doesn't have direct Reels support
        bot.upload_video(video_path, caption=caption)
        
        logger.info("✅ Video uploaded via instabot")
        return "uploaded"
        
    except Exception as e:
        logger.error(f"❌ Instabot upload failed: {e}")
        return None


def upload_using_graph_api(video_path: str, topic: str, metadata: Dict = None) -> Optional[str]:
    """
    Official Meta Graph API method (requires Business account)
    More reliable but needs Facebook Business setup
    
    Setup steps:
    1. Convert to Business/Creator account
    2. Connect to Facebook Page
    3. Get access token from developers.facebook.com
    4. Add to .env: INSTAGRAM_ACCESS_TOKEN="your_token"
    """
    try:
        import requests
        
        access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
        instagram_account_id = os.getenv("INSTAGRAM_ACCOUNT_ID")
        
        if not access_token or not instagram_account_id:
            logger.error("❌ Missing INSTAGRAM_ACCESS_TOKEN or INSTAGRAM_ACCOUNT_ID")
            return None
        
        # Step 1: Create container
        url = f"https://graph.facebook.com/v18.0/{instagram_account_id}/media"
        
        caption = f"{topic}\n\n#programming #coding #tech"
        
        # Upload video file first (to Facebook hosting)
        files = {'file': open(video_path, 'rb')}
        data = {
            'media_type': 'REELS',
            'caption': caption,
            'access_token': access_token
        }
        
        response = requests.post(url, data=data, files=files)
        result = response.json()
        
        if 'id' not in result:
            logger.error(f"❌ Container creation failed: {result}")
            return None
        
        container_id = result['id']
        
        # Step 2: Publish container
        publish_url = f"https://graph.facebook.com/v18.0/{instagram_account_id}/media_publish"
        publish_data = {
            'creation_id': container_id,
            'access_token': access_token
        }
        
        publish_response = requests.post(publish_url, data=publish_data)
        publish_result = publish_response.json()
        
        if 'id' in publish_result:
            media_id = publish_result['id']
            logger.info(f"✅ Graph API upload successful: {media_id}")
            return media_id
        else:
            logger.error(f"❌ Publish failed: {publish_result}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Graph API upload failed: {e}")
        return None


if __name__ == "__main__":
    print("""
    INSTAGRAM UPLOAD ALTERNATIVES
    ==============================
    
    OPTION 1: Fix current instagrapi method
    - Login to Instagram manually from phone/browser first
    - Complete security challenges
    - Wait 30-60 minutes
    - Try script again
    
    OPTION 2: Use instabot (simpler but less features)
    - pip install instabot
    - Run: upload_using_instabot()
    
    OPTION 3: Use Official Graph API (most reliable)
    - Convert to Business/Creator account
    - Connect to Facebook Page
    - Get access token from developers.facebook.com
    - Run: upload_using_graph_api()
    
    Recommended: Option 1 (manual login first) or Option 3 (Graph API)
    """)
