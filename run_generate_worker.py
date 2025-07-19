import os
import time
import traceback
import base64
import asyncio
import logging
from generator.firebase_utils import (
    get_pending_jobs,
    update_job_status,
    update_video_status
)
from generator.video_generator.optimized_video_generator import OptimizedVideoGenerationPipeline, VideoGenerationConfig

# ✅ Setup logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ Load from environment
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ✅ Configure pipeline
config = VideoGenerationConfig(
    gemini_api_key=GEMINI_API_KEY,
    groq_api_key=GROQ_API_KEY
)
pipeline = OptimizedVideoGenerationPipeline(config)

async def run():
    logger.info("🟢 Video worker started")
    while True:
        try:
            job = get_pending_jobs()
            if job:
                job_id = job['id']
                topic = job.get("topic", "")
                duration = int(job.get("duration", 60))

                logger.info(f"\n⚙️  Processing job: {job_id}")
                logger.info(f"📚 Topic: {topic}, ⏱️ Duration: {duration} seconds")

                update_job_status(job_id, "processing")

                try:
                    logger.info("🚀 Starting video generation...")
                    final_video_path = await pipeline.generate_video_full_parallel(
                        topic,
                        duration
                    )
                    logger.info(f"✅ Video generated: {final_video_path}")

                    # Convert video to base64 and upload to Firestore
                    with open(final_video_path, "rb") as video_file:
                        video_data = video_file.read()
                        encoded_video = base64.b64encode(video_data).decode("utf-8")

                    update_video_status(job_id, base64_data=encoded_video, status="completed")
                    logger.info(f"📤 Uploaded video segments and marked job {job_id} as completed")

                except Exception as e:
                    logger.info(f"❌ Error during video generation for job {job_id}: {e}")
                    traceback.print_exc()
                    update_video_status(job_id, base64_data=None, status="failed", error=str(e))

            else:
                logger.info("⏳ No pending jobs. Sleeping 5s...")
                await asyncio.sleep(5)

        except Exception as e:
            logger.info(f"❌ Worker loop crashed: {e}")
            traceback.print_exc()
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(run())
