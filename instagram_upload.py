#!/usr/bin/env python3
"""
Instagram Reels Upload Module
Uploads videos to Instagram as Reels using instagrapi
"""

import os
import base64
import logging
from pathlib import Path
from typing import Optional, Dict
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, TwoFactorRequired, ChallengeRequired
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

class InstagramUploader:
    """Handle Instagram Reels uploads"""
    
    def __init__(self, username: str = None, password: str = None):
        self.username = username or os.getenv("INSTAGRAM_USERNAME")
        
        # Try base64 encoded password first, then fallback to plain text
        if password:
            self.password = password
        else:
            password_b64 = os.getenv("INSTAGRAM_PASSWORD_BASE64")
            if password_b64:
                try:
                    self.password = base64.b64decode(password_b64).decode('utf-8')
                    self.password = base64.b64decode(self.password).decode('utf-8')
                    logger.debug("✅ Instagram password decoded from base64")
                except Exception as e:
                    logger.error(f"❌ Failed to decode INSTAGRAM_PASSWORD_BASE64: {e}")
                    self.password = os.getenv("INSTAGRAM_PASSWORD")  # Fallback to plain text
            else:
                self.password = os.getenv("INSTAGRAM_PASSWORD")  # Fallback to plain text
        
        self.client = None
        self.session_file = Path("instagram_session.json")
        
        # Use more realistic device settings to avoid detection
        self.device_settings = {
            "manufacturer": "OnePlus",
            "model": "ONEPLUS A6013",
            "android_version": 29,
            "android_release": "10.0"
        }
        
        if not self.username or not self.password:
            raise ValueError("Instagram credentials not provided. Set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD_BASE64 (or INSTAGRAM_PASSWORD) in .env")
    
    def login(self) -> bool:
        """Login to Instagram with session persistence"""
        try:
            self.client = Client()
            self.client.delay_range = [2, 5]  # Increased delay to appear more human-like
            
            # Set device settings to avoid detection
            self.client.set_device(self.device_settings)
            
            # Set more realistic user agent
            self.client.set_user_agent(
                "Instagram 269.0.0.18.75 Android (29/10; 420dpi; 1080x2340; OnePlus; ONEPLUS A6013; OnePlus6T; qcom; en_US; 314665256)"
            )
            
            # Try to load existing session
            if self.session_file.exists():
                try:
                    logger.info("📱 Loading existing Instagram session...")
                    self.client.load_settings(self.session_file)
                    
                    # Relogin to refresh session
                    try:
                        self.client.relogin()
                        logger.info("✅ Instagram session relogin successful")
                        return True
                    except:
                        # If relogin fails, try full login
                        logger.info("⚠️ Relogin failed, attempting full login...")
                        self.client.login(self.username, self.password)
                    
                    # Verify session is valid
                    self.client.get_timeline_feed()
                    logger.info("✅ Instagram session loaded successfully")
                    return True
                except Exception as e:
                    logger.warning(f"⚠️ Existing session invalid: {e}")
                    self.session_file.unlink(missing_ok=True)
            
            # New login - use verification_code parameter for more reliable login
            logger.info("📱 Logging into Instagram (new session)...")
            logger.info("💡 If this fails, try logging in from Instagram app/browser first")
            
            self.client.login(self.username, self.password)
            
            # Save session for future use
            self.client.dump_settings(self.session_file)
            logger.info("✅ Instagram login successful, session saved")
            return True
            
        except TwoFactorRequired:
            logger.error("❌ Two-factor authentication required!")
            logger.error("💡 Disable 2FA temporarily or implement 2FA code input")
            return False
            
        except ChallengeRequired as e:
            logger.error("❌ Instagram challenge required (suspicious login detected)")
            logger.error("💡 Login manually from your device first, then try again")
            logger.error(f"Details: {e}")
            return False
            
        except LoginRequired as e:
            logger.error(f"❌ Login failed: {e}")
            return False
            
        except Exception as e:
            logger.error(f"❌ Unexpected login error: {e}")
            
            # Provide helpful troubleshooting steps
            logger.error("=" * 60)
            logger.error("💡 TROUBLESHOOTING STEPS:")
            logger.error("1. Login to Instagram from your phone/browser first")
            logger.error("2. Complete any security challenges manually")
            logger.error("3. Disable 2FA temporarily if enabled")
            logger.error("4. Wait 30-60 minutes before retrying")
            logger.error("5. Consider using a VPN or different network")
            logger.error("6. Ensure account is Business/Creator type")
            logger.error("=" * 60)
            
            return False
    
    def generate_caption(self, topic: str, metadata: Dict = None) -> str:
        """Generate Instagram-optimized caption with hashtags"""
        
        # Extract title from metadata if available
        if metadata and 'title' in metadata:
            title = metadata['title'].replace('#Shorts', '').replace('#shorts', '').strip()
        else:
            title = topic
        
        # Create engaging caption
        caption = f"{title}\n\n"
        caption += "💡 Quick tech knowledge for busy developers!\n\n"
        
        # Add hashtags optimized for Instagram Reels
        hashtags = [
            "#programming", "#coding", "#developer", "#tech",
            "#softwaredeveloper", "#webdevelopment", "#python",
            "#javascript", "#learntocode", "#100daysofcode",
            "#codinglife", "#programmingmemes", "#techreels",
            "#reelsinstagram", "#explorepage", "#viral",
            "#codetutorial", "#webdev", "#codingbootcamp",
            "#programmerslife"
        ]
        
        caption += " ".join(hashtags[:20])  # Instagram allows 30 hashtags, use 20
        caption += "\n\n📚 Follow for more tech content!"
        
        return caption
    
    def upload_reel(self, video_path: str, topic: str, metadata: Dict = None) -> Optional[str]:
        """
        Upload video to Instagram as a Reel
        
        Args:
            video_path: Path to the video file
            topic: Video topic/title
            metadata: Optional metadata dict from YouTube (contains title, description, tags)
            
        Returns:
            Media ID if successful, None otherwise
        """
        
        if not self.client:
            logger.error("❌ Not logged in to Instagram")
            return None
        
        try:
            # Check video file exists
            video_file = Path(video_path)
            if not video_file.exists():
                logger.error(f"❌ Video file not found: {video_path}")
                return None
            
            # Generate caption
            caption = self.generate_caption(topic, metadata)
            
            logger.info("📱 Uploading to Instagram Reels...")
            logger.info(f"📹 Video: {video_file.name}")
            logger.info(f"📝 Caption preview: {caption[:100]}...")
            
            # Upload as Reel (clip)
            media = self.client.clip_upload(
                path=video_path,
                caption=caption,
            )
            
            if media:
                media_id = media.pk
                media_code = media.code
                instagram_url = f"https://www.instagram.com/reel/{media_code}/"
                
                logger.info("✅ Instagram Reel uploaded successfully!")
                logger.info(f"📱 Media ID: {media_id}")
                logger.info(f"🔗 URL: {instagram_url}")
                
                return media_id
            else:
                logger.error("❌ Upload failed - no media returned")
                return None
                
        except Exception as e:
            logger.error(f"❌ Instagram upload failed: {e}")
            logger.error(f"💡 Check if account is flagged or rate limited")
            return None
    
    def logout(self):
        """Logout from Instagram"""
        if self.client:
            try:
                # Don't actually logout, keep session for reuse
                logger.info("📱 Instagram session preserved for reuse")
            except:
                pass


