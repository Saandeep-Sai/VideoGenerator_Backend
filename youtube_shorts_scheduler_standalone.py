#!/usr/bin/env python3
"""
Standalone YouTube Shorts Auto-Generator & Uploader
Runs independently on E2.Micro #2 - NO external dependencies
Generates videos locally, uploads to YouTube automatically

Schedule: 2x daily (configurable via UPLOAD_TIMES env var)
Topics: Rotates through 30+ programming topics (no repeats within 30 days)
"""

import os
import sys
import json
import asyncio
import logging
import gc
# Removed: import schedule, time (using systemd timer now)
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import local modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generator.video_generator.optimized_video_generator import OptimizedVideoGenerationPipeline, VideoGenerationConfig
from generator.oracle_storage import OracleStorageClient
from youtube_upload import upload_short
from generator.firebase_utils import create_job, update_video_status_with_url
from resource_monitor import resource_monitor
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Get configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
UPLOAD_TIMES = os.getenv("UPLOAD_TIMES", "09:00,18:00").split(",")
AI_TOPIC_GENERATION = os.getenv("AI_TOPIC_GENERATION", "true").lower() == "true"

if not GEMINI_API_KEY or not GROQ_API_KEY:
    logger.error("❌ Missing API keys! Set GEMINI_API_KEY and GROQ_API_KEY in .env")
    sys.exit(1)

logger.info("=" * 70)
logger.info("🎬 STANDALONE YOUTUBE SHORTS GENERATOR & UPLOADER")
logger.info("=" * 70)
logger.info(f"📅 Upload times (UTC): {', '.join(UPLOAD_TIMES)}")
logger.info("=" * 70)

# Topics database - 100+ unique topics
PROGRAMMING_TOPICS = [
    # Core Programming
    "Object-Oriented Programming", "Design Patterns in Python", "Async/Await Programming",
    "Data Structures and Algorithms", "Functional Programming", "Clean Code Practices",
    "Code Refactoring Techniques", "Debugging Techniques", "Memory Management",
    "Recursion and Dynamic Programming", "Big O Notation", "Sorting Algorithms",
    
    # Web Development
    "REST API Development", "GraphQL Basics", "WebSocket Programming",
    "Frontend Frameworks Comparison", "React Hooks Deep Dive", "Vue.js Essentials",
    "Angular Components", "Node.js Best Practices", "Express.js Middleware",
    "JavaScript ES6+ Features", "TypeScript Benefits", "CSS Grid vs Flexbox",
    
    # Database & Backend
    "Database Design Principles", "SQL Query Optimization", "NoSQL vs SQL",
    "MongoDB Aggregation", "Redis Caching", "Database Indexing",
    "ACID Properties", "Database Normalization", "Stored Procedures",
    
    # DevOps & Cloud
    "Docker and Containerization", "Kubernetes Orchestration", "CI/CD Pipelines",
    "Cloud Computing with AWS", "Azure Services Overview", "Google Cloud Platform",
    "Infrastructure as Code", "Terraform Basics", "Ansible Automation",
    "Jenkins Pipeline", "GitHub Actions", "Monitoring and Logging",
    
    # Architecture & Design
    "Microservices Architecture", "Monolith vs Microservices", "Event-Driven Architecture",
    "Distributed Systems", "Load Balancing", "API Gateway Design",
    "Caching Strategies", "Message Queues", "Service Mesh",
    "Domain-Driven Design", "CQRS Pattern", "Event Sourcing",
    
    # Security
    "Security Best Practices", "Authentication and Authorization", "OAuth 2.0 Explained",
    "JWT Tokens", "SQL Injection Prevention", "XSS Protection",
    "HTTPS and SSL", "API Security", "Password Hashing",
    "Two-Factor Authentication", "Penetration Testing", "Secure Coding",
    
    # AI & Machine Learning
    "Machine Learning Fundamentals", "Neural Networks Basics", "Deep Learning Introduction",
    "Natural Language Processing", "Computer Vision", "Reinforcement Learning",
    "TensorFlow vs PyTorch", "Data Preprocessing", "Model Training",
    "Overfitting and Underfitting", "Feature Engineering", "AI Ethics",
    
    # Mobile Development
    "React Native Development", "Flutter vs React Native", "iOS Swift Programming",
    "Android Kotlin Development", "Mobile App Architecture", "Push Notifications",
    "Mobile Security", "App Store Optimization", "Cross-Platform Development",
    
    # Testing & Quality
    "Test-Driven Development", "Unit Testing Best Practices", "Integration Testing",
    "End-to-End Testing", "Test Automation", "Code Coverage",
    "Performance Testing", "Load Testing", "Selenium WebDriver",
    
    # Tools & Productivity
    "Git and Version Control", "Git Branching Strategies", "Code Review Process",
    "IDE Tips and Tricks", "VS Code Extensions", "Command Line Mastery",
    "Regex Patterns", "Package Managers", "Build Tools",
    
    # Performance & Optimization
    "Performance Optimization", "Code Profiling", "Memory Leaks Detection",
    "Database Performance Tuning", "Web Performance", "CDN Implementation",
    "Lazy Loading", "Image Optimization", "Minification and Compression",
]

