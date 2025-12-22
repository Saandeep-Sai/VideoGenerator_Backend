"""
Centralized, rate-limited Gemini API client.

This module provides a thread-safe, async-compatible wrapper around Google's Gemini API
with built-in rate limiting, automatic retries, exponential backoff, and key rotation.

Features:
- Token bucket rate limiting (default: 20 requests/min)
- Automatic key rotation on quota exhaustion
- Exponential backoff on 429/503 errors
- Request/error metrics logging
- Support for multiple API keys with health tracking
"""

import asyncio
import time
import logging
import os
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

logger = logging.getLogger(__name__)


@dataclass
class APIKeyHealth:
    """Track health metrics for a single API key."""
    key_index: int
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    quota_errors: int = 0
    last_used: Optional[datetime] = None
    last_quota_error: Optional[datetime] = None
    is_healthy: bool = True
    
    def mark_success(self):
        self.total_requests += 1
        self.successful_requests += 1
        self.last_used = datetime.now()
        self.is_healthy = True
    
    def mark_quota_error(self):
        self.total_requests += 1
        self.failed_requests += 1
        self.quota_errors += 1
        self.last_quota_error = datetime.now()
        self.is_healthy = False
    
    def mark_failure(self):
        self.total_requests += 1
        self.failed_requests += 1


