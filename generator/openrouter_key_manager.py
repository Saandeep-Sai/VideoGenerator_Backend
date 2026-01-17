"""
OpenRouter API Key Manager with Automatic Rotation
Handles multiple API keys with automatic failover on quota/rate limit errors
"""

import logging
import os
from typing import List, Optional, Callable, Any, Dict
from datetime import datetime
from openai import OpenAI, RateLimitError, APIError

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Ensure DEBUG level logging


class OpenRouterKeyManager:
    """Manages multiple OpenRouter API keys with automatic rotation on failures"""
    
    def __init__(self, api_keys: Optional[List[str]] = None):
        """
        Initialize with list of API keys or load from environment
        
        Args:
            api_keys: List of OpenRouter API keys, or None to load from environment
        """
        self.api_keys = api_keys or self._load_keys_from_env()
        
        if not self.api_keys:
            raise ValueError("No OpenRouter API keys provided or found in environment")
        
        self.current_index = 0
        self.key_health = {
            i: {"failures": 0, "successes": 0, "last_used": None}
            for i in range(len(self.api_keys))
        }
        
        logger.info(f"✅ OpenRouterKeyManager initialized with {len(self.api_keys)} key(s)")
    
    def _load_keys_from_env(self) -> List[str]:
        """Load API keys from environment variables"""
        keys = []
        
        # Load primary key
        primary_key = os.getenv("OPENROUTER_API_KEY")
        if primary_key:
            keys.append(primary_key.strip().strip('"'))
            logger.info("✓ Loaded OPENROUTER_API_KEY")
        
        # Load additional numbered keys (_2, _3, _4, etc.)
        for i in range(2, 10):
            key_name = f"OPENROUTER_API_KEY_{i}"
            key_value = os.getenv(key_name)
            if key_value:
                keys.append(key_value.strip().strip('"'))
                logger.info(f"✓ Loaded {key_name}")
        
        if not keys:
            logger.warning("⚠️ No OPENROUTER_API_KEY* found in environment")
        
        return keys
    
    def get_current_key(self) -> str:
        """Get the current active API key"""
        return self.api_keys[self.current_index]
    
    def get_client(self, model: str = None) -> OpenAI:
        """
        Get OpenAI client configured for OpenRouter
        
        Args:
            model: Optional model name for reference
        """
        return OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.get_current_key(),
            max_retries=0,  # Disable automatic retries - we handle rotation manually
        )
    
    def rotate_key(self) -> None:
        """Rotate to the next API key"""
        old_index = self.current_index
        self.current_index = (self.current_index + 1) % len(self.api_keys)
        
        logger.warning(f"🔄 Rotated OpenRouter API key: {old_index} → {self.current_index}")
        
        # Update health tracking
        self.key_health[old_index]["failures"] += 1
        self.key_health[old_index]["last_used"] = datetime.now().isoformat()
    
    def mark_success(self) -> None:
        """Mark current key as successful"""
        self.key_health[self.current_index]["successes"] += 1
        self.key_health[self.current_index]["last_used"] = datetime.now().isoformat()
    
    def execute_with_rotation(
        self,
        func: Callable,
        max_total_retries: Optional[int] = None,
        model: str = None
    ) -> Any:
        """
        Execute a function with automatic key rotation on quota/rate limit errors
        
        Args:
            func: Function to execute (should accept 'client' parameter)
            max_total_retries: Maximum retries across all keys (default: 3 * num_keys)
            model: Model name for logging purposes
            
        Returns:
            Result from successful function execution
            
        Raises:
            Last exception if all keys exhausted
        """
        if max_total_retries is None:
            max_total_retries = len(self.api_keys) * 3
        
        logger.info(f"🔄 execute_with_rotation called with model={model}, max_retries={max_total_retries}")
        
        last_exception = None
        attempts = 0
        keys_tried = set()
        
        while attempts < max_total_retries:
            logger.info(f"🔄 Attempt {attempts+1}/{max_total_retries} with key index {self.current_index}")
            try:
                # Get client with current key
                client = self.get_client(model)
                
                # Execute function with client
                result = func(client)
                
                # Mark success
                self.mark_success()
                
                return result
                
            except Exception as e:
                error_str = str(e).lower()
                attempts += 1
                last_exception = e
                
                # DEBUG: Log exception details
                logger.debug(f"🔍 Exception type: {type(e).__name__}")
                logger.debug(f"🔍 Exception message: {str(e)[:300]}")
                logger.debug(f"🔍 Is RateLimitError: {isinstance(e, RateLimitError)}")
                logger.debug(f"🔍 Is APIError: {isinstance(e, APIError)}")
                if hasattr(e, 'status_code'):
                    logger.debug(f"🔍 Status code: {e.status_code}")
                
                # Check if this is a quota/rate limit error
                # OpenAI library throws RateLimitError for 429 status codes
                is_quota_error = (
                    isinstance(e, RateLimitError) or 
                    isinstance(e, APIError) and hasattr(e, 'status_code') and e.status_code == 429 or
                    any(term in error_str for term in [
                        "429", "quota", "rate limit", "resource_exhausted", 
                        "too many requests", "limit exceeded", "rate-limit"
                    ])
                )
                
                logger.debug(f"🔍 is_quota_error: {is_quota_error}")
                
                if is_quota_error:
                    current_key_index = self.current_index
                    keys_tried.add(current_key_index)
                    
                    # Extract rate limit info if available
                    rate_limit_info = ""
                    if hasattr(e, 'response') and hasattr(e.response, 'headers'):
                        headers = e.response.headers
                        remaining = headers.get('X-RateLimit-Remaining', 'unknown')
                        reset = headers.get('X-RateLimit-Reset', 'unknown')
                        rate_limit_info = f" (Remaining: {remaining}, Reset: {reset})"
                    
                    logger.warning(f"⚠️ Rate limit (429) on key {current_key_index}{rate_limit_info}")
                    logger.warning(f"   Error: {str(e)[:200]}")
                    
                    # Try rotating to next key
                    if len(keys_tried) < len(self.api_keys):
                        self.rotate_key()
                        logger.info(f"🔁 Retrying with key {self.current_index} (tried {len(keys_tried)}/{len(self.api_keys)} keys)...")
                        continue
                    else:
                        # All keys tried, reset and wait
                        logger.error(f"❌ All {len(self.api_keys)} keys exhausted quota")
                        self._reset_health()
                        keys_tried.clear()
                        
                        # One final retry after reset
                        if attempts < max_total_retries:
                            logger.info("⏳ Waiting before final retry...")
                            import time
                            time.sleep(2)
                            continue
                        else:
                            break
                else:
                    # Not a quota error - don't rotate, just fail
                    logger.error(f"❌ Non-quota error: {e}")
                    raise
        
        # All retries exhausted
        logger.error(f"❌ Failed after {attempts} attempts across all keys")
        raise last_exception
    
    def _reset_health(self) -> None:
        """Reset failure counts for all keys"""
        for key_index in self.key_health:
            self.key_health[key_index]["failures"] = 0
        logger.info("🔄 Reset health tracking for all keys")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics about key usage"""
        return {
            "total_keys": len(self.api_keys),
            "current_index": self.current_index,
            "health": self.key_health
        }
    
    def print_stats(self) -> None:
        """Print formatted statistics"""
        stats = self.get_stats()
        print(f"\n📊 OpenRouter Key Manager Stats:")
        print(f"   Total keys: {stats['total_keys']}")
        print(f"   Current key index: {stats['current_index']}")
        
        for i, health in stats['health'].items():
            status = "✅" if health['failures'] == 0 else "⚠️"
            print(f"   Key {i}: {status} {health['successes']} success, ❌ {health['failures']} failures")
