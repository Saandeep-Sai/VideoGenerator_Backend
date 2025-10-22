# Render Deployment Fix - Port Binding Issue

## Problem
```
==> Detected service running on port 10000
==> Docs on specifying a port: https://render.com/docs/web-services#port-binding
```
Video generation stops when Render detects the port.

## Root Cause
1. **Render expects web services to bind to port 10000** (set via `$PORT` env var)
2. **Worker was starting too early**, interfering with gunicorn's port binding
3. **No health check confirmation**, causing Render to think service isn't ready

## Solution Applied

### 1. **Updated `run_combined.py`**
✅ Added health check wait before starting worker
✅ Added proper logging for debugging
✅ Worker now waits for Django to be fully ready before starting
✅ Better error handling

**Key Changes:**
```python
def wait_for_health_check(port, max_retries=30):
    """Wait for Django server to be healthy before starting worker"""
    health_url = f"http://localhost:{port}/api/health/"
    
    for i in range(max_retries):
        try:
            response = requests.get(health_url, timeout=2)
            if response.status_code == 200:
                return True
        except:
            pass
        time.sleep(2)
```

### 2. **Updated `render.yaml`**
✅ Added explicit `healthCheckPath: /api/health/`
✅ Set `PORT=10000` environment variable
✅ Removed duplicate `DJANGO_SETTINGS_MODULE`

### 3. **Updated `run_generate_worker.py`**
✅ Better error logging
✅ Graceful shutdown handling
✅ Consecutive error tracking (exits after 5 errors)
✅ API key validation on startup

## Deployment Flow

```
1. Render starts service
   ↓
2. run_combined.py executes
   ↓
3. Gunicorn binds to port 10000
   ↓
4. Django starts responding to health checks
   ↓
5. Worker thread waits for health check to pass
   ↓
6. Worker starts AFTER server is ready
   ↓
7. Render marks service as "Live" ✅
   ↓
8. Worker polls for jobs in background
```

## What You'll See in Render Logs

### ✅ Successful Startup:
```
============================================================
🚀 VIDEO GENERATOR SERVICE STARTING
📍 Port: 10000
🌍 Environment: PRODUCTION (Render)
============================================================
✅ Background worker thread initiated
🌐 Starting Gunicorn on 0.0.0.0:10000...
📊 Health check endpoint: http://0.0.0.0:10000/api/health/
🎬 Generate endpoint: http://0.0.0.0:10000/api/generate/
============================================================
[INFO] Starting gunicorn...
[INFO] Listening at: http://0.0.0.0:10000
🔍 Checking if Django server is healthy...
⏳ Waiting for server to be ready... (1/30)
⏳ Waiting for server to be ready... (2/30)
✅ Health check passed! Server is ready on port 10000
🛠️ Starting background video worker...
============================================================
🎬 VIDEO GENERATION WORKER INITIALIZED
============================================================
🟢 Video worker started - polling for jobs...
```

### ❌ Error Signs to Watch For:
```
❌ Server health check timeout - starting worker anyway
❌ Missing API keys! Check environment variables.
❌ Worker loop error (5/5): ...
```

## Testing on Render

### 1. **Check Service Status**
- Go to Render Dashboard → Your Service
- Should show **"Live"** status (green)
- Not "Deploy failed" or "Deploying..."

### 2. **Check Logs**
```bash
# Should see both:
- Gunicorn startup logs
- Worker initialization logs
```

### 3. **Test Health Check**
```bash
curl https://your-app.onrender.com/api/health/

# Expected response:
{
    "status": "healthy",
    "timestamp": "2025-10-22T..."
}
```

### 4. **Test Video Generation**
```bash
curl -X POST https://your-app.onrender.com/api/generate/ \
  -H "Content-Type: application/json" \
  -d '{"topic": "Test", "num_segments": 4}'

# Expected response:
{
    "job_id": "abc123",
    "status": "pending"
}
```

### 5. **Monitor Worker Logs**
- Worker should show: `"⏳ No pending jobs. Sleeping 10s..."`
- When job arrives: `"⚙️ NEW JOB RECEIVED"`

## Troubleshooting

### Problem: Service keeps restarting
**Cause:** Worker crashing on startup
**Fix:** Check environment variables in Render dashboard:
```
GEMINI_API_KEY ✓
GROQ_API_KEY ✓
FIREBASE_CREDENTIALS_BASE64 ✓
FIREBASE_PROJECT_ID ✓
```

### Problem: Port binding timeout
**Cause:** Gunicorn taking too long to start
**Fix:** 
1. Check Render plan (free tier is slower)
2. Increase timeout in `run_combined.py`:
   ```python
   wait_for_health_check(port, max_retries=60)  # 2 minutes
   ```

### Problem: Worker not processing jobs
**Cause:** Worker thread not starting
**Fix:** Check logs for:
```
✅ Background worker thread initiated
🛠️ Starting background video worker...
```

### Problem: Health check failing
**Cause:** Django not responding
**Fix:** 
1. Check `ALLOWED_HOSTS` in `settings.py`
2. Verify health check endpoint exists: `/api/health/`
3. Check Render logs for Django errors

## Environment Variables Checklist

Required in Render Dashboard:

```bash
# ✅ API Keys
GEMINI_API_KEY = "AIza..."
GEMINI_API_KEY_2 = "AIza..."  # Optional backup
GROQ_API_KEY = "gsk_..."

# ✅ Firebase
FIREBASE_CREDENTIALS_BASE64 = "ew0KICAidHlw..."
FIREBASE_PROJECT_ID = "your-project-id"

# ✅ Django
DJANGO_SECRET_KEY = "your-secret-key"
DJANGO_SETTINGS_MODULE = "video_gen.settings"

# ✅ Port (auto-set by Render)
PORT = "10000"  # Usually auto-set, but can be explicit
```

## Common Render Errors

### Error: "Your service did not bind to 0.0.0.0:10000"
**Fix:** Already fixed! `run_combined.py` now binds correctly.

### Error: "Health check timeout"
**Fix:** `healthCheckPath: /api/health/` added to `render.yaml`

### Error: "Build failed"
**Fix:** Check `requirements.txt` has all dependencies

### Error: "Deploy succeeded but service is not running"
**Fix:** Check logs for worker crashes

## Next Steps After Deployment

1. **Wait for "Live" status** (~2-3 minutes)
2. **Check logs** for startup messages
3. **Test health check** endpoint
4. **Send test video request** (4 segments for quick test)
5. **Monitor logs** for job processing
6. **Check Firebase** for completed video

## Performance Notes

On Render Free Tier:
- **Cold start**: ~30-60 seconds
- **Health check timeout**: 60 seconds max
- **Video generation**: 3-4 min (4 segments), 12-14 min (16 segments)
- **Worker polling interval**: 10 seconds

## Success Indicators

✅ Service shows "Live" in Render dashboard
✅ Health check returns 200 OK
✅ Logs show "Worker started - polling for jobs"
✅ Can submit video generation request
✅ Worker picks up and processes jobs
✅ Videos upload to Firebase successfully

## Support

If issues persist:
1. Share Render logs (last 100 lines)
2. Check environment variables are set
3. Test health endpoint manually
4. Verify Firebase credentials are valid
