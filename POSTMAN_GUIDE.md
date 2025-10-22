# Postman API Testing Guide

## Quick Start

### 1. Import Collection
1. Open Postman
2. Click **Import** button
3. Select `Video_Generator_API.postman_collection.json`
4. Collection will appear in your workspace

### 2. Import Environment
Import one or both environment files:
- **Local**: `Video_Generator_Local.postman_environment.json`
- **Production**: `Video_Generator_Production.postman_environment.json`

For production, update the `base_url` to your actual Render URL:
```
https://your-app-name.onrender.com
```

### 3. Select Environment
In the top-right corner of Postman, select the environment you want to use (Local or Production).

---

## API Endpoints

### 1. Health Check
**GET** `/api/health/`

Test if the service is running:
```bash
GET http://localhost:8000/api/health/
```

**Response (200 OK):**
```json
{
    "status": "healthy",
    "timestamp": "2025-10-22T12:00:00Z"
}
```

---

### 2. Generate Video (Async)
**POST** `/api/generate/`

Start a video generation job:

**Request Body:**
```json
{
    "topic": "Explain how photosynthesis works",
    "num_segments": 8
}
```

**Parameters:**
- `topic` (required): Topic for the video
- `num_segments` (optional): 4-20 segments (default: 16)

**Response (202 Accepted):**
```json
{
    "job_id": "abc123def456",
    "status": "pending",
    "message": "Video generation started"
}
```

**Note:** The `job_id` is automatically saved to the environment variable for status checking.

---

### 3. Check Job Status
**GET** `/api/status/{job_id}/`

Check the progress of your video generation:

**Response (Processing):**
```json
{
    "job_id": "abc123def456",
    "status": "processing",
    "progress": 45,
    "current_step": "Generating segment 7 of 16",
    "estimated_time_remaining": "6 minutes"
}
```

**Response (Completed):**
```json
{
    "job_id": "abc123def456",
    "status": "completed",
    "progress": 100,
    "download_url": "https://storage.googleapis.com/.../final_video.mp4",
    "firebase_path": "videos/Explanation_about_photosynthesis_final_video.mp4"
}
```

**Response (Failed):**
```json
{
    "job_id": "abc123def456",
    "status": "failed",
    "error": "Error message here"
}
```

---

## Testing Workflow

### Full Workflow Example

1. **Start Health Check**
   - Run "Health Check" request
   - Verify service is running

2. **Generate Video**
   - Run "Generate Video - Quick Test (Cancer)" for fast testing
   - Check response for `job_id` (auto-saved)

3. **Poll Status**
   - Run "Check Job Status" repeatedly
   - Watch `progress` and `current_step` fields
   - Continue until `status` is "completed" or "failed"

4. **Download Video**
   - Copy `download_url` from completed response
   - Open in browser or download programmatically

---

## Pre-configured Test Requests

The collection includes these ready-to-use requests:

### 1. Quick Test (4 segments, ~3-4 min)
```json
{
    "topic": "Explanation about cancer",
    "num_segments": 4
}
```

### 2. Medium Test (8 segments, ~6-7 min)
```json
{
    "topic": "How artificial intelligence is transforming healthcare",
    "num_segments": 8
}
```

### 3. Full Test (16 segments, ~12-14 min)
```json
{
    "topic": "Understanding climate change and its global impact",
    "num_segments": 16
}
```

---

## Automatic Scripts

The collection includes **automatic test scripts** that:

1. **Auto-save job_id**: When you generate a video, the `job_id` is automatically saved
2. **Use saved job_id**: Status check automatically uses the saved `job_id`

---

## Status Polling Script

You can manually poll the status, or use this JavaScript in Postman's **Pre-request Script** for the Status endpoint:

```javascript
// Poll every 30 seconds until completed
const jobId = pm.environment.get("job_id");

if (!jobId) {
    console.log("No job_id found. Generate a video first.");
    return;
}

setTimeout(() => {
    pm.sendRequest(pm.request.url, (err, response) => {
        const status = response.json().status;
        console.log("Status:", status);
        
        if (status === "processing" || status === "pending") {
            console.log("Still processing... check again in 30s");
        } else if (status === "completed") {
            console.log("Video ready!");
        }
    });
}, 30000);
```

---

## Expected Response Times

| Segments | Estimated Time | Use Case |
|----------|---------------|----------|
| 4        | 3-4 minutes   | Quick test |
| 8        | 6-7 minutes   | Medium video |
| 12       | 9-10 minutes  | Long video |
| 16       | 12-14 minutes | Full video |

**Note:** Times may vary based on:
- Topic complexity
- Server load
- API rate limiting (20 req/min)
- Cache hits (faster on repeated topics)

---

## Rate Limiting

The API uses **token bucket rate limiting**:
- **Rate**: 20 requests per minute (Gemini API limit)
- **Burst**: 10 tokens available immediately
- **Recovery**: 20 tokens/minute

**Automatic handling:**
- Rate limiter queues requests
- Waits when quota exhausted
- No manual intervention needed

---

## Caching

The API caches results for **7 days**:
- **Cache hit**: Instant response from cache
- **Cache miss**: Full generation process
- **Cache key**: Based on topic + num_segments

**Testing cache:**
1. Generate video with topic "Test cache"
2. Wait for completion
3. Generate again with same topic
4. Second request completes much faster

---

## Troubleshooting

### "Service Unavailable"
- Check if Django server is running: `python manage.py runserver 8000`
- Verify `base_url` in environment matches server

### Job Status Returns 404
- Ensure `job_id` is correct
- Check if job was created successfully
- Jobs may expire after 24 hours

### Video Generation Fails
- Check server logs for errors
- Verify Gemini/Groq API keys in `.env`
- Ensure Manim is installed correctly
- Check Firebase credentials

### Slow Generation
- Normal: 12-14 minutes for 16 segments
- Check API rate limiting (20 req/min)
- Monitor server resources (CPU/RAM)

---

## Testing on Render

1. **Update Production Environment**:
   - Replace `https://your-app-name.onrender.com` with actual URL

2. **First Test**:
   - Use "Quick Test (4 segments)" to verify deployment
   - Monitor Render logs for errors

3. **Health Check Monitoring**:
   - Render checks `/api/health/` every minute
   - Should always return 200 OK in < 100ms

4. **Long-running Jobs**:
   - Video generation continues in background
   - Health checks pass while processing
   - Poll status endpoint for progress

---

## Example: Full Test Flow

```bash
# 1. Health Check
GET /api/health/
→ 200 OK

# 2. Start Job
POST /api/generate/
{
    "topic": "Photosynthesis",
    "num_segments": 4
}
→ 202 Accepted
{
    "job_id": "abc123",
    "status": "pending"
}

# 3. Check Status (repeat every 30s)
GET /api/status/abc123/
→ 200 OK
{
    "status": "processing",
    "progress": 25,
    "current_step": "Generating segment 1 of 4"
}

# 4. Final Status
GET /api/status/abc123/
→ 200 OK
{
    "status": "completed",
    "download_url": "https://storage.googleapis.com/.../video.mp4"
}
```

---

## cURL Examples

If you prefer command-line testing:

```bash
# Health Check
curl http://localhost:8000/api/health/

# Generate Video
curl -X POST http://localhost:8000/api/generate/ \
  -H "Content-Type: application/json" \
  -d '{"topic": "Test video", "num_segments": 4}'

# Check Status
curl http://localhost:8000/api/status/{job_id}/
```

---

## Support

For issues or questions:
1. Check server logs: `tail -f logs/django.log`
2. Review Render deployment logs
3. Verify environment variables in `.env`
4. Test with minimal segments (4) first
