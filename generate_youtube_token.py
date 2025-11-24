#!/usr/bin/env python3
"""
Headless YouTube OAuth token generator for cloud instances.
This script generates a token.json without requiring a browser on the instance.

Usage:
1. Run this script on the instance
2. Copy the URL and paste it in your LOCAL browser
3. Grant permissions
4. Copy the authorization code back
5. Script saves token.json automatically
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def generate_token_headless():
    """
    Generate YouTube token without a browser.
    The authorization URL will be printed - you visit it in your local browser.
    """
    print("=" * 70)
    print("🎬 HEADLESS YOUTUBE OAUTH TOKEN GENERATION")
    print("=" * 70)
    
    if not os.path.exists("client_secret.json"):
        print("❌ ERROR: client_secret.json not found!")
        print("   Download from: https://console.cloud.google.com/")
        return False
    
    try:
        # Create flow
        flow = InstalledAppFlow.from_client_secrets_file(
            "client_secret.json", 
            SCOPES
        )
        
        # Generate the authorization URL
        # run_local_server would require a browser, so we use run_console instead
        print("\n📋 STEP 1: Copy this URL and paste it in your LOCAL browser:")
        print("-" * 70)
        
        # For headless, we need to manually handle the flow
        auth_url, _ = flow.authorization_url(prompt='consent')
        
        print(auth_url)
        print("-" * 70)
        
        print("\n✅ STEP 2: After visiting the URL and granting permission:")
        print("   1. You'll be redirected to: http://localhost/?code=AUTH_CODE")
        print("   2. Copy the 'code' parameter from the URL")
        print("   3. Paste it below (you may only see the code, not the full URL)")
        
        auth_code = input("\n🔑 Paste the authorization code here: ").strip()
        
        if not auth_code:
            print("❌ No authorization code provided!")
            return False
        
        # Exchange the code for credentials
        try:
            creds = flow.fetch_token(code=auth_code)
        except Exception as e:
            print(f"❌ Failed to exchange authorization code: {e}")
            print("   Make sure you copied the exact code (letters, numbers, hyphens)")
            return False
        
        # Save the token
        with open("token.json", "w") as token_file:
            token_file.write(creds.to_json())
        
        # Set secure permissions
        os.chmod("token.json", 0o600)
        
        print("\n" + "=" * 70)
        print("✅ SUCCESS! token.json created and saved securely")
        print("=" * 70)
        print("\n📊 Token Information:")
        print(f"   - User: {creds.get('email', 'Unknown')}")
        print(f"   - Scope: YouTube Upload")
        print(f"   - Expires: {creds.get('expiry', 'Never (refresh token available)')}")
        print(f"   - File: token.json (permissions: 600)")
        
        print("\n✅ You're ready to use YouTube uploads!")
        print("   Run: python3 run_generate_worker.py")
        print("   Videos with video_type='short' will auto-upload to YouTube")
        
        return True
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        print("\nTroubleshooting:")
        print("  - Make sure client_secret.json exists")
        print("  - Make sure the authorization code is correct")
        print("  - Check the Google Cloud Console for project issues")
        return False

if __name__ == "__main__":
    success = generate_token_headless()
    exit(0 if success else 1)
