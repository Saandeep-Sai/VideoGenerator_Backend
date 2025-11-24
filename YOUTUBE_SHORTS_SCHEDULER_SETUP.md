# YouTube Shorts Scheduler Setup for Oracle E2.1.Micro

## Overview

This scheduler runs on a small VM (E2.1.Micro) and automatically:
1. **Generates** a YouTube Short (9:16 vertical format) by calling your main backend
2. **Uploads** to YouTube as **PUBLIC** (not private or unlisted)
3. **Tracks** in Firebase `youtube-shorts` collection with status, video ID, URL
4. **Retries** on failure with exponential backoff (max 3 attempts)
5. **Runs twice daily** (9 AM & 6 PM UTC by default, configurable)

## Prerequisites

- **Main backend instance** running and accessible (e.g., A1.Flex with video generation)
- **YouTube OAuth credentials**: `client_secret.json` and `token.json` (run `setup_youtube_automation.py` first)
- **Firebase Firestore** configured with `FIREBASE_CREDENTIALS_BASE64` and `FIREBASE_PROJECT_ID` in `.env`
- **E2.1.Micro instance** with Python 3, git, venv

## Setup Steps

### Step 1: SSH into E2.1.Micro
```bash
ssh ubuntu@<YOUR_E2_MICRO_IP>
```

### Step 2: Clone and Setup Python
```bash
# Create directory
mkdir -p ~/video_generator
cd ~/video_generator

# Clone repo
git clone https://github.com/Saandeep-Sai/VideoGenerator_Backend.git backend
cd backend

# Create venv
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install google-auth-oauthlib google-api-python-client
pip install firebase-admin
pip install python-dotenv schedule
```

### Step 3: Copy YouTube Credentials
Copy these files from your main backend to E2.1.Micro:

```bash
# From your LOCAL machine (or main backend):
scp client_secret.json ubuntu@<E2_MICRO_IP>:~/video_generator/backend/
scp token.json ubuntu@<E2_MICRO_IP>:~/video_generator/backend/
```

### Step 4: Configure .env
On the E2.1.Micro, edit `.env`:

```bash
nano .env
```

Add/update these:
```env
# Main backend instance (where generation happens)
GENERATOR_URL=http://<MAIN_BACKEND_IP>:8000

# Firebase credentials (from your project)
FIREBASE_CREDENTIALS_BASE64=<your_base64_encoded_firebase_json>
FIREBASE_PROJECT_ID=your-firebase-project-id

# Schedule times (UTC, comma-separated, HH:MM format)
UPLOAD_TIMES=09:00,18:00
```

**To get FIREBASE_CREDENTIALS_BASE64**:
```bash
# On local machine, encode your Firebase JSON:
cat firebase-key.json | base64 -w 0
# Copy output and paste into .env
```

### Step 5: Test Connections
```bash
source .venv/bin/activate
python youtube_shorts_scheduler.py --test
```

Expected output:
```
✅ YouTube API: Connected
✅ Firebase: Connected
```

### Step 6: Test Single Upload Cycle
```bash
source .venv/bin/activate
python youtube_shorts_scheduler.py --once
```

This will:
1. Pick a random programming topic
2. Request generation from main backend
3. Wait for the video to be ready
4. Upload to YouTube (PUBLIC)
5. Save to Firebase `youtube-shorts` collection

### Step 7: Setup Systemd Auto-Start
```bash
# Copy service file
sudo cp youtube_shorts_scheduler.service /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable youtube_shorts_scheduler
sudo systemctl start youtube_shorts_scheduler

# Check status
sudo systemctl status youtube_shorts_scheduler

# View logs
sudo journalctl -u youtube_shorts_scheduler -f
```

## Usage

### Manual Modes
```bash
source .venv/bin/activate

# Generate & upload one short immediately
python youtube_shorts_scheduler.py --once

# Run scheduled uploads (09:00, 18:00 UTC by default)
python youtube_shorts_scheduler.py --schedule

# Test connections without uploading
python youtube_shorts_scheduler.py --test
```