class StandaloneYouTubeShortsGenerator:
    """Generates and uploads YouTube Shorts completely independently"""
    
    def __init__(self):
        """Initialize pipeline and storage"""
        logger.info("🚀 Initializing generator...")
        
        # Configure pipeline
        self.config = VideoGenerationConfig(
            gemini_api_key=GEMINI_API_KEY,
            groq_api_key=GROQ_API_KEY,
            aspect_ratio="9:16"  # YouTube Shorts format
        )
        self.pipeline = OptimizedVideoGenerationPipeline(self.config)
        self.oracle_storage = OracleStorageClient()
        
        # Initialize Gemini for topic generation
        if AI_TOPIC_GENERATION:
            import google.generativeai as genai
            genai.configure(api_key=GEMINI_API_KEY)
            self.gemini_client = genai.GenerativeModel('gemini-2.5-flash')
            logger.info("🤖 AI topic generation enabled")
        else:
            self.gemini_client = None
            logger.info("📝 Using predefined topics only")
        
        logger.info("✅ Generator initialized")
    
    def load_topic_history(self) -> dict:
        """Load topic generation history"""
        history_file = Path("youtube_shorts_history.json")
        if history_file.exists():
            try:
                with open(history_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                logger.warning("⚠️ Corrupted history file, starting fresh")
                return {}
        return {}
    
    def save_topic_history(self, history: dict):
        """Save topic generation history"""
        try:
            with open("youtube_shorts_history.json", "w") as f:
                json.dump(history, f, indent=2)
            logger.debug(f"📝 History saved: {len(history)} topics tracked")
        except Exception as e:
            logger.error(f"❌ Failed to save history: {e}")
    
    def generate_ai_topic(self) -> Optional[str]:
        """Generate a fresh programming topic using Gemini AI."""
        if not self.gemini_client:
            return None
            
        try:
            history = self.load_topic_history()
            recent_topics = list(history.keys())[-10:]  # Last 10 topics
            
            prompt = f"""Generate 1 unique programming/tech topic for a 60-second YouTube Short.

Requirements:
- Educational and engaging for developers
- Different from recent topics: {', '.join(recent_topics) if recent_topics else 'None'}
- Suitable for visual explanation
- Trending in 2024

Categories: Web Dev, AI/ML, DevOps, Mobile, Security, Databases, Architecture

Output format: Just the topic title (no quotes, no explanation)
Example: "Microservices vs Serverless Architecture"

Generate topic:"""
            
            response = self.gemini_client.generate_content(prompt)
            ai_topic = response.text.strip().replace('"', '').replace("'", "")
            
            if len(ai_topic) > 5 and len(ai_topic) < 80:
                logger.info(f"🤖 AI generated topic: {ai_topic}")
                return ai_topic
            else:
                logger.warning(f"⚠️ AI topic invalid length: {ai_topic}")
                return None
                
        except Exception as e:
            logger.error(f"❌ AI topic generation failed: {e}")
            return None
    
    def get_next_topic(self) -> str:
        """Get next topic (AI generation + rotation fallback)."""
        # Try AI generation first (if enabled)
        if AI_TOPIC_GENERATION and self.gemini_client:
            ai_topic = self.generate_ai_topic()
            if ai_topic:
                return ai_topic
            logger.warning("⚠️ AI topic generation failed, using predefined topics")
        
        # Fallback to predefined topics with rotation
        history = self.load_topic_history()
        today = datetime.now()
        thirty_days_ago = today - timedelta(days=30)
        
        # Filter out recently used topics
        recent_topics = set()
        for topic, last_used_str in history.items():
            try:
                last_used = datetime.fromisoformat(last_used_str)
                if last_used > thirty_days_ago:
                    recent_topics.add(topic)
            except ValueError:
                logger.warning(f"⚠️ Invalid date format for topic: {topic}")
        
        # Find next topic in rotation order
        if history:
            # Get last used topic and find next in sequence
            last_topic = max(history.items(), key=lambda x: x[1])[0]
            try:
                last_index = PROGRAMMING_TOPICS.index(last_topic)
                # Start from next topic in sequence
                for i in range(len(PROGRAMMING_TOPICS)):
                    next_index = (last_index + 1 + i) % len(PROGRAMMING_TOPICS)
                    next_topic = PROGRAMMING_TOPICS[next_index]
                    if next_topic not in recent_topics:
                        logger.info(f"📋 Selected topic: {next_topic} (continuing rotation from {last_topic})")
                        return next_topic
            except ValueError:
                # Last topic not in current list, start from beginning
                pass
        
        # Fallback: find first available topic
        for topic in PROGRAMMING_TOPICS:
            if topic not in recent_topics:
                logger.info(f"📋 Selected topic: {topic} (first available)")
                return topic
        
        # If all topics used recently, start fresh cycle
        logger.warning("⚠️ All topics used in last 30 days, starting fresh cycle")
        return PROGRAMMING_TOPICS[0]
    
    def mark_topic_used(self, topic: str):
        """Mark topic as used and log statistics"""
        history = self.load_topic_history()
        history[topic] = datetime.now().isoformat()
        self.save_topic_history(history)
        
        # Log topic statistics
        total_topics = len(PROGRAMMING_TOPICS)
        used_topics = len(history)
        recent_topics = len([t for t, date_str in history.items() 
                           if datetime.fromisoformat(date_str) > datetime.now() - timedelta(days=30)])
        
        logger.info(f"✅ Topic marked as used: {topic}")
        logger.info(f"📊 Topic Stats: {used_topics} total used, {recent_topics} recent (30d), {total_topics} available")
    
    async def generate_video(self, topic: str, duration: int = 60) -> Optional[str]:
        """Generate video locally with resource monitoring for E2.Micro."""
        try:
            # Check system resources before starting
            resource_monitor.log_system_status()
            overloaded, reason = resource_monitor.is_system_overloaded()
            
            if overloaded:
                logger.warning(f"⚠️ System overloaded before generation: {reason}")
                if not resource_monitor.wait_for_resources(max_wait=180):
                    logger.error("❌ System resources unavailable - aborting generation")
                    return None
            
            logger.info(f"🎬 Generating video locally...")
            logger.info(f"   Topic: {topic}")
            logger.info(f"   Duration: {duration}s")
            logger.info(f"   Format: 9:16 (YouTube Shorts)")
            
            # Set memory optimization before video generation
            os.environ["MALLOC_TRIM_THRESHOLD_"] = "65536"
            
            # Generate video using local pipeline
            final_video_path = await self.pipeline.generate_video_full_parallel(
                topic, 
                duration
            )
            
            # Cleanup after generation
            gc.collect()
            resource_monitor.cleanup_memory()
            
            logger.info(f"✅ Video generated: {final_video_path}")
            return final_video_path
            
        except Exception as e:
            logger.error(f"❌ Video generation failed: {e}")
            # Cleanup on failure
            resource_monitor.cleanup_memory()
            return None
    
    def upload_to_youtube(self, video_path: str, topic: str, duration: int) -> Optional[str]:
        """Upload video to YouTube"""
        try:
            logger.info(f"📤 Uploading to YouTube...")
            
            title = f"{topic} in {duration} Seconds! #Shorts #Programming #LearnToCode"
            description = f"""Quick tutorial on {topic}!

🔥 Learn programming concepts in bite-sized videos
💡 Perfect for developers on the go
📚 Master coding one short at a time

Thanks to Code Tapasya for the amazing content!

#Programming #Coding #Tutorial #LearnToCode #Developer #TechTips"""
            
            response = upload_short(video_path, title, description)
            video_id = response.get('id')
            
            if video_id:
                youtube_url = f"https://youtube.com/watch?v={video_id}"
                logger.info(f"✅ YouTube upload successful!")
                logger.info(f"📺 Video ID: {video_id}")
                logger.info(f"🔗 URL: {youtube_url}")
                return video_id
            else:
                logger.error("❌ No video ID returned from YouTube")
                return None
                
        except Exception as e:
            logger.error(f"❌ YouTube upload failed: {e}")
            return None
    
    def upload_to_oracle(self, video_path: str, job_id: str) -> Optional[str]:
        """Upload video to Oracle Object Storage"""
        try:
            logger.info(f"📤 Uploading to Oracle Object Storage...")
            video_url = self.oracle_storage.upload_video(video_path, job_id)
            logger.info(f"✅ Oracle upload successful: {video_url}")
            return video_url
        except Exception as e:
            logger.error(f"❌ Oracle upload failed: {e}")
            return None
    
    async def generate_and_upload_short(self) -> Tuple[bool, Optional[str]]:
        """Full workflow: generate locally → upload to YouTube + Oracle → Firebase"""
        try:
            logger.info("=" * 70)
            logger.info("🎯 Starting YouTube Short generation & upload")
            logger.info("=" * 70)
            
            # Get next topic
            topic = self.get_next_topic()
            duration = 60
            
            # Log topic source
            topic_source = "🤖 AI Generated" if AI_TOPIC_GENERATION and self.gemini_client else "📝 Predefined"
            
            logger.info(f"📋 Topic: {topic} ({topic_source})")
            logger.info(f"⏱️ Duration: {duration}s")
            logger.info(f"📅 Time: {datetime.now().isoformat()}")
            logger.info("=" * 70)
            
            # Create Firebase job record
            job_id = create_job(topic, duration, "9:16", "short")
            logger.info(f"📝 Firebase job created: {job_id}")
            
            # Step 1: Generate video locally (with timeout - max 20 minutes)
            logger.info("🎬 Step 1: Generating video locally...")
            logger.info("⚠️ NOTE: This may take 10-20 minutes on E2.Micro (1 vCPU)")
            logger.info("🔄 Generating narration → scripts → rendering → final assembly...")
            try:
                video_path = await asyncio.wait_for(
                    self.generate_video(topic, duration),
                    timeout=1200  # 20 minutes timeout
                )
            except asyncio.TimeoutError:
                logger.error("❌ Video generation timed out (>20 minutes). E2.Micro may be too slow.")
                logger.error("💡 Consider upgrading instance type or reducing video duration")
                raise RuntimeError("Video generation timeout")
            if not video_path:
                raise RuntimeError("Video generation failed")
            
            # Step 2: Upload to YouTube
            logger.info("📺 Step 2: Uploading to YouTube...")
            youtube_video_id = self.upload_to_youtube(video_path, topic, duration)
            if not youtube_video_id:
                logger.warning("⚠️ YouTube upload failed, but continuing with Oracle")
            
            # Step 3: Upload to Oracle Storage
            logger.info("☁️ Step 3: Uploading to Oracle Object Storage...")
            video_url = self.upload_to_oracle(video_path, job_id)
            if not video_url:
                raise RuntimeError("Oracle upload failed")
            
            # Step 4: Update Firebase
            logger.info("🔥 Step 4: Updating Firebase...")
            update_video_status_with_url(
                job_id, 
                video_url, 
                status="completed", 
                youtube_video_id=youtube_video_id
            )
            logger.info("✅ Firebase updated")
            
            # Step 5: Mark topic as used
            self.mark_topic_used(topic)
            
            # Step 6: Cleanup
            try:
                Path(video_path).unlink()
                logger.info("🧹 Local video cleaned up")
            except:
                pass
            
            # Force memory cleanup after upload
            del video_path
            gc.collect()
            resource_monitor.cleanup_memory()
            resource_monitor.log_system_status()
            
            logger.info("=" * 70)
            logger.info("✅ COMPLETE: Video generated and uploaded successfully!")
            logger.info(f"🎉 YouTube: https://youtube.com/watch?v={youtube_video_id}")
            logger.info("=" * 70)
            
            return True, youtube_video_id
            
        except Exception as e:
            logger.error(f"❌ FAILED: {e}")
            logger.error("=" * 70)
            return False, None
    


def main():
    """Main entry point - systemd timer mode"""
    generator = StandaloneYouTubeShortsGenerator()
    
    # Check command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        # Run once and exit (systemd timer mode)
        logger.info("🔄 Running in systemd timer mode...")
        success, video_id = asyncio.run(generator.generate_and_upload_short())
        
        # Force cleanup before exit
        resource_monitor.cleanup_memory()
        
        if success:
            logger.info("✅ Job completed successfully - exiting")
            sys.exit(0)
        else:
            logger.error("❌ Job failed - exiting with error")
            sys.exit(1)
    else:
        # Legacy mode warning
        logger.error("❌ Legacy scheduler mode disabled!")
        logger.error("📝 Use systemd timer instead:")
        logger.error("   sudo systemctl start youtube-shorts-scheduler.timer")
        sys.exit(1)

if __name__ == "__main__":
    main()
