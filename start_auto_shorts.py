import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('auto_shorts.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

def check_requirements():
    required_files = ["client_secret.json", ".env"]
    missing_files = [f for f in required_files if not Path(f).exists()]
    
    if missing_files:
        logger.error(f"❌ Missing files: {missing_files}")
        return False
    
    required_vars = ["GEMINI_API_KEY", "GROQ_API_KEY"]
    missing_vars = [v for v in required_vars if not os.getenv(v)]
    
    if missing_vars:
        logger.error(f"❌ Missing env vars: {missing_vars}")
        return False
    
    logger.info("✅ All requirements satisfied")
    return True

def main():
    logger.info("🚀 Starting Auto YouTube Shorts Generator")
    
    if not check_requirements():
        sys.exit(1)
    
    try:
        from auto_shorts_generator import AutoShortsGenerator
        generator = AutoShortsGenerator()
        
        if len(sys.argv) > 1 and sys.argv[1] == "--test":
            logger.info("🧪 Test mode: Generating single video")
            import asyncio
            asyncio.run(generator.generate_and_upload_short())
            return
        
        logger.info("📅 Starting scheduled uploads (9 AM & 6 PM daily)")
        generator.schedule_daily_uploads()
        
    except KeyboardInterrupt:
        logger.info("⏹️ Stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()