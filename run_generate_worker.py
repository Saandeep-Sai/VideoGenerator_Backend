import os
import time
import traceback
from generator.firebase_utils import get_pending_jobs, update_job_status
from generator.video_generator.optimized_video_generator import VideoGenerationConfig, OptimizedVideoGenerationPipeline

# ✅ Load from environment
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ✅ Provide required arguments
config = VideoGenerationConfig(
    gemini_api_key=GEMINI_API_KEY,
    groq_api_key=GROQ_API_KEY
)
pipeline = OptimizedVideoGenerationPipeline(config)

def run():
    print("🟢 Video worker started")
    while True:
        try:
            job = get_pending_jobs()
            if job:
                print(f"⚙️  Processing job: {job['id']}")
                update_job_status(job['id'], "processing")

                topic = job['topic']
                duration = int(job['duration'])

                print(f"🎬 Starting generation for topic: {topic} ({duration}s)")
                pipeline.generate_video_full_parallel(topic, duration)

                update_job_status(job['id'], "completed")
                print(f"✅ Job {job['id']} completed")

            else:
                print("⏳ No pending jobs. Sleeping...")
                time.sleep(5)
        except Exception as e:
            print("❌ Worker error:", e)
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    run()
