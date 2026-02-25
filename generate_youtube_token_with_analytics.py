"""
Generate YouTube Token with Analytics Scopes
=============================================

Run this LOCALLY (not on server) to generate a token.json
that includes both upload AND analytics permissions.

This replaces the old token.json with one that can:
1. Upload videos (existing)
2. Read video stats (new)
3. Read detailed analytics like retention (new)
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# Extended scopes for both upload and analytics
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",        # Upload videos
    "https://www.googleapis.com/auth/youtube.readonly",      # Read video data
    "https://www.googleapis.com/auth/yt-analytics.readonly"  # Read analytics
]

def main():
    print("=" * 60)
    print("YouTube Token Generator (with Analytics)")
    print("=" * 60)
    
    # Check for client_secret.json
    if not os.path.exists("client_secret.json"):
        print("\n[ERROR] client_secret.json not found!")
        print("Download it from Google Cloud Console:")
        print("  1. Go to console.cloud.google.com")
        print("  2. Select your project")
        print("  3. APIs & Services > Credentials")
        print("  4. Download OAuth 2.0 Client ID")
        return
    
    # Check existing token
    if os.path.exists("token.json"):
        print("\n[INFO] Existing token.json found")
        creds = Credentials.from_authorized_user_file("token.json")
        
        # Check if it has all scopes
        existing_scopes = set(creds.scopes) if creds.scopes else set()
        required_scopes = set(SCOPES)
        
        if required_scopes.issubset(existing_scopes):
            print("[OK] Token already has all required scopes!")
            print("Scopes: " + ", ".join(SCOPES))
            return
        else:
            missing = required_scopes - existing_scopes
            print(f"[INFO] Missing scopes: {missing}")
            print("[INFO] Will regenerate token with all scopes...")
            os.rename("token.json", "token.json.backup")
            print("[INFO] Backed up old token to token.json.backup")
    
    # Generate new token
    print("\n[INFO] Starting OAuth flow...")
    print("[INFO] A browser window will open - log in with your YouTube account")
    print("[INFO] Grant ALL the permissions requested\n")
    
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    
    try:
        creds = flow.run_local_server(port=0)
        
        # Save the new token
        with open("token.json", "w") as token:
            token.write(creds.to_json())
        
        print("\n" + "=" * 60)
        print("[SUCCESS] Token generated with full permissions!")
        print("=" * 60)
        print("\nScopes granted:")
        for scope in SCOPES:
            print(f"  - {scope.split('/')[-1]}")
        
        print("\nThe token.json file now supports:")
        print("  - Video uploads")
        print("  - Reading video statistics")
        print("  - Reading detailed analytics (retention, watch time, etc.)")
        
        print("\nIf you're on a server, copy the token.json:")
        print("  scp token.json ubuntu@<your-server>:~/VideoGenerator_Backend/")
        
    except Exception as e:
        print(f"\n[ERROR] OAuth flow failed: {e}")
        if os.path.exists("token.json.backup"):
            os.rename("token.json.backup", "token.json")
            print("[INFO] Restored backup token.json")


if __name__ == "__main__":
    main()
