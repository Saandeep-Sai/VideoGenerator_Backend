# Credential Management Guide

## Files That MUST NOT Be Committed

These files are **NEVER** committed to git (they contain secret API keys):

- ✅ `client_secret.json` — Google OAuth credentials (YouTube API)
- ✅ `token.json` — Refresh token for YouTube API access
- ✅ `firebase-key.json` — Firebase service account key
- ✅ `.env` — Environment variables with API keys

All of these are now in `.gitignore` — they will not be tracked by git.

---

## How to Deploy Credentials to Instances

### Option 1: Manual Copy via SCP (Recommended for Production)

**Step 1: On your local machine, copy credentials to the VM**

```bash
# Copy YouTube credentials to main backend (A1.Flex/generation)
scp client_secret.json ubuntu@<MAIN_VM_IP>:~/video_generator/backend/
scp token.json ubuntu@<MAIN_VM_IP>:~/video_generator/backend/

# Copy to E2.Micro (scheduler instance)
scp client_secret.json ubuntu@<E2_MICRO_IP>:~/video_generator/backend/
scp token.json ubuntu@<E2_MICRO_IP>:~/video_generator/backend/
```

**Step 2: Copy .env file**

```bash
# Copy to main backend
scp .env ubuntu@<MAIN_VM_IP>:~/video_generator/backend/

# Copy to scheduler instance
scp .env ubuntu@<E2_MICRO_IP>:~/video_generator/backend/
```

**Step 3: Restrict permissions (on the VM)**

```bash
# SSH into VM
ssh ubuntu@<VM_IP>

# Restrict file permissions (only owner can read)
chmod 600 client_secret.json token.json .env
chmod 600 firebase-key.json  # if using Firebase

# Verify
ls -la client_secret.json token.json .env
# Should show: -rw------- (600 permissions)
```

---

### Option 2: Use Environment Variables (Alternative)

Instead of keeping files, encode credentials as base64 in `.env`:

**Step 1: Encode credentials**

On your local machine:

```bash
# Encode client_secret.json
cat client_secret.json | base64 -w 0 > client_secret.b64

# Encode token.json
cat token.json | base64 -w 0 > token.b64

# Encode Firebase key (if using)
cat firebase-key.json | base64 -w 0 > firebase-key.b64
```

**Step 2: Add to .env**

```env
# Base64-encoded credentials
CLIENT_SECRET_B64=<paste output from client_secret.b64>
TOKEN_B64=<paste output from token.b64>
FIREBASE_CREDENTIALS_B64=<paste output from firebase-key.b64>
```

**Step 3: Update Python scripts**

Modify scripts to decode from environment variables:

```python
import base64
import json
import os

# Decode and load client_secret
client_secret_b64 = os.getenv("CLIENT_SECRET_B64")
if client_secret_b64:
    client_secret_dict = json.loads(
        base64.b64decode(client_secret_b64).decode()
    )
    # Save to temporary file
    with open("client_secret.json", "w") as f:
        json.dump(client_secret_dict, f)

# Similar for token.json and firebase-key.json
```

**Pros**:

- No files to copy
- Works with environment variables
- Good for containerized deployments

**Cons**:

- More complex
- Larger .env file
- Need to update code

---

### Option 3: Use Secrets Management Service (Enterprise)

For production systems, use:

- **HashiCorp Vault** — Secret storage
- **AWS Secrets Manager** — AWS-native secrets
- **Google Secret Manager** — GCP-native secrets
- **Azure Key Vault** — Azure-native secrets
- **1Password / LastPass** — Team credential sharing

Not recommended for small deployments, but good to know for scaling.

---

## Setup Process (Recommended Approach)

### On Main Backend (A1.Flex or generation VM)

