"""
Weekly Content Planner
======================

Generates a structured weekly content plan every Sunday using Gemini.
Topics are broken into multi-part series with continuity and outlines.

Schedule: Sunday 12:00 AM IST (via weekly-planner.timer)
Output:   weekly_plan.json (local) + Firebase (scheduled-videos)

Usage:
    python weekly_planner.py             # Generate this week's plan
    python weekly_planner.py --dry-run   # Preview without saving
    python weekly_planner.py --next      # Show next pending video
    python weekly_planner.py --status    # Show plan progress
"""

import os
import sys
import json
import logging
import argparse
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

# IST timezone offset
IST = timezone(timedelta(hours=5, minutes=30))

PLAN_FILE = Path(__file__).parent / "weekly_plan.json"

# Day mapping for the plan (Monday=0 through Saturday=5)
PLAN_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
SLOTS_PER_DAY = 4
TOTAL_SLOTS = len(PLAN_DAYS) * SLOTS_PER_DAY  # 24


# ═══════════════════════════════════════════════════════════════
# PLAN GENERATION
# ═══════════════════════════════════════════════════════════════

WEEKLY_PLAN_PROMPT = """You are a YouTube Shorts content strategist for "Code Tapasya", a programming education channel.

Create a structured weekly content plan for 24 short videos (Monday to Saturday, 4 per day).

RULES:
1. Pick 4-8 broad programming/tech topics for the week.
2. Break each topic into sequential PARTS (default ~4 parts, but adjust based on topic depth — simpler topics can be 2-3 parts, complex topics can be 5-6 parts).
3. Total parts across ALL topics MUST equal exactly 24.
4. Each part builds on the previous — progressive learning within a series.
5. Assign parts to days so that a single topic spans 1-2 consecutive days maximum.
6. For EACH part, write a specific 2-sentence outline of WHAT to cover and HOW it connects to the previous part.
7. Parts of the same topic MUST be scheduled in order (Part 1 before Part 2, etc.) and on the same or consecutive days.
8. Every video is part of a series. Only use standalone (1-part) topics if slots remain after all series are planned.

{exclusion_text}

{performance_text}

OUTPUT FORMAT — Return ONLY valid JSON, no markdown:
{{
  "topics": [
    {{
      "topic_id": "snake_case_id",
      "title": "Human Readable Topic Title",
      "total_parts": 4,
      "parts": [
        {{
          "part_number": 1,
          "subtitle": "Short subtitle for this part",
          "outline": "2-sentence outline. What to cover and how it connects to previous part.",
          "scheduled_day": "monday",
          "scheduled_slot": 1
        }},
        {{
          "part_number": 2,
          "subtitle": "Next part subtitle",
          "outline": "2-sentence outline referencing Part 1 concepts.",
          "scheduled_day": "monday",
          "scheduled_slot": 2
        }}
      ]
    }}
  ]
}}

SLOT ASSIGNMENT:
- monday slots: 1, 2, 3, 4
- tuesday slots: 1, 2, 3, 4
- wednesday slots: 1, 2, 3, 4
- thursday slots: 1, 2, 3, 4
- friday slots: 1, 2, 3, 4
- saturday slots: 1, 2, 3, 4

Each (day, slot) pair must be unique. Fill all 24 slots.

Generate the weekly plan now:"""


def _load_exclusion_context() -> str:
    """Load recently used topics to avoid repeats."""
    history_file = Path(__file__).parent / "youtube_shorts_history.json"
    if not history_file.exists():
        return ""

    try:
        with open(history_file) as f:
            history = json.load(f)

        thirty_days_ago = datetime.now() - timedelta(days=30)
        recent = []
        for topic, date_str in history.items():
            try:
                if datetime.fromisoformat(date_str) > thirty_days_ago:
                    recent.append(topic)
            except (ValueError, TypeError):
                pass

        if recent:
            topics_list = "\n".join(f"- {t}" for t in recent[:30])
            return f"""RECENTLY USED TOPICS (DO NOT REPEAT or create similar topics):
{topics_list}

Generate COMPLETELY DIFFERENT topics from the above."""
        return ""
    except Exception as e:
        logger.warning(f"Failed to load topic history: {e}")
        return ""


def _load_performance_context() -> str:
    """Load winning patterns for performance-aware planning."""
    patterns_file = Path(__file__).parent / "data" / "analytics" / "winning_patterns.json"
    if not patterns_file.exists():
        return ""

    try:
        with open(patterns_file) as f:
            patterns = json.load(f)

        wins = patterns.get("winners", [])[:5]
        if wins:
            titles = "\n".join(f"- \"{w['title']}\" ({w.get('views', '?')} views)" for w in wins)
            return f"""LAST WEEK'S TOP PERFORMERS (create similar energy/topics):
{titles}"""
        return ""
    except Exception:
        return ""


