# DUPLICATE GENERATION FIX - CRITICAL

## Problem Analysis

**You have TWO scheduler systems running simultaneously, causing duplicate video generation:**

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    E2.Micro Instance #1                      │
│                  (Manual API Server)                         │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  1. Django API (run_api_only.py)                            │
│     - Receives manual requests                               │
│     - Creates jobs in "videos" collection                    │
│     - Status: "pending"                                      │
│                                                               │
│  2. Worker (run_generate_worker.py)                         │
│     - Polls "videos" collection for status="pending"        │
│     - Generates videos                                       │
│     - Updates to status="completed"                          │
│                                                               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    E2.Micro Instance #2                      │
│                  (Autonomous Scheduler)                      │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  CORRECT (NEW): youtube_shorts_scheduler_standalone.py      │
│     ✅ Creates jobs in "scheduled-videos" collection        │
│     ✅ Status: "processing" (worker ignores this)           │
│     ✅ Generates video LOCALLY                              │
│     ✅ Uploads to YouTube + Oracle                          │
│     ✅ NO interaction with "videos" collection              │
│                                                               │
│  WRONG (OLD): youtube_shorts_scheduler.py                   │
│     ❌ Calls API endpoint /api/generate/                    │
│     ❌ API creates job in "videos" collection               │
│     ❌ Worker picks up the job and generates                │
│     ❌ Scheduler ALSO waits and processes the same job      │
│     ❌ RESULT: DOUBLE GENERATION + DOUBLE UPLOAD            │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Firebase Collections Explained

### `videos` Collection
- **Purpose:** Manual API requests ONLY
- **Created by:** `create_job()` function (from API)
- **Consumed by:** Worker (`get_pending_jobs()`)
- **Status flow:** pending → processing → completed
- **Source:** "manual_api"

### `scheduled-videos` Collection  
- **Purpose:** Autonomous scheduler ONLY
- **Created by:** `create_scheduled_job()` function
- **Consumed by:** NOBODY (scheduler handles it entirely)
- **Status flow:** processing → completed
- **Source:** "automated_scheduler"
- **Isolation:** Worker NEVER queries this collection

### `youtube-shorts` Collection
- **Purpose:** Legacy tracking (deprecated)
- **Created by:** Old `youtube_shorts_scheduler.py`
- **Should be:** Removed/ignored

## Service Files Explained

### ❌ DISABLE THESE (Cause duplicates):