```bash
# SSH in
ssh ubuntu@<MAIN_VM_IP>

# Create directories if not done
mkdir -p ~/video_generator/backend
cd ~/video_generator/backend

# Wait for files to be copied via SCP
# (From local: scp client_secret.json token.json .env ubuntu@<IP>:~/video_generator/backend/)

# Verify files exist
ls -la client_secret.json token.json .env

# Restrict permissions
chmod 600 client_secret.json token.json .env

# Setup Python venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Test YouTube setup
python setup_youtube_automation.py

# If token.json is old, refresh it:
# The script will auto-refresh if needed, or run:
python -c "from google.auth.transport.requests import Request; from google.oauth2.credentials import Credentials; creds = Credentials.from_authorized_user_file('token.json', ['https://www.googleapis.com/auth/youtube.upload']); creds.refresh(Request()); print('Token refreshed')"
```

### On E2.Micro (Scheduler VM)

```bash
# SSH in
ssh ubuntu@<E2_MICRO_IP>

# Create directories
mkdir -p ~/video_generator/backend
cd ~/video_generator/backend

# Wait for credentials via SCP
# (From local: scp client_secret.json token.json .env ubuntu@<IP>:~/video_generator/backend/)

# Verify
ls -la client_secret.json token.json .env

# Restrict permissions
chmod 600 client_secret.json token.json .env

# Setup Python
python3 -m venv .venv
source .venv/bin/activate
pip install google-auth-oauthlib google-api-python-client firebase-admin python-dotenv schedule

# Test YouTube auth
python youtube_shorts_scheduler.py --test
```

---

## Credential File Locations

After setup, your instance should have:

```
~/video_generator/backend/
├── .env                          ← Environment variables (IGNORED)
├── client_secret.json            ← Google OAuth (IGNORED)
├── token.json                    ← YouTube refresh token (IGNORED)
├── firebase-key.json             ← Firebase service account (IGNORED, if using)
├── .venv/                        ← Python venv
├── youtube_shorts_scheduler.py   ← Scheduler script
├── requirements.txt              ← Dependencies
└── ... other files
```

None of the `.json` or `.env` files are in git — they're unique to each instance.

---

## Creating YouTube Credentials (First Time Setup)

If you don't have `client_secret.json` and `token.json` yet:

**Step 1: Get Google OAuth credentials**

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project or select existing
3. Enable YouTube Data API v3
4. Create OAuth 2.0 credentials (Desktop app)
5. Download as `client_secret.json`
6. Save locally

**Step 2: Generate token.json**

Run this on your local machine or main backend:

```bash
python setup_youtube_automation.py
```

This will:

1. Open a browser for you to authorize
2. Create `token.json` after authorization
3. Save refresh tokens for future use

**Step 3: Copy both files to instances**

```bash
scp client_secret.json ubuntu@<MAIN_VM_IP>:~/video_generator/backend/
scp token.json ubuntu@<MAIN_VM_IP>:~/video_generator/backend/

scp client_secret.json ubuntu@<E2_MICRO_IP>:~/video_generator/backend/
scp token.json ubuntu@<E2_MICRO_IP>:~/video_generator/backend/
```

---

## Firebase Credentials

If using Firebase Firestore:

**Step 1: Get service account key**

