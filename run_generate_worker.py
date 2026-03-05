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
from generator.dynamic_content_generator import DynamicContentGenerator
from youtube_shorts_uploader import upload_video_to_youtube
from instagram_upload import upload_reel_to_instagram

# Analytics tracking - tracks uploaded videos for performance monitoring
try:
    from analytics.integrated_analytics import track_uploaded_video, get_analytics_service
    ANALYTICS_ENABLED = True
except ImportError:
    ANALYTICS_ENABLED = False
    track_uploaded_video = lambda *args, **kwargs: None  # No-op fallback

# ✅ Setup logger with better formatting
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ✅ Load from environment - Load OpenRouter API key (primary) and Gemini keys for content generation
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Load Gemini keys for dynamic content generation
GEMINI_API_KEYS = []
for key_name in ["GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"]:
    key_value = os.getenv(key_name)
    if key_value:
        GEMINI_API_KEYS.append(key_value)
        logger.info(f"✓ Loaded {key_name}")

if not OPENROUTER_API_KEY or not GROQ_API_KEY:
    logger.error("❌ Missing API keys! Set OPENROUTER_API_KEY and GROQ_API_KEY")
    sys.exit(1)

logger.info(f"✓ Loaded OPENROUTER_API_KEY")
logger.info(f"📊 Loaded {len(GEMINI_API_KEYS)} Gemini API key(s) for content generation")

# ✅ Configure pipeline
config = VideoGenerationConfig(
    openrouter_api_key=OPENROUTER_API_KEY,
    groq_api_key=GROQ_API_KEY
)
pipeline = OptimizedVideoGenerationPipeline(config)

# ✅ Initialize Oracle Storage Client
oracle_storage = OracleStorageClient()

# ✅ Initialize Dynamic Content Generator (uses first Gemini key, or loads from env)
dynamic_content = DynamicContentGenerator(gemini_api_key=GEMINI_API_KEYS[0] if GEMINI_API_KEYS else None)

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
                use_quality_pipeline = job.get("use_quality_pipeline", True)

                logger.info("=" * 60)
                logger.info(f"⚙️  NEW JOB RECEIVED")
                logger.info(f"📋 Job ID: {job_id}")
                logger.info(f"📚 Topic: {topic}")
                logger.info(f"⏱️  Duration: {duration} seconds")
                logger.info(f"📐 Aspect Ratio: {aspect_ratio}")
                logger.info(f"🎬 Video Type: {video_type}")
                logger.info(f"🔧 Quality Pipeline: {use_quality_pipeline}")
                logger.info("=" * 60)

                update_job_status(job_id, "processing")

                try:
                    # Update config with aspect ratio and video type from job
                    config.aspect_ratio = aspect_ratio
                    config.video_type = video_type
                    config.use_quality_pipeline = use_quality_pipeline
                    
                    # Reinitialize pipeline with updated config
                    pipeline_instance = OptimizedVideoGenerationPipeline(config)
                    
                    logger.info("🚀 Starting video generation pipeline...")
                    final_video_path = await pipeline_instance.generate_video_full_parallel(
                        topic,
                        duration
                    )
                    logger.info(f"✅ Video generated successfully: {final_video_path}")

                    # Upload video to Oracle Object Storage
                    logger.info("📤 Uploading video to Oracle Object Storage...")
                    video_url = oracle_storage.upload_video(final_video_path, job_id)
                    logger.info(f"✅ Video uploaded: {video_url}")

                    # Check if this is a YouTube Short and upload with dynamic metadata
                    youtube_video_id = None
                    instagram_media_id = None
                    if video_type == "short":
                        logger.info("🎬 Detected YouTube Short - generating dynamic metadata...")
                        
                        # Generate dynamic metadata for better YouTube performance
                        try:
                            metadata = dynamic_content.generate_youtube_metadata(topic, duration)
                            logger.info(f"📈 Generated metadata - Title: {metadata['title'][:50]}...")
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to generate metadata, using fallback: {e}")
                            metadata = None
                        
                        # Upload to YouTube with dynamic metadata
                        youtube_video_id = upload_video_to_youtube(final_video_path, topic, duration, metadata)
                        if youtube_video_id:
                            logger.info(f"✅ YouTube Short uploaded: {youtube_video_id}")
                            
                            # Track video for analytics (retention, views, decision engine)
                            if ANALYTICS_ENABLED:
                                try:
                                    track_uploaded_video(
                                        youtube_video_id=youtube_video_id,
                                        topic=topic,
                                        metadata=metadata
                                    )
                                    logger.info(f"📊 Video tracked for analytics: {youtube_video_id}")
                                except Exception as e:
                                    logger.warning(f"⚠️ Analytics tracking failed (non-critical): {e}")
                        else:
                            logger.error("❌ YouTube Short upload failed")
                        
                        # Upload to Instagram Reels
                        logger.info("📱 Uploading to Instagram Reels...")
                        try:
                            instagram_media_id = upload_reel_to_instagram(final_video_path, topic, metadata)
                            if instagram_media_id:
                                logger.info(f"✅ Instagram Reel uploaded: {instagram_media_id}")
                            else:
                                logger.info("ℹ️ Instagram upload skipped or disabled")
                        except Exception as e:
                            logger.warning(f"⚠️ Instagram upload failed: {e}")
                        
                        # Delete from Oracle bucket if uploaded to YouTube or Instagram
                        if youtube_video_id or instagram_media_id:
                            logger.info("🗑️ Deleting video from Oracle bucket...")
                            try:
                                deleted = oracle_storage.delete_video(job_id)
                                if deleted:
                                    logger.info("✅ Video deleted from Oracle bucket (already on YouTube/Instagram)")
                                else:
                                    logger.warning("⚠️ Failed to delete video from Oracle bucket")
                            except Exception as e:
                                logger.warning(f"⚠️ Error deleting from Oracle: {e}")
                        else:
                            logger.info("ℹ️ Keeping video in Oracle bucket as backup")

                    # Update Firestore with video URL and YouTube ID (single update, no duplicates)
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
