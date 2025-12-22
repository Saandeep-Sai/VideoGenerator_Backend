"""
Utility to add Gemini API key rotation to VideoGenerationConfig
Monkey-patches the config to support multiple keys with automatic rotation
"""

import os
import logging
from typing import List
from generator.gemini_key_manager import GeminiKeyManager

logger = logging.getLogger(__name__)


def setup_key_rotation_for_config(config, api_keys: List[str] = None):
    """
    Add key rotation support to a VideoGenerationConfig instance.
    
    This creates a GeminiKeyManager and makes it available to the config.
    The video generator can then use this for automatic key rotation.
    
    Args:
        config: VideoGenerationConfig instance
        api_keys: List of API keys (optional, loads from env if not provided)
    
    Returns:
        Modified config with key_manager attribute
    """
    if not hasattr(config, 'key_manager'):
        if api_keys:
            config.key_manager = GeminiKeyManager(api_keys=api_keys)
        else:
            config.key_manager = GeminiKeyManager()
        
        logger.info(f"✅ Added key rotation to config ({config.key_manager.get_stats()['total_keys']} keys)")
    
    return config


def get_all_gemini_keys_from_env() -> List[str]:
    """
    Load all Gemini API keys from environment variables.
    
    Returns:
        List of API keys in order: GEMINI_API_KEY, GEMINI_API_KEY_2, etc.
    """
    keys = []
    
    # Load primary key
    primary = os.getenv("GEMINI_API_KEY")
    if primary:
        keys.append(primary)
    
    # Load numbered keys
    for i in range(2, 10):
        key = os.getenv(f"GEMINI_API_KEY_{i}")
        if key:
            keys.append(key)
    
    return keys