def generate_weekly_plan(dry_run: bool = False) -> Optional[Dict]:
    """
    Generate a weekly content plan using Gemini.
    
    Returns:
        The weekly plan dict, or None on failure.
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.error("google-genai not installed. Install it with: pip install -U google-genai")
        return None

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not set")
        return None

    # New Google GenAI SDK client.
    # The API key is passed directly to the client instead of using
    # the legacy genai.configure() pattern.
    client = genai.Client(api_key=api_key)

    exclusion_text = _load_exclusion_context()
    performance_text = _load_performance_context()

    prompt = WEEKLY_PLAN_PROMPT.format(
        exclusion_text=exclusion_text,
        performance_text=performance_text,
    )

    # Calculate week boundaries
    now = datetime.now(IST)
    # Find next Monday
    days_until_monday = (7 - now.weekday()) % 7
    if days_until_monday == 0 and now.hour >= 1:  # If it's already Monday past 1 AM
        days_until_monday = 0
    week_start = (now + timedelta(days=days_until_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end = week_start + timedelta(days=5)  # Saturday
    week_id = week_start.strftime("%Y-W%V")

    logger.info(f"📅 Generating weekly plan: {week_id}")
    logger.info(f"   Monday: {week_start.strftime('%Y-%m-%d')}")
    logger.info(f"   Saturday: {week_end.strftime('%Y-%m-%d')}")

    # Call Gemini
    models_to_try = ["gemini-3.6-flash", "gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash-lite"]
    plan_data = None

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    max_output_tokens=4096,
                    response_mime_type="application/json",
                ),
            )

            raw = (response.text or "").strip()

            # JSON mode is enabled above, so Gemini should return valid JSON.
            # Keep a small fallback extraction for robustness.
            try:
                plan_data = json.loads(raw)
            except json.JSONDecodeError:
                json_match = re.search(r"\{[\s\S]*\}", raw)
                if json_match:
                    plan_data = json.loads(json_match.group())
                else:
                    raise ValueError("Gemini returned no valid JSON")

            break
        except Exception as e:
            logger.warning(f"Model {model_name} failed: {e}")
            continue

    if not plan_data:
        logger.error("All Gemini models failed to generate plan")
        return None

    # Validate and enrich the plan
    plan = _validate_and_enrich_plan(plan_data, week_id, week_start)
    if not plan:
        return None

    if dry_run:
        logger.info("🏁 DRY RUN — not saving plan")
        _print_plan_summary(plan)
        return plan

    # Save locally
    save_weekly_plan(plan)
    logger.info(f"✅ Weekly plan saved to {PLAN_FILE}")

    _print_plan_summary(plan)
    return plan


def _validate_and_enrich_plan(raw: Dict, week_id: str, week_start: datetime) -> Optional[Dict]:
    """Validate the Gemini output and add metadata fields."""
    topics = raw.get("topics", [])
    if not topics:
        logger.error("Plan has no topics")
        return None

    # Count total parts
    total_parts = sum(t.get("total_parts", len(t.get("parts", []))) for t in topics)

    if total_parts != TOTAL_SLOTS:
        logger.warning(f"Plan has {total_parts} parts (expected {TOTAL_SLOTS}). Accepting anyway.")

    # Check for slot collisions
    used_slots = set()
    for topic in topics:
        for part in topic.get("parts", []):
            slot_key = (part.get("scheduled_day", ""), part.get("scheduled_slot", 0))
            if slot_key in used_slots:
                logger.warning(f"Duplicate slot: {slot_key}")
            used_slots.add(slot_key)

            # Add tracking fields
            part["status"] = "pending"
            part["video_id"] = None
            part["youtube_video_id"] = None
            part["narration_summary"] = None
            part["previous_part_summary"] = None
            part["generated_at"] = None
            part["error"] = None
            part["retry_count"] = 0

    # Build the enriched plan
    plan = {
        "week_id": week_id,
        "week_start": week_start.strftime("%Y-%m-%d"),
        "week_end": (week_start + timedelta(days=5)).strftime("%Y-%m-%d"),
        "generated_at": datetime.now(IST).isoformat(),
        "status": "active",
        "topics": topics,
    }

    logger.info(f"✅ Plan validated: {len(topics)} topics, {total_parts} total parts")
    return plan


# ═══════════════════════════════════════════════════════════════
# PLAN PERSISTENCE
# ═══════════════════════════════════════════════════════════════

def save_weekly_plan(plan: Dict) -> None:
    """Save the weekly plan to disk."""
    with open(PLAN_FILE, "w") as f:
        json.dump(plan, f, indent=2)
    logger.info(f"💾 Plan saved: {PLAN_FILE}")


def load_weekly_plan() -> Optional[Dict]:
    """Load the current weekly plan from disk."""
    if not PLAN_FILE.exists():
        logger.info("No weekly plan found")
        return None

    try:
        with open(PLAN_FILE) as f:
            plan = json.load(f)
        logger.info(f"📋 Loaded weekly plan: {plan.get('week_id', 'unknown')}")
        return plan
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to load weekly plan: {e}")
        return None


def is_plan_active() -> bool:
    """Check if there's an active plan for this week."""
    plan = load_weekly_plan()
    if not plan:
        return False

    # Check if plan is for current week
    try:
        week_end = datetime.strptime(plan["week_end"], "%Y-%m-%d").replace(tzinfo=IST)
        now = datetime.now(IST)
        return now.date() <= week_end.date() and plan.get("status") == "active"
    except (KeyError, ValueError):
        return False


