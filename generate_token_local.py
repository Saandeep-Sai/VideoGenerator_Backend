#!/usr/bin/env python3
"""
Simple YouTube token generator - Works on LOCAL machine with browser
Run this on your Windows/Mac machine (where you have VS Code open)
"""

import os
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def generate_token_local():
    """
    Generate token on local machine with browser.
    This is the SIMPLEST method and works 100% of the time.
    """
    print("=" * 70)
    print("🎬 YOUTUBE OAUTH TOKEN GENERATION (LOCAL MACHINE)")
    print("=" * 70)
    
    if not os.path.exists("client_secret.json"):
        print("❌ ERROR: client_secret.json not found!")
        print("   Make sure you're in: d:\\Video_Generator\\backend\\")
        sys.exit(1)
    
    try:
        # Create the flow
        flow = InstalledAppFlow.from_client_secrets_file(
            "client_secret.json", 
            SCOPES
        )
        
        print("\n📋 Opening Google authentication in your browser...")
        print("   - A browser window will open automatically")
        print("   - Log in with your Google account")
        print("   - Grant YouTube upload permissions")
        print("   - Token will be saved automatically")
        
        # This opens a browser and handles the OAuth flow
        # Only works on machines with a display (Windows/Mac/Linux GUI)
        creds = flow.run_local_server(port=8080, open_browser=True)
        
        # Save the token
        with open("token.json", "w") as f:
            f.write(creds.to_json())
        
        os.chmod("token.json", 0o600)
        
        print("\n" + "=" * 70)
        print("✅ SUCCESS! token.json created")
        print("=" * 70)
        print("\n📊 Token saved at: d:\\Video_Generator\\backend\\token.json")
        print("\n📋 NEXT STEP - Copy to your instance:")
        print("   scp token.json ubuntu@<instance-ip>:~/VideoGenerator_Backend/")
        print("\n   Example:")
        print("   scp token.json ubuntu@140.238.1.2:~/VideoGenerator_Backend/")
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        print("\nTroubleshooting:")
        print("  - Make sure client_secret.json exists and is valid")
        print("  - Make sure you're connected to the internet")
        print("  - Try running again - auth codes expire after 10 minutes")
        return False

if __name__ == "__main__":
    success = generate_token_local()
    sys.exit(0 if success else 1)
