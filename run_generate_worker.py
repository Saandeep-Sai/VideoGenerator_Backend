import os
import time
import traceback
import time
import traceback
import base64
from generator.firebase_utils import (
    get_pending_jobs,
    update_job_status,
    update_video_status
)
from generator.video_generator.optimized_video_generator import OptimizedVideoGenerationPipeline,VideoGenerationConfig

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
                job_id = job['id']
                topic = job.get("topic", "")
                duration = int(job.get("duration", 60))

                print(f"\n⚙️  Processing job: {job_id}")
                print(f"📚 Topic: {topic}, ⏱️ Duration: {duration} seconds")

                update_job_status(job_id, "processing")

                try:
                    print("🚀 Starting video generation...")
                    final_video_path = pipeline.generate_video_full_parallel(
                        topic,
                        duration
                    )
                    print(f"✅ Video generated: {final_video_path}")

                    # Convert video to base64 and update Firestore using existing utility
                    with open(final_video_path, "rb") as video_file:
                        video_data = video_file.read()
                        encoded_video = base64.b64encode(video_data).decode("utf-8")

                    update_video_status(job_id, base64_data=encoded_video, status="completed")
                    print(f"📤 Uploaded video segments and marked job {job_id} as completed")

                except Exception as e:
                    print(f"❌ Error during video generation for job {job_id}: {e}")
                    traceback.print_exc()
                    update_video_status(job_id, base64_data=None, status="failed", error=str(e))

            else:
                print("⏳ No pending jobs. Sleeping 5s...")
                time.sleep(5)

        except Exception as e:
            print("❌ Worker loop crashed:", e)
            traceback.print_exc()
            time.sleep(5)
if __name__ == "__main__":
    run()