1. Go to [Firebase Console](https://console.firebase.google.com)
2. Select your project
3. Settings → Service Accounts
4. Generate new private key → Downloads as JSON

**Step 2: Encode it for .env (Option 2) or copy it (Option 1)**

Option 1 (file-based):

```bash
scp firebase-key.json ubuntu@<VM_IP>:~/video_generator/backend/
chmod 600 firebase-key.json
```

Option 2 (environment variable):

```bash
cat firebase-key.json | base64 -w 0
# Paste into .env as FIREBASE_CREDENTIALS_B64
```

**Step 3: Add to .env**

```env
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_CREDENTIALS_BASE64=<base64 encoded key>
```

---

## .env File Example

Create a template (safe to commit) and a real one (git-ignored):

**`.env.example`** (commit this to git):

```env
# YouTube
GENERATOR_URL=http://localhost:8000

# Firebase
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_CREDENTIALS_BASE64=<base64-encoded-key>

# Schedule
UPLOAD_TIMES=09:00,18:00

# Gemini/Groq/TTS API Keys
GEMINI_API_KEY=<your-key>
GROQ_API_KEY=<your-key>
ELEVENLABS_API_KEY=<your-key>
```

**`.env`** (git-ignored, fill in real values):

```env
GENERATOR_URL=http://192.0.2.100:8000
FIREBASE_PROJECT_ID=my-actual-project
FIREBASE_CREDENTIALS_BASE64=LS0tLS1CRUdJTi... (real base64)
UPLOAD_TIMES=09:00,18:00
GEMINI_API_KEY=AIzaSy... (real key)
GROQ_API_KEY=gsk_... (real key)
ELEVENLABS_API_KEY=sk_... (real key)
```

Users can copy `.env.example` to `.env` and fill in their own credentials.

---

## Security Best Practices

✅ **DO:**

- Keep `.env`, `client_secret.json`, `token.json` in `.gitignore`
- Use file permissions `600` (only owner can read)
- Rotate API keys regularly
- Use separate credentials for each environment (local, staging, prod)
- Store credentials in secure vaults for team sharing

❌ **DON'T:**

- Commit credentials to git (even private repos)
- Share credentials via email or Slack
- Hardcode API keys in Python files
- Use weak file permissions (777, 644)
- Use the same credentials for multiple projects

---

## Testing Credential Setup

### Test YouTube

```bash
source .venv/bin/activate
python youtube_shorts_scheduler.py --test
```

Should show:

```
✅ YouTube API: Connected
```

### Test Firebase

```bash
python -c "from generator.firebase_utils import initialize_firebase; initialize_firebase(); print('✅ Firebase connected')"
```

### Test API Keys

```bash
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('GEMINI_API_KEY:', 'set' if os.getenv('GEMINI_API_KEY') else 'NOT SET')"
```

---

## Quick Deployment Command

```bash
# Local machine
cd ~/your_repo/backend

# Copy to main backend
scp client_secret.json token.json .env ubuntu@<MAIN_IP>:~/video_generator/backend/
ssh ubuntu@<MAIN_IP> "cd ~/video_generator/backend && chmod 600 client_secret.json token.json .env"

# Copy to scheduler (E2.Micro)
scp client_secret.json token.json .env ubuntu@<E2_IP>:~/video_generator/backend/
ssh ubuntu@<E2_IP> "cd ~/video_generator/backend && chmod 600 client_secret.json token.json .env"

# Test both
ssh ubuntu@<MAIN_IP> "cd ~/video_generator/backend && source .venv/bin/activate && python -m generator.views"
ssh ubuntu@<E2_IP> "cd ~/video_generator/backend && source .venv/bin/activate && python youtube_shorts_scheduler.py --test"
```

---

## Troubleshooting

### "FileNotFoundError: client_secret.json"

- Copy `client_secret.json` to VM: `scp client_secret.json ubuntu@<IP>:~/video_generator/backend/`
- Verify it exists: `ssh ubuntu@<IP> ls -la ~/video_generator/backend/client_secret.json`

### "Token expired"

- Run: `python setup_youtube_automation.py`
- Or let the script auto-refresh (if implemented)

### "Firebase credentials invalid"

- Check base64 encoding: `cat firebase-key.json | base64 -w 0`
- Ensure `FIREBASE_PROJECT_ID` matches your project ID
- Test: `python -c "from generator.firebase_utils import initialize_firebase; initialize_firebase()"`

### "Permission denied: .env"

- Fix permissions: `chmod 600 .env client_secret.json token.json`

---

## Summary

**For production deployment:**

1. ✅ Add credentials to `.gitignore` (already done)
2. ✅ Get `client_secret.json`, `token.json`, `firebase-key.json`
3. ✅ Create `.env` with all API keys
4. ✅ Copy files to VMs via SCP (never git push them)
5. ✅ Set file permissions to `600`
6. ✅ Test connections before deploying

**Never commit secrets to git.** Always use SCP or environment variables for credentials.
