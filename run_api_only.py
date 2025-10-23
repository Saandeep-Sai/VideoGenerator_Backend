import subprocess
import os
import sys

if __name__ == "__main__":
    port = os.environ.get("PORT", "8000")
    
    print("=" * 60)
    print(f"🚀 VIDEO GENERATOR API SERVER (API ONLY)")
    print(f"📍 Port: {port}")
    print(f"🌍 Environment: Render (No Worker)")
    print(f"📊 Health check: http://0.0.0.0:{port}/api/health/")
    print(f"🎬 Generate: http://0.0.0.0:{port}/api/generate/")
    print(f"📋 Worker: Running on GCP VM (separate)")
    print("=" * 60)
    
    try:
        subprocess.run([
            "gunicorn",
            "video_gen.wsgi:application",
            "--bind", f"0.0.0.0:{port}",
            "--workers", "1",
            "--timeout", "300",
            "--log-level", "info",
            "--access-logfile", "-",
            "--error-logfile", "-"
        ])
    except Exception as e:
        print(f"❌ Gunicorn failed: {e}")
        sys.exit(1)
