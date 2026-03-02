    #!/usr/bin/env python3
"""
Quick setup script for YouTube Shorts automation
"""
import os
import sys
from pathlib import Path

def create_directories():
    """Create required directories"""
    dirs = ["auto_shorts_output", "auto_shorts_temp"]
    for dir_name in dirs:
        Path(dir_name).mkdir(exist_ok=True)
        print(f"✅ Created directory: {dir_name}")

def check_env_file():
    """Check if .env file exists with required variables"""
    if not Path(".env").exists():
        print("❌ .env file not found!")
        print("Create .env file with:")
        print("GEMINI_API_KEY=your_key_here")
        print("GROQ_API_KEY=your_key_here")
        return False
    
    # Check if keys exist
    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    if not os.getenv("GEMINI_API_KEY"):
        print("❌ GEMINI_API_KEY not found in .env")
        return False
    
    if not os.getenv("GROQ_API_KEY"):
        print("❌ GROQ_API_KEY not found in .env")
        return False
    
    print("✅ Environment variables configured")
    return True

def check_youtube_credentials():
    """Check YouTube API credentials"""
    if not Path("client_secret.json").exists():
        print("❌ client_secret.json not found!")
        print("Download from Google Cloud Console:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create project → Enable YouTube Data API v3")
        print("3. Create OAuth 2.0 credentials")
        print("4. Download as client_secret.json")
        return False
    
    print("✅ YouTube credentials found")
    return True

def install_dependencies():
    """Install required packages"""
    try:
        import schedule
        import google_auth_oauthlib
        print("✅ Dependencies already installed")
        return True
    except ImportError:
        print("📦 Installing dependencies...")
        os.system("pip install google-auth-oauthlib schedule")
        return True

def main():
    print("🚀 Setting up YouTube Shorts Automation")
    print("=" * 40)
    
    # Create directories
    create_directories()
    
    # Check dependencies
    install_dependencies()
    
    # Check environment
    env_ok = check_env_file()
    youtube_ok = check_youtube_credentials()
    
    if env_ok and youtube_ok:
        print("\n✅ Setup complete!")
        print("\nTo test:")
        print("python start_auto_shorts.py --test")
        print("\nTo start automation:")
        print("python start_auto_shorts.py")
    else:
        print("\n❌ Setup incomplete. Fix the issues above.")
        sys.exit(1)

if __name__ == "__main__":
    main()