1. **`youtube_shorts_scheduler.service`**
   ```bash
   # DISABLE THIS SERVICE
   sudo systemctl stop youtube_shorts_scheduler.service
   sudo systemctl disable youtube_shorts_scheduler.service
   ```
   - Runs: `youtube_shorts_scheduler.py --schedule`
   - Problem: Calls API, creates jobs in "videos" collection
   - Result: Worker processes the job (duplicate #1)

2. **`youtube_shorts_scheduler_standalone.service`** (Type=simple)
   ```bash
   # DISABLE THIS SERVICE (wrong type)
   sudo systemctl stop youtube_shorts_scheduler_standalone.service
   sudo systemctl disable youtube_shorts_scheduler_standalone.service
   ```
   - Runs: `youtube_shorts_scheduler_standalone.py` (continuous loop)
   - Problem: Wrong execution mode (should be one-shot with timer)

### ✅ ENABLE THESE (Correct setup):

3. **`youtube-shorts-scheduler.service`** (Type=oneshot)
   ```bash
   # ENABLE THIS SERVICE
   sudo systemctl enable youtube-shorts-scheduler.service
   ```
   - Runs: `youtube_shorts_scheduler_standalone.py --once`
   - Uses: `scheduled-videos` collection
   - Triggered by: systemd timer (4x daily)

4. **`youtube-shorts-scheduler.timer`**
   ```bash
   # ENABLE THIS TIMER
   sudo systemctl enable youtube-shorts-scheduler.timer
   sudo systemctl start youtube-shorts-scheduler.timer
   ```
   - Triggers the oneshot service at: 03:30, 06:30, 09:30, 12:30 UTC
   - IST times: 9AM, 12PM, 3PM, 6PM

## Fix Instructions

### On E2.Micro Instance #2 (Scheduler):

```bash
# 1. Stop all scheduler services
sudo systemctl stop youtube_shorts_scheduler.service
sudo systemctl stop youtube_shorts_scheduler_standalone.service
sudo systemctl stop youtube-shorts-scheduler.timer

# 2. Disable the OLD/WRONG services
sudo systemctl disable youtube_shorts_scheduler.service
sudo systemctl disable youtube_shorts_scheduler_standalone.service

# 3. Enable ONLY the correct timer-based service
sudo systemctl enable youtube-shorts-scheduler.service
sudo systemctl enable youtube-shorts-scheduler.timer

# 4. Start the timer
sudo systemctl start youtube-shorts-scheduler.timer

# 5. Verify timer status
sudo systemctl status youtube-shorts-scheduler.timer
sudo systemctl list-timers | grep youtube

# 6. Check that old services are disabled
sudo systemctl is-enabled youtube_shorts_scheduler.service        # Should say "disabled"
sudo systemctl is-enabled youtube_shorts_scheduler_standalone.service  # Should say "disabled"

# 7. Check that new services are enabled
sudo systemctl is-enabled youtube-shorts-scheduler.service        # Should say "enabled"
sudo systemctl is-enabled youtube-shorts-scheduler.timer          # Should say "enabled"
```

### Test the Fix

```bash
# Run once manually to verify it works
sudo systemctl start youtube-shorts-scheduler.service

# Check logs
sudo journalctl -u youtube-shorts-scheduler.service -f

# Verify Firebase collection
# Should see new entry in "scheduled-videos" collection
# Should NOT see new entry in "videos" collection
```

### On E2.Micro Instance #1 (API + Worker):

```bash
# Verify worker is running correctly
sudo systemctl status run_generate_worker.service

# Check worker logs - should only process "videos" collection
sudo journalctl -u run_generate_worker.service -f
```

## Verification Checklist

- [ ] Old scheduler service disabled: `youtube_shorts_scheduler.service`
- [ ] Old standalone service disabled: `youtube_shorts_scheduler_standalone.service`
- [ ] New oneshot service enabled: `youtube-shorts-scheduler.service`
- [ ] New timer enabled and active: `youtube-shorts-scheduler.timer`
- [ ] Timer shows next 4 execution times (03:30, 06:30, 09:30, 12:30 UTC)
- [ ] Manual test run creates job in `scheduled-videos` collection
- [ ] Manual test run does NOT create job in `videos` collection
- [ ] Worker only processes jobs from `videos` collection
- [ ] No duplicate generations occurring

## Expected Behavior After Fix

### Manual API Request Flow:
1. User calls `/api/generate/` → Creates job in `videos` (status="pending")
2. Worker picks up job → Generates video → Updates to "completed"
3. ✅ ONE video generated

### Scheduled Autonomous Flow:
1. Timer triggers at scheduled time (e.g., 03:30 UTC)
2. `youtube_shorts_scheduler_standalone.py --once` runs
3. Creates job in `scheduled-videos` (status="processing")
4. Generates video LOCALLY
5. Uploads to YouTube + Oracle
6. Updates `scheduled-videos` to "completed"
7. Worker NEVER sees this job (different collection)
8. ✅ ONE video generated, NO worker involvement

## Code Changes Made

### 1. `firebase_utils.py` - Two Separate Functions:

```python
# For manual API requests → "videos" collection
def create_job(topic, duration, aspect_ratio="16:9", video_type="regular"):
    doc_ref = db.collection("videos").document()
    doc_ref.set({
        "status": "pending",  # Worker will pick this up
        "source": "manual_api"
    })

# For autonomous scheduler → "scheduled-videos" collection  
def create_scheduled_job(topic, duration, aspect_ratio="16:16", video_type="short"):
    doc_ref = db.collection("scheduled-videos").document()
    doc_ref.set({
        "status": "processing",  # Worker ignores this
        "source": "automated_scheduler"
    })
```

### 2. `run_generate_worker.py` - Only Queries "videos":

```python
def get_pending_jobs():
    # ONLY queries "videos" collection
    jobs = db.collection("videos").where("status", "==", "pending").limit(1).stream()
    # Will NEVER see "scheduled-videos" collection
```

### 3. `youtube_shorts_scheduler_standalone.py` - Uses Separate Collection:

```python
# Import the correct functions
from generator.firebase_utils import create_scheduled_job, update_scheduled_job_status

# Create job in SEPARATE collection
job_id = create_scheduled_job(topic, duration, "9:16", "short")
# This creates in "scheduled-videos" - worker won't see it

# Update SEPARATE collection
update_scheduled_job_status(job_id, video_url, status="completed", youtube_video_id=youtube_video_id)
```

## Files to Deprecate/Rename

Consider renaming these files to prevent accidental use:

```bash
# On the server
cd /home/ubuntu/VideoGenerator_Backend

# Rename old scheduler to prevent accidental execution
mv youtube_shorts_scheduler.py youtube_shorts_scheduler.py.OLD_DEPRECATED
mv youtube_shorts_scheduler.service youtube_shorts_scheduler.service.OLD_DEPRECATED
mv youtube_shorts_scheduler_standalone.service youtube_shorts_scheduler_standalone.service.OLD_DEPRECATED
```

## Monitoring

After deploying the fix, monitor these logs:

```bash
# Scheduler logs (should run 4x daily)
sudo journalctl -u youtube-shorts-scheduler.service --since today

# Timer logs (should show 4 activations)
sudo journalctl -u youtube-shorts-scheduler.timer --since today

# Worker logs (should only process manual API jobs)
sudo journalctl -u run_generate_worker.service --since today
```

## Summary

**Root Cause:** Two different scheduler implementations running simultaneously
- OLD: `youtube_shorts_scheduler.py` calls API → creates jobs in "videos" → worker processes
- NEW: `youtube_shorts_scheduler_standalone.py` generates locally → uses "scheduled-videos" → worker ignores

**Solution:** Disable old scheduler, use only the standalone version with timer-based execution

**Result:** Each video generated exactly ONCE, no duplicates
