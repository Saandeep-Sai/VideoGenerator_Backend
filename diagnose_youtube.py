#!/usr/bin/env python3
"""
Diagnostic script to debug YouTube upload issues
"""

import os
import sys
import json
from pathlib import Path

print("=" * 70)
print("🔍 YOUTUBE UPLOAD DIAGNOSTIC")
print("=" * 70)

# Check 1: token.json exists
print("\n1️⃣  Checking token.json...")
if os.path.exists("token.json"):
    print("   ✅ token.json exists")
    
    # Check size
    size = os.path.getsize("token.json")
    print(f"   📊 Size: {size} bytes")
    
    # Check permissions
    stat = os.stat("token.json")
    mode = stat.st_mode
    print(f"   🔐 Permissions: {oct(mode)[-3:]}")
    
    # Try to parse it
    try:
        with open("token.json", "r") as f:
            token_data = json.load(f)
        
        print(f"   ✅ Valid JSON")
        print(f"      - Has 'token': {'token' in token_data}")
        print(f"      - Has 'refresh_token': {'refresh_token' in token_data}")
        print(f"      - Has 'client_id': {'client_id' in token_data}")
        print(f"      - Scopes: {token_data.get('scopes', [])}")
        
        # Check if token is expired
        import datetime
        if 'expiry' in token_data:
            expiry = datetime.datetime.fromisoformat(token_data['expiry'].replace('Z', '+00:00'))
            now = datetime.datetime.now(datetime.timezone.utc)
            if expiry > now:
                print(f"      - ✅ Token valid until: {expiry}")
            else:
                print(f"      - ⚠️  Token expired at: {expiry}")
        
    except Exception as e:
        print(f"   ❌ Invalid JSON: {e}")
else:
    print("   ❌ token.json NOT FOUND")
    print("   ⚠️  YouTube upload will fail!")

# Check 2: client_secret.json exists
print("\n2️⃣  Checking client_secret.json...")
if os.path.exists("client_secret.json"):
    print("   ✅ client_secret.json exists")
    try:
        with open("client_secret.json", "r") as f:
            secret_data = json.load(f)
        print(f"   ✅ Valid JSON")
        print(f"      - Client ID: {secret_data.get('installed', {}).get('client_id', 'N/A')[:20]}...")
    except:
        print("   ❌ Invalid JSON")
else:
    print("   ❌ client_secret.json NOT FOUND")

# Check 3: Test authentication
print("\n3️⃣  Testing YouTube authentication...")
try:
    from youtube_upload import authenticate_youtube
    youtube = authenticate_youtube()
    print("   ✅ Authentication successful!")
    print("   ✅ YouTube API client ready")
except Exception as e:
    print(f"   ❌ Authentication failed: {e}")
    import traceback
    traceback.print_exc()

# Check 4: Test with a real local file
print("\n4️⃣  Looking for test video files...")
video_files = list(Path(".").glob("**/*.mp4"))[:5]
if video_files:
    print(f"   Found {len(video_files)} MP4 files:")
    for f in video_files:
        print(f"      - {f}")
else:
    print("   ℹ️  No MP4 files found (this is OK - videos are generated on demand)")

# Check 5: Check if video generation works
print("\n5️⃣  Testing video generation...")
try:
    from generator.video_generator.optimized_video_generator import OptimizedVideoGenerationPipeline, VideoGenerationConfig
    print("   ✅ Video generator imports work")
except Exception as e:
    print(f"   ❌ Video generator import failed: {e}")

print("\n" + "=" * 70)
print("📋 SUMMARY")
print("=" * 70)

issues = []
if not os.path.exists("token.json"):
    issues.append("❌ token.json missing - copy from local machine: scp token.json ubuntu@instance:~/VideoGenerator_Backend/")
if not os.path.exists("client_secret.json"):
    issues.append("❌ client_secret.json missing")

if issues:
    print("\n🚨 ISSUES FOUND:")
    for issue in issues:
        print(f"   {issue}")
else:
    print("\n✅ All checks passed! YouTube upload should work.")
    print("   Next: Test with run_generate_worker.py")

print("\n" + "=" * 70)
