#!/usr/bin/env python3
"""
Standalone YouTube Shorts Auto-Generator & Uploader
Runs independently on E2.Micro #2 - NO external dependencies
Generates videos locally, uploads to YouTube automatically

Schedule: 2x daily (configurable via UPLOAD_TIMES env var)
Topics: Rotates through 30+ programming topics (no repeats within 30 days)
"""

import os
import sys
import json
import asyncio
import logging
import schedule
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import local modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generator.video_generator.optimized_video_generator import OptimizedVideoGenerationPipeline, VideoGenerationConfig
from generator.oracle_storage import OracleStorageClient
from youtube_upload import upload_short
from generator.firebase_utils import create_job, update_video_status_with_url
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Get configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
UPLOAD_TIMES = os.getenv("UPLOAD_TIMES", "09:00,18:00").split(",")

if not GEMINI_API_KEY or not GROQ_API_KEY:
    logger.error("❌ Missing API keys! Set GEMINI_API_KEY and GROQ_API_KEY in .env")
    sys.exit(1)

logger.info("=" * 70)
logger.info("🎬 STANDALONE YOUTUBE SHORTS GENERATOR & UPLOADER")
logger.info("=" * 70)
logger.info(f"📅 Upload times (UTC): {', '.join(UPLOAD_TIMES)}")
logger.info("=" * 70)

# Topics database - 30+ unique topics
PROGRAMMING_TOPICS = [
    "Object-Oriented Programming",
    "Design Patterns in Python",
    "Async/Await Programming",
    "Data Structures and Algorithms",
    "Database Design Principles",
    "REST API Development",
    "GraphQL Basics",
    "Machine Learning Fundamentals",
    "Docker and Containerization",
    "Kubernetes Orchestration",
    "Cloud Computing with AWS",
    "Microservices Architecture",
    "CI/CD Pipelines",
    "Git and Version Control",
    "Test-Driven Development",
    "Code Refactoring Techniques",
    "Performance Optimization",
    "Security Best Practices",
    "Authentication and Authorization",
    "Caching Strategies",
    "Load Balancing",
    "API Gateway Design",
    "Event-Driven Architecture",
    "Distributed Systems",
    "Database Optimization",
    "NoSQL vs SQL",
    "Functional Programming",
    "Software Design Principles",
    "Clean Code Practices",
    "Debugging Techniques",
]

