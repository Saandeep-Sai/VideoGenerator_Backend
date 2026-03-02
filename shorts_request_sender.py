#!/usr/bin/env python3
"""
Lightweight Shorts Request Sender for Oracle E2.1.Micro VM

This script runs on a tiny VM and sends requests to your main backend instance
to generate YouTube Shorts. It requires NO heavy dependencies (no Manim, no rendering).

Setup on E2.1.Micro:
1. Clone repo: git clone <repo> && cd backend
2. Create venv: python3 -m venv .venv && source .venv/bin/activate
3. Install deps: pip install requests python-dotenv schedule firebase-admin
4. Copy this file: cp shorts_request_sender.py /path/to/backend/
5. Create .env with: BACKEND_URL, FIREBASE_KEY (optional), SCHEDULE_TIMES
6. Run: python shorts_request_sender.py

For systemd (auto-start):
Create /etc/systemd/system/shorts-requester.service with content from SYSTEMD_UNIT.txt
"""

import os
import sys
import json
import logging
import random
import schedule
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv(override=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('shorts_requester.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class ShortsRequestSender:
    """Lightweight requester that sends generation requests to backend"""
    
    def __init__(self):
        # Config from environment
        self.backend_url = os.getenv('BACKEND_URL', 'http://localhost:8000')
        self.firebase_db_url = os.getenv('FIREBASE_DB_URL', None)
        self.upload_history_file = 'upload_history.json'
        
        # List of programming topics (avoid repetition)
        self.programming_topics = [
            "Python Variables and Data Types",
            "JavaScript Functions Explained",
            "Git Version Control Basics",
            "CSS Flexbox Layout",
            "Python List Comprehensions",
            "React Hooks Tutorial",
            "SQL JOIN Operations",
            "Docker Containers Explained",
            "REST vs GraphQL APIs",
            "Python Decorators",
            "JavaScript Async/Await",
            "Linux Command Line Basics",
            "Database Indexing Explained",
            "Web Security Best Practices",
            "Algorithm Time Complexity",
            "Python Exception Handling",
            "HTML Semantic Elements",
            "Node.js Event Loop",
            "CSS Grid Layout",
            "Object-Oriented Programming",
            "Design Patterns in Code",
            "Testing and Debugging",
            "Regular Expressions Mastery",
            "Memory Management Techniques",
            "Microservices Architecture",
            "CI/CD Pipeline Basics",
            "Cloud Computing Fundamentals",
            "Data Structures Explained",
            "Binary Search Algorithm",
            "JSON and XML Parsing"
        ]
        
        logger.info("🚀 Shorts Request Sender initialized")
        logger.info(f"   Backend URL: {self.backend_url}")
        if self.firebase_db_url:
            logger.info(f"   Firebase DB: {self.firebase_db_url}")
    
    def load_upload_history(self):
        """Load history of previously generated topics to avoid repeats"""
        if Path(self.upload_history_file).exists():
            try:
                with open(self.upload_history_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load history: {e}")
        return {"uploads": []}
    
    def save_upload_history(self, topic, job_id, status='requested'):
        """Save request to history"""
        try:
            history = self.load_upload_history()
            history["uploads"].append({
                "topic": topic,
                "job_id": job_id,
                "status": status,
                "timestamp": datetime.now().isoformat()
            })
            with open(self.upload_history_file, 'w') as f:
                json.dump(history, f, indent=2)
            logger.info(f"📝 History saved: {topic}")
        except Exception as e:
            logger.error(f"Failed to save history: {e}")
    
    def get_unused_topic(self):
        """Get a topic that hasn't been used in the last 30 days"""
        history = self.load_upload_history()
        recent_topics = set()
        
        # Look at last 30 days
        cutoff_date = datetime.now() - timedelta(days=30)
        
        for upload in history.get("uploads", []):
            try:
                upload_date = datetime.fromisoformat(upload["timestamp"])
                if upload_date > cutoff_date:
                    recent_topics.add(upload["topic"])
            except Exception as e:
                logger.warning(f"Could not parse date: {e}")
        
        # Get unused topic
        unused_topics = [t for t in self.programming_topics if t not in recent_topics]
        
        if not unused_topics:
            logger.warning("⚠️ All topics used recently, resetting")
            unused_topics = self.programming_topics
        
        selected_topic = random.choice(unused_topics)
        logger.info(f"📌 Selected topic (not used in 30 days): {selected_topic}")
        logger.info(f"   Recent topics: {len(recent_topics)}, Available: {len(unused_topics)}")
        
        return selected_topic
    
    def send_generation_request(self):
        """Send request to backend API to generate a short"""
        try:
            topic = self.get_unused_topic()
            duration = random.randint(45, 60)
            
            logger.info(f"\n🎬 Requesting Short generation:")
            logger.info(f"   Topic: {topic}")
            logger.info(f"   Duration: {duration}s")
            logger.info(f"   Aspect Ratio: 9:16 (vertical)")
            
            payload = {
                "topic": topic,
                "duration": duration,
                "aspect_ratio": "9:16",
                "video_type": "short",
                "quality": "qm"  # Medium quality (720p)
            }
            
            try:
                response = requests.post(
                    f"{self.backend_url}/api/generate/",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=10
                )
                
                if response.status_code in [200, 202]:
                    job_data = response.json()
                    job_id = job_data.get('job_id', 'unknown')
                    
                    logger.info(f"✅ Request successful!")
                    logger.info(f"   Job ID: {job_id}")
                    logger.info(f"   Status: {job_data.get('status', 'processing')}")
                    
                    # Save to history
                    self.save_upload_history(topic, job_id, 'requested')
                    
                    # Optional: update Firebase with job info
                    if self.firebase_db_url:
                        self.update_firebase(job_id, topic, 'pending')
                    
                    return job_id
                else:
                    logger.error(f"❌ API request failed: HTTP {response.status_code}")
                    logger.error(f"   Response: {response.text[:200]}")
                    return None
                    
            except requests.exceptions.Timeout:
                logger.error("❌ Request timeout (backend not responding)")
                return None
            except requests.exceptions.ConnectionError:
                logger.error(f"❌ Cannot connect to backend at {self.backend_url}")
                logger.error("   Make sure backend is running and URL is correct")
                return None
            
        except Exception as e:
            logger.error(f"❌ Failed to send request: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def update_firebase(self, job_id, topic, status):
        """Optional: Update Firebase with job status"""
        if not self.firebase_db_url:
            return
        
        try:
            payload = {
                "job_id": job_id,
                "topic": topic,
                "status": status,
                "timestamp": datetime.now().isoformat(),
                "requester": "shorts_requester_vm"
            }
            
            # Firebase Realtime Database REST API endpoint
            url = f"{self.firebase_db_url}/shorts_jobs/{job_id}.json"
            
            response = requests.put(url, json=payload, timeout=5)
            
            if response.status_code == 200:
                logger.info(f"📤 Firebase updated: {job_id}")
            else:
                logger.warning(f"⚠️ Firebase update failed: {response.status_code}")
                
        except Exception as e:
            logger.warning(f"⚠️ Firebase update error: {e}")
    
    def schedule_requests(self):
        """Schedule requests at specific times"""
        schedule_times = os.getenv('SCHEDULE_TIMES', '09:00,18:00').split(',')
        
        logger.info(f"\n📅 Scheduling requests at: {schedule_times}")
        
        for time_str in schedule_times:
            time_str = time_str.strip()
            schedule.every().day.at(time_str).do(self.send_generation_request)
            logger.info(f"   ⏰ {time_str} UTC")
        
        logger.info("\n🎯 Scheduler running. Requests will be sent at scheduled times.")
        logger.info("   Press Ctrl+C to stop.")
        
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    
    def run_once(self):
        """Run a single request (useful for testing)"""
        logger.info("\n🧪 Running single request...")
        return self.send_generation_request()
    
    def run_continuous(self, interval_minutes=60):
        """Run requests continuously at fixed intervals"""
        logger.info(f"\n🔄 Running continuous mode (every {interval_minutes} minutes)")
        
        while True:
            self.send_generation_request()
            logger.info(f"⏳ Waiting {interval_minutes} minutes until next request...\n")
            time.sleep(interval_minutes * 60)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Lightweight YouTube Shorts Request Sender')
    parser.add_argument('--once', action='store_true', help='Send one request and exit')
    parser.add_argument('--schedule', action='store_true', help='Use scheduled times (default)')
    parser.add_argument('--continuous', type=int, metavar='MINUTES', 
                       help='Send requests every N minutes')
    parser.add_argument('--test', action='store_true', help='Test backend connection')
    
    args = parser.parse_args()
    
    sender = ShortsRequestSender()
    
    # Test mode
    if args.test:
        logger.info("🧪 Testing backend connection...")
        try:
            response = requests.get(f"{sender.backend_url}/api/health/", timeout=5)
            if response.status_code == 200:
                logger.info(f"✅ Backend is online: {sender.backend_url}")
            else:
                logger.error(f"⚠️ Backend returned: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Cannot reach backend: {e}")
        return
    
    # Run once
    if args.once:
        logger.info("📌 Running single request mode")
        sender.run_once()
        return
    
    # Continuous
    if args.continuous:
        logger.info(f"🔄 Running continuous mode ({args.continuous} min intervals)")
        sender.run_continuous(args.continuous)
        return
    
    # Default: scheduled (09:00, 18:00)
    logger.info("📅 Running scheduled mode (default)")
    sender.schedule_requests()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n⏹️ Stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n💥 Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)
