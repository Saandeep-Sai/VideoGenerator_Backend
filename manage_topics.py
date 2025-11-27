#!/usr/bin/env python3
"""
Topic Management Utility
Manage YouTube Shorts topics and history
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

def load_history():
    """Load topic history."""
    history_file = Path("youtube_shorts_history.json")
    if history_file.exists():
        with open(history_file, "r") as f:
            return json.load(f)
    return {}

def show_stats():
    """Show topic statistics."""
    history = load_history()
    
    if not history:
        print("📋 No topic history found")
        return
    
    total_used = len(history)
    recent_count = len([t for t, date_str in history.items() 
                       if datetime.fromisoformat(date_str) > datetime.now() - timedelta(days=30)])
    
    print(f"📊 Topic Statistics:")
    print(f"   Total topics used: {total_used}")
    print(f"   Recent topics (30d): {recent_count}")
    print(f"   Available predefined: 100+")
    
    # Show recent topics
    if recent_count > 0:
        print(f"\n🕒 Recent topics:")
        recent_topics = [(t, date_str) for t, date_str in history.items() 
                        if datetime.fromisoformat(date_str) > datetime.now() - timedelta(days=30)]
        recent_topics.sort(key=lambda x: x[1], reverse=True)
        
        for topic, date_str in recent_topics[:10]:
            date_obj = datetime.fromisoformat(date_str)
            days_ago = (datetime.now() - date_obj).days
            print(f"   • {topic} ({days_ago}d ago)")

def clear_history():
    """Clear topic history."""
    history_file = Path("youtube_shorts_history.json")
    if history_file.exists():
        history_file.unlink()
        print("✅ Topic history cleared")
    else:
        print("📋 No history file found")

def test_ai_topic():
    """Test AI topic generation."""
    try:
        import os
        from dotenv import load_dotenv
        import google.generativeai as genai
        
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")
        
        if not api_key:
            print("❌ GEMINI_API_KEY not found in .env")
            return
        
        genai.configure(api_key=api_key)
        client = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = """Generate 1 unique programming/tech topic for a 60-second YouTube Short.

Requirements:
- Educational and engaging for developers
- Suitable for visual explanation
- Trending in 2024

Output format: Just the topic title (no quotes, no explanation)
Example: "Microservices vs Serverless Architecture"

Generate topic:"""
        
        response = client.generate_content(prompt)
        ai_topic = response.text.strip().replace('"', '').replace("'", "")
        
        print(f"🤖 AI Generated Topic: {ai_topic}")
        
    except Exception as e:
        print(f"❌ AI topic generation failed: {e}")

def main():
    """Main CLI interface."""
    if len(sys.argv) < 2:
        print("📋 Topic Management Utility")
        print("\nCommands:")
        print("  stats    - Show topic statistics")
        print("  clear    - Clear topic history")
        print("  test-ai  - Test AI topic generation")
        return
    
    command = sys.argv[1]
    
    if command == "stats":
        show_stats()
    elif command == "clear":
        clear_history()
    elif command == "test-ai":
        test_ai_topic()
    else:
        print(f"❌ Unknown command: {command}")

if __name__ == "__main__":
    main()