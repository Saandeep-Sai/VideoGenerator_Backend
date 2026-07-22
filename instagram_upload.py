#!/usr/bin/env python3
"""
Instagram Reels Upload Module — Graph API
==========================================

Uploads videos to Instagram as Reels using the official Instagram Graph API.
Uses a 3-step container-based workflow:
  1. POST /{ig-user-id}/media  → Create container (media_type=REELS)
  2. GET  /{creation-id}?fields=status_code  → Poll until FINISHED
  3. POST /{ig-user-id}/media_publish  → Publish the Reel

Requirements:
  - Instagram Business account connected to a Facebook Page
  - Instagram_Access_Token in .env (long-lived user access token)
  - INSTAGRAM_USER_ID in .env (Instagram Business account ID)
  - Video must be at a publicly accessible URL (e.g., Oracle Object Storage)

Video Specifications:
  - Aspect ratio: 9:16 (recommended)
  - Duration: 5–90 seconds
  - Format: H.264 / MP4
"""

import os
import time
import logging
from typing import Optional, Dict

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

# Graph API version
GRAPH_API_VERSION = "v25.0"
GRAPH_API_BASE = f"https://graph.instagram.com/{GRAPH_API_VERSION}"


class InstagramGraphUploader:
    """Upload Reels to Instagram via the official Graph API."""

    def __init__(self, access_token: str = None, user_id: str = None):
        self.access_token = access_token or os.getenv("Instagram_Access_Token")
        self.user_id = user_id or os.getenv("INSTAGRAM_USER_ID")

        if not self.access_token:
            raise ValueError(
                "Instagram access token not found. "
                "Set Instagram_Access_Token in .env"
            )
        if not self.user_id:
            raise ValueError(
                "Instagram user ID not found. "
                "Set INSTAGRAM_USER_ID in .env"
            )

    # ── STEP 1: Create Media Container ──────────────────────────────
    def create_container(
        self, video_url: str, caption: str
    ) -> Optional[str]:
        """
        Create a Reels media container.

        Args:
            video_url: Publicly accessible URL to the video file.
            caption: Caption text including hashtags.

        Returns:
            Container creation ID, or None on failure.
        """
        url = f"{GRAPH_API_BASE}/{self.user_id}/media"
        payload = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": self.access_token,
        }

        try:
            resp = requests.post(url, data=payload, timeout=60)
            data = resp.json()

            if "id" in data:
                creation_id = data["id"]
                logger.info(f"✅ Container created: {creation_id}")
                return creation_id
            else:
                error = data.get("error", {})
                logger.error(
                    f"❌ Container creation failed: "
                    f"{error.get('message', data)}"
                )
                return None

        except requests.RequestException as e:
            logger.error(f"❌ Container creation request failed: {e}")
            return None

    # ── STEP 2: Poll Container Status ───────────────────────────────
    def wait_for_container(
        self,
        creation_id: str,
        max_wait: int = 300,
        poll_interval: int = 10,
    ) -> bool:
        """
        Poll the container until its status is FINISHED.

        Args:
            creation_id: The container ID from step 1.
            max_wait: Maximum seconds to wait.
            poll_interval: Seconds between polls.

        Returns:
            True if container is FINISHED, False on timeout/error.
        """
        url = f"{GRAPH_API_BASE}/{creation_id}"
        params = {
            "fields": "status_code",
            "access_token": self.access_token,
        }

        elapsed = 0
        while elapsed < max_wait:
            try:
                resp = requests.get(url, params=params, timeout=30)
                data = resp.json()
                status = data.get("status_code", "UNKNOWN")

                logger.info(
                    f"📊 Container {creation_id} status: {status} "
                    f"(waited {elapsed}s)"
                )

                if status == "FINISHED":
                    return True
                elif status == "ERROR":
                    logger.error(
                        f"❌ Container processing failed: {data}"
                    )
                    return False
                # IN_PROGRESS — keep waiting

            except requests.RequestException as e:
                logger.warning(f"⚠️ Poll request failed: {e}")

            time.sleep(poll_interval)
            elapsed += poll_interval

        logger.error(
            f"❌ Container {creation_id} timed out after {max_wait}s"
        )
        return False

    # ── STEP 3: Publish the Reel ────────────────────────────────────
    def publish(self, creation_id: str) -> Optional[str]:
        """
        Publish a finished container as a Reel.

        Args:
            creation_id: The container ID from step 1.

        Returns:
            Published media ID, or None on failure.
        """
        url = f"{GRAPH_API_BASE}/{self.user_id}/media_publish"
        payload = {
            "creation_id": creation_id,
            "access_token": self.access_token,
        }

        try:
            resp = requests.post(url, data=payload, timeout=60)
            data = resp.json()

            if "id" in data:
                media_id = data["id"]
                logger.info(f"✅ Reel published! Media ID: {media_id}")
                return media_id
            else:
                error = data.get("error", {})
                logger.error(
                    f"❌ Publish failed: {error.get('message', data)}"
                )
                return None

        except requests.RequestException as e:
            logger.error(f"❌ Publish request failed: {e}")
            return None

    # ── Full Upload Flow ────────────────────────────────────────────
    def upload_reel(
        self, video_url: str, topic: str, metadata: Dict = None
    ) -> Optional[str]:
        """
        Complete Reel upload: create → poll → publish.

        Args:
            video_url: Public URL to the video (e.g., Oracle Storage URL).
            topic: Video topic for caption generation.
            metadata: Optional metadata dict (title, description, tags).

        Returns:
            Published media ID, or None on failure.
        """
        caption = self.generate_caption(topic, metadata)

        logger.info("📱 Instagram Graph API: Starting Reel upload...")
        logger.info(f"📹 Video URL: {video_url[:80]}...")
        logger.info(f"📝 Caption preview: {caption[:100]}...")

        # Step 1: Create container
        creation_id = self.create_container(video_url, caption)
        if not creation_id:
            return None

        # Step 2: Wait for processing
        logger.info("⏳ Waiting for video processing...")
        if not self.wait_for_container(creation_id):
            return None

        # Step 3: Publish
        media_id = self.publish(creation_id)
        if media_id:
            logger.info(
                f"🎉 Instagram Reel live! "
                f"https://www.instagram.com/reel/{media_id}/"
            )
        return media_id

    # ── Caption Generator ───────────────────────────────────────────
    @staticmethod
    def generate_caption(topic: str, metadata: Dict = None) -> str:
        """Generate Instagram-optimized caption with hashtags."""
        if metadata and "title" in metadata:
            title = (
                metadata["title"]
                .replace("#Shorts", "")
                .replace("#shorts", "")
                .strip()
            )
        else:
            title = topic

        caption = f"{title}\n\n"
        caption += "💡 Quick tech knowledge for busy developers!\n\n"

        hashtags = [
            "#programming", "#coding", "#developer", "#tech",
            "#softwaredeveloper", "#webdevelopment", "#python",
            "#javascript", "#learntocode", "#100daysofcode",
            "#codinglife", "#programmingmemes", "#techreels",
            "#reelsinstagram", "#explorepage", "#viral",
            "#codetutorial", "#webdev", "#codingbootcamp",
            "#programmerslife",
        ]

        caption += " ".join(hashtags[:20])
        caption += "\n\n📚 Follow for more tech content!"

        return caption


