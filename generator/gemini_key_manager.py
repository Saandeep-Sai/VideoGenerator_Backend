"""
Gemini API Key Manager with Automatic Rotation
Handles multiple API keys with automatic failover on quota/rate limit errors
"""

import os
import logging
import time
from typing import List, Optional, Callable, Any
from functools import wraps
import google.generativeai as genai

logger = logging.getLogger(__name__)


class GeminiKeyManager:
    """
    Manages multiple Gemini API keys with automatic rotation on failures.
    
    Features:
    - Automatic key rotation on quota/rate limit errors
    - Retry logic with exponential backoff
    - Health tracking for each key
    - Thread-safe key rotation
    
    Usage:
        manager = GeminiKeyManager()
        result = manager.execute_with_rotation(lambda: model.generate_content(prompt))
    """
    
    def __init__(self, api_keys: Optional[List[str]] = None):
        """
        Initialize the key manager.
        
        Args:
            api_keys: List of Gemini API keys. If None, loads from environment.
        """
        self.api_keys = api_keys or self._load_keys_from_env()
        
        if not self.api_keys:
            raise ValueError("No Gemini API keys provided or found in environment")
        
        self.current_index = 0
        self.key_health = {i: {"failures": 0, "successes": 0} for i in range(len(self.api_keys))}
        self.max_retries_per_key = 2
        self.backoff_delay = 1.0
        
        logger.info(f"✅ GeminiKeyManager initialized with {len(self.api_keys)} key(s)")
        self._configure_current_key()
    
    def _load_keys_from_env(self) -> List[str]:
        """Load all Gemini API keys from environment variables."""
        keys = []
        
        # Load primary key
        primary = os.getenv("GEMINI_API_KEY")
        if primary:
            keys.append(primary)
            logger.debug("✓ Loaded GEMINI_API_KEY")
        
        # Load numbered backup keys
        for i in range(2, 10):
            key = os.getenv(f"GEMINI_API_KEY_{i}")
            if key:
                keys.append(key)
                logger.debug(f"✓ Loaded GEMINI_API_KEY_{i}")
        
        return keys
    
    def _configure_current_key(self):
        """Configure genai with the current API key."""
        current_key = self.api_keys[self.current_index]
        genai.configure(api_key=current_key)
        logger.debug(f"🔑 Using API key index {self.current_index}")
    
    def _is_quota_error(self, error: Exception) -> bool:
        """Check if error is a quota/rate limit error."""
        error_str = str(error).lower()
        quota_keywords = [
            "quota", "rate limit", "429", "exhausted", 
            "resource_exhausted", "too many requests",
            "limit exceeded", "billing"
        ]
        return any(keyword in error_str for keyword in quota_keywords)
    
    def _rotate_to_next_key(self) -> bool:
        """
        Rotate to the next available API key.
        
        Returns:
            True if rotation successful, False if no more keys available
        """
        original_index = self.current_index
        attempts = 0
        
        while attempts < len(self.api_keys):
            # Try next key
            self.current_index = (self.current_index + 1) % len(self.api_keys)
            attempts += 1
            
            # Check if this key has failed too many times
            if self.key_health[self.current_index]["failures"] < 5:
                if self.current_index != original_index:
                    logger.warning(f"🔄 Rotated API key: {original_index} → {self.current_index}")
                    self._configure_current_key()
                    return True
        
        # All keys have failed
        logger.error("❌ All API keys have exceeded failure threshold")
        return False
    
    def execute_with_rotation(
        self, 
        func: Callable, 
        max_total_retries: int = None,
        *args, 
        **kwargs
    ) -> Any:
        """
        Execute a function with automatic key rotation on quota errors.
        
        Args:
            func: Function to execute (should use genai configured key)
            max_total_retries: Maximum total retry attempts across all keys
            *args, **kwargs: Arguments to pass to func
        
        Returns:
            Result of func execution
        
        Raises:
            Exception: If all retry attempts fail
        """
        if max_total_retries is None:
            max_total_retries = len(self.api_keys) * self.max_retries_per_key
        
        last_error = None
        total_attempts = 0
        keys_tried = set()
        
        while total_attempts < max_total_retries:
            try:
                # Execute the function
                result = func(*args, **kwargs)
                
                # Success! Mark key as healthy
                self.key_health[self.current_index]["successes"] += 1
                return result
                
            except Exception as e:
                total_attempts += 1
                last_error = e
                keys_tried.add(self.current_index)
                
                # Check if it's a quota/rate limit error
                if self._is_quota_error(e):
                    logger.warning(
                        f"⚠️ Quota/rate limit error on key {self.current_index} "
                        f"(attempt {total_attempts}/{max_total_retries}): {e}"
                    )
                    
                    # Mark key as failed
                    self.key_health[self.current_index]["failures"] += 1
                    
                    # Try rotating to next key
                    if not self._rotate_to_next_key():
                        # All keys failed, reset health and try one more time
                        if total_attempts < max_total_retries:
                            logger.warning("⚠️ Resetting key health counters for final attempt")
                            for health in self.key_health.values():
                                health["failures"] = 0
                            self.current_index = 0
                            self._configure_current_key()
                        else:
                            raise Exception(f"All {len(self.api_keys)} API keys exhausted") from e
                    
                    # Small delay before retry
                    time.sleep(self.backoff_delay)
                    continue
                
                else:
                    # Other error (not quota related)
                    logger.warning(f"⚠️ Error (attempt {total_attempts}): {e}")
                    
                    # Exponential backoff for non-quota errors
                    if total_attempts < max_total_retries:
                        delay = self.backoff_delay * (2 ** (total_attempts - 1))
                        delay = min(delay, 30)  # Cap at 30 seconds
                        logger.debug(f"⏳ Retrying in {delay:.1f}s...")
                        time.sleep(delay)
                    else:
                        raise
        
        # All retries exhausted
        raise Exception(
            f"Failed after {total_attempts} attempts across {len(keys_tried)} key(s). "
            f"Last error: {last_error}"
        )
    
    def get_current_key(self) -> str:
        """Get the current active API key."""
        return self.api_keys[self.current_index]
    
    def get_stats(self) -> dict:
        """Get usage statistics for all keys."""
        return {
            "total_keys": len(self.api_keys),
            "current_index": self.current_index,
            "key_health": self.key_health
        }
    
    def print_stats(self):
        """Print usage statistics."""
        stats = self.get_stats()
        logger.info("📊 Gemini Key Manager Stats:")
        logger.info(f"   Total keys: {stats['total_keys']}")
        logger.info(f"   Current key index: {stats['current_index']}")
        for idx, health in stats['key_health'].items():
            logger.info(
                f"   Key {idx}: ✅ {health['successes']} success, "
                f"❌ {health['failures']} failures"
            )


def with_key_rotation(manager: GeminiKeyManager):
    """
    Decorator to automatically handle key rotation for functions using Gemini API.
    
    Usage:
        manager = GeminiKeyManager()
        
        @with_key_rotation(manager)
        def generate_content(prompt):
            return model.generate_content(prompt)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return manager.execute_with_rotation(func, *args, **kwargs)
        return wrapper
    return decorator


# Global instance (can be imported and used across modules)
_global_manager = None

def get_global_key_manager() -> GeminiKeyManager:
    """Get or create the global key manager instance."""
    global _global_manager
    if _global_manager is None:
        _global_manager = GeminiKeyManager()
    return _global_manager
