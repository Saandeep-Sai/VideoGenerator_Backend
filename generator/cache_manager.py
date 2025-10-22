"""
Simple file-based cache manager for LLM responses.

This module provides a lightweight caching layer for expensive LLM operations,
reducing API calls by storing and reusing previous responses.

Features:
- File-based storage (no external dependencies)
- Automatic cache expiration (TTL)
- LRU eviction when cache size limit reached
- Thread-safe operations
- Deterministic cache key generation
"""

import hashlib
import json
import os
import time
import logging
from pathlib import Path
from typing import Optional, Any, Dict
from dataclasses import dataclass
import threading

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Represents a single cache entry."""
    key: str
    value: Any
    created_at: float
    last_accessed: float
    hit_count: int = 0
    
    def is_expired(self, ttl_seconds: float) -> bool:
        """Check if entry has exceeded TTL."""
        return (time.time() - self.created_at) > ttl_seconds
    
    def touch(self):
        """Update last accessed time and increment hit count."""
        self.last_accessed = time.time()
        self.hit_count += 1


class CacheManager:
    """
    Simple file-based cache for LLM responses.
    
    Stores responses as JSON files in a cache directory.
    Implements LRU eviction and TTL-based expiration.
    
    Usage:
        cache = CacheManager(cache_dir="./cache", max_entries=1000, ttl_days=7)
        
        # Try to get cached response
        cached = cache.get("prompt_hash_key")
        if cached:
            return cached
        
        # Generate new response
        response = call_llm(prompt)
        
        # Store in cache
        cache.set("prompt_hash_key", response)
    """
    
    def __init__(
        self,
        cache_dir: str = "./cache",
        max_entries: int = 1000,
        ttl_days: int = 7
    ):
        """
        Initialize cache manager.
        
        Args:
            cache_dir: Directory to store cache files
            max_entries: Maximum number of cache entries (LRU eviction)
            ttl_days: Time-to-live in days for cache entries
        """
        self.cache_dir = Path(cache_dir)
        self.max_entries = max_entries
        self.ttl_seconds = ttl_days * 24 * 3600
        
        # Thread safety
        self._lock = threading.Lock()
        
        # Create cache directory
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Metadata file
        self.metadata_file = self.cache_dir / "_metadata.json"
        self.metadata: Dict[str, Dict] = self._load_metadata()
        
        # Stats
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        
        logger.info(f"✅ CacheManager initialized:")
        logger.info(f"   - Cache dir: {self.cache_dir}")
        logger.info(f"   - Max entries: {max_entries}")
        logger.info(f"   - TTL: {ttl_days} days")
        logger.info(f"   - Current entries: {len(self.metadata)}")
    
    def _load_metadata(self) -> Dict[str, Dict]:
        """Load cache metadata from disk."""
        if not self.metadata_file.exists():
            return {}
        
        try:
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load cache metadata: {e}")
            return {}
    
    def _save_metadata(self):
        """Save cache metadata to disk."""
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save cache metadata: {e}")
    
    def _get_cache_file_path(self, key: str) -> Path:
        """Get the file path for a cache key."""
        # Use first 2 chars for subdirectory to avoid too many files in one dir
        subdir = key[:2]
        cache_subdir = self.cache_dir / subdir
        cache_subdir.mkdir(exist_ok=True)
        return cache_subdir / f"{key}.json"
    
    def _evict_lru_entries(self):
        """Evict least recently used entries if cache is full."""
        if len(self.metadata) < self.max_entries:
            return
        
        # Sort by last accessed time
        sorted_entries = sorted(
            self.metadata.items(),
            key=lambda x: x[1].get('last_accessed', 0)
        )
        
        # Remove oldest 10% of entries
        num_to_remove = max(1, len(self.metadata) // 10)
        for key, _ in sorted_entries[:num_to_remove]:
            self._remove_entry(key)
            self.evictions += 1
        
        logger.info(f"🗑️ Evicted {num_to_remove} LRU cache entries")
    
    def _remove_entry(self, key: str):
        """Remove a cache entry."""
        try:
            # Remove file
            cache_file = self._get_cache_file_path(key)
            if cache_file.exists():
                cache_file.unlink()
            
            # Remove from metadata
            if key in self.metadata:
                del self.metadata[key]
        except Exception as e:
            logger.warning(f"Failed to remove cache entry {key}: {e}")
    
    def _clean_expired_entries(self):
        """Remove expired cache entries."""
        now = time.time()
        expired_keys = [
            key for key, meta in self.metadata.items()
            if (now - meta.get('created_at', 0)) > self.ttl_seconds
        ]
        
        for key in expired_keys:
            self._remove_entry(key)
        
        if expired_keys:
            logger.info(f"🗑️ Cleaned {len(expired_keys)} expired cache entries")
    
    def generate_key(self, *args, **kwargs) -> str:
        """
        Generate a deterministic cache key from arguments.
        
        Args:
            *args: Positional arguments to hash
            **kwargs: Keyword arguments to hash
        
        Returns:
            64-character hex string (SHA256 hash)
        """
        # Create a stable string representation
        key_data = {
            'args': args,
            'kwargs': kwargs
        }
        key_str = json.dumps(key_data, sort_keys=True, default=str)
        
        # Hash it
        return hashlib.sha256(key_str.encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve value from cache.
        
        Args:
            key: Cache key (use generate_key() to create)
        
        Returns:
            Cached value if found and not expired, else None
        """
        with self._lock:
            # Check metadata
            if key not in self.metadata:
                self.misses += 1
                logger.debug(f"❌ Cache miss: {key[:16]}...")
                return None
            
            # Check expiration
            meta = self.metadata[key]
            if (time.time() - meta.get('created_at', 0)) > self.ttl_seconds:
                logger.debug(f"⏰ Cache expired: {key[:16]}...")
                self._remove_entry(key)
                self.misses += 1
                return None
            
            # Load from file
            try:
                cache_file = self._get_cache_file_path(key)
                if not cache_file.exists():
                    logger.warning(f"Cache file missing: {key[:16]}...")
                    del self.metadata[key]
                    self.misses += 1
                    return None
                
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Update access time
                self.metadata[key]['last_accessed'] = time.time()
                self.metadata[key]['hit_count'] = meta.get('hit_count', 0) + 1
                self._save_metadata()
                
                self.hits += 1
                logger.debug(f"✅ Cache hit: {key[:16]}... (hits: {self.metadata[key]['hit_count']})")
                return data.get('value')
            
            except Exception as e:
                logger.error(f"Failed to load cache entry {key[:16]}...: {e}")
                self.misses += 1
                return None
    
    def set(self, key: str, value: Any):
        """
        Store value in cache.
        
        Args:
            key: Cache key (use generate_key() to create)
            value: Value to cache (must be JSON-serializable)
        """
        with self._lock:
            try:
                # Evict if needed
                self._evict_lru_entries()
                
                # Save to file
                cache_file = self._get_cache_file_path(key)
                data = {
                    'key': key,
                    'value': value,
                    'created_at': time.time()
                }
                
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, default=str)
                
                # Update metadata
                self.metadata[key] = {
                    'created_at': time.time(),
                    'last_accessed': time.time(),
                    'hit_count': 0
                }
                self._save_metadata()
                
                logger.debug(f"💾 Cached: {key[:16]}... ({len(str(value))} chars)")
            
            except Exception as e:
                logger.error(f"Failed to save cache entry {key[:16]}...: {e}")
    
    def clear(self):
        """Clear all cache entries."""
        with self._lock:
            try:
                # Remove all cache files
                for cache_file in self.cache_dir.glob("*/*.json"):
                    cache_file.unlink()
                
                # Clear metadata
                self.metadata = {}
                self._save_metadata()
                
                logger.info("🗑️ Cache cleared")
            except Exception as e:
                logger.error(f"Failed to clear cache: {e}")
    
    def cleanup(self):
        """Run cleanup: remove expired entries."""
        with self._lock:
            self._clean_expired_entries()
            self._save_metadata()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{hit_rate:.1f}%",
            "entries": len(self.metadata),
            "max_entries": self.max_entries,
            "evictions": self.evictions
        }
    
    def print_stats(self):
        """Print cache statistics to logger."""
        stats = self.get_stats()
        logger.info("📊 Cache Statistics:")
        logger.info(f"   Hits: {stats['hits']}")
        logger.info(f"   Misses: {stats['misses']}")
        logger.info(f"   Hit rate: {stats['hit_rate']}")
        logger.info(f"   Entries: {stats['entries']}/{stats['max_entries']}")
        logger.info(f"   Evictions: {stats['evictions']}")
