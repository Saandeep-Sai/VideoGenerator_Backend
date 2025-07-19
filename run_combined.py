import subprocess
import threading
import os
import time

def start_worker():
    time.sleep(10)  # Allow web server to bind before launching worker
    print("🛠️ Starting background video worker...")
    subprocess.run(["python", "run_generate_worker.py"])

if __name__ == "__main__":
    # 🧵 Start background worker in daemon thread
    threading.Thread(target=start_worker, daemon=True).start()

    # 🌐 Start Django web server (must be in main thread)
    port = os.environ.get("PORT", "8000")
    print(f"🌐 Starting Django web server on port {port}")
    subprocess.run([
        "gunicorn",
        "video_gen.wsgi:application",
        "--bind", f"0.0.0.0:{port}",
        "--workers", "1",
        "--timeout", "3600"
    ])
