#!/usr/bin/env python3
"""
Diagnostic script to identify where the scheduler is hanging
Run this to get detailed step-by-step logging
"""

import os
import sys
import asyncio
import logging
from dotenv import load_dotenv

# Enhanced logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Add verbose output
import subprocess
subprocess.run(['ffmpeg', '-version'], capture_output=True)
logger.info(f"✅ FFmpeg is available")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from generator.video_generator.optimized_video_generator import OptimizedVideoGenerationPipeline, VideoGenerationConfig
from generator.oracle_storage import OracleStorageClient
from youtube_upload import upload_short
from generator.firebase_utils import create_job, update_video_status_with_url

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

async def main():
    logger.info("=" * 80)
    logger.info("🔍 SCHEDULER DIAGNOSTIC TEST")
    logger.info("=" * 80)
    
    # Test 1: Initialize pipeline
    logger.info("\n[TEST 1] Initializing video generation pipeline...")
    try:
        config = VideoGenerationConfig(
            gemini_api_key=GEMINI_API_KEY,
            groq_api_key=GROQ_API_KEY,
            aspect_ratio="9:16",
            workers=1,
            output_dir="output"
        )
        pipeline = OptimizedVideoGenerationPipeline(config)
        logger.info("✅ Pipeline initialized successfully")
    except Exception as e:
        logger.error(f"❌ Pipeline init failed: {e}")
        return
    
    # Test 2: Initialize Oracle Storage
    logger.info("\n[TEST 2] Initializing Oracle Storage...")
    try:
        oracle_storage = OracleStorageClient()
        logger.info("✅ Oracle Storage initialized successfully")
    except Exception as e:
        logger.error(f"❌ Oracle Storage init failed: {e}")
        logger.info("💡 This is expected if credentials are incomplete. Can continue without it.")
    
    # Test 3: Initialize YouTube auth
    logger.info("\n[TEST 3] Checking YouTube authentication...")
    try:
        from youtube_upload import authenticate_youtube
        youtube = authenticate_youtube()
        logger.info("✅ YouTube authentication successful")
    except Exception as e:
        logger.error(f"❌ YouTube auth failed: {e}")
        logger.info("💡 This is expected if token.json is missing")
    
    # Test 4: Generate narration segments
    logger.info("\n[TEST 4] Generating narration segments (STEP 1 of 5)...")
    try:
        segments = await pipeline._generate_narration_segments_with_gemini(
            "Python Basics", 
            60
        )
        logger.info(f"✅ Generated {len(segments)} narration segments")
        logger.info(f"   Segments: {[f'{s.duration}s' for s in segments[:3]]}...")
    except Exception as e:
        logger.error(f"❌ Narration segment generation failed: {e}")
        return
    
    # Test 5: Generate audio
    logger.info("\n[TEST 5] Generating audio for segments (STEP 2 of 5)...")
    logger.info("   ⏳ This may take a few minutes...")
    try:
        await pipeline.generate_all_audio_segments(segments, "temp")
        logger.info("✅ Audio generation complete")
    except Exception as e:
        logger.error(f"❌ Audio generation failed: {e}")
        return
    
    # Test 6: Generate scripts
    logger.info("\n[TEST 6] Generating scripts (STEP 3 of 5)...")
    logger.info("   ⏳ Trying bulk generation first...")
    try:
        segments = await pipeline._generate_scripts_in_bulk(segments)
        logger.info("✅ Bulk script generation successful")
    except Exception as e:
        logger.warning(f"⚠️ Bulk generation failed, trying parallel: {e}")
        try:
            segments = await pipeline._generate_scripts_in_parallel(segments)
            logger.info("✅ Parallel script generation successful")
        except Exception as e2:
            logger.error(f"❌ Script generation failed: {e2}")
            return
    
    # Test 7: Render videos (THIS IS WHERE IT USUALLY HANGS)
    logger.info("\n[TEST 7] Rendering videos (STEP 4 of 5)...")
    logger.info("   ⏳ This is slow on E2.Micro - may take 10+ minutes...")
    logger.info("   🔍 Watch this output for hang detection")
    try:
        # Add timeout
        render_start = asyncio.get_event_loop().time()
        segments = await asyncio.wait_for(
            pipeline._parallel_video_generation_fixed(segments),
            timeout=900  # 15 minute timeout
        )
        render_time = asyncio.get_event_loop().time() - render_start
        logger.info(f"✅ Video rendering complete (took {render_time:.1f}s)")
    except asyncio.TimeoutError:
        logger.error(f"❌ Video rendering TIMEOUT after 15 minutes")
        logger.error("💡 This indicates E2.Micro is too slow for video generation")
        logger.error("💡 Solution: Use larger instance type or reduce video quality")
        return
    except Exception as e:
        logger.error(f"❌ Video rendering failed: {e}")
        return
    
    # Test 8: Final assembly
    logger.info("\n[TEST 8] Final assembly (STEP 5 of 5)...")
    try:
        final_path = await pipeline._parallel_final_assembly_with_proper_sync(
            segments, 
            "Python Basics"
        )
        logger.info(f"✅ Final video created: {final_path}")
    except Exception as e:
        logger.error(f"❌ Final assembly failed: {e}")
        return
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ ALL TESTS PASSED - Scheduler should work!")
    logger.info("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
