#!/usr/bin/env python3
"""
Bootstrap Analytics Data
========================

One-time script to fetch all existing YouTube videos and populate the
'video_analytics' Firestore collection. This enables the smart topic
selector to use REAL viewership data instead of mock/hardcoded numbers.

Usage:
    python bootstrap_analytics.py              # Full run (writes to Firestore)
    python bootstrap_analytics.py --dry-run    # Preview only (no writes)
    python bootstrap_analytics.py --limit 50   # Process only first 50 videos
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

# Setup path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(override=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bootstrap_analytics.log')
    ]
)
logger = logging.getLogger(__name__)

# Firebase
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    HAS_FIREBASE = True
except ImportError:
    HAS_FIREBASE = False
    logger.warning("Firebase libraries not installed")

# YouTube
try:
    from analytics.youtube_oauth_analytics import YouTubeAnalyticsFetcher, get_authenticated_services
    HAS_YOUTUBE = True
except ImportError:
    HAS_YOUTUBE = False
    logger.error("YouTube analytics module not found")


# ============================================================================
# TOPIC CLUSTER INFERENCE
# ============================================================================

def infer_topic_cluster(title: str) -> str:
    """Infer topic cluster from video title (same logic as IntegratedAnalyticsService)."""
    title_lower = title.lower()

    clusters = {
        "python": ["python", "django", "flask", "pandas", "numpy", "pip", "decorator", "comprehension",
                   "pydantic", "fastapi", "polars", "mojo", "type hint", "match statement"],
        "javascript": ["javascript", "js", "react", "node", "typescript", "vue", "angular", "next.js",
                       "bun", "deno", "npm", "signal", "usestate", "hooks", "package"],
        "web": ["html", "css", "web", "frontend", "backend", "api", "rest", "graphql", "htmx",
                "responsive", "container quer", "view transition", "media quer", "wasm",
                "webassembly", "island", "monorepo", "page", "browser"],
        "devops": ["docker", "kubernetes", "aws", "cloud", "devops", "ci/cd", "terraform", "ansible",
                   "jenkins", "github action", "serverless", "deploy", "pipeline", "ephemeral",
                   "platform engineer", "feature flag", "cold start", "edge function",
                   "dev container", "pr environment", "sbom", "supply chain"],
        "database": ["sql", "database", "mongodb", "postgres", "mysql", "redis", "nosql",
                     "indexing", "duckdb", "supabase"],
        "algorithms": ["algorithm", "data structure", "leetcode", "sort", "search", "binary",
                       "recursion", "big o", "time complexity", "hash"],
        "ai_ml": ["ai", "machine learning", "deep learning", "neural", "gpt", "chatgpt", "llm",
                  "nlp", "tensorflow", "pytorch", "rag", "vector", "embedding", "hallucination",
                  "prompt", "quantization", "tinyml", "synthetic data", "federated",
                  "agent", "model", "token", "inference"],
        "security": ["security", "auth", "oauth", "jwt", "encryption", "https", "ssl", "xss",
                     "injection", "passkey", "password", "vulnerability", "supply chain attack",
                     "zero trust", "secret"],
        "mobile": ["mobile", "react native", "flutter", "ios", "android", "swift", "kotlin",
                   "kmm", "cross-platform"],
        "career": ["career", "job", "interview", "resume", "salary", "remote", "developer life"],
        "git": ["git", "rebase", "merge", "commit", "branch", "version control"],
    }

    for cluster, keywords in clusters.items():
        if any(kw in title_lower for kw in keywords):
            return cluster

    return "general"


# ============================================================================
# FIRESTORE CLIENT
# ============================================================================

class BootstrapFirestoreClient:
    """Minimal Firestore client for bootstrap operations."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._db = None
        self.collection_name = "video_analytics"

        if dry_run:
            logger.info("🧪 DRY RUN MODE — no data will be written to Firestore")
            return

        if not HAS_FIREBASE:
            logger.error("Firebase libraries required for live run")
            return

        self._initialize()

    def _initialize(self):
        """Initialize Firebase connection."""
        try:
            try:
                firebase_admin.get_app()
            except ValueError:
                cred_b64 = os.getenv("FIREBASE_CREDENTIALS_BASE64")
                project_id = os.getenv("FIREBASE_PROJECT_ID")

                if cred_b64:
                    import base64
                    import json
                    cred_json = base64.b64decode(cred_b64).decode('utf-8')
                    cred_dict = json.loads(cred_json)
                    cred = credentials.Certificate(cred_dict)
                    firebase_admin.initialize_app(cred, {'projectId': project_id})
                else:
                    firebase_admin.initialize_app(options={'projectId': project_id})

            self._db = firestore.client()
            logger.info(f"✅ Firestore connected: {os.getenv('FIREBASE_PROJECT_ID')}")

        except Exception as e:
            logger.error(f"❌ Firebase init failed: {e}")

    def video_exists(self, video_id: str) -> bool:
        """Check if video already exists in Firestore."""
        if self.dry_run or not self._db:
            return False

        doc = self._db.collection(self.collection_name).document(video_id).get()
        return doc.exists

    def save_video(self, video_id: str, data: Dict[str, Any]) -> bool:
        """Save video data to Firestore."""
        if self.dry_run:
            logger.info(f"  [DRY RUN] Would save: {video_id}")
            return True

        if not self._db:
            return False

        try:
            self._db.collection(self.collection_name).document(video_id).set(data, merge=True)
            return True
        except Exception as e:
            logger.error(f"  ❌ Failed to save {video_id}: {e}")
            return False

    def get_count(self) -> int:
        """Get total documents in the collection."""
        if self.dry_run or not self._db:
            return 0

        try:
            docs = self._db.collection(self.collection_name).limit(500).get()
            return len(docs)
        except:
            return 0