class TokenBucket:
    """
    Thread-safe token bucket rate limiter.
    
    Allows bursts up to capacity, then enforces rate limit.
    Tokens refill at a constant rate.
    """
    
    def __init__(self, rate: float, capacity: int):
        """
        Args:
            rate: Tokens to add per second (e.g., 20/60 = 0.333 for 20/min)
            capacity: Maximum tokens in bucket (burst allowance)
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = float(capacity)
        self.last_refill = time.time()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 1) -> None:
        """Acquire tokens, blocking if necessary until tokens available."""
        async with self._lock:
            while self.tokens < tokens:
                # Refill tokens based on time elapsed
                now = time.time()
                elapsed = now - self.last_refill
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_refill = now
                
                if self.tokens < tokens:
                    # Calculate wait time
                    needed = tokens - self.tokens
                    wait_time = needed / self.rate
                    logger.debug(f"⏳ Rate limit: waiting {wait_time:.2f}s for {tokens} token(s)")
                    await asyncio.sleep(wait_time)
            
            # Consume tokens
            self.tokens -= tokens
            logger.debug(f"✓ Acquired {tokens} token(s), {self.tokens:.2f} remaining")


class GeminiRateLimitedClient:
    """
    Centralized Gemini API client with rate limiting and key rotation.
    
    This client ensures all Gemini API calls respect the provider's rate limits
    by using a token bucket algorithm. It also manages multiple API keys,
    rotating to healthy keys when quota is exhausted.
    
    Usage:
        client = GeminiRateLimitedClient(
            api_keys=["key1", "key2"],
            requests_per_minute=20
        )
        
        response = await client.generate_content(
            prompt="Explain quantum computing",
            temperature=0.7
        )
    """
    
    def __init__(
        self,
        api_keys: Optional[List[str]] = None,
        requests_per_minute: int = 20,
        model_name: str = "gemini-2.5-flash",
        max_retries: int = 3,
        base_retry_delay: float = 2.0
    ):
        """
        Initialize the rate-limited Gemini client.
        
        Args:
            api_keys: List of Gemini API keys (or None to load from env)
            requests_per_minute: Maximum requests allowed per minute
            model_name: Gemini model to use
            max_retries: Maximum retry attempts on transient errors
            base_retry_delay: Base delay for exponential backoff (seconds)
        """
        # Load API keys
        self.api_keys = api_keys or self._load_api_keys_from_env()
        if not self.api_keys:
            raise ValueError("No Gemini API keys provided or found in environment")
        
        self.model_name = model_name
        self.max_retries = max_retries
        self.base_retry_delay = base_retry_delay
        
        # Initialize rate limiter (token bucket)
        # rate = requests_per_minute / 60 seconds
        rate = requests_per_minute / 60.0
        capacity = min(requests_per_minute, 10)  # Allow small bursts
        self.rate_limiter = TokenBucket(rate=rate, capacity=capacity)
        
        # Track key health
        self.key_health: Dict[int, APIKeyHealth] = {
            i: APIKeyHealth(key_index=i) for i in range(len(self.api_keys))
        }
        self.current_key_index = 0
        
        # Metrics
        self.total_requests = 0
        self.total_429_errors = 0
        self.total_cache_hits = 0
        
        # Initialize first model
        self._current_model = None
        self._initialize_model()
        
        logger.info(f"✅ GeminiRateLimitedClient initialized:")
        logger.info(f"   - {len(self.api_keys)} API key(s) loaded")
        logger.info(f"   - Rate limit: {requests_per_minute} req/min")
        logger.info(f"   - Model: {model_name}")
    
    def _load_api_keys_from_env(self) -> List[str]:
        """Load API keys from environment variables."""
        keys = []
        
        # Load primary key first (GEMINI_API_KEY)
        primary_key = os.getenv("GEMINI_API_KEY")
        if primary_key:
            keys.append(primary_key)
            logger.debug("✓ Loaded GEMINI_API_KEY")
        
        # Load numbered backup keys (GEMINI_API_KEY_2, GEMINI_API_KEY_3, etc.)
        for i in range(2, 10):
            key = os.getenv(f"GEMINI_API_KEY_{i}")
            if key:
                keys.append(key)
                logger.debug(f"✓ Loaded GEMINI_API_KEY_{i}")
        
        if not keys:
            logger.warning("⚠️ No Gemini API keys found in environment")
        
        return keys
    
    def _initialize_model(self):
        """Initialize the Gemini model with the current API key."""
        try:
            genai.configure(api_key=self.api_keys[self.current_key_index])
            self._current_model = genai.GenerativeModel(self.model_name)
            logger.debug(f"Initialized model with key index {self.current_key_index}")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini model: {e}")
            raise
    
    def _get_next_healthy_key_index(self) -> Optional[int]:
        """Find the next healthy API key, or None if all are unhealthy."""
        # Try healthy keys first
        for i in range(len(self.api_keys)):
            if self.key_health[i].is_healthy:
                return i
        
        # If all unhealthy, reset health and try again
        logger.warning("⚠️ All API keys marked unhealthy, resetting health status")
        for health in self.key_health.values():
            health.is_healthy = True
        
        return 0  # Return first key
    
    def _rotate_to_next_key(self):
        """Rotate to the next healthy API key."""
        next_index = self._get_next_healthy_key_index()
        if next_index is None:
            raise RuntimeError("No healthy API keys available")
        
        if next_index != self.current_key_index:
            old_index = self.current_key_index
            self.current_key_index = next_index
            self._initialize_model()
            logger.warning(f"🔄 Rotated API key: {old_index} → {next_index}")
    
    async def generate_content(
        self,
        prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 8192,
        safety_settings: Optional[Dict] = None,
        priority: str = "normal"
    ) -> str:
        """
        Generate content using Gemini with rate limiting and retries.
        
        Args:
            prompt: The prompt to send to Gemini
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens in response
            safety_settings: Optional safety settings dict
            priority: "normal" or "urgent" (for future queue prioritization)
        
        Returns:
            Generated text content
        
        Raises:
            RuntimeError: If all retry attempts fail
        """
        # Default safety settings (permissive for educational content)
        if safety_settings is None:
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            }
        
        # Acquire rate limit token (may block)
        await self.rate_limiter.acquire(tokens=1)
        
        # Retry loop with exponential backoff
        for attempt in range(self.max_retries):
            try:
                self.total_requests += 1
                self.key_health[self.current_key_index].total_requests += 1
                
                # Configure generation
                generation_config = genai.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                )
                
                # Make API call
                logger.debug(f"📤 Gemini request (attempt {attempt + 1}/{self.max_retries}, prompt length: {len(prompt)} chars)")
                response = self._current_model.generate_content(
                    prompt,
                    generation_config=generation_config,
                    safety_settings=safety_settings
                )
                
                # Validate response
                if not response.parts or not response.text:
                    # Log more details about why response is empty
                    logger.warning(f"⚠️ Empty response details:")
                    logger.warning(f"   - response.parts: {response.parts}")
                    logger.warning(f"   - response.prompt_feedback: {response.prompt_feedback}")
                    if hasattr(response, 'candidates'):
                        logger.warning(f"   - candidates: {response.candidates}")
                    raise ValueError("Empty response from Gemini")
                
                # Success!
                self.key_health[self.current_key_index].mark_success()
                logger.debug(f"✅ Gemini response received ({len(response.text)} chars)")
                return response.text.strip()
            
            except Exception as e:
                error_msg = str(e).lower()
                
                # Check for quota/rate limit errors
                if any(keyword in error_msg for keyword in ["quota", "limit", "429", "exhausted", "rate"]):
                    self.total_429_errors += 1
                    self.key_health[self.current_key_index].mark_quota_error()
                    logger.warning(f"⚠️ Quota/rate limit error on key {self.current_key_index}: {e}")
                    
                    # Try rotating to next key
                    try:
                        self._rotate_to_next_key()
                        continue  # Retry immediately with new key
                    except RuntimeError:
                        # No healthy keys left
                        logger.error("❌ All API keys exhausted")
                        raise
                
                # Other errors
                self.key_health[self.current_key_index].mark_failure()
                logger.warning(f"⚠️ Gemini error (attempt {attempt + 1}): {e}")
                
                # Last attempt?
                if attempt == self.max_retries - 1:
                    raise RuntimeError(f"Gemini API failed after {self.max_retries} attempts: {e}")
                
                # Exponential backoff
                delay = self.base_retry_delay * (2 ** attempt)
                logger.debug(f"⏳ Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
        
        raise RuntimeError("Unexpected end of retry loop")
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics for monitoring."""
        return {
            "total_requests": self.total_requests,
            "total_429_errors": self.total_429_errors,
            "current_key_index": self.current_key_index,
            "keys_health": {
                i: {
                    "total": health.total_requests,
                    "success": health.successful_requests,
                    "failed": health.failed_requests,
                    "quota_errors": health.quota_errors,
                    "is_healthy": health.is_healthy
                }
                for i, health in self.key_health.items()
            }
        }
    
    def print_metrics(self):
        """Print metrics to logger."""
        metrics = self.get_metrics()
        logger.info("📊 Gemini Client Metrics:")
        logger.info(f"   Total requests: {metrics['total_requests']}")
        logger.info(f"   429 errors: {metrics['total_429_errors']}")
        logger.info(f"   Current key: {metrics['current_key_index']}")
        for i, health in metrics['keys_health'].items():
            logger.info(f"   Key {i}: {health['success']}/{health['total']} success, "
                       f"healthy={health['is_healthy']}")
