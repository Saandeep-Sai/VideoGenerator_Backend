#!/usr/bin/env python3
"""
Test script for Dynamic Content Generator
Tests topic generation and YouTube metadata creation
"""

import os
import sys
from dotenv import load_dotenv
from generator.dynamic_content_generator import DynamicContentGenerator

def main():
    load_dotenv()
    
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        print("❌ GEMINI_API_KEY not found in environment")
        sys.exit(1)
    
    print("🧪 Testing Dynamic Content Generator")
    print("=" * 50)
    
    # Initialize generator
    try:
        generator = DynamicContentGenerator(gemini_api_key)
        print("✅ Generator initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize generator: {e}")
        sys.exit(1)
    
    # Test 1: Generate trending topic
    print("\n📋 Test 1: Generate Trending Topic")
    try:
        topic = generator.generate_trending_topic()
        print(f"✅ Generated topic: {topic}")
    except Exception as e:
        print(f"❌ Topic generation failed: {e}")
        return
    
    # Test 2: Generate YouTube metadata
    print("\n📋 Test 2: Generate YouTube Metadata")
    try:
        metadata = generator.generate_youtube_metadata(topic, 60)
        print(f"✅ Generated metadata:")
        print(f"   📺 Title: {metadata['title']}")
        print(f"   📝 Description: {metadata['description'][:100]}...")
        print(f"   🏷️  Tags: {', '.join(metadata['tags'][:5])}...")
    except Exception as e:
        print(f"❌ Metadata generation failed: {e}")
        return
    
    # Test 3: Generate multiple high-demand topics
    print("\n📋 Test 3: Generate High-Demand Topics")
    try:
        topics = generator.get_high_demand_topics(3)
        print(f"✅ Generated {len(topics)} high-demand topics:")
        for i, topic in enumerate(topics, 1):
            print(f"   {i}. {topic}")
    except Exception as e:
        print(f"❌ High-demand topics generation failed: {e}")
        return
    
    print("\n🎉 All tests passed successfully!")
    print("=" * 50)

if __name__ == "__main__":
    main()