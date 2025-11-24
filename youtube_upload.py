import os
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# 1. Define the scopes (permissions)
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def authenticate_youtube():
    creds = None
    # The file token.json stores the user's access and refresh tokens.
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "client_secret.json", SCOPES
            )
            
            # Try browser-based authentication first (works on local machines with GUI)
            # If that fails (headless instances), provide manual instructions
            try:
                creds = flow.run_local_server(port=0)
            except Exception as e:
                if "could not locate runnable browser" in str(e):
                    print("\n" + "=" * 70)
                    print("⚠️  NO BROWSER DETECTED (Headless Environment)")
                    print("=" * 70)
                    print("\n📋 Run this on your LOCAL machine instead:")
                    print("   python3 generate_youtube_token.py")
                    print("\n   OR copy token.json from your local machine:")
                    print("   scp token.json ubuntu@<instance-ip>:~/VideoGenerator_Backend/")
                    print("\n" + "=" * 70)
                    raise RuntimeError(
                        "YouTube authentication requires token.json. "
                        "Generate it on your local machine using: python3 generate_youtube_token.py"
                    )
                else:
                    raise
        
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)

def upload_short(video_path, title, description):
    youtube = authenticate_youtube()

    print(f"Uploading {video_path}...")

    # 2. Configure the upload body
    request_body = {
        "snippet": {
            "title": title[:100], 
            "description": description + " #Shorts",
            "tags": ["Shorts", "Programming", "Coding", "Tutorial", "Education"],
            "categoryId": "27"  # Education category
        },
        "status": {
            "privacyStatus": "public",  # Auto-publish
            "selfDeclaredMadeForKids": False
        }
    }

    # 3. Upload the file
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    
    request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media
    )

    response = request.execute()
    print(f"Upload Successful! Video ID: {response['id']}")
    return response

if __name__ == "__main__":
    # REPLACE with your actual file path
    VIDEO_FILE = "test_short.mp4" 
    
    if os.path.exists(VIDEO_FILE):
        upload_short(
            VIDEO_FILE, 
            "My Automated Short", 
            "Uploaded via Python API"
        )
    else:
        print(f"Error: File {VIDEO_FILE} not found.")