### Systemd Commands
```bash
# View status
sudo systemctl status youtube_shorts_scheduler

# View live logs
sudo journalctl -u youtube_shorts_scheduler -f

# View last 100 lines
sudo journalctl -u youtube_shorts_scheduler -n 100

# Stop/start/restart
sudo systemctl stop youtube_shorts_scheduler
sudo systemctl start youtube_shorts_scheduler
sudo systemctl restart youtube_shorts_scheduler

# Disable auto-start
sudo systemctl disable youtube_shorts_scheduler
```

## What Gets Uploaded

Each short is uploaded with:
- **Title**: `{topic} in {duration} Seconds! #Shorts`
- **Description**: Programming tips + hashtags
- **Privacy**: `PUBLIC` (not private, not unlisted)
- **Category**: Education (27)
- **Tags**: Shorts, Programming, Coding, Tutorial, Education
- **Made for Kids**: False
- **Embeddable**: True
- **License**: Creative Commons

## Firebase Structure

Videos are saved in the `youtube-shorts` collection:

```json
{
  "topic": "Python List Comprehensions",
  "video_id": "dQw4w9WgXcQ",
  "status": "uploaded",
  "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
  "uploaded_at": "2025-11-24T15:30:45.123Z",
  "privacy": "public"
}
```

Failed uploads are also logged:
```json
{
  "topic": "Python Exception Handling",
  "video_id": "failed_1234567890",
  "status": "failed",
  "error": "Generation timed out",
  "uploaded_at": "2025-11-24T15:31:00.000Z"
}
```

## Configuration

### Change Schedule Times
Edit `.env`:
```env
# Wake up at 7 AM, upload at 2 PM
UPLOAD_TIMES=07:00,14:00
```

### Retry on Failure
The script automatically retries up to 3 times on failure (configurable in code).

### Topic List
Topics are hardcoded in the script. Edit the `self.programming_topics` list to add more:
```python
self.programming_topics = [
    "Your Topic Here",
    "Another Topic",
    ...
]
```

## Troubleshooting

### "Cannot reach backend"
- Check `GENERATOR_URL` in `.env` is correct
- Ensure main backend is running: `curl http://<MAIN_IP>:8000/api/health/`
- Check firewall rules allow port 8000 from E2.Micro

### "YouTube authentication failed"
- Make sure `token.json` exists
- Run `python setup_youtube_automation.py` to refresh token
- Check `client_secret.json` is valid

### "Firebase not enabled"
- Check `FIREBASE_CREDENTIALS_BASE64` and `FIREBASE_PROJECT_ID` in `.env`
- Ensure Firebase JSON is valid (base64 encoded correctly)
- Check Firebase project allows read/write to `youtube-shorts` collection

### "Generation timed out"
- Default timeout is 10 minutes (600s)
- Check generation on main backend is working
- View main backend logs to diagnose generation issues

### Videos not uploading
- Check YouTube quota (50 uploads/day per default quota)
- Ensure `token.json` has fresh credentials
- Check YouTube API is enabled in Google Cloud Console

### High CPU/Memory on E2.Micro
- This script uses ~10-20MB RAM
- If spiking, check if generation is running locally (shouldn't be)
- Restart: `sudo systemctl restart youtube_shorts_scheduler`

## Logs

Log files:
- **Systemd journal**: `sudo journalctl -u youtube_shorts_scheduler -f`
- **Local file**: `youtube_shorts_scheduler.log` (in backend directory)
- **History file**: `youtube_shorts_history.json` (uploaded shorts)

## Notes

- **No local generation**: This VM sends requests to main backend, it doesn't render videos
- **30-day topic memory**: Avoids repeating the same topic within 30 days
- **Public uploads only**: All videos are immediately public (visible to everyone)
- **Firebase optional**: Works without Firebase (just logs locally)
- **Error recovery**: Retries failed uploads and logs to Firebase

## Next Steps

1. **Deploy on E2.1.Micro** using steps above
2. **Monitor logs** for first 24 hours: `sudo journalctl -u youtube_shorts_scheduler -f`
3. **Check Firebase** `youtube-shorts` collection to see uploaded videos
4. **Adjust schedule** in `.env` if needed (UPLOAD_TIMES)
5. **Add more topics** if you want variety

---

**Quick Start Command** (copy-paste on E2.1.Micro):
```bash
cd ~/video_generator/backend && source .venv/bin/activate && python youtube_shorts_scheduler.py --test
```

If all tests pass, enable systemd and you're done!