# ═══════════════════════════════════════════════════════════════════
# STANDALONE FUNCTION (backward-compatible interface)
# ═══════════════════════════════════════════════════════════════════

def upload_reel_to_instagram(
    video_url: str, topic: str, metadata: Dict = None
) -> Optional[str]:
    """
    Standalone function to upload a Reel via Graph API.

    Args:
        video_url: Public URL to video file (Oracle Storage / CDN).
        topic: Video topic for caption.
        metadata: Optional metadata from YouTube.

    Returns:
        Instagram media ID if successful, None otherwise.
    """
    # Check if Instagram upload is enabled
    if os.getenv("INSTAGRAM_ENABLED", "false").lower() != "true":
        logger.info(
            "ℹ️ Instagram upload disabled "
            "(set INSTAGRAM_ENABLED=true to enable)"
        )
        return None

    try:
        uploader = InstagramGraphUploader()
        return uploader.upload_reel(video_url, topic, metadata)

    except ValueError as e:
        logger.error(f"❌ Instagram config error: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Instagram upload error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if len(sys.argv) < 3:
        print("Usage: python instagram_upload.py <video_url> <topic>")
        print(
            "Example: python instagram_upload.py "
            "'https://objectstorage.../video.mp4' 'Python Variables'"
        )
        sys.exit(1)

    video_url = sys.argv[1]
    topic = sys.argv[2]

    print("🧪 Testing Instagram Graph API Reel Upload")
    print("=" * 60)

    media_id = upload_reel_to_instagram(video_url, topic)

    if media_id:
        print("=" * 60)
        print("✅ TEST SUCCESSFUL")
        print(f"Media ID: {media_id}")
    else:
        print("=" * 60)
        print("❌ TEST FAILED")
        sys.exit(1)
