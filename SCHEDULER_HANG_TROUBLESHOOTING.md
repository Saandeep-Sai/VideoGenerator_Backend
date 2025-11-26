# Scheduler Hang Troubleshooting Guide

## Problem: Instance Gets Stuck During Execution

When running the scheduler, it appears to hang with no output after some time.

---

## Root Causes (In Order of Likelihood)

### 1. **Video Rendering is Slow on E2.Micro** (80% likely)

- E2.Micro has only **1 vCPU** and **1GB RAM**
- Manim video rendering is extremely CPU and memory intensive
- **Expected time: 10-20 minutes per 60-second video**
- May look like it's hung but is actually just processing slowly

**Solution:**

- Be patient - let it run for 20+ minutes
- Monitor system resources:
  ```bash
  top -b -n 1 | head -20
  free -h
  ps aux | grep python
  ```
- If CPU is at 100% and memory is high, it's working (not hung)

---

### 2. **FFmpeg Issue** (10% likely)

Error: `RuntimeError: FFmpeg is required but not found or failed`

**Solution:**

```bash
# Verify FFmpeg is installed
ffmpeg -version

# If not found, install it
sudo apt-get update
sudo apt-get install -y ffmpeg

# Verify it's in PATH
which ffmpeg
```

---

### 3. **Oracle Credentials Invalid** (5% likely)

Error: `401 NotAuthenticated` on Oracle API call

**Solution:**

- Verify `.env` has correct values:
  ```bash
  echo $ORACLE_USER_OCID
  echo $ORACLE_FINGERPRINT
  echo $ORACLE_TENANCY_OCID
  ```
- Double-check against Oracle Cloud Console
- Make sure private key file exists: `ls -la /home/ubuntu/oracle-api-key.pem`

---

### 4. **YouTube Token Expired** (3% likely)

Error: `401 Unauthorized` when uploading to YouTube

**Solution:**

```bash
# Regenerate token
python3 generate_youtube_token.py

# Or if on local machine
python3 generate_token_local.py
```

---

### 5. **Out of Memory** (2% likely)

System completely freezes, cursor unresponsive

**Solution:**

```bash
# Check available memory
free -h

# Kill other processes to free memory
ps aux
sudo killall -9 python3  # Use with caution
```

---

## Diagnosis Steps

### Step 1: Run Diagnostic Script

This identifies exactly where it's hanging:

```bash
cd ~/VideoGenerator_Backend
source venv/bin/activate

python3 diagnose_scheduler_hang.py 2>&1 | tee diagnostic.log
```

This tests each component:

1. Pipeline initialization
2. Oracle Storage connection
3. YouTube authentication
4. Narration generation
5. Audio generation
6. Script generation
7. **Video rendering** (where it usually hangs)
8. Final assembly

### Step 2: Monitor Resource Usage

Open another SSH session and run:

```bash
# Monitor CPU and memory every 5 seconds
watch -n 5 'free -h && echo "---" && top -b -n 1 | head -15'

# Or detailed process monitoring
while true; do
  ps aux | grep python3
  free -h
  sleep 10
done
```

### Step 3: Check Logs

```bash
# View real-time logs
tail -f ~/VideoGenerator_Backend/scheduler.log

# Or grep for errors
grep "ERROR\|Failed\|Timeout" ~/VideoGenerator_Backend/scheduler.log
```

---

## Performance Expectations on E2.Micro

| Stage                | Time          | Notes                  |
| -------------------- | ------------- | ---------------------- |
| Narration generation | 30-60s        | Gemini API call        |
| Audio generation     | 2-5 min       | TTS for each segment   |
| Script generation    | 1-3 min       | Gemini/Groq API calls  |
| **Video rendering**  | **10-15 min** | Manim rendering (SLOW) |
| Audio/Video sync     | 2-3 min       | FFmpeg merging         |
| Total time           | **15-30 min** | For 60-second video    |

**If rendering takes >20 minutes, it's likely out of memory or CPU throttled.**

---

## Solutions by Instance Type

### Option 1: Wait & Let It Run

- Let the process run for 30+ minutes
- Don't interrupt it
- Check `top` to confirm it's still processing

### Option 2: Reduce Video Quality

Edit `optimized_video_generator.py` and lower:

- `quality = "720p"` (from 1080p)
- `fps = 30` (from 60)
- Fewer animation segments

### Option 3: Upgrade Instance

Current: E2.Micro (1 vCPU, 1GB RAM)
Recommended:

- **E2.Small** (2 vCPU, 2GB RAM) - 3-5 min rendering
- **E2.Medium** (2 vCPU, 4GB RAM) - 2-3 min rendering
- **A1.Flex** (1-4 vCPU, 1-6GB RAM) - 1-2 min rendering (cheap)

---

## Quick Fix: Skip Video Rendering

If you just want to test the full pipeline without waiting for rendering:

Edit `optimized_video_generator.py` line ~2850:

```python
# TEMPORARY: Skip rendering, create dummy video
if os.getenv("SKIP_RENDER") == "1":
    logger.warning("⚠️ SKIPPING VIDEO RENDERING FOR TESTING")
    for segment in segments:
        segment.video_path = "dummy_video.mp4"
    return
```

Then run:

```bash
export SKIP_RENDER=1
python3 youtube_shorts_scheduler_standalone.py --once
```

This will let you test YouTube upload, Oracle storage, and Firebase without waiting for rendering.

---

## Contact Support

If none of this works:

1. Run `diagnose_scheduler_hang.py` and save output
2. Share the last 100 lines of logs
3. Share output of `free -h` and `nproc`
4. Share instance type and resource allocation
