# run_combined.py
import multiprocessing
import subprocess
import os

def start_web():
    port = os.environ.get("PORT", "8000")
    print(f"🌐 Starting Django web server on port {port}")
    subprocess.run([
        "gunicorn",
        "video_gen.wsgi:application",
        "--bind",
        f"0.0.0.0:{port}",
        "--workers",
        "3"
    ])

def start_worker():
    print("🛠️ Starting background video worker...")
    subprocess.run(["python", "run_generate_worker.py"])

if __name__ == "__main__":
    web_process = multiprocessing.Process(target=start_web)
    worker_process = multiprocessing.Process(target=start_worker)

    web_process.start()
    worker_process.start()

    web_process.join()
    worker_process.join()
