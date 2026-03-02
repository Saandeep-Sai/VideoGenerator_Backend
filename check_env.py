"""Quick environment check script."""
import os
from dotenv import load_dotenv
load_dotenv(override=True)

print('=== Environment Variables Check ===')
print(f'GEMINI_API_KEY: {"[OK] Set" if os.getenv("GEMINI_API_KEY") else "[X] Missing"}')
print(f'OPENROUTER_API_KEY: {"[OK] Set" if os.getenv("OPENROUTER_API_KEY") else "[X] Missing"}')
print(f'GROQ_API_KEY: {"[OK] Set" if os.getenv("GROQ_API_KEY") else "[X] Missing"}')
print(f'FIREBASE_PROJECT_ID: {os.getenv("FIREBASE_PROJECT_ID", "[X] Missing")}')

cred_b64 = os.getenv("FIREBASE_CREDENTIALS_BASE64", "")
if cred_b64:
    print(f'FIREBASE_CREDENTIALS_BASE64: [OK] Set ({len(cred_b64)} chars)')
else:
    print('FIREBASE_CREDENTIALS_BASE64: [X] Missing')

yt_channel = os.getenv("YOUTUBE_CHANNEL_ID")
if yt_channel:
    print(f'YOUTUBE_CHANNEL_ID: {yt_channel}')
else:
    print('YOUTUBE_CHANNEL_ID: [!] Missing (will use mock mode for YouTube)')

print()

# Test base64 decode
import base64
import json

if cred_b64:
    try:
        cred_json = base64.b64decode(cred_b64).decode('utf-8')
        cred_dict = json.loads(cred_json)
        print('=== Firebase Credentials ===')
        print(f'Project ID: {cred_dict.get("project_id")}')
        print(f'Client Email: {cred_dict.get("client_email")}')
        print('[OK] Credentials decode successfully')
    except Exception as e:
        print(f'[X] Failed to decode: {e}')

