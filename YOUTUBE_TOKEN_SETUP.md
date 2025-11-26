# 🎥 YouTube OAuth Token Setup for Headless Instances

**TL;DR:** Your instance doesn't have a browser, so you need to generate the token on your LOCAL machine and copy it to the instance.

---

## ✅ Option 1: Generate Token on LOCAL Machine (Recommended)

This is the **easiest and most reliable** method.

### Step 1: On your LOCAL machine (Windows/Mac with VS Code)

```bash
cd d:\Video_Generator\backend

# Run the headless token generator
python3 generate_youtube_token.py

# OR use the original method (your local machine has a browser)
python3 -c "from youtube_upload import authenticate_youtube; authenticate_youtube()"
```

**What happens:**

- A browser window opens
- You log in with your Google account
- Grant YouTube upload permissions
- `token.json` is created in your local `d:\Video_Generator\backend\`

### Step 2: Copy token.json to your instance

```bash
# Get your instance IP
# Example: 140.238.1.2

scp token.json ubuntu@140.238.1.2:~/VideoGenerator_Backend/

# Verify it arrived
ssh ubuntu@140.238.1.2 "ls -la ~/VideoGenerator_Backend/token.json"
```

### Step 3: Set permissions on instance

```bash
ssh ubuntu@140.238.1.2
cd ~/VideoGenerator_Backend
chmod 600 token.json
ls -la token.json  # Should show: -rw------- (600)
```

✅ **Done!** Your instance can now upload to YouTube.

---

## 🔧 Option 2: Use the Headless Script on Instance

If you can SSH into your instance and access a terminal on your LOCAL machine:

### Step 1: On your INSTANCE, run the headless generator

```bash
ssh ubuntu@your-instance-ip
cd ~/VideoGenerator_Backend
python3 generate_youtube_token.py
```

### Step 2: You'll see this:

```
======================================================================
🎬 HEADLESS YOUTUBE OAUTH TOKEN GENERATION
======================================================================

📋 STEP 1: Copy this URL and paste it in your LOCAL browser:
----------------------------------------------------------------------
https://accounts.google.com/o/oauth2/auth?client_id=589521187290...
----------------------------------------------------------------------

✅ STEP 2: After visiting the URL and granting permission:
   1. You'll be redirected to: http://localhost/?code=AUTH_CODE
   2. Copy the 'code' parameter from the URL
   3. Paste it below (you may only see the code, not the full URL)

🔑 Paste the authorization code here:
```

### Step 3: On your LOCAL machine

1. **Copy the URL** from the output above
2. **Paste it in your browser** (Chrome, Firefox, Safari, etc.)
3. **Log in with Google** and grant YouTube permissions
4. **You'll be redirected** to: `http://localhost/?code=4/0A...`
5. **Copy the code** (the long string after `code=`)
6. **Paste it back** into the instance terminal

### Step 4: Token is saved!

```
======================================================================
✅ SUCCESS! token.json created and saved securely
======================================================================

📊 Token Information:
   - User: your-email@gmail.com
   - Scope: YouTube Upload
   - Expires: Never (refresh token available)
   - File: token.json (permissions: 600)

✅ You're ready to use YouTube uploads!
   Run: python3 run_generate_worker.py
   Videos with video_type='short' will auto-upload to YouTube
```

✅ **Done!** Your instance can now upload to YouTube.

---

## 🚀 Option 3: Use Environment Variable (For CI/CD)

If you want to automate this for deployments:

### Step 1: Encode your local token.json

On your LOCAL machine:

```bash
python3 -c "
import base64
import json

# Read your local token.json
with open('token.json', 'rb') as f:
    token_data = f.read()

# Encode to base64
encoded = base64.b64encode(token_data).decode()
print('YOUTUBE_TOKEN_JSON=' + encoded)
"
```

Copy the output (it's a long string starting with `YOUTUBE_TOKEN_JSON=`)

### Step 2: Set environment variable on instance

```bash
# Add to ~/.bashrc or .env file
export YOUTUBE_TOKEN_JSON="<paste-the-long-base64-string-here>"

# Or set it directly in .env
echo "YOUTUBE_TOKEN_JSON=<paste-here>" >> .env
```

### Step 3: Generate token from environment

```bash
python3 generate_youtube_token_alt.py
# Choose option 2 (From environment variable)
```

✅ **Done!** Token is now saved from the environment variable.

---

## ✅ Verify Everything Works

After any of the three options above:

```bash
# On the instance
cd ~/VideoGenerator_Backend

# Check token.json exists
ls -la token.json
# Should show: -rw------- (600) with your username

# Test authentication
python3 -c "
from youtube_upload import authenticate_youtube
try:
    yt = authenticate_youtube()
    print('✅ YouTube authentication successful!')
except Exception as e:
    print(f'❌ Error: {e}')
"
```

---

## 🎯 Now Test the Full Flow

Once token.json is in place:

```bash
# Start the worker
python3 run_generate_worker.py

# In another terminal, send a test request
curl -X POST http://localhost:8000/api/generate/ \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "2.5d and 2d Visuals",
    "duration": 60,
    "aspect_ratio": "9:16",
    "video_type": "short"
  }'

# Expected output:
# {
#   "status": "queued",
#   "message": "Video job has been queued.",
#   "job_id": "abc123..."
# }

# Monitor worker logs - should show:
# 🎬 Detected YouTube Short - uploading to YouTube...
# ✅ YouTube Short uploaded: <video_id>
# 📺 Watch: https://youtube.com/watch?v=<video_id>
```

---

## 🛠️ Troubleshooting

| Problem                                               | Solution                                                  |
| ----------------------------------------------------- | --------------------------------------------------------- |
| `FileNotFoundError: token.json`                       | Use **Option 1**: Generate locally and copy               |
| `webbrowser.Error: could not locate runnable browser` | Use **Option 1** or **Option 2** (headless script)        |
| `TokenError: code not recognized`                     | Make sure you copied the EXACT code from the URL          |
| `Permission denied on token.json`                     | Run `chmod 600 token.json`                                |
| `ModuleNotFoundError: google_auth_oauthlib`           | Run `pip3 install -r requirements.txt`                    |
| Token expired                                         | Delete token.json, regenerate (refresh token auto-renews) |

---

## 📋 Quick Reference

| Task                           | Command                                                                                |
| ------------------------------ | -------------------------------------------------------------------------------------- |
| Generate token (local machine) | `python3 generate_youtube_token.py`                                                    |
| Copy to instance               | `scp token.json ubuntu@<ip>:~/VideoGenerator_Backend/`                                 |
| Secure permissions             | `chmod 600 token.json`                                                                 |
| Test authentication            | `python3 -c "from youtube_upload import authenticate_youtube; authenticate_youtube()"` |
| Start worker                   | `python3 run_generate_worker.py`                                                       |
| Send test request              | `curl -X POST http://localhost:8000/api/generate/ ...`                                 |

---

## ✨ What Happens Next

Once token.json is in place:

1. **You send request**: `POST /api/generate/` with `"video_type": "short"`
2. **Worker receives job** from Firebase
3. **Video is generated** (narration → audio → Manim scripts → rendering)
4. **Video uploads** to Oracle Object Storage
5. **YouTube upload starts** ← _This is where token.json is used_
6. **Firebase updates** with YouTube URL and video ID
7. **Video is LIVE** on YouTube as PUBLIC

All automatically! 🚀

---

**Which option will you use? Let me know if you need help with any step!**
