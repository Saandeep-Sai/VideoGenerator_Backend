#!/usr/bin/env python3
"""
⚠️ ⚠️ ⚠️  DEPRECATED - DO NOT USE  ⚠️ ⚠️ ⚠️

THIS FILE IS DEPRECATED AND CAUSES DUPLICATE VIDEO GENERATION!

Use youtube_shorts_scheduler_standalone.py instead.

See DUPLICATE_GENERATION_FIX.md for details.

REASON FOR DEPRECATION:
- This scheduler calls the API endpoint /api/generate/
- The API creates jobs in the "videos" collection
- The worker picks up these jobs and generates videos
- This creates DUPLICATE generations (scheduler + worker both generate the same video)

REPLACEMENT:
- Use: youtube_shorts_scheduler_standalone.py
- Service: youtube-shorts-scheduler.service (Type=oneshot)
- Timer: youtube-shorts-scheduler.timer
- Collection: "scheduled-videos" (separate from worker queue)

⚠️ ⚠️ ⚠️  DEPRECATED - DO NOT USE  ⚠️ ⚠️ ⚠️
"""

import os
import sys

# SAFETY CHECK: Prevent accidental execution
FORCE_ENABLE = os.getenv("ENABLE_OLD_SCHEDULER", "false").lower() == "true"

if not FORCE_ENABLE:
    print("=" * 80)
    print("❌ ERROR: This scheduler is DEPRECATED and causes duplicate generations!")
    print("=" * 80)
    print()
    print("🚫 This file should NOT be used anymore.")
    print()
    print("✅ Instead, use: youtube_shorts_scheduler_standalone.py")
    print()
    print("📋 Reason:")
    print("   - This script calls the API which creates jobs in 'videos' collection")
    print("   - The worker then picks up the same job and generates the video")
    print("   - Result: DUPLICATE video generation and upload")
    print()
    print("📋 Solution:")
    print("   - Use youtube_shorts_scheduler_standalone.py (generates locally)")
    print("   - Uses 'scheduled-videos' collection (worker ignores it)")
    print("   - No API calls, no worker involvement, no duplicates")
    print()
    print("📖 See DUPLICATE_GENERATION_FIX.md for full details")
    print()
    print("=" * 80)
    print()
    print("To force enable (NOT RECOMMENDED):")
    print("  export ENABLE_OLD_SCHEDULER=true")
    print("  python youtube_shorts_scheduler.py")
    print()
    sys.exit(1)

# Original imports (only reached if FORCE_ENABLE=true)
import json
import logging
import random
import schedule
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional, Dict, Tuple

# YouTube API
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore

