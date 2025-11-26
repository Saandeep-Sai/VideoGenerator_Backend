# 🎬 Complete Setup Guide: E2.Micro #2 YouTube Shorts Auto-Scheduler

**Goal:** Create a second E2.Micro instance that automatically generates and uploads YouTube Shorts 2x daily.

**Timeline:** ~20 minutes total

---

## **Phase 1: Create New E2.Micro Instance (5 minutes)**

### Step 1.1: Create Instance on Oracle Cloud

1. Go to: https://cloud.oracle.com/compute/instances
2. Click **"Create Instance"**
3. Configure:
   - **Name:** `video-shorts-scheduler` (or similar)
   - **Image:** Ubuntu 22.04 (same as main instance)
   - **Shape:** Ampere (always free) → E2.1.Micro
   - **VCN:** Same as main instance (if you want private network)
   - **Key Pair:** Download new key OR use existing if available
   - Click **"Create"**

4. Wait ~2 minutes for instance to start
5. Note the **Public IP Address** (e.g., `140.238.1.5`)

### Step 1.2: SSH into New Instance

```bash
# Windows PowerShell or Git Bash
ssh -i path/to/private-key ubuntu@140.238.1.5

# Linux/Mac
ssh -i ~/.ssh/oracle-key ubuntu@140.238.1.5

# You should see:
# ubuntu@video-shorts-scheduler:~$
```

---

## **Phase 2: Initial Setup (3 minutes)**

### Step 2.1: Update System

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y python3 python3-pip git
```

### Step 2.2: Clone Repository

```bash
cd ~
git clone https://github.com/Saandeep-Sai/VideoGenerator_Backend.git
cd VideoGenerator_Backend

# Verify clone
ls -la
# Should show: requirements.txt, youtube_shorts_scheduler.py, etc.
```

---

## **Phase 3: Copy Credentials from Main Instance (5 minutes)**

These files must be copied from your main E2.Micro #1 instance:

### Step 3.1: Get Credentials from Main Instance

From **your local machine** (Windows with VS Code), copy from main instance to local:

```bash
# Get the main instance IP (from Oracle Cloud Console)
# Example: 140.238.1.2

# Copy credentials to your local machine
scp -i path/to/oracle-key ubuntu@140.238.1.2:~/VideoGenerator_Backend/client_secret.json .
scp -i path/to/oracle-key ubuntu@140.238.1.2:~/VideoGenerator_Backend/token.json .
scp -i path/to/oracle-key ubuntu@140.238.1.2:~/VideoGenerator_Backend/.env .

# Verify they're in d:\Video_Generator\backend\
ls client_secret.json token.json .env
```

### Step 3.2: Copy to New Instance

```bash
# From your local machine, copy to new instance
scp -i ssh-key-2025-11-24.key client_secret.json ubuntu@144.24.56.59:~/VideoGenerator_Backend/
scp -i ssh-key-2025-11-24.key token.json ubuntu@144.24.56.59:~/VideoGenerator_Backend/
scp -i ssh-key-2025-11-24.key .env ubuntu@144.24.56.59:~/VideoGenerator_Backend/

# Verify on new instance (SSH into it first)
ssh -i ssh-key-2025-11-24.key ubuntu@144.24.56.59
cd ~/VideoGenerator_Backend
ls -la client_secret.json token.json .env
# Should all be there
```

### Step 3.3: Secure Permissions

```bash
# On the new instance
cd ~/VideoGenerator_Backend
chmod 600 client_secret.json token.json .env
chmod 600 .gitignore  # Ensure credentials won't be committed

# Verify
ls -la client_secret.json token.json .env
# Should show: -rw------- (600)
```

---

## **Phase 4: Install Dependencies (3 minutes)**

```bash
# On the new instance
cd ~/VideoGenerator_Backend

# Install all Python packages
pip3 install -r requirements.txt

# Verify key packages
pip3 list | grep -E "google|youtube|schedule|firebase"

# Expected output should show:
# firebase-admin
# google-api-python-client
# google-auth-oauthlib
# schedule
```

---

## **Phase 5: Configure Scheduler (2 minutes)**

### Step 5.1: (Optional) Customize Schedule Times

Edit `youtube_shorts_scheduler.py` to set your preferred upload times:

```bash
# On new instance
nano youtube_shorts_scheduler.py
```

Find this line (~line 460):
```python
UPLOAD_TIMES = ["09:00", "18:00"]  # UTC times
```

Change to your preferred times:
```python
UPLOAD_TIMES = ["08:00", "20:00"]  # UTC - change as needed
```

Save: `Ctrl+X` → `Y` → `Enter`

### Step 5.2: (Optional) Set via Environment Variable

Instead of editing, you can set via .env:

```bash
# Add to .env
echo "UPLOAD_TIMES=08:00,20:00" >> .env
```

---

## **Phase 6: Test Before Running (2 minutes)**

### Step 6.1: Test Topic Generation

```bash
# On new instance
python3 -c "
from youtube_shorts_scheduler import load_topic_history, get_next_topic

