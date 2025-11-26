#!/usr/bin/env python3
"""
Resource Monitor for E2.Micro Instances
Prevents system overload during video generation
"""

import psutil
import logging
import time
import gc
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class ResourceMonitor:
    """Monitor system resources and prevent overload on E2.Micro instances."""
    
    def __init__(self):
        self.memory_threshold = 85  # Stop at 85% memory usage
        self.cpu_threshold = 90     # Stop at 90% CPU usage
        self.check_interval = 5     # Check every 5 seconds
        
    def get_system_stats(self) -> Dict[str, float]:
        """Get current system resource usage."""
        try:
            memory = psutil.virtual_memory()
            cpu_percent = psutil.cpu_percent(interval=1)
            
            return {
                'memory_percent': memory.percent,
                'memory_available_mb': memory.available / 1024 / 1024,
                'cpu_percent': cpu_percent,
                'load_average': psutil.getloadavg()[0] if hasattr(psutil, 'getloadavg') else 0
            }
        except Exception as e:
            logger.error(f"❌ Failed to get system stats: {e}")
            return {
                'memory_percent': 50,
                'memory_available_mb': 500,
                'cpu_percent': 50,
                'load_average': 1.0
            }
    
    def is_system_overloaded(self) -> tuple[bool, str]:
        """Check if system is overloaded."""
        stats = self.get_system_stats()
        
        if stats['memory_percent'] > self.memory_threshold:
            return True, f"Memory usage too high: {stats['memory_percent']:.1f}%"
        
        if stats['cpu_percent'] > self.cpu_threshold:
            return True, f"CPU usage too high: {stats['cpu_percent']:.1f}%"
        
        if stats['memory_available_mb'] < 100:
            return True, f"Available memory too low: {stats['memory_available_mb']:.1f}MB"
        
        return False, "System OK"
    
    def wait_for_resources(self, max_wait: int = 300) -> bool:
        """Wait for system resources to become available."""
        logger.info("⏳ Waiting for system resources...")
        
        start_time = time.time()
        while time.time() - start_time < max_wait:
            overloaded, reason = self.is_system_overloaded()
            
            if not overloaded:
                logger.info("✅ System resources available")
                return True
            
            logger.warning(f"⚠️ System overloaded: {reason}")
            logger.info("🧹 Forcing garbage collection...")
            gc.collect()
            
            time.sleep(self.check_interval)
        
        logger.error(f"❌ System still overloaded after {max_wait}s")
        return False
    
    def log_system_status(self):
        """Log current system status."""
        stats = self.get_system_stats()
        logger.info(f"📊 System Status:")
        logger.info(f"   Memory: {stats['memory_percent']:.1f}% ({stats['memory_available_mb']:.0f}MB available)")
        logger.info(f"   CPU: {stats['cpu_percent']:.1f}%")
        logger.info(f"   Load: {stats['load_average']:.2f}")
    
    def cleanup_memory(self):
        """Force memory cleanup."""
        logger.info("🧹 Cleaning up memory...")
        gc.collect()
        
        # Additional cleanup for Python
        import sys
        if hasattr(sys, '_clear_type_cache'):
            sys._clear_type_cache()
        
        logger.info("✅ Memory cleanup complete")

# Global instance
resource_monitor = ResourceMonitor()