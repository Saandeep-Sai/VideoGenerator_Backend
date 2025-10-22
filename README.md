# 🎬 AI Video Generator - Backend

Automated educational video generation using Gemini AI, Manim animations, and Edge TTS.

## ✨ Features

- 🤖 **AI-Powered Script Generation** - Gemini AI creates engaging educational content
- 🎨 **Manim Animations** - Professional mathematical and educational visualizations  
- 🎙️ **Text-to-Speech** - Natural voiceover using Edge TTS
- ⚡ **Rate Limiting** - Token bucket algorithm (20 req/min) for API quota management
- 💾 **Smart Caching** - 7-day TTL cache to reduce API calls
- 🔄 **Async Processing** - Background job processing for cloud deployment
- � **Progress Tracking** - Real-time status updates for clients
- 🌐 **Cloud-Ready** - Optimized for Render.com deployment

## �🚀 Quick Start

### Prerequisites
- Python 3.11+
- FFmpeg
- NVIDIA GPU (optional, for faster rendering)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/Saandeep-Sai/VideoGenerator_Backend.git
   cd VideoGenerator_Backend
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env and add your API keys
   ```

5. **Run migrations**
   ```bash
   python manage.py migrate
   ```

6. **Start the server**
   ```bash
   python manage.py runserver
   ```

## 🔑 Environment Variables

```env
# Required API Keys
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here

# Optional: Additional Gemini keys for rotation
GEMINI_API_KEY_1=additional_key_1
GEMINI_API_KEY_2=additional_key_2

# Django Settings
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
SECRET_KEY=your_secret_key

# Firebase (for video storage)
FIREBASE_CREDENTIALS_PATH=path/to/credentials.json
```

## 📡 API Endpoints

### Health Check
```bash
GET /api/health/
```
**Response:**
```json
{
  "status": "healthy",
  "service": "video-generator",
  "timestamp": "2025-10-22T21:00:00"
}
```

### Generate Video (Async)
```bash
POST /api/generate/
Content-Type: application/json

{
  "topic": "Explanation about cancer",
  "duration": 180
}
```
**Response:**
```json
{
  "status": "accepted",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Video generation started in background",
  "status_url": "/api/status/550e8400-e29b-41d4-a716-446655440000/"
}
```

### Check Status
```bash
GET /api/status/{job_id}/
```
**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "topic": "Explanation about cancer",
  "duration": 180,
  "progress": "Generating video...",
  "created_at": "2025-10-22T20:30:00"
}
```

## 🏗️ Architecture

### Rate Limiting & Caching
- **Token Bucket Algorithm**: 20 requests/minute with 10 burst capacity
- **LRU Cache**: File-based with 7-day TTL, 500 max entries
- **Automatic Key Rotation**: Switches between multiple Gemini API keys

### Background Processing
- **Threading**: Non-blocking video generation
- **Job Tracking**: In-memory job status (use Redis for production)
- **Progress Updates**: Real-time progress tracking

### Video Pipeline
1. **Script Generation** - Gemini AI creates Manim scripts (batch size: 5)
2. **Audio Generation** - Edge TTS creates voiceover
3. **Video Rendering** - Manim renders animations (8 parallel workers)
4. **Audio-Video Sync** - FFmpeg combines media
5. **Firebase Upload** - Stores final video

## 🎥 Performance

### Local (with GPU)
- Script generation: ~2 minutes
- Video rendering: ~3-5 minutes (with NVENC)
- Audio-video sync: ~1 minute
- **Total: 6-8 minutes**

### Cloud (CPU-only - Render)
- Script generation: ~2-3 minutes
- Video rendering: ~6-8 minutes (720p30)
- Audio-video sync: ~2-3 minutes
- **Total: 10-13 minutes**

### Optimizations Applied
- ✅ 8 parallel workers for video rendering
- ✅ 720p30 quality (balanced speed/quality)
- ✅ Batch processing (5 scripts per API call)
- ✅ Smart caching (100% hit rate on repeated topics)
- ✅ CUDA fallback (auto-detects GPU availability)

## 🌐 Render.com Deployment

## Problem Solved ✅
Video generation (10-13 min) was timing out Render's health checks (60s).  
**Solution:** Background processing + dedicated health check endpoint.

## 🌐 Render.com Deployment

### Problem Solved ✅
Video generation (10-13 min) was timing out Render's health checks (60s).  
**Solution:** Background processing + dedicated health check endpoint.

### Deploy to Render

**Step 1: Push Code**
```bash
git add .
git commit -m "Add async processing and health check"
git push origin main
```

**Step 2: Configure Render Dashboard**

**Health Check:**
- Path: `/api/health/`
- Leave other settings as default

**Environment Variables:**
```
GEMINI_API_KEY=your_gemini_key
GROQ_API_KEY=your_groq_key
ALLOWED_HOSTS=.onrender.com,localhost
DEBUG=False
FORCE_CPU=true
```

