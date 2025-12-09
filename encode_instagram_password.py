#!/usr/bin/env python3
"""
Helper script to encode Instagram password to base64
Run this to generate the base64 encoded password for .env file
"""

import base64
import getpass

def encode_password():
    """Encode password to base64 TWICE for extra security"""
    print("=" * 60)
    print("Instagram Password Encoder (Double Base64)")
    print("=" * 60)
    print()
    print("This script will encode your Instagram password to base64 TWICE")
    print("This adds an extra layer of obfuscation")
    print("You can then use it in .env as INSTAGRAM_PASSWORD_BASE64")
    print()
    
    # Get password securely (won't show on screen)
    password = getpass.getpass("Enter your Instagram password: ")
    
    if not password:
        print("❌ Password cannot be empty")
        return
    
    # First encoding
    password_bytes = password.encode('utf-8')
    base64_once = base64.b64encode(password_bytes)
    
    # Second encoding (encode the already encoded string)
    base64_twice = base64.b64encode(base64_once)
    base64_string = base64_twice.decode('utf-8')
    
    print()
    print("=" * 60)
    print("✅ Password double-encoded successfully!")
    print("=" * 60)
    print()
    print("Add this to your .env file:")
    print()
    print(f'INSTAGRAM_PASSWORD_BASE64="{base64_string}"')
    print()
    print("⚠️  IMPORTANT:")
    print("- This password is base64 encoded TWICE")
    print("- Remove any INSTAGRAM_PASSWORD entry from .env")
    print("- Keep this encoded password secure")
    print("- Don't share the .env file")
    print("- Even if leaked, it's harder to decode (requires 2 decodes)")
    print()

if __name__ == "__main__":
    try:
        encode_password()
    except KeyboardInterrupt:
        print("\n\n❌ Cancelled by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
