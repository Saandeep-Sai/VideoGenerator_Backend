import subprocess
import threading
import os
import time
import sys
import requests

def wait_for_health_check(port, max_retries=30):
    """Wait for Django server to be healthy before starting worker"""
    health_url = f"http://localhost:{port}/api/health/"
    
    for i in range(max_retries):
        try:
            response = requests.get(health_url, timeout=2)
            if response.status_code == 200:
                print(f"✅ Health check passed! Server is ready on port {port}")
                return True
        except Exception as e:
            pass
        
        print(f"⏳ Waiting for server to be ready... ({i+1}/{max_retries})")
        time.sleep(2)
    
    print("⚠️ Server health check timeout - starting worker anyway")
    return False

def start_worker():
    port = os.environ.get("PORT", "8000")
    
    # Wait for Django to be fully ready
    print("🔍 Checking if Django server is healthy...")
    wait_for_health_check(port)
    
    print("🛠️ Starting background video worker...")
    try:
        subprocess.run(["python", "run_generate_worker.py"])
    except Exception as e:
        print(f"❌ Worker failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    port = os.environ.get("PORT", "8000")
    
    print("=" * 60)
    print(f"🚀 VIDEO GENERATOR SERVICE STARTING")
    print(f"📍 Port: {port}")
    print(f"🌍 Environment: {'PRODUCTION (Render)' if port == '10000' else 'DEVELOPMENT'}")
    print("=" * 60)
    
    # 🧵 Start background worker in daemon thread (will wait for health check)
    worker_thread = threading.Thread(target=start_worker, daemon=True)
    worker_thread.start()
    print("✅ Background worker thread initiated")

    # 🌐 Start Django web server (MUST be in main thread for Render)
    print(f"🌐 Starting Gunicorn on 0.0.0.0:{port}...")
    print(f"📊 Health check endpoint: http://0.0.0.0:{port}/api/health/")
    print(f"🎬 Generate endpoint: http://0.0.0.0:{port}/api/generate/")
    print("=" * 60)
    
    try:
        subprocess.run([
            "gunicorn",
            "video_gen.wsgi:application",
            "--bind", f"0.0.0.0:{port}",
            "--workers", "1",
            "--timeout", "3600",
            "--log-level", "info",
            "--access-logfile", "-",
            "--error-logfile", "-"
        ])
    except Exception as e:
        print(f"❌ Gunicorn failed: {e}")
        sys.exit(1)
