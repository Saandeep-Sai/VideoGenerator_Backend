"""
Smart Topic Selector
====================

Selects topics based on analytics data, not just trends.
Uses viewership data to prioritize topic clusters that perform well.

The loop:
1. Analyze past video performance by topic cluster
2. Identify high-performing clusters (good retention, returning viewers)
3. Prioritize topics from those clusters
4. Mix in exploration (new clusters) for discovery
5. Avoid declining clusters

This closes the feedback loop:
Upload Video → Track Analytics → Learn What Works → Generate Better Topics
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
import random

# Load env
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

# Local imports
try:
    from .integrated_analytics import get_analytics_service, IntegratedAnalyticsService
    from .firestore_schema import VideoStatus
except ImportError:
    from analytics.integrated_analytics import get_analytics_service, IntegratedAnalyticsService
    from analytics.firestore_schema import VideoStatus

logger = logging.getLogger(__name__)


# =============================================================================
# TOPIC CLUSTER PERFORMANCE
# =============================================================================

@dataclass
class ClusterPerformance:
    """Performance metrics for a topic cluster."""
    cluster_name: str
    video_count: int
    avg_views: float
    avg_retention: float
    avg_engagement: float  # likes + comments per view
    trend: str  # "rising", "stable", "declining"
    priority_score: float  # 0-1, higher = better to make more content
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster": self.cluster_name,
            "videos": self.video_count,
            "avg_views": self.avg_views,
            "avg_retention": self.avg_retention,
            "trend": self.trend,
            "priority": self.priority_score
        }


class TopicClusterAnalyzer:
    """Analyzes topic cluster performance from analytics data."""
    
    def __init__(self, analytics_service: Optional[IntegratedAnalyticsService] = None):
        self.analytics = analytics_service or get_analytics_service()
    
    def get_cluster_performance(self) -> List[ClusterPerformance]:
        """
        Analyze all topic clusters and return their performance.
        
        Returns list sorted by priority (best clusters first).
        """
        if not self.analytics._db:
            logger.warning("No Firestore, using mock cluster data")
            return self._mock_cluster_performance()
        
        try:
            # Get all tracked videos
            docs = (
                self.analytics._db.collection(self.analytics.config.collection_name)
                .where("status", "==", VideoStatus.ACTIVE.value)
                .get()
            )
            
            # Group by cluster
            clusters: Dict[str, List[Dict]] = {}
            for doc in docs:
                data = doc.to_dict()
                cluster = data.get("topic_cluster", "general")
                if cluster not in clusters:
                    clusters[cluster] = []
                clusters[cluster].append(data)
            
            # Calculate performance for each cluster
            performances = []
            for cluster_name, videos in clusters.items():
                perf = self._calculate_cluster_performance(cluster_name, videos)
                performances.append(perf)
            
            # Sort by priority (highest first)
            performances.sort(key=lambda p: p.priority_score, reverse=True)
            
            return performances
            
        except Exception as e:
            logger.error(f"Failed to analyze clusters: {e}")
            return self._mock_cluster_performance()
    
    def _calculate_cluster_performance(
        self, 
        cluster_name: str, 
        videos: List[Dict]
    ) -> ClusterPerformance:
        """Calculate performance metrics for a cluster."""
        
        if not videos:
            return ClusterPerformance(
                cluster_name=cluster_name,
                video_count=0,
                avg_views=0,
                avg_retention=0,
                avg_engagement=0,
                trend="unknown",
                priority_score=0.3  # Low priority for empty clusters
            )
        
        # Calculate averages
        total_views = sum(v.get("metrics", {}).get("views_total", 0) for v in videos)
        total_retention = sum(v.get("metrics", {}).get("avg_view_percentage", 0) for v in videos)
        
        avg_views = total_views / len(videos)
        avg_retention = total_retention / len(videos)
        
        # Calculate engagement rate
        total_likes = sum(v.get("metrics", {}).get("likes", 0) for v in videos)
        total_comments = sum(v.get("metrics", {}).get("comments", 0) for v in videos)
        avg_engagement = (total_likes + total_comments) / max(1, total_views) * 100
        
        # Determine trend (compare recent vs older videos)
        trend = self._calculate_trend(videos)
        
        # Calculate priority score (0-1)
        # Weight: retention (50%), engagement (30%), views (20%)
        retention_score = min(avg_retention / 100, 1.0)  # 100% retention = 1.0
        engagement_score = min(avg_engagement / 5, 1.0)  # 5% engagement = 1.0
        views_score = min(avg_views / 5000, 1.0)  # 5000 views = 1.0
        
        # Trend modifier
        trend_modifier = {"rising": 1.2, "stable": 1.0, "declining": 0.7}.get(trend, 1.0)
        
        priority_score = (
            retention_score * 0.5 +
            engagement_score * 0.3 +
            views_score * 0.2
        ) * trend_modifier
        
        # Clamp to 0-1
        priority_score = max(0, min(1, priority_score))
        
        return ClusterPerformance(
            cluster_name=cluster_name,
            video_count=len(videos),
            avg_views=avg_views,
            avg_retention=avg_retention,
            avg_engagement=avg_engagement,
            trend=trend,
            priority_score=priority_score
        )
    
    def _calculate_trend(self, videos: List[Dict]) -> str:
        """Calculate trend based on recent vs older video performance."""
        if len(videos) < 2:
            return "unknown"
        
        # Sort by publish date
        sorted_videos = sorted(
            videos, 
            key=lambda v: v.get("published_at", ""),
            reverse=True
        )
        
        # Compare recent half vs older half
        mid = len(sorted_videos) // 2
        recent = sorted_videos[:mid]
        older = sorted_videos[mid:]
        
        recent_retention = sum(
            v.get("metrics", {}).get("avg_view_percentage", 0) for v in recent
        ) / len(recent)
        
        older_retention = sum(
            v.get("metrics", {}).get("avg_view_percentage", 0) for v in older
        ) / len(older)
        
        if recent_retention > older_retention * 1.1:
            return "rising"
        elif recent_retention < older_retention * 0.9:
            return "declining"
        else:
            return "stable"
    
    def _mock_cluster_performance(self) -> List[ClusterPerformance]:
        """Return mock performance data for testing."""
        return [
            ClusterPerformance("python", 10, 2500, 65.0, 2.5, "rising", 0.75),
            ClusterPerformance("javascript", 8, 2000, 58.0, 2.0, "stable", 0.60),
            ClusterPerformance("web", 12, 1800, 52.0, 1.8, "stable", 0.50),
            ClusterPerformance("devops", 5, 3000, 70.0, 3.0, "rising", 0.80),
            ClusterPerformance("algorithms", 3, 1200, 45.0, 1.5, "declining", 0.35),
        ]


# =============================================================================
# SMART TOPIC SELECTOR
# =============================================================================

class SmartTopicSelector:
    """
    Selects topics based on analytics-driven cluster priorities.
    
    Strategy:
    - 60% from high-priority clusters (what's working)
    - 25% from medium-priority clusters (maintain breadth)
    - 15% exploration (new/underperforming clusters for discovery)
    """
    
    def __init__(self):
        self.analyzer = TopicClusterAnalyzer()
        self._cluster_cache = None
        self._cache_time = None
        self._cache_duration_seconds = 3600  # Refresh every hour
    
    def get_cluster_priorities(self, force_refresh: bool = False) -> List[ClusterPerformance]:
        """Get cluster priorities, with caching."""
        now = datetime.now(timezone.utc)
        
        if (force_refresh or 
            self._cluster_cache is None or 
            self._cache_time is None or
            (now - self._cache_time).total_seconds() > self._cache_duration_seconds):
            
            self._cluster_cache = self.analyzer.get_cluster_performance()
            self._cache_time = now
            logger.info(f"Refreshed cluster priorities: {len(self._cluster_cache)} clusters")
        
        return self._cluster_cache
    
    def select_cluster_for_next_video(self) -> str:
        """
        Select which topic cluster to focus on for the next video.
        
        Returns cluster name based on weighted selection.
        """
        clusters = self.get_cluster_priorities()
        
        if not clusters:
            return "general"
        
        # Categorize clusters
        high_priority = [c for c in clusters if c.priority_score >= 0.6]
        medium_priority = [c for c in clusters if 0.3 <= c.priority_score < 0.6]
        low_priority = [c for c in clusters if c.priority_score < 0.3]
        
        # Weighted random selection
        roll = random.random()
        
        if roll < 0.60 and high_priority:
            # 60% chance: pick from high priority
            selected = self._weighted_select(high_priority)
            logger.info(f"Selected HIGH priority cluster: {selected}")
            return selected
        elif roll < 0.85 and medium_priority:
            # 25% chance: pick from medium priority
            selected = self._weighted_select(medium_priority)
            logger.info(f"Selected MEDIUM priority cluster: {selected}")
            return selected
        elif low_priority:
            # 15% chance: exploration (pick from low priority or random)
            selected = random.choice(low_priority).cluster_name
            logger.info(f"EXPLORATION: selected low priority cluster: {selected}")
            return selected
        else:
            # Fallback to any available
            selected = random.choice(clusters).cluster_name
            logger.info(f"Fallback selection: {selected}")
            return selected
    
    def _weighted_select(self, clusters: List[ClusterPerformance]) -> str:
        """Select cluster weighted by priority score."""
        total_weight = sum(c.priority_score for c in clusters)
        if total_weight == 0:
            return random.choice(clusters).cluster_name
        
        roll = random.uniform(0, total_weight)
        cumulative = 0
        
        for cluster in clusters:
            cumulative += cluster.priority_score
            if roll <= cumulative:
                return cluster.cluster_name
        
        return clusters[-1].cluster_name
    
    def get_topic_suggestions_for_cluster(self, cluster: str) -> List[str]:
        """Get topic suggestions for a specific cluster."""
        
        # Cluster-specific topic banks
        cluster_topics = {
            "python": [
                "Python List Comprehensions Explained",
                "Python Decorators in 60 Seconds",
                "Why Python's GIL Matters",
                "Python Virtual Environments Simplified",
                "Python Error Handling Best Practices",
                "Python Dictionary Tricks You Need",
                "Async Python Made Simple",
                "Python F-Strings Advanced Usage",
            ],
            "javascript": [
                "JavaScript Closures Finally Explained",
                "Promise vs Async Await",
                "JavaScript Event Loop Simplified",
                "Why Use TypeScript in 2025",
                "React Hooks Every Dev Needs",
                "JavaScript Array Methods Cheatsheet",
                "Node.js vs Deno vs Bun",
                "JavaScript Memory Leaks to Avoid",
            ],
            "web": [
                "CSS Grid vs Flexbox Decision Guide",
                "Why Your Website is Slow",
                "Responsive Design in 60 Seconds",
                "Web Accessibility Basics",
                "HTTPS Explained Simply",
                "Browser DevTools Tricks",
                "Progressive Web Apps Explained",
                "Web Performance Optimization Tips",
            ],
            "devops": [
                "Docker Containers vs VMs",
                "Kubernetes Explained Simply",
                "CI/CD Pipeline Basics",
                "Infrastructure as Code Intro",
                "Terraform vs Ansible",
                "Monitoring with Prometheus",
                "GitHub Actions Tutorial",
                "DevOps Best Practices 2025",
            ],
            "database": [
                "SQL vs NoSQL Decision Guide",
                "Database Indexing Explained",
                "PostgreSQL vs MySQL",
                "MongoDB Basics for Beginners",
                "Redis Cache Explained",
                "Database Normalization Simply",
                "Connection Pooling Explained",
                "Database Transactions Simplified",
            ],
            "algorithms": [
                "Big O Notation Made Simple",
                "Binary Search in 60 Seconds",
                "Hash Tables Explained",
                "Recursion vs Iteration",
                "Sorting Algorithms Compared",
                "Graph Algorithms Basics",
                "Dynamic Programming Intro",
                "Time Complexity Explained",
            ],
            "general": [
                "How to Get Your First Dev Job",
                "Technical Interview Tips",
                "Code Review Best Practices",
                "Clean Code Principles",
                "SOLID Principles Explained",
                "Design Patterns Overview",
                "Technical Debt Explained",
                "Debugging Tips for Beginners",
            ]
        }
        
        return cluster_topics.get(cluster, cluster_topics["general"])
    
    def get_next_topic_suggestion(self, used_topics: set = None) -> Tuple[str, str]:
        """
        Get the next topic suggestion based on analytics.
        Filters out recently used topics to prevent repeats.
        
        Args:
            used_topics: Set of recently used topic strings (lowercase).
        
        Returns:
            Tuple of (cluster_name, suggested_topic)
        """
        cluster = self.select_cluster_for_next_video()
        suggestions = self.get_topic_suggestions_for_cluster(cluster)
        
        # Filter out used topics (exact + semantic similarity)
        if used_topics:
            available = [
                s for s in suggestions
                if s.lower().strip() not in used_topics
                and not _is_topic_similar(s, used_topics)
            ]
            if available:
                suggestions = available
            else:
                logger.warning(f"⚠️ All topics in cluster '{cluster}' already used, picking least similar")
        
        topic = random.choice(suggestions)
        return cluster, topic
    
    def get_analytics_summary(self) -> Dict[str, Any]:
        """Get a summary of cluster analytics for dashboard."""
        clusters = self.get_cluster_priorities()
        
        return {
            "total_clusters": len(clusters),
            "clusters": [c.to_dict() for c in clusters],
            "recommendation": self.select_cluster_for_next_video(),
            "strategy": {
                "high_priority": "60% of content",
                "medium_priority": "25% of content",
                "exploration": "15% of content"
            }
        }


# =============================================================================
# INTEGRATION WITH CONTENT GENERATOR
# =============================================================================

def _is_topic_similar(candidate: str, used_topics: set, threshold: float = 0.6) -> bool:
    """
    Check if a candidate topic is semantically similar to any used topic
    using Jaccard word-overlap similarity.
    
    Catches near-duplicates like:
      "Python Decorators Explained" vs "Understanding Python Decorators in 60s"
    
    Args:
        candidate: The new topic string to check.
        used_topics: Set of previously used topic strings (lowercase).
        threshold: Similarity threshold (0.0-1.0). Default 0.6.
    
    Returns:
        True if the candidate is too similar to any used topic.
    """
    # Normalize: lowercase, strip, remove common filler words
    stop_words = {
        "in", "the", "a", "an", "of", "for", "to", "and", "is", "are",
        "was", "with", "on", "at", "by", "from", "how", "what", "why",
        "this", "that", "it", "you", "your", "60s", "seconds", "explained",
        "understanding", "quick", "guide", "tutorial", "learn", "about",
    }
    
    def tokenize(text: str) -> set:
        words = set(text.lower().strip().split())
        return words - stop_words
    
    candidate_words = tokenize(candidate)
    if not candidate_words:
        return False
    
    for used in used_topics:
        used_words = tokenize(used)
        if not used_words:
            continue
        
        # Jaccard similarity = |intersection| / |union|
        intersection = candidate_words & used_words
        union = candidate_words | used_words
        similarity = len(intersection) / len(union) if union else 0
        
        if similarity >= threshold:
            logger.debug(
                f"Topic '{candidate}' similar to '{used}' "
                f"(Jaccard={similarity:.2f} >= {threshold})"
            )
            return True
    
    return False

def get_smart_topic_from_clusters(used_topics: set = None) -> str:
    """Get topic from cluster analytics with dedup filtering."""
    if used_topics is None:
        used_topics = _load_used_topics(days=30)
    selector = SmartTopicSelector()
    cluster, topic = selector.get_next_topic_suggestion(used_topics=used_topics)
    logger.info(f"Cluster-based topic: [{cluster}] {topic}")
    return topic


def get_prioritized_cluster() -> str:
    """Get the highest priority cluster for next video."""
    selector = SmartTopicSelector()
    return selector.select_cluster_for_next_video()


def _load_winning_patterns() -> list:
    """Load winning patterns from file."""
    import json
    patterns_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                  "winning_patterns.json")
    try:
        if os.path.exists(patterns_path):
            with open(patterns_path, 'r') as f:
                data = json.load(f)
                return data.get("winners", [])
    except Exception as e:
        logger.debug(f"Could not load winning patterns: {e}")
    return []


def _load_used_topics(days: int = 30) -> set:
    """Load recently used topics from history file."""
    import json
    from datetime import timedelta
    
    history_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "youtube_shorts_history.json")
    used = set()
    try:
        if os.path.exists(history_path):
            with open(history_path, 'r') as f:
                history = json.load(f)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            for topic, ts in history.items():
                try:
                    t = datetime.fromisoformat(ts)
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                    if t > cutoff:
                        used.add(topic.lower().strip())
                except (ValueError, TypeError):
                    used.add(topic.lower().strip())
    except Exception as e:
        logger.debug(f"Could not load topic history: {e}")
    return used


def get_smart_topic() -> str:
    """
    Get a smart topic using trending-NOW generation + winning patterns feedback.
    
    Strategy:
    1. Load winning title patterns from past performance
    2. Ask Gemini for a trending tech topic RIGHT NOW
    3. Cross-reference against used topics to avoid repeats
    4. Fall back to cluster-based selection if Gemini fails
    """
    import json
    
    # Load context
    winners = _load_winning_patterns()
    used_topics = _load_used_topics(days=30)
    
    # Build winning context for Gemini
    winning_context = ""
    if winners:
        winner_titles = [w["title"] for w in winners[:8]]
        winning_context = f"""
These recent video titles performed BEST with our audience:
{chr(10).join(f'  - "{t}"' for t in winner_titles)}

Generate a topic that follows similar ENERGY and patterns — but on a DIFFERENT subject."""

    # Build exclusion list
    exclusion_text = ""
    if used_topics:
        recent = list(used_topics)[:50]  # Send full exclusion list (was [:15] — too few)
        exclusion_text = f"""
DO NOT generate anything similar to these recently covered topics:
{chr(10).join(f'  - {t}' for t in recent)}"""

    prompt = f"""You are a YouTube Shorts content strategist for a programming/tech channel called "Code Tapasya".

Generate ONE specific topic for a 60-second YouTube Short that is:
1. TRENDING RIGHT NOW in tech/programming (March 2026)
2. Highly searchable — something developers are actively Googling
3. Perfect for a punchy, scroll-stopping 60-second explainer
4. Beginner to intermediate level

{winning_context}
{exclusion_text}

THINK about what's hot in tech RIGHT NOW:
- New framework releases, language updates, AI tool launches
- Viral dev debates (tabs vs spaces, is X dead, etc.)
- Emerging trends that developers are buzzing about
- Security incidents or breaking changes developers need to know about

OUTPUT: Return ONLY the topic title. Make it specific, curiosity-driven, and click-worthy.
Example good outputs:
"Why Every Developer is Switching to Bun in 2026"
"The AI Coding Tool That's Replacing Stack Overflow"
"This New CSS Feature Makes Flexbox Obsolete"

Your topic:"""

    # Try Gemini for trending topic
    try:
        from google import genai
        from google.genai import types
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("No GEMINI_API_KEY")
        
        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(temperature=0.8, max_output_tokens=200)
        
        for attempt in range(3):
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config=config
            )
            
            if response and response.text:
                topic = response.text.strip().replace('"', '').replace("'", "")
                # Check exact match AND semantic similarity
                if topic.lower().strip() in used_topics:
                    logger.warning(f"⚠️ Trending topic '{topic}' already used (exact match), retrying...")
                elif _is_topic_similar(topic, used_topics):
                    logger.warning(f"⚠️ Trending topic '{topic}' too similar to used topic, retrying...")
                else:
                    logger.info(f"🔥 Trending topic: {topic}")
                    return topic
        
        logger.warning("⚠️ Trending generation exhausted, falling back to clusters")
    except Exception as e:
        logger.warning(f"⚠️ Trending topic generation failed: {e}, falling back to clusters")
    
    # Fallback to cluster-based selection (pass used_topics for filtering)
    return get_smart_topic_from_clusters(used_topics=used_topics)


def get_winning_patterns() -> list:
    """Get winning patterns for use by other modules."""
    return _load_winning_patterns()


# =============================================================================
# CLI TESTING
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=== Smart Topic Selector ===\n")
    
    # Test trending topic
    print("--- Trending Topic (Gemini) ---")
    topic = get_smart_topic()
    print(f"  → {topic}")
    
    # Show cluster analytics
    print("\n--- Cluster Performance ---")
    selector = SmartTopicSelector()
    for cluster in selector.get_cluster_priorities():
        trend_emoji = {"rising": "📈", "stable": "➡️", "declining": "📉"}.get(cluster.trend, "❓")
        print(f"  {cluster.cluster_name}: priority={cluster.priority_score:.2f} {trend_emoji} ({cluster.video_count} videos)")
    
    # Show winning patterns
    print("\n--- Winning Patterns ---")
    winners = _load_winning_patterns()
    if winners:
        for w in winners[:5]:
            print(f"  ✅ {w['title']} ({w.get('views', '?')} views)")
    else:
        print("  (none yet — run sync_analytics.py first)")

