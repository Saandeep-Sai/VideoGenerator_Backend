"""
Test script for GeminiRateLimitedClient.

Run this to validate that rate limiting works correctly.
"""

import asyncio
import os
import sys
import time
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from gemini_client import GeminiRateLimitedClient
from cache_manager import CacheManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_rate_limiting():
    """Test that rate limiting works correctly."""
    logger.info("=" * 60)
    logger.info("TEST 1: Rate Limiting")
    logger.info("=" * 60)
    
    # Create client with very low rate for testing
    client = GeminiRateLimitedClient(
        requests_per_minute=6,  # Only 6/min for visible rate limiting
        model_name="gemini-2.5-flash"
    )
    
    # Send 10 requests and measure time
    logger.info("Sending 10 requests (should take ~90 seconds at 6/min)...")
    start_time = time.time()
    
    for i in range(10):
        try:
            response = await client.generate_content(
                prompt=f"Count to {i + 1}",
                temperature=0.0,
                max_tokens=50
            )
            logger.info(f"Request {i + 1}/10 completed: {response[:50]}...")
        except Exception as e:
            logger.error(f"Request {i + 1} failed: {e}")
    
    elapsed = time.time() - start_time
    logger.info(f"✅ Completed 10 requests in {elapsed:.1f}s")
    logger.info(f"   Expected: ~90s (6 req/min)")
    logger.info(f"   Actual rate: {10 / elapsed * 60:.1f} req/min")
    
    # Print metrics
    client.print_metrics()


async def test_caching():
    """Test that caching works correctly."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: Caching")
    logger.info("=" * 60)
    
    # Create cache
    cache = CacheManager(cache_dir="./test_cache", ttl_days=1)
    
    # Generate cache key
    prompt = "Explain Python decorators"
    cache_key = cache.generate_key("narration", prompt=prompt)
    
    # First call - should be miss
    logger.info("First call (cache miss expected)...")
    cached = cache.get(cache_key)
    assert cached is None, "Expected cache miss"
    logger.info("✅ Cache miss as expected")
    
    # Store result
    fake_response = "Decorators are a way to modify functions..."
    cache.set(cache_key, fake_response)
    logger.info("✅ Stored in cache")
    
    # Second call - should be hit
    logger.info("Second call (cache hit expected)...")
    cached = cache.get(cache_key)
    assert cached == fake_response, "Expected cache hit"
    logger.info("✅ Cache hit as expected")
    
    # Print stats
    cache.print_stats()
    
    # Cleanup
    cache.clear()
    logger.info("✅ Cache cleared")


async def test_key_rotation():
    """Test that key rotation works when quota exhausted."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 3: Key Rotation")
    logger.info("=" * 60)
    
    # This test requires multiple keys in environment
    keys = []
    for i in range(1, 5):
        key = os.getenv(f"GEMINI_API_KEY_{i}")
        if key:
            keys.append(key)
    
    if len(keys) < 2:
        logger.warning("⚠️ Skipping key rotation test (need 2+ keys)")
        logger.warning("   Set GEMINI_API_KEY_1, GEMINI_API_KEY_2, etc.")
        return
    
    logger.info(f"Found {len(keys)} API keys")
    
    # Create client
    client = GeminiRateLimitedClient(
        api_keys=keys,
        requests_per_minute=20
    )
    
    # Make a few requests
    for i in range(3):
        try:
            response = await client.generate_content(
                prompt=f"Say hello {i + 1}",
                temperature=0.0,
                max_tokens=20
            )
            logger.info(f"✅ Request {i + 1} successful")
        except Exception as e:
            logger.error(f"Request {i + 1} failed: {e}")
    
    # Print metrics
    client.print_metrics()


async def test_integration():
    """Integration test: rate limiting + caching."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 4: Integration (Rate Limiting + Caching)")
    logger.info("=" * 60)
    
    client = GeminiRateLimitedClient(requests_per_minute=10)
    cache = CacheManager(cache_dir="./test_cache")
    
    prompts = [
        "Explain Python",
        "Explain JavaScript",
        "Explain Python",  # Duplicate - should use cache
        "Explain TypeScript",
        "Explain Python"   # Duplicate - should use cache
    ]
    
    for i, prompt in enumerate(prompts):
        cache_key = cache.generate_key("test", prompt=prompt)
        
        # Check cache first
        cached = cache.get(cache_key)
        if cached:
            logger.info(f"Request {i + 1}: ✅ Cache hit for '{prompt}'")
            continue
        
        # Generate new
        logger.info(f"Request {i + 1}: 📤 API call for '{prompt}'")
        try:
            response = await client.generate_content(
                prompt=prompt,
                temperature=0.0,
                max_tokens=100
            )
            cache.set(cache_key, response)
            logger.info(f"   ✅ Generated and cached")
        except Exception as e:
            logger.error(f"   ❌ Failed: {e}")
    
    # Print stats
    logger.info("\n" + "-" * 60)
    cache.print_stats()
    client.print_metrics()
    
    # Cleanup
    cache.clear()


async def main():
    """Run all tests."""
    logger.info("🧪 Starting GeminiRateLimitedClient Tests")
    logger.info("")
    
    # Check if API key exists
    if not os.getenv("GEMINI_API_KEY") and not os.getenv("GEMINI_API_KEY_1"):
        logger.error("❌ No GEMINI_API_KEY found in environment")
        logger.error("   Set GEMINI_API_KEY or GEMINI_API_KEY_1")
        return
    
    try:
        # Run tests
        await test_caching()
        await test_rate_limiting()
        await test_key_rotation()
        await test_integration()
        
        logger.info("\n" + "=" * 60)
        logger.info("✅ All tests completed!")
        logger.info("=" * 60)
    
    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