# ═══════════════════════════════════════════════════════════════
# SLOT MANAGEMENT
# ═══════════════════════════════════════════════════════════════

def get_next_planned_video() -> Optional[Dict]:
    """
    Get the next video to generate from the weekly plan.
    
    Picks the first pending slot for today (or any earlier missed slot).
    Handles retry logic: failed slots are retried before moving on.
    
    Returns:
        Dict with topic, part_number, total_parts, subtitle, outline,
        previous_part_summary, series_id — or None if no pending slots.
    """
    plan = load_weekly_plan()
    if not plan:
        return None

    now = datetime.now(IST)
    today = PLAN_DAYS[now.weekday()] if now.weekday() < 6 else None  # Sunday = 6

    if today is None:
        logger.info("📅 It's Sunday — no videos scheduled")
        return None

    # Build ordered list of all parts, sorted by day then slot
    day_order = {d: i for i, d in enumerate(PLAN_DAYS)}
    all_parts = []

    for topic in plan.get("topics", []):
        for part in topic.get("parts", []):
            all_parts.append({
                "topic": topic,
                "part": part,
                "day_index": day_order.get(part.get("scheduled_day", ""), 99),
                "slot": part.get("scheduled_slot", 99),
            })

    all_parts.sort(key=lambda x: (x["day_index"], x["slot"]))

    # Find the first pending or failed-retryable slot (today or earlier)
    today_index = day_order.get(today, 99)

    for item in all_parts:
        part = item["part"]
        topic = item["topic"]

        if item["day_index"] > today_index:
            break  # Don't look ahead to future days

        if part["status"] == "pending" or (part["status"] == "failed" and part.get("retry_count", 0) < 2):
            # Load previous part's narration summary for continuity
            previous_summary = _get_previous_part_summary(plan, topic["topic_id"], part["part_number"])

            # Look up the next part's subtitle for the outro teaser
            next_subtitle = _get_next_part_subtitle(plan, topic["topic_id"], part["part_number"])

            result = {
                "topic": topic["title"],
                "topic_id": topic["topic_id"],
                "part_number": part["part_number"],
                "total_parts": topic["total_parts"],
                "subtitle": part.get("subtitle", ""),
                "outline": part.get("outline", ""),
                "previous_part_summary": previous_summary,
                "next_part_subtitle": next_subtitle,
                "series_id": topic["topic_id"],
                "scheduled_day": part.get("scheduled_day"),
                "scheduled_slot": part.get("scheduled_slot"),
            }

            logger.info(f"📌 Next video: {result['topic']} — Part {result['part_number']}/{result['total_parts']}")
            if next_subtitle:
                logger.info(f"   Outro teaser: Part {result['part_number'] + 1} — {next_subtitle}")
            return result

    logger.info("✅ All slots for today (and earlier) are completed!")
    return None


def _get_previous_part_summary(plan: Dict, topic_id: str, current_part: int) -> Optional[str]:
    """Get the narration summary from the previous part in the same series."""
    if current_part <= 1:
        return None

    for topic in plan.get("topics", []):
        if topic["topic_id"] == topic_id:
            for part in topic.get("parts", []):
                if part["part_number"] == current_part - 1:
                    return part.get("narration_summary")
    return None


def _get_next_part_subtitle(plan: Dict, topic_id: str, current_part: int) -> Optional[str]:
    """Get the subtitle of the next part in the same series (for outro teaser)."""
    for topic in plan.get("topics", []):
        if topic["topic_id"] == topic_id:
            for part in topic.get("parts", []):
                if part["part_number"] == current_part + 1:
                    return part.get("subtitle")
    return None  # Returns None for the final part — no teaser needed


