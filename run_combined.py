import multiprocessing
import subprocess
import os
import threading
import time

def start_web():
    port = os.environ.get("PORT", "8000")
    print(f"🌐 Starting Django web server on port {port}")
    subprocess.run([
        "gunicorn",
        "video_gen.wsgi:application",
        "--bind", f"0.0.0.0:{port}",
        "--workers", "1",
        "--timeout", "3600"
    ])

def start_worker():
    time.sleep(15)  # Give web server time to start up before running worker
    print("🛠️ Starting background video worker...")
    subprocess.run(["python", "run_generate_worker.py"])

if __name__ == "__main__":
    # Start web server in main thread (Render expects this)
    threading.Thread(target=start_worker, daemon=True).start()
    start_web()
