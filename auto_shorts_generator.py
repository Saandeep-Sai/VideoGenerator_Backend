import json
import logging
import random
import schedule
import time
import os
import requests
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from generator.dynamic_content_generator import DynamicContentGenerator

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AutoShortsGenerator:
    def __init__(self):
        self.upload_history_file = "upload_history.json"
        self.api_base_url = "http://localhost:8000"  # Django API URL
        
        # Initialize dynamic content generator
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        if gemini_api_key:
            self.dynamic_content = DynamicContentGenerator(gemini_api_key)
            self.use_dynamic_topics = True
            logger.info("✅ Dynamic content generator initialized")
        else:
            self.use_dynamic_topics = False
            logger.warning("⚠️ No Gemini API key found, using static topics")
        
    def get_programming_topics(self):
        return [
            "Python Variables and Data Types",
            "JavaScript Functions Explained", 
            "Git Version Control Basics",
            "CSS Flexbox Layout",
            "Python List Comprehensions",
            "React Hooks Tutorial",
            "SQL JOIN Operations",
            "Docker Containers Explained",
            "API REST vs GraphQL",
            "Python Decorators",
            "JavaScript Async/Await",
            "Linux Command Line Basics",
            "Database Indexing",
            "Web Security Best Practices",
            "Algorithm Time Complexity",
            "Python Exception Handling",
            "HTML Semantic Elements",
            "Node.js Event Loop",
            "CSS Grid Layout",
            "Python Classes and Objects"
        ]
    
    def load_upload_history(self):
        if Path(self.upload_history_file).exists():
            with open(self.upload_history_file, 'r') as f:
                return json.load(f)
        return {"uploads": []}
    
    def save_upload_history(self, topic, video_id):
        history = self.load_upload_history()
        history["uploads"].append({
            "topic": topic,
            "video_id": video_id,
            "timestamp": datetime.now().isoformat()
        })
        with open(self.upload_history_file, 'w') as f:
            json.dump(history, f, indent=2)
    
    def get_unused_topic(self):
        # Use dynamic topic generation if available
        if self.use_dynamic_topics:
            try:
                # Generate a fresh trending topic
                topic = self.dynamic_content.generate_trending_topic()
                logger.info(f"🎯 Generated dynamic topic: {topic}")
                return topic
            except Exception as e:
                logger.warning(f"⚠️ Dynamic topic generation failed: {e}")
                # Fall back to static topics
        
        # Fallback to static topic selection
        topics = self.get_programming_topics()
        history = self.load_upload_history()
        
        recent_topics = set()
        cutoff_date = datetime.now() - timedelta(days=30)
        
        for upload in history.get("uploads", []):
            upload_date = datetime.fromisoformat(upload["timestamp"])
            if upload_date > cutoff_date:
                recent_topics.add(upload["topic"])
        
        unused_topics = [t for t in topics if t not in recent_topics]
        selected_topic = random.choice(unused_topics if unused_topics else topics)
        logger.info(f"📚 Selected static topic: {selected_topic}")
        return selected_topic
    
    def create_short_job(self):
        """Send API request to Django to create a Short video job"""
        try:
            topic = self.get_unused_topic()
            duration = random.randint(45, 60)
            
            logger.info(f"🎬 Creating Short job: '{topic}' ({duration}s)")
            
            payload = {
                "topic": topic,
                "duration": duration,
                "aspect_ratio": "9:16",
                "video_type": "short"  # Mark as YouTube Short
            }
            
            response = requests.post(
                f"{self.api_base_url}/api/generate/",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 202:
                job_data = response.json()
                job_id = job_data.get('job_id')
                logger.info(f"✅ Short job created: {job_id}")
                return job_id
            else:
                logger.error(f"❌ API request failed: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Failed to create short job: {e}")
            return None
    
    def run_upload_job(self):
        try:
            logger.info("🚀 Starting scheduled Short job...")
            job_id = self.create_short_job()
            if job_id:
                logger.info(f"📋 Short job queued: {job_id}")
            else:
                logger.error("❌ Failed to queue Short job")
        except Exception as e:
            logger.error(f"❌ Scheduled job failed: {e}")
    
    def schedule_daily_uploads(self):
        schedule.every().day.at("09:00").do(self.run_upload_job)
        schedule.every().day.at("18:00").do(self.run_upload_job)
        
        logger.info("📅 Scheduled daily uploads at 9:00 AM and 6:00 PM")
        
        while True:
            schedule.run_pending()
            time.sleep(60)

if __name__ == "__main__":
    generator = AutoShortsGenerator()
    
    # Test mode
    if len(os.sys.argv) > 1 and os.sys.argv[1] == "--test":
        generator.create_short_job()
    else:
        generator.schedule_daily_uploads()