# Load env
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('youtube_shorts_scheduler.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Import dynamic content generator
try:
    from generator.dynamic_content_generator import DynamicContentGenerator
except ImportError:
    logger.warning("⚠️ Could not import DynamicContentGenerator, using static topics")
    DynamicContentGenerator = None

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

class YouTubeShortsScheduler:
    """Integrated scheduler: generate → upload → track in Firebase"""
    
    def __init__(self):
        self.upload_history_file = "youtube_shorts_history.json"
        self.max_retries = 3
        self.retry_delay_base = 5  # seconds
        
        # Topics list (programming, no repeats)
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
        
        # Initialize Firebase
        self._initialize_firebase()
        
        # Initialize dynamic content generator
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        if gemini_api_key and DynamicContentGenerator:
            try:
                self.dynamic_content = DynamicContentGenerator(gemini_api_key)
                self.use_dynamic_topics = True
                logger.info("✅ Dynamic content generator initialized")
            except Exception as e:
                logger.warning(f"⚠️ Dynamic content init failed: {e}")
                self.use_dynamic_topics = False
        else:
            self.use_dynamic_topics = False
            logger.warning("⚠️ Using static topics (no Gemini API key or import failed)")
        
        logger.info("✅ YouTube Shorts Scheduler initialized")
        logger.info(f"   Topics available: {len(self.programming_topics)}")
        logger.info(f"   Dynamic topics: {self.use_dynamic_topics}")
        logger.info(f"   Max retries: {self.max_retries}")
    
    def _initialize_firebase(self):
        """Initialize Firebase Firestore"""
        try:
            if firebase_admin._apps:
                return
            
            b64 = os.getenv("FIREBASE_CREDENTIALS_BASE64")
            project_id = os.getenv("FIREBASE_PROJECT_ID")
            
            if not b64 or not project_id:
                logger.warning("⚠️ Firebase not configured (missing env vars)")
                self.firebase_enabled = False
                return
            
            import base64
            decoded = base64.b64decode(b64)
            cred_dict = json.loads(decoded.decode())
            cred = credentials.Certificate(cred_dict)
            
            firebase_admin.initialize_app(cred, {
                "projectId": project_id,
                "storageBucket": f"{project_id}.appspot.com"
            })
            
            self.firebase_enabled = True
            logger.info("✅ Firebase Firestore initialized")
            
        except Exception as e:
            logger.warning(f"⚠️ Firebase initialization failed: {e}")
            self.firebase_enabled = False
    
    def load_upload_history(self) -> Dict:
        """Load history of uploaded shorts"""
        if Path(self.upload_history_file).exists():
            try:
                with open(self.upload_history_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load history: {e}")
        return {"uploads": []}
    
    def save_upload_history(self, topic: str, video_id: str, status: str = "uploaded"):
        """Save successful upload to history"""
        try:
            history = self.load_upload_history()
            history["uploads"].append({
                "topic": topic,
                "video_id": video_id,
                "status": status,
                "timestamp": datetime.now().isoformat(),
                "url": f"https://youtube.com/watch?v={video_id}"
            })
            with open(self.upload_history_file, 'w') as f:
                json.dump(history, f, indent=2)
            logger.info(f"📝 History saved: {topic}")
        except Exception as e:
            logger.error(f"Failed to save history: {e}")
    
    def get_unused_topic(self) -> str:
        """Get a topic not used in last 30 days (dynamic or static)"""
        # Use dynamic topic generation if available
        if self.use_dynamic_topics:
            try:
                topic = self.dynamic_content.generate_trending_topic()
                logger.info(f"🎯 Generated dynamic topic: {topic}")
                return topic
            except Exception as e:
                logger.warning(f"⚠️ Dynamic topic generation failed: {e}, falling back to static")
        
        # Fallback to static topic selection
        history = self.load_upload_history()
        recent_topics = set()
        
        cutoff_date = datetime.now() - timedelta(days=30)
        for upload in history.get("uploads", []):
            try:
                upload_date = datetime.fromisoformat(upload["timestamp"])
                if upload_date > cutoff_date:
                    recent_topics.add(upload["topic"])
            except:
                pass
        
        unused_topics = [t for t in self.programming_topics if t not in recent_topics]
        
        if not unused_topics:
            logger.warning("⚠️ All topics used in last 30 days, resetting")
            unused_topics = self.programming_topics
        
        topic = random.choice(unused_topics)
        logger.info(f"📌 Selected static topic: {topic}")
        return topic
    
    def authenticate_youtube(self) -> build:
        """Authenticate with YouTube API"""
        try:
            creds = None
            
            if os.path.exists("token.json"):
                creds = Credentials.from_authorized_user_file("token.json", SCOPES)
            
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    if not os.path.exists("client_secret.json"):
                        raise FileNotFoundError("❌ client_secret.json not found. Run setup_youtube_automation.py")
                    
                    flow = InstalledAppFlow.from_client_secrets_file(
                        "client_secret.json", SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                
                with open("token.json", "w") as token:
                    token.write(creds.to_json())
            
            return build("youtube", "v3", credentials=creds)
        
        except Exception as e:
            logger.error(f"❌ YouTube authentication failed: {e}")
            raise
    
    def upload_short_to_youtube(self, video_path: str, topic: str, duration: int) -> Optional[str]:
        """Upload video to YouTube as PUBLIC Short with dynamic metadata"""
        try:
            if not Path(video_path).exists():
                logger.error(f"❌ Video file not found: {video_path}")
                return None
            
            logger.info(f"📤 Uploading to YouTube...")
            logger.info(f"   Video: {video_path}")
            logger.info(f"   Size: {Path(video_path).stat().st_size / 1024 / 1024:.1f} MB")
            
            youtube = self.authenticate_youtube()
            
            # Generate dynamic metadata if available
            if self.use_dynamic_topics:
                try:
                    metadata = self.dynamic_content.generate_youtube_metadata(topic, duration)
                    title = metadata['title']
                    description = metadata['description']
                    tags = metadata['tags']
                    logger.info(f"📈 Using dynamic metadata - Title: {title[:50]}...")
                except Exception as e:
                    logger.warning(f"⚠️ Dynamic metadata failed: {e}, using fallback")
                    # Fallback to static metadata
                    title = f"{topic} in {duration} Seconds! #Shorts"
                    description = f"""Quick tutorial on {topic}!

🔥 Learn programming concepts in bite-sized videos
💡 Perfect for developers on the go
📚 More tutorials coming daily

Thanks to Code Tapasya for the amazing content!

#Programming #Coding #Tutorial #LearnToCode #Developer #TechTips"""
                    tags = ["Shorts", "Programming", "Coding", "Tutorial", "Education"]
            else:
                # Static metadata
                title = f"{topic} in {duration} Seconds! #Shorts"
                description = f"""Quick tutorial on {topic}!

🔥 Learn programming concepts in bite-sized videos
💡 Perfect for developers on the go
📚 More tutorials coming daily

Thanks to Code Tapasya for the amazing content!

#Programming #Coding #Tutorial #LearnToCode #Developer #TechTips"""
                tags = ["Shorts", "Programming", "Coding", "Tutorial", "Education"]
            
            # Upload body - CRITICAL: privacyStatus = "public" and made for kids = false
            request_body = {
                "snippet": {
                    "title": title[:100],
                    "description": description,
                    "tags": tags[:15],  # YouTube allows max 15 tags
                    "categoryId": "27"  # Education category
                },
                "status": {
                    "privacyStatus": "public",  # ✅ PUBLIC (not private, not unlisted)
                    "selfDeclaredMadeForKids": False,  # ✅ Not for kids
                    "embeddable": True,  # ✅ Allow embedding
                    "license": "creativeCommon",  # ✅ Creative Commons
                    "publicStatsViewable": True  # ✅ Show stats
                }
            }
            
            # Upload file
            media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
            
            request = youtube.videos().insert(
                part="snippet,status",
                body=request_body,
                media_body=media
            )
            
            logger.info("⏳ Uploading to YouTube (this may take a few minutes)...")
            response = request.execute()
            
            video_id = response.get('id')
            if video_id:
                logger.info(f"✅ Upload successful!")
                logger.info(f"   Video ID: {video_id}")
                logger.info(f"   URL: https://youtube.com/watch?v={video_id}")
                logger.info(f"   Privacy: PUBLIC")
                return video_id
            else:
                logger.error("❌ Upload returned no video ID")
                return None
        
        except Exception as e:
            logger.error(f"❌ YouTube upload failed: {e}")
            logger.error(traceback.format_exc())
            return None
    
    def update_firebase_shorts(self, video_id: str, topic: str, 
                               status: str = "uploaded", 
                               error: str = None) -> bool:
        """Update 'youtube-shorts' collection in Firebase"""
        if not self.firebase_enabled:
            logger.warning("⚠️ Firebase not enabled, skipping update")
            return False
        
        try:
            db = firestore.client()
            
            doc_data = {
                "topic": topic,
                "video_id": video_id,
                "status": status,
                "url": f"https://youtube.com/watch?v={video_id}" if status == "uploaded" else None,
                "uploaded_at": firestore.SERVER_TIMESTAMP,
                "privacy": "public"
            }
            
            if error:
                doc_data["error"] = error
            
            # Add to 'youtube-shorts' collection
            db.collection("youtube-shorts").document(video_id).set(doc_data)
            
            logger.info(f"📤 Firebase updated: {video_id}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Firebase update failed: {e}")
            return False
    
    def generate_short(self, topic: str, duration: int) -> Optional[str]:
        """Call generator API to create a short video"""
        try:
            import requests
            
            # Try local generator first
            generator_url = os.getenv("GENERATOR_URL", "http://localhost:8000")
            
            logger.info(f"🎬 Requesting video generation...")
            logger.info(f"   Topic: {topic}")
            logger.info(f"   Duration: {duration}s")
            
            payload = {
                "topic": topic,
                "duration": duration,
                "aspect_ratio": "9:16",  # Vertical Shorts format
                "video_type": "short",
                "quality": "qm"  # Medium quality 720p
            }
            
            response = requests.post(
                f"{generator_url}/api/generate/",
                json=payload,
                timeout=30
            )
            
            if response.status_code in [200, 202]:
                job_data = response.json()
                job_id = job_data.get('job_id')
                logger.info(f"✅ Generation job created: {job_id}")
                
                # Wait for generation to complete
                video_path = self._wait_for_generation(job_id, timeout=600)
                return video_path
            else:
                logger.error(f"❌ Generation request failed: {response.status_code}")
                return None
        
        except Exception as e:
            logger.error(f"❌ Generation failed: {e}")
            logger.error(traceback.format_exc())
            return None
    
    def _wait_for_generation(self, job_id: str, timeout: int = 600) -> Optional[str]:
        """Wait for generation job to complete"""
        import requests
        
        generator_url = os.getenv("GENERATOR_URL", "http://localhost:8000")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                response = requests.get(
                    f"{generator_url}/api/generate/{job_id}/",
                    timeout=10
                )
                
                if response.status_code == 200:
                    job_data = response.json()
                    status = job_data.get('status')
                    
                    if status == 'completed':
                        video_path = job_data.get('video_path')
                        logger.info(f"✅ Generation complete: {video_path}")
                        return video_path
                    
                    elif status == 'failed':
                        error = job_data.get('error', 'Unknown error')
                        logger.error(f"❌ Generation failed: {error}")
                        return None
                    
                    else:
                        logger.info(f"⏳ Generation in progress ({status})...")
                
                time.sleep(10)  # Check every 10 seconds
            
            except Exception as e:
                logger.warning(f"⚠️ Error checking status: {e}")
                time.sleep(10)
        
        logger.error(f"❌ Generation timed out after {timeout}s")
        return None
    
    def generate_and_upload_short(self) -> Tuple[bool, Optional[str]]:
        """Full workflow: generate → upload → update Firebase"""
        topic = None
        video_path = None
        job_status = "failed"
        error_msg = None
        
        try:
            topic = self.get_unused_topic()
            duration = random.randint(45, 60)
            
            logger.info(f"\n{'='*60}")
            logger.info(f"🎯 Starting YouTube Short generation & upload")
            logger.info(f"   Topic: {topic}")
            logger.info(f"   Duration: {duration}s")
            logger.info(f"   Time: {datetime.now().isoformat()}")
            logger.info(f"{'='*60}")
            
            # Step 1: Generate video
            video_path = self.generate_short(topic, duration)
            
            if not video_path:
                error_msg = "Generation failed or timed out"
                raise RuntimeError(error_msg)
            
            # Step 2: Upload to YouTube
            video_id = self.upload_short_to_youtube(video_path, topic, duration)
            
            if not video_id:
                error_msg = "YouTube upload failed"
                raise RuntimeError(error_msg)
            
            # Step 3: Save history
            self.save_upload_history(topic, video_id, "uploaded")
            
            # Step 4: Update Firebase
            self.update_firebase_shorts(video_id, topic, "uploaded")
            
            job_status = "completed"
            
            logger.info(f"\n{'='*60}")
            logger.info(f"✅ SUCCESS!")
            logger.info(f"   Video: {video_id}")
            logger.info(f"   Topic: {topic}")
            logger.info(f"   URL: https://youtube.com/watch?v={video_id}")
            logger.info(f"{'='*60}\n")
            
            return True, video_id
        
        except Exception as e:
            error_msg = str(e)
            logger.error(f"\n❌ FAILED: {error_msg}")
            logger.error(traceback.format_exc())
            
            # Update Firebase with error
            if topic:
                self.update_firebase_shorts(
                    f"failed_{datetime.now().timestamp()}",
                    topic,
                    "failed",
                    error_msg
                )
            
            return False, None
    
    def schedule_uploads(self):
        """Schedule 2 uploads per day"""
        upload_times = os.getenv("UPLOAD_TIMES", "09:00,18:00").split(',')
        upload_times = [t.strip() for t in upload_times]
        
        logger.info(f"\n📅 Scheduling uploads at: {upload_times} UTC")
        
        for time_str in upload_times:
            schedule.every().day.at(time_str).do(self.generate_and_upload_short)
            logger.info(f"   ⏰ {time_str}")
        
        logger.info("✅ Scheduler running. Press Ctrl+C to stop.\n")
        
        while True:
            schedule.run_pending()
            time.sleep(60)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='YouTube Shorts Scheduler & Uploader')
    parser.add_argument('--once', action='store_true', help='Generate and upload one short')
    parser.add_argument('--schedule', action='store_true', help='Run scheduled uploads (default)')
    parser.add_argument('--test', action='store_true', help='Test connections (YouTube, Firebase)')
    
    args = parser.parse_args()
    
    scheduler = YouTubeShortsScheduler()
    
    # Test mode
    if args.test:
        logger.info("🧪 Testing connections...\n")
        
        # Test YouTube
        try:
            scheduler.authenticate_youtube()
            logger.info("✅ YouTube API: Connected")
        except Exception as e:
            logger.error(f"❌ YouTube API: {e}")
        
        # Test Firebase
        if scheduler.firebase_enabled:
            logger.info("✅ Firebase: Connected")
        else:
            logger.warning("⚠️ Firebase: Not configured")
        
        return
    
    # Run once
    if args.once:
        logger.info("📌 Running single upload cycle")
        success, video_id = scheduler.generate_and_upload_short()
        sys.exit(0 if success else 1)
    
    # Default: scheduled
    logger.info("📅 Running scheduled mode (default)")
    scheduler.schedule_uploads()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n⏹️ Stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n💥 Fatal error: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)
