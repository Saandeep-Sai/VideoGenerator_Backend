#!/usr/bin/env python3
"""
Weekly Analytics Sync
======================

Lightweight script that runs weekly (via systemd timer) to:
1. Refresh YouTube metrics for all tracked videos in Firestore
2. Ingest any NEW videos not yet tracked
3. Keep the smart topic selector updated with fresh data

Usage:
    python sync_analytics.py              # Full sync
    python sync_analytics.py --dry-run    # Preview only
"""

import os
import sys
import io
import time
import logging
import argparse
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(override=True)

# Force UTF-8 for stdout on Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('sync_analytics.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Firebase
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    import base64
    import json
    HAS_FIREBASE = True
except ImportError:
    HAS_FIREBASE = False

# YouTube
try:
    from analytics.youtube_oauth_analytics import YouTubeAnalyticsFetcher
    HAS_YOUTUBE = True
except ImportError:
    HAS_YOUTUBE = False


def init_firestore():
    """Initialize Firestore and return client."""
    if not HAS_FIREBASE:
        return None
    try:
        try:
            firebase_admin.get_app()
        except ValueError:
            cred_b64 = os.getenv("FIREBASE_CREDENTIALS_BASE64")
            project_id = os.getenv("FIREBASE_PROJECT_ID")
            if cred_b64:
                cred_json = base64.b64decode(cred_b64).decode('utf-8')
                cred_dict = json.loads(cred_json)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred, {'projectId': project_id})
            else:
                firebase_admin.initialize_app(options={'projectId': project_id})
        return firestore.client()
    except Exception as e:
        logger.error(f"❌ Firebase init failed: {e}")
        return None


def infer_topic_cluster(title: str) -> str:
    """Infer topic cluster from video title."""
    title_lower = title.lower()
    clusters = {
        "python": ["python", "django", "flask", "pandas", "numpy", "pydantic", "fastapi",
                    "polars", "mojo", "type hint", "match statement"],
        "javascript": ["javascript", "js", "react", "node", "typescript", "vue", "angular",
                        "next.js", "bun", "deno", "npm", "signal", "hooks"],
        "web": ["html", "css", "web", "frontend", "backend", "api", "graphql", "htmx",
                "container quer", "view transition", "wasm", "webassembly", "island", "monorepo"],
        "devops": ["docker", "kubernetes", "aws", "cloud", "devops", "ci/cd", "terraform",
                   "serverless", "deploy", "pipeline", "ephemeral", "platform engineer",
                   "feature flag", "cold start", "edge function", "dev container", "sbom"],
        "database": ["sql", "database", "mongodb", "postgres", "mysql", "redis", "duckdb"],
        "ai_ml": ["ai", "machine learning", "deep learning", "neural", "gpt", "llm",
                  "rag", "vector", "embedding", "hallucination", "prompt", "quantization",
                  "tinyml", "synthetic data", "federated", "agent"],
        "security": ["security", "auth", "oauth", "jwt", "encryption", "passkey", "password",
                     "vulnerability", "zero trust"],
        "git": ["git", "rebase", "merge", "commit", "branch"],
    }
    for cluster, keywords in clusters.items():
        if any(kw in title_lower for kw in keywords):
            return cluster
    return "general"


def sync_analytics(dry_run: bool = False):
    """Main sync function."""
    logger.info("=" * 60)
    logger.info(f"📊 WEEKLY ANALYTICS SYNC {'(DRY RUN)' if dry_run else '(LIVE)'}")
    logger.info("=" * 60)

    # Connect YouTube
    if not HAS_YOUTUBE:
        logger.error("❌ YouTube module not available")
        return False

    youtube = YouTubeAnalyticsFetcher()
    if not youtube.is_connected:
        logger.error("❌ YouTube not connected")
        return False
    logger.info("✅ YouTube connected")

    # Connect Firestore
    db = None if dry_run else init_firestore()
    if not dry_run and not db:
        logger.error("❌ Firestore not connected")
        return False
    if not dry_run:
        logger.info("✅ Firestore connected")

    collection = "video_analytics"
    stats = {"synced": 0, "new": 0, "failed": 0, "skipped": 0}

    # Step 1: Get existing tracked video IDs from Firestore
    tracked_ids = set()
    if db:
        try:
            docs = db.collection(collection).limit(500).get()
            tracked_ids = {doc.id for doc in docs}
            logger.info(f"📋 Currently tracking {len(tracked_ids)} videos in Firestore")
        except Exception as e:
            logger.error(f"❌ Failed to read Firestore: {e}")

    # Step 2: Fetch all channel videos
    all_videos = youtube.get_recent_videos(max_results=50)
    logger.info(f"📺 Found {len(all_videos)} recent videos from YouTube")

    # Step 3: Sync each video
    for i, video in enumerate(all_videos, 1):
        vid = video["video_id"]
        title = video["title"]

        try:
            # Fetch fresh stats
            fresh_stats = youtube.get_video_statistics(vid)
            if not fresh_stats:
                stats["failed"] += 1
                continue

            time.sleep(0.3)

            # Fetch analytics (last 28 days)
            analytics = youtube.get_video_analytics(vid, days=28) or {}
            time.sleep(0.3)

            metrics = {
                "views_total": fresh_stats.get("view_count", 0),
                "views_24h": analytics.get("views", 0),
                "avg_view_percentage": analytics.get("avg_view_percentage", 0.0),
                "likes": fresh_stats.get("like_count", 0),
                "comments": fresh_stats.get("comment_count", 0),
                "shares": analytics.get("shares", 0),
                "subscribers_gained": analytics.get("subscribers_gained", 0),
                "subscribers_lost": analytics.get("subscribers_lost", 0),
            }

            is_new = vid not in tracked_ids

            if dry_run:
                action = "NEW" if is_new else "UPDATE"
                logger.info(f"  [{action}] {title[:45]}... ({metrics['views_total']} views, {metrics['avg_view_percentage']:.1f}% retention)")
            elif db:
                update_data = {
                    "metrics": metrics,
                    "last_synced": datetime.now(timezone.utc).isoformat(),
                    "title": fresh_stats.get("title", title),
                }
                if is_new:
                    update_data.update({
                        "youtube_video_id": vid,
                        "topic": title,
                        "topic_cluster": infer_topic_cluster(title),
                        "status": "active",
                        "published_at": video.get("published_at", ""),
                        "source": "weekly_sync",
                    })

                db.collection(collection).document(vid).set(update_data, merge=True)

            if is_new:
                stats["new"] += 1
            else:
                stats["synced"] += 1

        except Exception as e:
            logger.error(f"  ❌ Error syncing {vid}: {e}")
            stats["failed"] += 1

        if i % 10 == 0:
            logger.info(f"  Progress: {i}/{len(all_videos)}")

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("📊 SYNC COMPLETE")
    logger.info(f"  Updated: {stats['synced']}")
    logger.info(f"  New:     {stats['new']}")
    logger.info(f"  Failed:  {stats['failed']}")
    logger.info("=" * 60)
    
    # Step 4: Generate winning patterns
    if not dry_run and db:
        generate_winning_patterns(db, collection)
    elif dry_run:
        logger.info("  [DRY RUN] Would generate winning_patterns.json")
    
    return True