# ============================================================================
# BOOTSTRAP ENGINE
# ============================================================================

class AnalyticsBootstrapper:
    """Fetches all YouTube videos and populates Firestore."""

    def __init__(self, dry_run: bool = False, limit: int = 300):
        self.dry_run = dry_run
        self.limit = limit
        self.youtube = None
        self.firestore = BootstrapFirestoreClient(dry_run=dry_run)

        # Stats
        self.stats = {
            "total_found": 0,
            "already_tracked": 0,
            "newly_saved": 0,
            "stats_fetched": 0,
            "analytics_fetched": 0,
            "failed": 0,
            "clusters": {}
        }

    def connect_youtube(self) -> bool:
        """Connect to YouTube API."""
        if not HAS_YOUTUBE:
            logger.error("❌ YouTube analytics module not available")
            return False

        self.youtube = YouTubeAnalyticsFetcher()

        if not self.youtube.is_connected:
            logger.error("❌ Failed to connect to YouTube. Check token.json")
            return False

        logger.info("✅ YouTube API connected")
        return True

    def fetch_all_videos(self) -> List[Dict[str, Any]]:
        """Fetch all videos from the channel uploads playlist (paginated)."""
        if not self.youtube or not self.youtube._youtube_data:
            return []

        try:
            # Get uploads playlist ID
            channel_response = self.youtube._youtube_data.channels().list(
                part="contentDetails,snippet,statistics",
                mine=True
            ).execute()

            if not channel_response.get("items"):
                logger.error("❌ No channel found")
                return []

            channel = channel_response["items"][0]
            uploads_playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]
            channel_title = channel["snippet"]["title"]
            total_videos = int(channel["statistics"]["videoCount"])

            logger.info(f"📺 Channel: {channel_title}")
            logger.info(f"📊 Total videos on channel: {total_videos}")
            logger.info(f"📋 Fetching up to {self.limit} videos...")

            # Paginate through uploads playlist
            videos = []
            next_page_token = None

            while len(videos) < self.limit:
                response = self.youtube._youtube_data.playlistItems().list(
                    part="snippet,contentDetails",
                    playlistId=uploads_playlist,
                    maxResults=50,
                    pageToken=next_page_token
                ).execute()

                for item in response.get("items", []):
                    videos.append({
                        "video_id": item["contentDetails"]["videoId"],
                        "title": item["snippet"]["title"],
                        "published_at": item["snippet"]["publishedAt"],
                        "thumbnail": item["snippet"]["thumbnails"].get("default", {}).get("url", ""),
                    })

                next_page_token = response.get("nextPageToken")
                logger.info(f"  Fetched {len(videos)} videos so far...")

                if not next_page_token:
                    break

                time.sleep(0.5)  # Rate limit

            self.stats["total_found"] = len(videos)
            logger.info(f"✅ Found {len(videos)} videos total")
            return videos[:self.limit]

        except Exception as e:
            logger.error(f"❌ Failed to fetch videos: {e}")
            import traceback
            traceback.print_exc()
            return []

    def process_video(self, video: Dict[str, Any]) -> bool:
        """Process a single video: fetch stats + analytics + save to Firestore."""
        video_id = video["video_id"]
        title = video["title"]

        # Skip if already tracked
        if self.firestore.video_exists(video_id):
            self.stats["already_tracked"] += 1
            return True

        # Infer topic cluster
        cluster = infer_topic_cluster(title)

        # Fetch statistics
        stats = self.youtube.get_video_statistics(video_id)
        if stats:
            self.stats["stats_fetched"] += 1
        else:
            stats = {"view_count": 0, "like_count": 0, "comment_count": 0, "title": title}

        time.sleep(0.3)  # Rate limit between calls

        # Fetch detailed analytics — use lifetime window from publish date
        try:
            published = video.get("published_at", "")
            if published:
                pub_date = datetime.fromisoformat(published.replace("Z", "+00:00"))
                days_since = (datetime.now(timezone.utc) - pub_date).days
                analytics_days = max(7, min(days_since, 365))  # 7 to 365 days
            else:
                analytics_days = 90

            analytics = self.youtube.get_video_analytics(video_id, days=analytics_days)
            if analytics:
                self.stats["analytics_fetched"] += 1
            else:
                analytics = {}
        except Exception as e:
            logger.debug(f"  Analytics query failed for {video_id}: {e}")
            analytics = {}

        time.sleep(0.3)  # Rate limit

        # Build document
        doc = {
            "youtube_video_id": video_id,
            "topic": title,
            "title": stats.get("title", title),
            "topic_cluster": cluster,
            "status": "active",
            "published_at": video.get("published_at", ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_synced": datetime.now(timezone.utc).isoformat(),
            "source": "bootstrap",
            "metrics": {
                "views_total": stats.get("view_count", 0),
                "views_24h": analytics.get("views", 0),
                "avg_view_percentage": analytics.get("avg_view_percentage", 0.0),
                "likes": stats.get("like_count", 0),
                "comments": stats.get("comment_count", 0),
                "shares": analytics.get("shares", 0),
                "subscribers_gained": analytics.get("subscribers_gained", 0),
                "subscribers_lost": analytics.get("subscribers_lost", 0),
            },
            "metadata": {
                "thumbnail": video.get("thumbnail", ""),
                "duration": stats.get("duration", ""),
            }
        }

        # Track cluster distribution
        self.stats["clusters"][cluster] = self.stats["clusters"].get(cluster, 0) + 1

        # Save to Firestore
        if self.firestore.save_video(video_id, doc):
            self.stats["newly_saved"] += 1
            return True
        else:
            self.stats["failed"] += 1
            return False

    def run(self):
        """Run the full bootstrap process."""
        logger.info("=" * 70)
        logger.info("🚀 ANALYTICS BOOTSTRAP")
        logger.info(f"   Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        logger.info(f"   Limit: {self.limit} videos")
        logger.info("=" * 70)

        # Step 1: Connect
        if not self.connect_youtube():
            logger.error("❌ Cannot proceed without YouTube connection")
            return False

        # Step 2: Fetch all videos
        videos = self.fetch_all_videos()
        if not videos:
            logger.error("❌ No videos found")
            return False

        # Step 3: Process each video
        logger.info(f"\n📊 Processing {len(videos)} videos...")
        for i, video in enumerate(videos, 1):
            try:
                title_short = video["title"][:50]
                cluster = infer_topic_cluster(video["title"])

                if i % 10 == 0 or i <= 5:
                    logger.info(f"  [{i}/{len(videos)}] {title_short}... [{cluster}]")

                self.process_video(video)

            except Exception as e:
                logger.error(f"  ❌ Error processing {video['video_id']}: {e}")
                self.stats["failed"] += 1

            # Progress report every 50 videos
            if i % 50 == 0:
                logger.info(f"\n📈 Progress: {i}/{len(videos)} processed")
                logger.info(f"   Saved: {self.stats['newly_saved']}, Skipped: {self.stats['already_tracked']}, Failed: {self.stats['failed']}")

        # Step 4: Print summary
        self._print_summary()
        return True

    def _print_summary(self):
        """Print final summary."""
        logger.info("\n" + "=" * 70)
        logger.info("📊 BOOTSTRAP COMPLETE")
        logger.info("=" * 70)
        logger.info(f"  Total videos found:       {self.stats['total_found']}")
        logger.info(f"  Already tracked (skipped): {self.stats['already_tracked']}")
        logger.info(f"  Newly saved to Firestore:  {self.stats['newly_saved']}")
        logger.info(f"  Statistics fetched:        {self.stats['stats_fetched']}")
        logger.info(f"  Analytics fetched:         {self.stats['analytics_fetched']}")
        logger.info(f"  Failed:                    {self.stats['failed']}")

        if self.stats["clusters"]:
            logger.info(f"\n📋 Topic Cluster Distribution:")
            sorted_clusters = sorted(self.stats["clusters"].items(), key=lambda x: x[1], reverse=True)
            for cluster, count in sorted_clusters:
                bar = "█" * min(count, 40)
                logger.info(f"  {cluster:15s} {count:3d} {bar}")

        if not self.dry_run:
            total_in_firestore = self.firestore.get_count()
            logger.info(f"\n🔥 Total docs in '{self.firestore.collection_name}': {total_in_firestore}")

        logger.info("\n✅ Next steps:")
        logger.info("   1. Run: python -m analytics.smart_topic_selector")
        logger.info("   2. Check cluster priorities are now based on REAL data")
        logger.info("=" * 70)


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Bootstrap analytics data from YouTube")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to Firestore")
    parser.add_argument("--limit", type=int, default=300, help="Max videos to process (default: 300)")
    args = parser.parse_args()

    bootstrapper = AnalyticsBootstrapper(dry_run=args.dry_run, limit=args.limit)
    success = bootstrapper.run()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