# Test if it can load topics
topics = [
    'OOP Concepts', 'Decorators', 'Async Programming', 
    'Data Structures', 'Design Patterns'
]
history = load_topic_history()
next_topic = get_next_topic(topics, history)
print(f'✅ Next topic to generate: {next_topic}')
"
```

Expected output:
```
✅ Next topic to generate: Decorators
```

### Step 6.2: Test Firebase Connection

```bash
# On new instance
python3 -c "
from firebase_admin import credentials, firestore, initialize_app
initialize_app(credentials.Certificate('firebase-key.json'))
db = firestore.client()
print('✅ Firebase connected!')
"
```

Or if using .env:

```bash
python3 -c "
import os
from dotenv import load_dotenv
load_dotenv()
print('✅ .env loaded successfully')
print(f'   GEMINI_API_KEY set: {bool(os.getenv(\"GEMINI_API_KEY\"))}')
print(f'   GROQ_API_KEY set: {bool(os.getenv(\"GROQ_API_KEY\"))}')
"
```

### Step 6.3: Test YouTube Authentication

```bash
# On new instance
python3 -c "
from youtube_upload import authenticate_youtube
try:
    yt = authenticate_youtube()
    print('✅ YouTube authentication successful!')
except Exception as e:
    print(f'❌ Error: {e}')
"
```

Expected output:
```
✅ YouTube authentication successful!
```

---

## **Phase 7: Run as Background Service (2 minutes)**

### Option A: Run in tmux (Recommended for Testing)

```bash
# On new instance
tmux new-session -d -s scheduler "cd ~/VideoGenerator_Backend && python3 youtube_shorts_scheduler.py"

# Check if running
tmux list-sessions
# Should show: scheduler

# View logs
tmux capture-pane -p -t scheduler
```

### Option B: Run as Systemd Service (Recommended for Production)

```bash
# Create service file
sudo nano /etc/systemd/system/youtube-shorts-scheduler.service
```

Paste this:
```ini
[Unit]
Description=YouTube Shorts Auto Scheduler
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/VideoGenerator_Backend
ExecStart=/usr/bin/python3 /home/ubuntu/VideoGenerator_Backend/youtube_shorts_scheduler.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Save and enable:
```bash
# Save: Ctrl+X → Y → Enter

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable youtube-shorts-scheduler
sudo systemctl start youtube-shorts-scheduler

# Check status
sudo systemctl status youtube-shorts-scheduler

# View logs
sudo journalctl -u youtube-shorts-scheduler -f
```

---

## **Phase 8: Verify It's Working (2 minutes)**

### Step 8.1: Check Logs

```bash
# If using tmux
tmux capture-pane -p -t scheduler

# If using systemd
sudo journalctl -u youtube-shorts-scheduler -n 50 -f

# Expected output should show:
# 📅 Scheduler started
# 🕐 Next scheduled upload: 09:00 UTC
# ⏰ Waiting for scheduled time...
```

### Step 8.2: Monitor Firebase

Go to Firebase Console → videodemo-52cdd → Firestore:
- Watch `youtube-shorts` collection
- At 09:00 UTC, new record should appear
- Status should change: `pending` → `processing` → `uploaded`

### Step 8.3: Check YouTube

After first scheduled upload (wait for 09:00 UTC):
1. Go to: https://youtube.com/shorts
2. Search for your channel
3. New Short should appear (Public)
4. Description includes topic

---

## **Phase 9: Configure Logging (Optional, 1 minute)**

### Step 9.1: Create Log Directory

```bash
# On new instance
cd ~/VideoGenerator_Backend
mkdir -p logs

# Create a simple logging config
python3 -c "
import logging
import logging.handlers

# Logs will be written to logs/scheduler.log
handler = logging.FileHandler('logs/scheduler.log')
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logger = logging.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.INFO)

print('✅ Logging configured')
"
```

### Step 9.2: View Logs

```bash
# Real-time logs
tail -f logs/scheduler.log

# Last 50 lines
tail -50 logs/scheduler.log

# All logs with timestamps
cat logs/scheduler.log
```

---

## **Phase 10: Troubleshooting**

If something doesn't work, use this checklist:

