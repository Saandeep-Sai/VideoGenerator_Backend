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
    update_video_status
)
from generator.video_generator.optimized_video_generator import OptimizedVideoGenerationPipeline, VideoGenerationConfig

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

logger.info("=" * 60)
logger.info("🎬 VIDEO GENERATION WORKER INITIALIZED")
logger.info("=" * 60)

async def run():
    logger.info("🟢 Video worker started - polling for jobs...")
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while True:
        try:
            job = get_pending_jobs()
            if job:
                consecutive_errors = 0  # Reset error counter on successful job fetch
                
                job_id = job['id']
                topic = job.get("topic", "")
                duration = int(job.get("duration", 60))

                logger.info("=" * 60)
                logger.info(f"⚙️  NEW JOB RECEIVED")
                logger.info(f"📋 Job ID: {job_id}")
                logger.info(f"📚 Topic: {topic}")
                logger.info(f"⏱️  Duration: {duration} seconds")
                logger.info("=" * 60)

                update_job_status(job_id, "processing")

                try:
                    logger.info("🚀 Starting video generation pipeline...")
                    final_video_path = await pipeline.generate_video_full_parallel(
                        topic,
                        duration
                    )
                    logger.info(f"✅ Video generated successfully: {final_video_path}")

                    # Convert video to base64 and upload to Firestore
                    logger.info("📤 Uploading video to Firebase...")
                    with open(final_video_path, "rb") as video_file:
                        video_data = video_file.read()
                        encoded_video = base64.b64encode(video_data).decode("utf-8")

                    update_video_status(job_id, base64_data=encoded_video, status="completed")
                    logger.info(f"✅ Job {job_id} completed successfully!")
                    logger.info("=" * 60)

                except Exception as e:
                    logger.error(f"❌ Error during video generation for job {job_id}: {e}")
                    logger.error(traceback.format_exc())
                    update_video_status(job_id, base64_data=None, status="failed", error=str(e))
                    logger.info("=" * 60)

            else:
                # No jobs - sleep and continue
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