def mark_slot_completed(
    topic_id: str,
    part_number: int,
    narration_summary: str,
    youtube_video_id: str = None,
) -> bool:
    """
    Mark a slot as completed and save the narration summary for continuity.
    
    Args:
        topic_id: The topic series ID.
        part_number: Which part was completed.
        narration_summary: Condensed narration text for recap by next part.
        youtube_video_id: YouTube video ID if uploaded.
    
    Returns:
        True if successfully updated.
    """
    plan = load_weekly_plan()
    if not plan:
        return False

    for topic in plan.get("topics", []):
        if topic["topic_id"] == topic_id:
            for part in topic.get("parts", []):
                if part["part_number"] == part_number:
                    part["status"] = "completed"
                    part["narration_summary"] = narration_summary
                    part["youtube_video_id"] = youtube_video_id
                    part["generated_at"] = datetime.now(IST).isoformat()

                    # Also set previous_part_summary on the NEXT part
                    for next_part in topic["parts"]:
                        if next_part["part_number"] == part_number + 1:
                            next_part["previous_part_summary"] = narration_summary

                    save_weekly_plan(plan)
                    logger.info(f"✅ Marked {topic_id} Part {part_number} as completed")
                    return True

    logger.error(f"Slot not found: {topic_id} Part {part_number}")
    return False


def mark_slot_failed(topic_id: str, part_number: int, error: str) -> bool:
    """Mark a slot as failed (will be retried in next scheduler run)."""
    plan = load_weekly_plan()
    if not plan:
        return False

    for topic in plan.get("topics", []):
        if topic["topic_id"] == topic_id:
            for part in topic.get("parts", []):
                if part["part_number"] == part_number:
                    part["status"] = "failed"
                    part["error"] = error
                    part["retry_count"] = part.get("retry_count", 0) + 1
                    save_weekly_plan(plan)
                    logger.info(f"⚠️ Marked {topic_id} Part {part_number} as failed (retry #{part['retry_count']})")
                    return True
    return False


# ═══════════════════════════════════════════════════════════════
# DISPLAY HELPERS
# ═══════════════════════════════════════════════════════════════

def _print_plan_summary(plan: Dict) -> None:
    """Print a readable summary of the weekly plan."""
    print(f"\n{'='*60}")
    print(f"  WEEKLY PLAN: {plan.get('week_id', '?')}")
    print(f"  {plan.get('week_start')} to {plan.get('week_end')}")
    print(f"{'='*60}")

    for topic in plan.get("topics", []):
        completed = sum(1 for p in topic["parts"] if p.get("status") == "completed")
        total = topic["total_parts"]
        bar = f"[{'#' * completed}{'.' * (total - completed)}]"
        print(f"\n  {topic['title']} ({total} parts) {bar}")

        for part in topic["parts"]:
            status_icon = {
                "completed": "done",
                "failed": "FAIL",
                "pending": "    ",
            }.get(part.get("status", "pending"), "    ")
            print(f"    Part {part['part_number']}: {part.get('subtitle', '?'):<40} "
                  f"{part.get('scheduled_day', '?'):<10} slot {part.get('scheduled_slot', '?')} [{status_icon}]")

    # Count stats
    all_parts = [p for t in plan.get("topics", []) for p in t.get("parts", [])]
    done = sum(1 for p in all_parts if p.get("status") == "completed")
    failed = sum(1 for p in all_parts if p.get("status") == "failed")
    pending = sum(1 for p in all_parts if p.get("status") == "pending")
    print(f"\n  Progress: {done} done, {pending} pending, {failed} failed")
    print(f"{'='*60}\n")


def show_plan_status():
    """Show current plan progress."""
    plan = load_weekly_plan()
    if not plan:
        print("No active weekly plan found.")
        return
    _print_plan_summary(plan)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    sys.path.insert(0, str(Path(__file__).parent))

    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ImportError:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(description="Weekly Content Planner")
    parser.add_argument("--dry-run", action="store_true", help="Preview plan without saving")
    parser.add_argument("--next", action="store_true", help="Show next pending video")
    parser.add_argument("--status", action="store_true", help="Show plan progress")
    args = parser.parse_args()

    if args.status:
        show_plan_status()
    elif args.next:
        video = get_next_planned_video()
        if video:
            print(f"\nNext video:")
            print(f"  Topic:    {video['topic']}")
            print(f"  Part:     {video['part_number']}/{video['total_parts']}")
            print(f"  Subtitle: {video['subtitle']}")
            print(f"  Outline:  {video['outline']}")
            if video['previous_part_summary']:
                print(f"  Recap:    {video['previous_part_summary'][:100]}...")
        else:
            print("No pending videos.")
    else:
        plan = generate_weekly_plan(dry_run=args.dry_run)
        if plan:
            print("Plan generated successfully!")
        else:
            print("Failed to generate plan.")
            sys.exit(1)


if __name__ == "__main__":
    main()