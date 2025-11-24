#!/usr/bin/env python3
"""
Alternative: Generate token using your Google credentials directly.
This is a fallback if the headless method doesn't work.
"""

import os
import json
from pathlib import Path
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def create_token_from_service_account():
    """
    If you have a service account JSON, use this to generate a token.
    This is useful for CI/CD and automated scenarios.
    """
    service_account_file = "firebase-key.json"  # or your service account file
    
    if not os.path.exists(service_account_file):
        print(f"❌ {service_account_file} not found")
        return False
    
    try:
        # Create credentials from service account
        creds = ServiceAccountCredentials.from_service_account_file(
            service_account_file, 
            scopes=SCOPES
        )
        
        # Refresh to get valid access token
        creds.refresh(Request())
        
        # Save as token.json
        token_data = {
            "type": "authorized_user",
            "client_id": creds.service_account_email,
            "client_secret": "N/A",
            "refresh_token": creds.refresh_token,
            "access_token": creds.token,
        }
        
        with open("token.json", "w") as f:
            json.dump(token_data, f)
        
        os.chmod("token.json", 0o600)
        print("✅ token.json created from service account")
        return True
        
    except Exception as e:
        print(f"❌ Service account method failed: {e}")
        return False

def copy_existing_token():
    """
    Copy token.json from your local machine via environment variable.
    Useful for deployment.
    """
    token_json_env = os.getenv("YOUTUBE_TOKEN_JSON")
    
    if not token_json_env:
        print("❌ YOUTUBE_TOKEN_JSON environment variable not set")
        return False
    
    try:
        # token_json_env should be base64-encoded JSON
        import base64
        token_data = base64.b64decode(token_json_env).decode()
        
        with open("token.json", "w") as f:
            f.write(token_data)
        
        os.chmod("token.json", 0o600)
        print("✅ token.json created from environment variable")
        return True
        
    except Exception as e:
        print(f"❌ Environment variable method failed: {e}")
        return False

if __name__ == "__main__":
    print("Alternative token generation methods:")
    print("1. From service account file")
    print("2. From environment variable")
    
    method = input("Choose method (1 or 2): ").strip()
    
    if method == "1":
        success = create_token_from_service_account()
    elif method == "2":
        success = copy_existing_token()
    else:
        print("Invalid choice")
        success = False
    
    exit(0 if success else 1)