def generate_winning_patterns(db, collection: str = "video_analytics"):
    """
    Analyze all tracked videos, tag as win/loss, and save winning patterns.
    
    Win = views above channel average
    Loss = views below channel average
    
    Saves winning_patterns.json for the smart topic selector.
    """
    import json
    
    logger.info("\n🏆 Generating winning patterns...")
    
    try:
        # Read all videos from Firestore
        docs = db.collection(collection).limit(500).get()
        videos = []
        for doc in docs:
            data = doc.to_dict()
            metrics = data.get("metrics", {})
            views = metrics.get("views_total", 0)
            if isinstance(views, str):
                views = int(views) if views.isdigit() else 0
            
            videos.append({
                "video_id": doc.id,
                "title": data.get("title", data.get("topic", "")),
                "views": views,
                "retention": metrics.get("avg_view_percentage", 0),
                "likes": metrics.get("likes", 0),
                "comments": metrics.get("comments", 0),
                "cluster": data.get("topic_cluster", "general"),
                "published_at": data.get("published_at", ""),
            })
        
        if not videos:
            logger.warning("  No videos found in Firestore")
            return
        
        # Calculate channel average
        total_views = sum(v["views"] for v in videos)
        avg_views = total_views / len(videos)
        
        # Tag videos as win/loss
        wins = []
        losses = 0
        for v in videos:
            if v["views"] >= avg_views:
                wins.append(v)
            else:
                losses += 1
        
        # Sort wins by views (best first)
        wins.sort(key=lambda x: x["views"], reverse=True)
        
        # Save winning patterns
        patterns = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "total_videos": len(videos),
            "channel_avg_views": round(avg_views, 1),
            "win_count": len(wins),
            "loss_count": losses,
            "winners": [
                {
                    "title": w["title"],
                    "views": w["views"],
                    "retention": round(w["retention"], 1),
                    "likes": w["likes"],
                    "cluster": w["cluster"],
                }
                for w in wins[:10]  # Top 10 winners
            ]
        }
        
        patterns_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                      "winning_patterns.json")
        with open(patterns_path, 'w') as f:
            json.dump(patterns, f, indent=2)
        
        logger.info(f"  ✅ Saved winning_patterns.json")
        logger.info(f"  📊 Channel avg: {avg_views:.0f} views")
        logger.info(f"  🏆 Winners: {len(wins)} | 📉 Losses: {losses}")
        logger.info(f"  🥇 Top: \"{wins[0]['title'][:45]}...\" ({wins[0]['views']} views)")
        
        # Also update Firestore with win/loss tags
        batch = db.batch()
        for v in videos:
            outcome = "win" if v["views"] >= avg_views else "loss"
            ref = db.collection(collection).document(v["video_id"])
            batch.update(ref, {"outcome": outcome})
        batch.commit()
        logger.info(f"  ✅ Tagged {len(videos)} videos with win/loss in Firestore")
        
    except Exception as e:
        logger.error(f"  ❌ Failed to generate winning patterns: {e}")
        import traceback
        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description="Weekly analytics sync")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    success = sync_analytics(dry_run=args.dry_run)
    
    # Send weekly email report (only on real runs, not dry-run)
    if success and not args.dry_run:
        try:
            from analytics.weekly_email_report import WeeklyReportGenerator
            report = WeeklyReportGenerator()
            if report.is_configured:
                logger.info("📧 Sending weekly analytics email report...")
                report.generate_and_send()
            else:
                logger.info("📧 SMTP not configured — skipping email report")
        except Exception as e:
            # Email failure should NEVER break the sync
            logger.warning(f"⚠️ Weekly email report failed (non-fatal): {e}")
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

