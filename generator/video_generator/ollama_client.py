"""
Ollama Cloud Correction Client
================================

Provider-agnostic client for Ollama Cloud models.
Primary: qwen3.5:397b-cloud (deterministic correction)
Secondary: gemma4:31b-cloud (fallback reasoning)

Uses the `ollama` Python library with Ollama Cloud endpoint.
"""

import os
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class OllamaCorrectionClient:
    """
    Ollama Cloud client with primary/secondary model failover.
    
    Qwen 3.5 handles: traceback repair, API fixes, minimal-diff patches.
    Gemma 4 handles: semantic reconstruction, difficult scene repair.
    """

    MODELS = {
        "primary": "qwen3-coder-next:cloud",       # Confirmed working on free tier
        "secondary": "gemma4:31b-cloud",       # Smaller Qwen variant (free)
    }

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OLLAMA_API_KEY")
        self._client = None

        if not self.api_key:
            logger.warning("⚠️ OLLAMA_API_KEY not set — correction client disabled")

    def _get_client(self):
        """Lazy-initialize the Ollama client."""
        if self._client is not None:
            return self._client

        if not self.api_key:
            raise RuntimeError("OLLAMA_API_KEY not set")

        try:
            from ollama import Client
            # Set the API key in environment for the client
            os.environ["OLLAMA_API_KEY"] = self.api_key
            self._client = Client(host="https://ollama.com")
            logger.info("✅ Ollama Cloud client initialized")
            return self._client
        except ImportError:
            raise RuntimeError("ollama package not installed. Run: pip install ollama")

    def correct(
        self,
        prompt: str,
        model: str = "primary",
        temperature: float = 0.1,
        max_retries: int = 2,
    ) -> Optional[str]:
        """
        Send a correction prompt to an Ollama Cloud model.
        
        Args:
            prompt: The correction prompt.
            model: "primary" (qwen3.5) or "secondary" (gemma4).
            temperature: Low for deterministic corrections.
            max_retries: Retry count on transient failures.
            
        Returns:
            Corrected code string, or None on failure.
        """
        model_name = self.MODELS.get(model, model)
        client = self._get_client()

        for attempt in range(max_retries + 1):
            try:
                response = client.chat(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": temperature},
                )

                content = response.message.content
                if not content or not content.strip():
                    logger.warning(
                        f"⚠️ {model_name} returned empty response "
                        f"(attempt {attempt + 1}/{max_retries + 1})"
                    )
                    if attempt < max_retries:
                        time.sleep(2)
                        continue
                    return None

                logger.info(
                    f"✅ {model_name} correction: {len(content)} chars"
                )
                return content.strip()

            except Exception as e:
                error_str = str(e).lower()
                is_transient = (
                    "timeout" in error_str
                    or "503" in error_str
                    or "429" in error_str
                    or "rate" in error_str
                    or "unavailable" in error_str
                    or "connection" in error_str
                )

                if is_transient and attempt < max_retries:
                    delay = 3 * (attempt + 1)
                    logger.warning(
                        f"⚠️ {model_name} transient error: {str(e)[:100]}. "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"❌ {model_name} failed: {e}")
                    return None

        return None

    def correct_with_fallback(self, prompt: str) -> Optional[str]:
        """
        Try primary (Qwen 3.5), fall back to secondary (Gemma 4).
        
        Returns corrected code or None if both fail.
        """
        # Try primary
        result = self.correct(prompt, model="primary")
        if result:
            return result

        # Fallback to secondary
        logger.info("🔄 Primary (Qwen) failed, falling back to Gemma 4...")
        result = self.correct(prompt, model="secondary")
        if result:
            return result

        logger.error("❌ Both Qwen and Gemma failed for correction")
        return None

    @property
    def is_available(self) -> bool:
        """Check if the client has an API key configured."""
        return bool(self.api_key)
