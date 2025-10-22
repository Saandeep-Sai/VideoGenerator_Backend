#!/usr/bin/env python3
"""
Test script for async video generation with health check
Run this after starting the Django server: python manage.py runserver
"""

import requests
import time
import json

BASE_URL = "http://localhost:8000"

def test_health_check():
    """Test the health check endpoint"""
    print("\n🔍 Testing Health Check...")
    try:
        response = requests.get(f"{BASE_URL}/api/health/", timeout=5)
        print(f"✅ Status Code: {response.status_code}")
        print(f"✅ Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False

def test_async_generation():
    """Test async video generation"""
    print("\n🎥 Testing Async Video Generation...")
    
    # 1. Start generation
    print("\n1️⃣ Starting video generation...")
    try:
        response = requests.post(
            f"{BASE_URL}/api/generate/",
            json={"topic": "Test Video", "duration": 30},
            timeout=10
        )
        
        if response.status_code != 202:
            print(f"❌ Unexpected status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
        data = response.json()
        job_id = data.get('job_id')
        
        print(f"✅ Job created: {job_id}")
        print(f"✅ Status URL: {data.get('status_url')}")
        
    except Exception as e:
        print(f"❌ Failed to start generation: {e}")
        return False
    
    # 2. Poll for status
    print("\n2️⃣ Polling for status (will take a few minutes)...")
    max_attempts = 120  # 10 minutes max
    attempt = 0
    
    while attempt < max_attempts:
        try:
            response = requests.get(f"{BASE_URL}/api/status/{job_id}/", timeout=5)
            status_data = response.json()
            
            status = status_data.get('status')
            progress = status_data.get('progress', 'N/A')
            
            print(f"   [{attempt+1}] Status: {status} - Progress: {progress}")
            
            if status == 'completed':
                print(f"\n✅ Video generation completed!")
                print(f"✅ Firestore Doc ID: {status_data.get('firestore_doc_id')}")
                return True
            
            if status == 'failed':
                print(f"\n❌ Video generation failed!")
                print(f"❌ Error: {status_data.get('error')}")
                return False
            
            # Wait 5 seconds before next poll
            time.sleep(5)
            attempt += 1
            
        except Exception as e:
            print(f"❌ Error polling status: {e}")
            return False
    
    print(f"\n⏱️ Timeout waiting for video generation")
    return False

def main():
    print("=" * 60)
    print("🧪 Video Generator Health Check & Async Test")
    print("=" * 60)
    
    # Test 1: Health Check
    health_ok = test_health_check()
    
    if not health_ok:
        print("\n❌ Health check failed. Make sure server is running:")
        print("   python manage.py runserver")
        return
    
    print("\n✅ Health check passed!")
    
    # Test 2: Async Generation
    print("\n" + "=" * 60)
    input("Press Enter to test async video generation (or Ctrl+C to exit)...")
    
    generation_ok = test_async_generation()
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Summary")
    print("=" * 60)
    print(f"Health Check: {'✅ PASS' if health_ok else '❌ FAIL'}")
    print(f"Async Generation: {'✅ PASS' if generation_ok else '❌ FAIL'}")
    print("=" * 60)
    
    if health_ok and generation_ok:
        print("\n🎉 All tests passed! Ready for Render deployment.")
    else:
        print("\n⚠️ Some tests failed. Check the errors above.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Tests cancelled by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
