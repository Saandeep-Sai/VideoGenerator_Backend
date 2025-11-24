# Setup & Run Shorts Request Sender on Oracle E2.1.Micro

## What this does
- **Tiny footprint**: Sends HTTP requests to your main backend instance (does NO rendering, NO generation)
- **No dependencies**: Only requires `requests`, `schedule`, and `python-dotenv` (MB in size)
- **Runs on E2.1.Micro**: 1 CPU, 1GB RAM — perfect for this weak VM
- **Avoids repetition**: Tracks topics used in last 30 days, picks random unused ones
- **Sends to Firebase**: Optional Realtime Database updates if you configure it

## Quick Setup on E2.1.Micro

### Step 1: SSH into the instance
```bash
ssh ubuntu@<YOUR_E2_MICRO_PUBLIC_IP>
```

### Step 2: Clone and setup
```bash
# Create directory
mkdir -p ~/video_generator
cd ~/video_generator

# Clone repo (or copy from main instance)
git clone https://github.com/Saandeep-Sai/VideoGenerator_Backend.git backend
cd backend

# Create Python venv (lightweight)
python3 -m venv .venv
source .venv/bin/activate

# Install ONLY required packages (not Manim, ffmpeg, etc.)
pip install --upgrade pip
pip install requests python-dotenv schedule

# Optional: Firebase support
pip install firebase-admin
```

### Step 3: Configure environment (.env)
Create or copy `.env` to the backend directory:

```bash
# On the E2.Micro VM:
nano .env
```

Paste this:
```env
# Backend instance (main generation VM)
BACKEND_URL=http://<MAIN_VM_PUBLIC_IP>:8000

# Optional: Firebase Realtime Database URL
FIREBASE_DB_URL=https://your-project.firebaseio.com

# Optional: Custom schedule (comma-separated times in UTC)
SCHEDULE_TIMES=09:00,18:00
```

**Replace**:
- `<MAIN_VM_PUBLIC_IP>` with the IP of your main A1.Flex instance (where generation happens)
- `your-project.firebaseio.com` if using Firebase (optional)

### Step 4: Test the connection
```bash
source .venv/bin/activate
python shorts_request_sender.py --test
```

Expected output:
```
✅ Backend is online: http://192.0.2.100:8000
```

If it fails, check:
- Main VM is running and API is listening on port 8000
- Firewall rules allow port 8000 from E2.Micro
- IP address is correct

### Step 5: Run manually (test)
```bash
# Send one request now
source .venv/bin/activate
python shorts_request_sender.py --once

# Or run scheduled (09:00, 18:00 UTC)
python shorts_request_sender.py --schedule

# Or run every N minutes
python shorts_request_sender.py --continuous 60
```

### Step 6: Setup systemd (auto-start on reboot)
Copy the service file to systemd:

```bash
sudo cp shorts_request_sender.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable shorts_request_sender
sudo systemctl start shorts_request_sender
```

Check status:
```bash
sudo systemctl status shorts_request_sender

# View logs
sudo journalctl -u shorts_request_sender -f
```

## Command Reference

### Manual modes
```bash
source .venv/bin/activate

# Test connection to backend
python shorts_request_sender.py --test

# Send one request immediately
python shorts_request_sender.py --once

# Schedule requests (09:00, 18:00 UTC by default, or set SCHEDULE_TIMES in .env)
python shorts_request_sender.py --schedule

# Continuous: send a request every 60 minutes
python shorts_request_sender.py --continuous 60
```

### Systemd (auto-running)
```bash
# View status
sudo systemctl status shorts_request_sender

# View logs (live)
sudo systemctl -u shorts_request_sender -f

# Stop/start/restart
sudo systemctl stop shorts_request_sender
sudo systemctl start shorts_request_sender
sudo systemctl restart shorts_request_sender

# View full log (last 100 lines)
sudo journalctl -u shorts_request_sender -n 100
```

## What gets sent to the backend

Each request is a JSON POST to `/api/generate/`:

```json
{
  "topic": "Python List Comprehensions",
  "duration": 52,
  "aspect_ratio": "9:16",
  "video_type": "short",
  "quality": "qm"
}
```

Backend should:
1. Queue the job (respond with job_id)
2. Generate the video
3. Convert to 9:16 vertical format
4. Upload to YouTube
5. Save result to Firebase (optional)

## Troubleshooting

### "Cannot connect to backend"
- Check main VM is running
- Check `BACKEND_URL` in .env is correct
- Check firewall rules allow port 8000 from E2.Micro
- Ping the main VM: `ping <MAIN_VM_IP>`

### "API request failed: HTTP 500"
- Backend has an error — check logs on main VM
- Make sure `/api/generate/` endpoint exists in your Django app

### "All topics used recently"
- Script will reset to full list and pick randomly
- History is saved in `upload_history.json` (30-day window)

### "Firebase update failed"
- Firebase URL might be wrong
- If not using Firebase, you can ignore this warning

### High CPU/Memory on E2.Micro
- This should never happen — requester uses <10MB RAM
- If CPU is high, the systemd process might be stuck (restart it)
- Check if your backend connection is slow (causing timeouts)

## What NOT to do

❌ Don't run Manim on E2.Micro — way too slow  
❌ Don't run the full pipeline on E2.Micro — needs A1.Flex  
❌ Don't put generation code here — this is request-only  

## Optional: Firebase Realtime Database

If you want to track job status in Firebase:

1. Create Firestore/Realtime Database in Firebase Console
2. Get the database URL (looks like `https://project-name.firebaseio.com`)
3. Add to `.env`:
   ```env
   FIREBASE_DB_URL=https://project-name.firebaseio.com
   ```
4. Script will automatically POST job info to `/shorts_jobs/{job_id}.json`

## Cron alternative (instead of systemd)

If you prefer cron for scheduling:

```bash
crontab -e
```

Add:
```cron
# Request a short at 9 AM and 6 PM (UTC)
0 9 * * * /home/ubuntu/video_generator/backend/.venv/bin/python /home/ubuntu/video_generator/backend/shorts_request_sender.py --once
0 18 * * * /home/ubuntu/video_generator/backend/.venv/bin/python /home/ubuntu/video_generator/backend/shorts_request_sender.py --once
```

## Files needed on E2.Micro

```
~/video_generator/backend/
├── .env                              ← Configure this (BACKEND_URL)
├── shorts_request_sender.py          ← The main script
├── upload_history.json               ← Auto-created (tracks topics)
├── shorts_requester.log              ← Auto-created (logs)
└── .venv/                            ← Virtual environment
```

## Next: Check if your backend has the /api/generate/ endpoint

On your main VM, verify the endpoint exists:

```bash
curl http://localhost:8000/api/generate/ -X POST -H "Content-Type: application/json" \
  -d '{"topic":"Test","duration":60,"aspect_ratio":"9:16"}'
```

Should return:
```json
{"job_id": "abc123", "status": "pending"}
```

If not, add this endpoint to your Django `urls.py` and a view that queues generation jobs.

---

**Summary**: This setup lets your tiny E2.Micro instance send "please generate a short" requests to your powerful A1.Flex instance. It uses essentially zero resources, avoids repeating topics, and can optionally update Firebase.