### Issue: "Token expired"
```bash
# Solution: Regenerate token.json on local machine
python3 generate_token_local.py
# Copy to new instance again
scp token.json ubuntu@140.238.1.5:~/VideoGenerator_Backend/
```

### Issue: "Firebase connection error"
```bash
# Check .env has credentials
cat .env | grep -i firebase

# Verify firebase-key.json exists
ls -la firebase-key.json

# If missing:
scp -i key ubuntu@main-instance:~/VideoGenerator_Backend/firebase-key.json .
```

### Issue: "No such module: schedule"
```bash
# Reinstall requirements
pip3 install -r requirements.txt --upgrade

# Or install individually
pip3 install schedule google-auth-oauthlib
```

### Issue: "YouTube upload fails silently"
```bash
# Check logs for errors
sudo journalctl -u youtube-shorts-scheduler -n 100

# Or run manually to see errors
python3 youtube_shorts_scheduler.py
# Ctrl+C after 30 seconds
```

### Issue: "Scheduled time not triggering"
```bash
# Check system time is correct
date
# Should be close to your UTC time

# Check if scheduler is running
ps aux | grep youtube_shorts_scheduler

# If not running, start it
sudo systemctl start youtube-shorts-scheduler
```

---

## **Phase 11: Monitoring Dashboard**

### Check Instance Status

```bash
# CPU and Memory
htop

# Disk space
df -h

# Python processes
ps aux | grep python3

# Network connections
netstat -an | grep ESTABLISHED
```

### Monitor Firebase

Create a simple Python script to check status:

```bash
# Create script
cat > check_status.py << 'EOF'
from firebase_admin import credentials, firestore, initialize_app
from datetime import datetime, timedelta

initialize_app(credentials.Certificate('firebase-key.json'))
db = firestore.client()

# Get last 5 uploaded shorts
shorts = db.collection('youtube-shorts').order_by('uploaded_at', direction='DESC').limit(5).stream()

print("📊 Last 5 YouTube Shorts:")
for doc in shorts:
    data = doc.to_dict()
    print(f"  • {data.get('topic')} - {data.get('status')} - {data.get('uploaded_at')}")
EOF

python3 check_status.py
```

---

## **Quick Reference Commands**

| Task | Command |
|------|---------|
| **Start scheduler** | `sudo systemctl start youtube-shorts-scheduler` |
| **Stop scheduler** | `sudo systemctl stop youtube-shorts-scheduler` |
| **Restart** | `sudo systemctl restart youtube-shorts-scheduler` |
| **Check status** | `sudo systemctl status youtube-shorts-scheduler` |
| **View logs** | `sudo journalctl -u youtube-shorts-scheduler -f` |
| **Edit schedule times** | `nano youtube_shorts_scheduler.py` |
| **Test authentication** | `python3 -c "from youtube_upload import authenticate_youtube; authenticate_youtube()"` |
| **Check resources** | `free -h && df -h` |
| **SSH to instance** | `ssh -i key ubuntu@140.238.1.5` |

---

## **Success Checklist**

- [ ] E2.Micro #2 instance created
- [ ] Code cloned from GitHub
- [ ] client_secret.json copied (permissions: 600)
- [ ] token.json copied (permissions: 600)
- [ ] .env copied with API keys
- [ ] Dependencies installed (`pip3 install -r requirements.txt`)
- [ ] YouTube authentication tested (✅ successful)
- [ ] Firebase connection tested (✅ successful)
- [ ] Scheduler running (systemd or tmux)
- [ ] Logs showing "Waiting for scheduled time..."
- [ ] First scheduled upload executed (check Firebase)
- [ ] Video appeared on YouTube as Public

---

## **What Happens Now**

1. **Daily at 09:00 UTC:**
   - Scheduler picks a new programming topic (not repeated)
   - Generates video (~5-10 minutes)
   - Uploads to YouTube as PUBLIC
   - Updates Firebase `youtube-shorts` collection
   - Posts video to your channel

2. **Daily at 18:00 UTC:**
   - Same process repeats
   - Different topic selected

3. **Your Main Instance (#1):**
   - Still handles manual API requests
   - Runs independently
   - No interference with scheduler

---

## **Next Steps**

1. ✅ Complete all 11 phases
2. ✅ Wait for first scheduled upload (watch logs)
3. ✅ Verify video appears on YouTube
4. ✅ Check Firebase records
5. ✅ Set up monitoring/alerts (optional)
6. ✅ Relax - it's now fully automated! 🎉

---

**Ready to start? Begin with Phase 1 - create the new E2.Micro instance!** 🚀