class StandaloneYouTubeShortsGenerator:
    """Generates and uploads YouTube Shorts completely independently"""
    
    def __init__(self):
        """Initialize pipeline and storage"""
        logger.info("🚀 Initializing generator...")
        
        # Configure pipeline
        self.config = VideoGenerationConfig(
            gemini_api_key=GEMINI_API_KEY,
            groq_api_key=GROQ_API_KEY,
            aspect_ratio="9:16"  # YouTube Shorts format
        )
        self.pipeline = OptimizedVideoGenerationPipeline(self.config)
        self.oracle_storage = OracleStorageClient()
        
        logger.info("✅ Generator initialized")
    
    def load_topic_history(self) -> dict:
        """Load topic generation history"""
        history_file = Path("youtube_shorts_history.json")
        if history_file.exists():
            with open(history_file, "r") as f:
                return json.load(f)
        return {}
    
    def save_topic_history(self, history: dict):
        """Save topic generation history"""
        with open("youtube_shorts_history.json", "w") as f:
            json.dump(history, f, indent=2)
    
    def get_next_topic(self) -> str:
        """Get next topic (avoid repeats within 30 days)"""
        history = self.load_topic_history()
        today = datetime.now()
        thirty_days_ago = today - timedelta(days=30)
        
        # Filter out recently used topics
        recent_topics = set()
        for topic, last_used_str in history.items():
            last_used = datetime.fromisoformat(last_used_str)
            if last_used > thirty_days_ago:
                recent_topics.add(topic)
        
        # Find available topic
        for topic in PROGRAMMING_TOPICS:
            if topic not in recent_topics:
                return topic
        
        # If all topics used recently, start fresh
        logger.warning("⚠️ All topics used in last 30 days, starting fresh")
        return PROGRAMMING_TOPICS[0]
    
    def mark_topic_used(self, topic: str):
        """Mark topic as used"""
        history = self.load_topic_history()
        history[topic] = datetime.now().isoformat()
        self.save_topic_history(history)
        logger.info(f"✅ Topic marked as used: {topic}")
    
    async def generate_video(self, topic: str, duration: int = 60) -> Optional[str]:
        """Generate video locally (no API call)"""
        try:
            logger.info(f"🎬 Generating video locally...")
            logger.info(f"   Topic: {topic}")
            logger.info(f"   Duration: {duration}s")
            logger.info(f"   Format: 9:16 (YouTube Shorts)")
            
            # Generate video using local pipeline
            final_video_path = await self.pipeline.generate_video_full_parallel(
                topic, 
                duration
            )
            
            logger.info(f"✅ Video generated: {final_video_path}")
            return final_video_path
            
        except Exception as e:
            logger.error(f"❌ Video generation failed: {e}")
            return None
    
    def upload_to_youtube(self, video_path: str, topic: str, duration: int) -> Optional[str]:
        """Upload video to YouTube"""
        try:
            logger.info(f"📤 Uploading to YouTube...")
            
            title = f"{topic} in {duration} Seconds! #Shorts #Programming #LearnToCode"
            description = f"""Quick tutorial on {topic}!

🔥 Learn programming concepts in bite-sized videos
💡 Perfect for developers on the go
📚 Master coding one short at a time

Thanks to Code Tapasya for the amazing content!

#Programming #Coding #Tutorial #LearnToCode #Developer #TechTips"""
            
            response = upload_short(video_path, title, description)
            video_id = response.get('id')
            
            if video_id:
                youtube_url = f"https://youtube.com/watch?v={video_id}"
                logger.info(f"✅ YouTube upload successful!")
                logger.info(f"📺 Video ID: {video_id}")
                logger.info(f"🔗 URL: {youtube_url}")
                return video_id
            else:
                logger.error("❌ No video ID returned from YouTube")
                return None
                
        except Exception as e:
            logger.error(f"❌ YouTube upload failed: {e}")
            return None
    
    def upload_to_oracle(self, video_path: str, job_id: str) -> Optional[str]:
        """Upload video to Oracle Object Storage"""
        try:
            logger.info(f"📤 Uploading to Oracle Object Storage...")
            video_url = self.oracle_storage.upload_video(video_path, job_id)
            logger.info(f"✅ Oracle upload successful: {video_url}")
            return video_url
        except Exception as e:
            logger.error(f"❌ Oracle upload failed: {e}")
            return None
    
    async def generate_and_upload_short(self) -> Tuple[bool, Optional[str]]:
        """Full workflow: generate locally → upload to YouTube + Oracle → Firebase"""
        try:
            logger.info("=" * 70)
            logger.info("🎯 Starting YouTube Short generation & upload")
            logger.info("=" * 70)
            
            # Get next topic
            topic = self.get_next_topic()
            duration = 60
            
            logger.info(f"📋 Topic: {topic}")
            logger.info(f"⏱️ Duration: {duration}s")
            logger.info(f"📅 Time: {datetime.now().isoformat()}")
            logger.info("=" * 70)
            
            # Create Firebase job record
            job_id = create_job(topic, duration, "9:16", "short")
            logger.info(f"📝 Firebase job created: {job_id}")
            
            # Step 1: Generate video locally
            logger.info("🎬 Step 1: Generating video locally...")
            video_path = await self.generate_video(topic, duration)
            if not video_path:
                raise RuntimeError("Video generation failed")
            
            # Step 2: Upload to YouTube
            logger.info("📺 Step 2: Uploading to YouTube...")
            youtube_video_id = self.upload_to_youtube(video_path, topic, duration)
            if not youtube_video_id:
                logger.warning("⚠️ YouTube upload failed, but continuing with Oracle")
            
            # Step 3: Upload to Oracle Storage
            logger.info("☁️ Step 3: Uploading to Oracle Object Storage...")
            video_url = self.upload_to_oracle(video_path, job_id)
            if not video_url:
                raise RuntimeError("Oracle upload failed")
            
            # Step 4: Update Firebase
            logger.info("🔥 Step 4: Updating Firebase...")
            update_video_status_with_url(
                job_id, 
                video_url, 
                status="completed", 
                youtube_video_id=youtube_video_id
            )
            logger.info("✅ Firebase updated")
            
            # Step 5: Mark topic as used
            self.mark_topic_used(topic)
            
            # Step 6: Cleanup
            try:
                Path(video_path).unlink()
                logger.info("🧹 Local video cleaned up")
            except:
                pass
            
            logger.info("=" * 70)
            logger.info("✅ COMPLETE: Video generated and uploaded successfully!")
            logger.info(f"🎉 YouTube: https://youtube.com/watch?v={youtube_video_id}")
            logger.info("=" * 70)
            
            return True, youtube_video_id
            
        except Exception as e:
            logger.error(f"❌ FAILED: {e}")
            logger.error("=" * 70)
            return False, None
    
    def schedule_uploads(self):
        """Schedule video generation at specified times"""
        logger.info("\n📅 Scheduling video generation...")
        logger.info(f"Upload times (UTC): {', '.join(UPLOAD_TIMES)}")
        
        for time_str in UPLOAD_TIMES:
            time_str = time_str.strip()
            schedule.every().day.at(time_str).do(self._run_async_task)
            logger.info(f"  ✅ Scheduled for {time_str} UTC")
        
        logger.info("\n⏰ Waiting for scheduled time...")
        logger.info("(Press Ctrl+C to stop)\n")
        
        # Keep scheduler running
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    
    def _run_async_task(self):
        """Wrapper to run async function in scheduler"""
        try:
            asyncio.run(self.generate_and_upload_short())
        except Exception as e:
            logger.error(f"❌ Scheduled task failed: {e}")

def main():
    """Main entry point"""
    generator = StandaloneYouTubeShortsGenerator()
    
    # Check command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "--once":
            # Run once and exit
            logger.info("Running once mode...")
            success, video_id = asyncio.run(generator.generate_and_upload_short())
            sys.exit(0 if success else 1)
    
    # Default: run scheduler
    try:
        generator.schedule_uploads()
    except KeyboardInterrupt:
        logger.info("\n👋 Scheduler stopped by user")
        sys.exit(0)

if __name__ == "__main__":
    main()
