import os
import time
import traceback
import base64
import asyncio
import logging
import sys

from generator.firebase_utils import (
    get_pending_jobs,
    update_job_status,
    update_video_status_with_url
)
from generator.video_generator.optimized_video_generator import OptimizedVideoGenerationPipeline, VideoGenerationConfig
from generator.oracle_storage import OracleStorageClient
from youtube_shorts_uploader import upload_video_to_youtube

# ✅ Setup logger with better formatting
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ✅ Load from environment
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GEMINI_API_KEY or not GROQ_API_KEY:
    logger.error("❌ Missing API keys! Check environment variables.")
    sys.exit(1)

# ✅ Configure pipeline
config = VideoGenerationConfig(
    gemini_api_key=GEMINI_API_KEY,
    groq_api_key=GROQ_API_KEY
)
pipeline = OptimizedVideoGenerationPipeline(config)

# ✅ Initialize Oracle Storage Client
oracle_storage = OracleStorageClient()

logger.info("=" * 60)
logger.info("🎬 VIDEO GENERATION WORKER INITIALIZED")
logger.info("=" * 60)

async def run():
    logger.info("🟢 Video worker started - polling for jobs...")
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while True:
        try:
            logger.info("⏳ Polling Firebase for pending jobs...")
            job = get_pending_jobs()
            logger.info(f"📊 Query result: {job if job else 'No pending jobs found'}")
            if job:
                consecutive_errors = 0  # Reset error counter on successful job fetch
                
                job_id = job['id']
                topic = job.get("topic", "")
                duration = int(job.get("duration", 60))
                aspect_ratio = job.get("aspect_ratio", "16:9")
                video_type = job.get("video_type", "regular")

                logger.info("=" * 60)
                logger.info(f"⚙️  NEW JOB RECEIVED")
                logger.info(f"📋 Job ID: {job_id}")
                logger.info(f"📚 Topic: {topic}")
                logger.info(f"⏱️  Duration: {duration} seconds")
                logger.info(f"📐 Aspect Ratio: {aspect_ratio}")
                logger.info(f"🎬 Video Type: {video_type}")
                logger.info("=" * 60)

                update_job_status(job_id, "processing")

                try:
                    # Update config with aspect ratio from job
                    config.aspect_ratio = aspect_ratio
                    
                    logger.info("🚀 Starting video generation pipeline...")
                    final_video_path = await pipeline.generate_video_full_parallel(
                        topic,
                        duration
                    )
                    logger.info(f"✅ Video generated successfully: {final_video_path}")

                    # Upload video to Oracle Object Storage
                    logger.info("📤 Uploading video to Oracle Object Storage...")
                    video_url = oracle_storage.upload_video(final_video_path, job_id)
                    logger.info(f"✅ Video uploaded: {video_url}")

                    # Check if this is a YouTube Short and upload
                    youtube_video_id = None
                    if video_type == "short":
                        logger.info("🎬 Detected YouTube Short - uploading to YouTube...")
                        youtube_video_id = upload_video_to_youtube(final_video_path, topic, duration)
                        if youtube_video_id:
                            logger.info(f"✅ YouTube Short uploaded: {youtube_video_id}")
                        else:
                            logger.error("❌ YouTube Short upload failed")

                    # Update Firestore with video URL and YouTube ID
                    update_data = {"video_url": video_url}
                    if youtube_video_id:
                        update_data["youtube_video_id"] = youtube_video_id
                    
                    update_video_status_with_url(job_id, video_url, status="completed", youtube_video_id=youtube_video_id)
                    logger.info(f"✅ Job {job_id} completed successfully!")
                    logger.info("=" * 60)

                except Exception as e:
                    logger.error(f"❌ Error during video generation for job {job_id}: {e}")
                    logger.error(traceback.format_exc())
                    update_video_status_with_url(job_id, video_url="", status="failed", error=str(e))
                    logger.info("=" * 60)

            else:
                # No jobs - sleep and continue
                logger.info("😴 No jobs available, sleeping for 10 seconds...")
                await asyncio.sleep(10)

        except Exception as e:
            consecutive_errors += 1
            logger.error(f"❌ Worker loop error ({consecutive_errors}/{max_consecutive_errors}): {e}")
            logger.error(traceback.format_exc())
            
            if consecutive_errors >= max_consecutive_errors:
                logger.error(f"❌ Too many consecutive errors ({consecutive_errors}). Exiting worker.")
                sys.exit(1)
            
            await asyncio.sleep(10)

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("👋 Worker stopped by user")
    except Exception as e:
        logger.error(f"❌ Worker crashed: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)
