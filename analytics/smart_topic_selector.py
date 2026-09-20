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
import json
import logging
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta
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

# =============================================================================
# LIVE TREND FETCHING
# =============================================================================

# Niche keywords used across all trend sources
_TREND_KEYWORDS = [
    "programming", "coding", "developer", "javascript", "python",
    "react", "AI", "software engineering", "web development", "rust",
    "typescript", "golang", "kubernetes", "docker", "LLM",
]

_TREND_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "trend_cache.json"
)

_TREND_CACHE_TTL_HOURS = 6  # Refresh every 6 hours (scheduler fires 4x/day)


def _load_trend_cache() -> Optional[dict]:
    """Load cached trend signals if they exist and are within TTL."""
    try:
        if not os.path.exists(_TREND_CACHE_PATH):
            return None
        with open(_TREND_CACHE_PATH, 'r') as f:
            cache = json.load(f)
        fetched_at = datetime.fromisoformat(cache.get("fetched_at", ""))
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
        if age_hours < _TREND_CACHE_TTL_HOURS:
            signals = cache.get("signals", [])
            if signals:
                logger.info(f"📦 Trend cache hit: {len(signals)} signals, {age_hours:.1f}h old")
                return cache
        logger.info(f"⏰ Trend cache expired ({age_hours:.1f}h old), will refresh")
    except Exception as e:
        logger.warning(f"⚠️ Could not load trend cache: {e}")
    return None


def _save_trend_cache(signals: list) -> None:
    """Persist trend signals to disk."""
    cache = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "ttl_hours": _TREND_CACHE_TTL_HOURS,
        "signals": signals,
    }
    try:
        with open(_TREND_CACHE_PATH, 'w') as f:
            json.dump(cache, f, indent=2)
        logger.info(f"💾 Saved {len(signals)} trend signals to cache")
    except Exception as e:
        logger.warning(f"⚠️ Could not save trend cache: {e}")


def _fetch_youtube_trends() -> list:
    """Fetch trending tech videos from YouTube Data API using existing OAuth creds.
    
    Uses the youtube.readonly scope already set up in youtube_oauth_analytics.py.
    Returns items ranked by viewCount (rank 1 = most viewed in last 48h).
    """
    signals = []
    try:
        try:
            from .youtube_oauth_analytics import get_authenticated_services
        except ImportError:
            from analytics.youtube_oauth_analytics import get_authenticated_services

        youtube_data, _ = get_authenticated_services()
        if not youtube_data:
            logger.warning("⚠️ YouTube OAuth not available, skipping YouTube trends")
            return []

        published_after = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        query = "programming OR coding OR developer OR software engineering"

        response = youtube_data.search().list(
            part="snippet",
            q=query,
            type="video",
            order="viewCount",
            publishedAfter=published_after,
            maxResults=15,
            relevanceLanguage="en",
        ).execute()

        now_iso = datetime.now(timezone.utc).isoformat()
        for rank, item in enumerate(response.get("items", []), start=1):
            snippet = item.get("snippet", {})
            title = snippet.get("title", "").strip()
            video_id = item.get("id", {}).get("videoId", "")
            if title:
                signals.append({
                    "title": title,
                    "source": "youtube",
                    "rank": rank,
                    "url": f"https://youtube.com/watch?v={video_id}" if video_id else "",
                    "fetched_at": now_iso,
                })

        logger.info(f"📺 YouTube: fetched {len(signals)} trending videos")
    except Exception as e:
        logger.warning(f"⚠️ YouTube trend fetch failed (non-fatal): {e}")
    return signals