**Build & Deploy:**
- Build: `pip install -r requirements.txt`
- Start: `gunicorn video_gen.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 900`

**Step 3: Test**
```bash
# Health check
curl https://your-app.onrender.com/api/health/

# Start video generation
curl -X POST https://your-app.onrender.com/api/generate/ \
  -H "Content-Type: application/json" \
  -d '{"topic": "Test", "duration": 60}'

# Check status
curl https://your-app.onrender.com/api/status/{job_id}/
```

## 💻 Frontend Integration

### JavaScript/TypeScript Example
```javascript
async function generateVideo(topic, duration) {
  // 1. Start generation
  const response = await fetch('/api/generate/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topic, duration })
  });
  
  const { job_id } = await response.json();
  console.log(`Job started: ${job_id}`);
  
  // 2. Poll for status every 5 seconds
  return await pollJobStatus(job_id);
}

async function pollJobStatus(jobId) {
  const maxAttempts = 120; // 10 minutes
  let attempts = 0;
  
  while (attempts < maxAttempts) {
    const response = await fetch(`/api/status/${jobId}/`);
    const status = await response.json();
    
    console.log(`Progress: ${status.progress}`);
    
    if (status.status === 'completed') {
      return { success: true, docId: status.firestore_doc_id };
    }
    
    if (status.status === 'failed') {
      return { success: false, error: status.error };
    }
    
    await new Promise(r => setTimeout(r, 5000));
    attempts++;
  }
  
  return { success: false, error: 'Timeout' };
}
```

## 🔧 Configuration

### Video Quality Settings
```python
# In VideoGenerationConfig
manim_quality = "m"  # Options: l (480p15), m (720p30), h (1080p60)
max_workers = 8      # Parallel video rendering workers
batch_size = 5       # Scripts generated per API call
```

### Rate Limiting
```python
# In GeminiRateLimitedClient
requests_per_minute = 20  # Gemini API limit
burst_capacity = 10       # Extra tokens for bursts
```

### Caching
```python
# In CacheManager
ttl_days = 7          # Cache entry lifetime
max_entries = 500     # Maximum cached items
```

## 🧪 Testing

### Run Test Suite
```bash
python test_health_check.py
```

### Manual Testing
```bash
# Terminal 1: Start server
python manage.py runserver

# Terminal 2: Test endpoints
curl http://localhost:8000/api/health/
curl -X POST http://localhost:8000/api/generate/ \
  -H "Content-Type: application/json" \
  -d '{"topic": "Test Video", "duration": 30}'
```

## 📊 Monitoring & Metrics

After each video generation, the system outputs:
```
============================================================
📊 Gemini Client Metrics:
   Total requests: 4
   429 errors: 0
   Current key: 0
   Key 0: 4/8 success, healthy=True

📊 Cache Statistics:
   Hits: 1
   Misses: 0
   Hit rate: 100.0%
   Entries: 1/500
   Evictions: 0

⏱️ Total time: 739.99s (~12 minutes)
============================================================
```

## 🐛 Troubleshooting

### CUDA Not Working
**Issue:** `CUDA failed, falling back to CPU`  
**Solution:** 
- Update NVIDIA driver to 570.0+ for NVENC support
- Or accept CPU encoding (automatic fallback)

### Health Check Fails on Render
**Issue:** Service marked unhealthy  
**Solution:**
- Verify health check path is `/api/health/`
- Check environment variables are set
- Ensure gunicorn timeout is 900s

### Rate Limiting Errors
**Issue:** `429 quota exceeded`  
**Solution:**
- Add more GEMINI_API_KEY_X environment variables
- System automatically rotates between keys
- Current limit: 20 req/min per key

### Slow Performance
**Issue:** Videos take > 15 minutes  
**Solution:**
- Reduce quality: `manim_quality = "l"` (480p15)
- Increase workers (if more CPU available)
- Use GPU acceleration (update driver)

## 📁 Project Structure

```
backend/
├── generator/
│   ├── views.py                 # API endpoints with async processing
│   ├── urls.py                  # URL routing
│   ├── models.py                # Database models
│   ├── serializers.py           # API serializers
│   ├── gemini_client.py         # Rate-limited Gemini client
│   ├── cache_manager.py         # LRU cache implementation
│   └── video_generator/
│       └── optimized_video_generator.py  # Main pipeline
├── video_gen/
│   ├── settings.py              # Django settings
│   ├── urls.py                  # Main URL config
│   └── wsgi.py                  # WSGI config
├── render.yaml                  # Render.com configuration
├── requirements.txt             # Python dependencies
├── test_health_check.py         # Test script
└── README.md                    # This file
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- **Gemini AI** - Script generation
- **Manim Community** - Animation library