def upload_reel_to_instagram(video_path: str, topic: str, metadata: Dict = None) -> Optional[str]:
    """
    Standalone function to upload a reel to Instagram
    
    Args:
        video_path: Path to video file
        topic: Video topic
        metadata: Optional metadata from YouTube
        
    Returns:
        Instagram media ID if successful, None otherwise
    """
    
    # Check if Instagram upload is enabled
    if os.getenv("INSTAGRAM_ENABLED", "false").lower() != "true":
        logger.info("ℹ️ Instagram upload disabled (set INSTAGRAM_ENABLED=true to enable)")
        return None
    
    try:
        uploader = InstagramUploader()
        
        # Login
        if not uploader.login():
            logger.error("❌ Instagram login failed")
            return None
        
        # Upload
        media_id = uploader.upload_reel(video_path, topic, metadata)
        
        # Don't logout, keep session
        uploader.logout()
        
        return media_id
        
    except Exception as e:
        logger.error(f"❌ Instagram upload error: {e}")
        return None


# Test function
if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) < 3:
        print("Usage: python instagram_upload.py <video_path> <topic>")
        print("Example: python instagram_upload.py output/final_video.mp4 'Python Variables Explained'")
        sys.exit(1)
    
    video_path = sys.argv[1]
    topic = sys.argv[2]
    
    print("🧪 Testing Instagram Reels Upload")
    print("=" * 60)
    
    media_id = upload_reel_to_instagram(video_path, topic)
    
    if media_id:
        print("=" * 60)
        print("✅ TEST SUCCESSFUL")
        print(f"Media ID: {media_id}")
    else:
        print("=" * 60)
        print("❌ TEST FAILED")
        sys.exit(1)
