# Quick Reference: Duplicate Generation Fix

## Problem
Two scheduler systems were running simultaneously, causing each video to be generated twice.

## Solution
Disable old scheduler, enable only the timer-based standalone scheduler.

## Commands to Run on Server

```bash
# Download and run the fix script
cd /home/ubuntu/VideoGenerator_Backend
git pull
chmod +x fix_duplicate_generation.sh
sudo ./fix_duplicate_generation.sh
```

## Manual Fix (if script fails)

```bash
# Stop and disable OLD services
sudo systemctl stop youtube_shorts_scheduler.service
sudo systemctl disable youtube_shorts_scheduler.service
sudo systemctl stop youtube_shorts_scheduler_standalone.service
sudo systemctl disable youtube_shorts_scheduler_standalone.service

# Enable and start NEW services
sudo systemctl enable youtube-shorts-scheduler.service
sudo systemctl enable youtube-shorts-scheduler.timer
sudo systemctl start youtube-shorts-scheduler.timer

# Verify
sudo systemctl status youtube-shorts-scheduler.timer
sudo systemctl list-timers | grep youtube
```

## Verification

After running the fix, you should see:

✅ **CORRECT:**
- `youtube-shorts-scheduler.timer` - **enabled** and **active**
- `youtube-shorts-scheduler.service` - **enabled** (runs when timer triggers)

❌ **DISABLED:**
- `youtube_shorts_scheduler.service` - **disabled** and **inactive**
- `youtube_shorts_scheduler_standalone.service` - **disabled** and **inactive**

## Test

```bash
# Run once manually
sudo systemctl start youtube-shorts-scheduler.service

# Check logs
sudo journalctl -u youtube-shorts-scheduler.service -n 50

# Should see:
# ✅ "Created scheduled job in 'scheduled-videos' collection"
# ✅ NOT "Created job in 'videos' collection"
```

## Files Changed

1. **`DUPLICATE_GENERATION_FIX.md`** - Complete technical analysis
2. **`youtube_shorts_scheduler.py`** - Added deprecation warning (exits on run)
3. **`fix_duplicate_generation.sh`** - Automated fix script
4. **`QUICK_FIX_SUMMARY.md`** - This file

## Architecture Summary

```
┌─────────────────────────────────────────┐
│  Manual Requests (Instance #1)          │
│  ↓                                       │
│  API creates job in "videos"            │
│  ↓                                       │
│  Worker processes from "videos"         │
│  ↓                                       │
│  ✅ ONE video generated                 │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│  Scheduled Requests (Instance #2)       │
│  ↓                                       │
│  Scheduler creates job in               │
│  "scheduled-videos"                     │
│  ↓                                       │
│  Scheduler generates LOCALLY            │
│  ↓                                       │
│  ✅ ONE video generated                 │
│  ✅ Worker NEVER sees this job          │
└─────────────────────────────────────────┘
```

## Key Points

1. **TWO separate Firebase collections:**
   - `videos` - Manual API requests (worker processes these)
   - `scheduled-videos` - Autonomous scheduler (worker ignores these)

2. **Worker only queries `videos` collection:**
   - `get_pending_jobs()` only looks at `collection("videos")`
   - Never sees jobs in `scheduled-videos`

3. **Standalone scheduler uses separate collection:**
   - `create_scheduled_job()` → creates in `scheduled-videos`
   - `update_scheduled_job_status()` → updates in `scheduled-videos`
   - NO API calls, NO worker involvement

## Monitoring

```bash
# Check timer is running
sudo systemctl list-timers youtube-shorts-scheduler.timer

# View logs
sudo journalctl -u youtube-shorts-scheduler.service --since today
sudo journalctl -u youtube-shorts-scheduler.timer --since today

# Verify no duplicates
# Should see 4 videos per day in Firebase "scheduled-videos" collection
# Should NOT see scheduler jobs in "videos" collection
```

## Support

For detailed technical explanation, see `DUPLICATE_GENERATION_FIX.md`