def _fetch_hackernews_trends() -> list:
    """Fetch trending tech stories from HackerNews Algolia API.
    
    No auth required. Most reliable source — designated fallback.
    Uses /search (relevance+recency) with points>50 filter.
    
    Note: numericFilters uses raw > which must NOT be URL-encoded,
    so we build that part of the URL manually.
    """
    signals = []
    try:
        query = urllib.parse.quote("programming OR coding OR javascript OR python OR AI")
        # Build URL manually — Algolia needs literal > in numericFilters, not %3E
        url = (
            f"https://hn.algolia.com/api/v1/search"
            f"?query={query}"
            f"&tags=story"
            f"&numericFilters=points>50"
            f"&hitsPerPage=15"
        )

        req = urllib.request.Request(url, headers={"User-Agent": "CodeTapasya/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        now_iso = datetime.now(timezone.utc).isoformat()
        for hit in data.get("hits", []):
            title = hit.get("title", "").strip()
            if title:
                signals.append({
                    "title": title,
                    "source": "hackernews",
                    "score": hit.get("points", 0),
                    "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
                    "fetched_at": now_iso,
                })

        logger.info(f"🟠 HackerNews: fetched {len(signals)} trending stories")
    except Exception as e:
        logger.warning(f"⚠️ HackerNews trend fetch failed (non-fatal): {e}")
    return signals


def _fetch_reddit_trends() -> list:
    """Fetch hot posts from r/programming and r/webdev via public JSON endpoints.
    
    No auth required. Supplementary signal — failure is non-fatal.
    Reddit requires a descriptive User-Agent and Accept header.
    """
    signals = []
    subreddits = ["programming", "webdev"]
    now_iso = datetime.now(timezone.utc).isoformat()
    headers = {
        "User-Agent": "script:CodeTapasya:v1.0 (trend fetch for content planning)",
        "Accept": "application/json",
    }

    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=10&raw_json=1"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                title = post.get("title", "").strip()
                if title and not post.get("stickied", False):
                    signals.append({
                        "title": title,
                        "source": "reddit",
                        "score": post.get("ups", 0),
                        "url": f"https://reddit.com{post.get('permalink', '')}",
                        "fetched_at": now_iso,
                    })
            # Small delay between subreddits to avoid rate-limiting
            import time
            time.sleep(1)
        except Exception as e:
            logger.warning(f"⚠️ Reddit r/{sub} fetch failed (non-fatal): {e}")

    logger.info(f"🔴 Reddit: fetched {len(signals)} trending posts")
    return signals


def fetch_live_trend_signals(force_refresh: bool = False) -> list:
    """Fetch and cache live trend signals from YouTube, HackerNews, and Reddit.
    
    Returns a flat list of normalized trend items. Uses cached data if within
    the 6-hour TTL window, unless force_refresh is True.
    
    Degrades gracefully: if one or more sources fail, returns whatever succeeded.
    If all sources fail AND cache is available (even expired), returns cached data.
    If absolutely nothing is available, returns an empty list.
    """
    # Check cache first
    if not force_refresh:
        cached = _load_trend_cache()
        if cached:
            return cached.get("signals", [])

    logger.info("🌐 Fetching live trend signals...")

    # Fetch from all sources — each one is independently fault-tolerant
    all_signals = []
    all_signals.extend(_fetch_hackernews_trends())  # Most reliable — fetch first
    all_signals.extend(_fetch_youtube_trends())
    all_signals.extend(_fetch_reddit_trends())

    if all_signals:
        _save_trend_cache(all_signals)
        logger.info(f"✅ Fetched {len(all_signals)} total trend signals")
    else:
        # All sources failed — try expired cache as last resort
        logger.warning("⚠️ All trend sources failed, checking expired cache...")
        try:
            if os.path.exists(_TREND_CACHE_PATH):
                with open(_TREND_CACHE_PATH, 'r') as f:
                    expired = json.load(f)
                all_signals = expired.get("signals", [])
                if all_signals:
                    logger.info(f"📦 Using expired cache ({len(all_signals)} signals)")
        except Exception:
            pass

    return all_signals


def _format_trend_signals_for_prompt(signals: list) -> str:
    """Format trend signals into a readable block for the Gemini prompt.
    
    YouTube items show rank (1 = most viewed); HN/Reddit items show points/upvotes.
    """
    if not signals:
        return "(No live trend data available)"

    lines = []
    for i, s in enumerate(signals, 1):
        source = s.get("source", "unknown")
        title = s.get("title", "")
        if source == "youtube":
            metric = f"rank #{s.get('rank', '?')} by views"
        else:
            metric = f"{s.get('score', 0)} points"
        lines.append(f"  {i}. [{source.upper()}] \"{title}\" ({metric})")

    return "\n".join(lines)


def get_smart_topic() -> str:
    """
    Get a smart topic using LIVE trend signals + winning patterns feedback.
    
    Strategy:
    1. Fetch real trending data from YouTube, HackerNews, Reddit (cached 6h)
    2. Load winning title patterns from past performance
    3. Ask Gemini to SELECT + REFRAME from real signals (not guess)
    4. Cross-reference against used topics to avoid repeats
    5. Fall back to cluster-based selection if Gemini fails
    """
    # Load context
    winners = _load_winning_patterns()
    used_topics = _load_used_topics(days=30)

    # Step 1: Fetch live trend signals (deterministic, separate from LLM)
    trend_signals = fetch_live_trend_signals()
    trend_block = _format_trend_signals_for_prompt(trend_signals)

    cache = _load_trend_cache()
    cache_age_desc = "unknown"
    if cache:
        try:
            fetched_at = datetime.fromisoformat(cache.get("fetched_at", ""))
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            hours_ago = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
            cache_age_desc = f"{hours_ago:.0f}"
        except Exception:
            pass

    # Build winning context for Gemini
    winning_context = ""
    if winners:
        winner_titles = [w["title"] for w in winners[:8]]
        winning_context = f"""
WINNING PATTERNS (titles that performed well with our audience):
{chr(10).join(f'  - "{t}"' for t in winner_titles)}

Select a topic that follows similar ENERGY and patterns — but on a DIFFERENT subject."""

    # Build exclusion list
    exclusion_text = ""
    if used_topics:
        recent = list(used_topics)[:50]
        exclusion_text = f"""
DO NOT select or generate anything similar to these recently covered topics:
{chr(10).join(f'  - {t}' for t in recent)}"""

    prompt = f"""You are a YouTube Shorts content strategist for a programming/tech channel called "Code Tapasya".

Below is a list of REAL trending topics from YouTube, HackerNews, and Reddit,
fetched in the last {cache_age_desc} hours. YouTube items are ranked by view count
(rank 1 = most viewed); HackerNews and Reddit items show engagement points.

TRENDING SIGNALS:
{trend_block}
{winning_context}
{exclusion_text}

YOUR TASK:
1. Review the trending signals above.
2. Select the ONE topic that would make the best 60-second YouTube Short for
   a programming education channel aimed at beginners-to-intermediate developers.
3. Reframe it into a specific, curiosity-driven, click-worthy topic title
   (not a copy-paste of the headline — make it your own).
4. If none of the signals fit (too niche, not educational, already covered),
   you may generate ONE original topic inspired by the general themes you see.

REQUIREMENTS:
- Beginner to intermediate level
- Perfect for a punchy, scroll-stopping 60-second explainer
- Specific and curiosity-driven

OUTPUT: Return ONLY the topic title. No explanation, no quotes.
Example good outputs:
"Why Every Developer is Switching to Bun in 2026"
"The AI Coding Tool That's Replacing Stack Overflow"
"This New CSS Feature Makes Flexbox Obsolete"

Your topic:"""

    # Try Gemini for topic selection from real signals
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
                # Check exact match AND semantic similarity (existing dedup — unchanged)
                if topic.lower().strip() in used_topics:
                    logger.warning(f"⚠️ Selected topic '{topic}' already used (exact match), retrying...")
                elif _is_topic_similar(topic, used_topics):
                    logger.warning(f"⚠️ Selected topic '{topic}' too similar to used topic, retrying...")
                else:
                    source_count = len(set(s.get("source") for s in trend_signals)) if trend_signals else 0
                    logger.info(f"🔥 Trend-grounded topic: {topic} (from {source_count} live sources)")
                    return topic

        logger.warning("⚠️ Trend-grounded selection exhausted, falling back to clusters")
    except Exception as e:
        logger.warning(f"⚠️ Trend-grounded topic selection failed: {e}, falling back to clusters")

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
    
    # Test live trend fetching
    print("--- Live Trend Signals ---")
    signals = fetch_live_trend_signals(force_refresh=True)
    for s in signals[:10]:
        source = s.get("source", "?")
        title = s.get("title", "?")
        if source == "youtube":
            metric = f"rank #{s.get('rank', '?')}"
        else:
            metric = f"{s.get('score', 0)} pts"
        print(f"  [{source.upper():^11}] {title[:60]:60} ({metric})")
    print(f"  ... {len(signals)} total signals\n")
    
    # Test topic selection from real signals
    print("--- Trend-Grounded Topic (Gemini) ---")
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

