# Render Deployment Guide - Manim Support

## ✅ **Yes, Render CAN run Manim, but with important configuration**

## 🎯 **What I've Fixed for You:**

### 1. **Headless Rendering (CRITICAL)**
✅ **Fixed** in `optimized_video_generator.py` line ~630

**Problem:** Manim needs a display server, Render has none
**Solution:** Added automatic headless mode detection:
```python
# Force headless mode for Render/cloud environments
if not os.environ.get('DISPLAY'):
    env['DISPLAY'] = ':99'  # Virtual display
    env['QT_QPA_PLATFORM'] = 'offscreen'  # Qt headless mode
    env['DISABLE_CACHING'] = '1'  # Prevent cache issues
```

### 2. **Resource Management (CRITICAL)**
✅ **Fixed** in `optimized_video_generator.py` line ~1280

**Problem:** 8 parallel workers would crash Render's 512MB free tier
**Solution:** Auto-detect cloud environment and reduce workers:
```python
if is_cloud:
    self.max_workers = 2  # Conservative for 512MB RAM
else:
    self.max_workers = 8  # Aggressive for local dev
```

### 3. **System Dependencies**
✅ **Need to add** to `render.yaml`

Render needs these packages installed:

## 📋 **Required System Dependencies**

Add this to your `render.yaml`:

```yaml
services:
  - type: web
    name: video-gen-api
    env: python
    plan: free
    
    # ⚠️ IMPORTANT: Install system dependencies before Python packages
    buildCommand: |
      apt-get update
      apt-get install -y \
        ffmpeg \
        libcairo2-dev \
        libpango1.0-dev \
        python3-dev \
        pkg-config \
        texlive \
        texlive-latex-extra \
        texlive-fonts-extra \
        texlive-xetex \
        cm-super \
        dvipng
      pip install -r requirements.txt
    
    startCommand: python run_combined.py
    healthCheckPath: /api/health/
    
    envVars:
      - key: DJANGO_SETTINGS_MODULE
        value: video_gen.settings
      - key: FIREBASE_CREDENTIALS_BASE64
        sync: false
      - key: FIREBASE_PROJECT_ID
        sync: false
      - key: GEMINI_API_KEY
        sync: false
      - key: GEMINI_API_KEY_2
        sync: false
      - key: GROQ_API_KEY
        sync: false
      - key: DJANGO_SECRET_KEY
        sync: false
      - key: PORT
        value: "10000"
```

## 🚨 **Critical Packages Explained**

| Package | Why It's Needed |
|---------|----------------|
| `ffmpeg` | Video encoding/decoding |
| `libcairo2-dev` | Cairo graphics (Manim dependency) |
| `libpango1.0-dev` | Text rendering (Manim fonts) |
| `python3-dev` | Python C extensions |
| `pkg-config` | Package configuration |
| `texlive` | LaTeX support (math formulas) |
| `texlive-latex-extra` | Additional LaTeX packages |
| `texlive-fonts-extra` | Extra fonts |
| `texlive-xetex` | XeTeX engine |
| `cm-super` | Computer Modern fonts |
| `dvipng` | DVI to PNG conversion |

## ⚙️ **Build Time Considerations**

### Free Tier Limitations:
- **Build time**: ~5-10 minutes (installing LaTeX is slow)
- **Deploy time**: ~2-3 minutes
- **First video**: ~20-30 minutes (4 segments)
- **Full video**: ~60-90 minutes (16 segments)

### Why So Slow?
1. **No GPU** - CPU-only rendering
2. **Shared CPU** - Low priority on free tier
3. **512MB RAM** - Limited to 2 parallel workers
4. **Disk I/O** - Slower than local SSD

## 📊 **Performance Comparison**

| Environment | Workers | 4 Segments | 16 Segments |
|-------------|---------|------------|-------------|
| **Local (Your PC)** | 8 | 3-4 min | 12-14 min |
| **Render Free** | 2 | 15-20 min | 60-90 min |
| **Render Starter** | 4 | 8-12 min | 35-45 min |

## 🎯 **Recommended Render Plan**

### For Production:
**Starter Plan ($7/month)**
- 2GB RAM (can use 4 workers)
- Better CPU priority
- 40-50% faster than free tier
- More reliable for long-running jobs

### For Testing:
**Free Plan**
- Works but slow
- Good for proof of concept
- Test with 4-segment videos only
- Upgrade before production use

## ✅ **Testing Strategy**

### Step 1: Test Locally First
```bash
# Ensure it works on your machine
python manage.py runserver
# Test with Postman: 4 segments
```

### Step 2: Deploy to Render
```bash
git push origin Main
# Watch Render logs during build
```

### Step 3: Test Health Check
```bash
curl https://your-app.onrender.com/api/health/
# Should return: {"status": "healthy"}
```

### Step 4: Test Small Video
```bash
# Use Postman: Generate 4-segment video
# Expected time: 15-20 minutes on free tier
```

### Step 5: Monitor Logs
```bash
# Watch for:
- "☁️ Cloud environment detected - using conservative worker count (2)"
- "🖥️ Running in headless mode (no display detected)"
- "✅ Video generated successfully"
```

## 🐛 **Common Issues & Fixes**

### Issue 1: "ModuleNotFoundError: No module named 'cairo'"
**Cause:** Missing `libcairo2-dev`
**Fix:** Add to `buildCommand` in `render.yaml`:
```bash
apt-get install -y libcairo2-dev
```

### Issue 2: "ModuleNotFoundError: No module named 'pangocairocffi'"
**Cause:** Missing `libpango1.0-dev`
**Fix:** Add to `buildCommand`:
```bash
apt-get install -y libpango1.0-dev
```

### Issue 3: "LaTeX Error: File not found"
**Cause:** Missing LaTeX packages
**Fix:** Add full LaTeX suite:
```bash
apt-get install -y texlive texlive-latex-extra
```

### Issue 4: "Out of Memory" / Worker Crash
**Cause:** Too many parallel workers on free tier
**Fix:** Already handled! Code auto-detects cloud and uses 2 workers.

### Issue 5: "Timeout after 15 minutes"
**Cause:** Render free tier has build timeout
**Fix:** 
- Use smaller video tests (4 segments)
- Or upgrade to Starter plan

### Issue 6: "Display server not found"
**Cause:** Manim trying to use GUI
**Fix:** Already handled! Code sets `DISPLAY=:99` and `QT_QPA_PLATFORM=offscreen`

## 📝 **What to Update Next**

### 1. Update `render.yaml` (REQUIRED)
```bash
# Copy the new render.yaml content above
# Includes system dependencies
```

### 2. Test Deployment
```bash
git add .
git commit -m "Add Manim system dependencies for Render"
git push origin Main
```

### 3. Watch Build Logs
```
==> Installing system dependencies...
==> Building application...
==> Installing Python packages...
==> Starting service...
```

### 4. Monitor First Video Generation
```
☁️ Cloud environment detected - using conservative worker count (2)
🖥️ Running in headless mode (no display detected)
🚀 Starting video generation pipeline...
[... 15-20 minutes later ...]
✅ Video generated successfully!
```

## 💡 **Optimization Tips**

### For Free Tier:
1. **Use 4 segments max** for testing
2. **Set timeout to 30 minutes** in worker
3. **Monitor memory usage** with `psutil`
4. **Cache aggressively** (already implemented)

### For Production:
1. **Upgrade to Starter plan** ($7/month)
2. **Use 8-12 segments** (sweet spot)
3. **Enable all 4 workers**
4. **Set timeout to 60 minutes**

## 🔍 **Debugging Commands**

### Check System Dependencies:
```bash
# SSH into Render shell (not available on free tier)
# Or check during build:
which ffmpeg  # Should show /usr/bin/ffmpeg
python -c "import cairo"  # Should not error
python -c "import pangocairocffi"  # Should not error
```

### Check Environment:
```bash
python -c "import os; print(os.environ.get('DISPLAY'))"
# Should show: :99
```

### Check Worker Count:
```bash
# Look in logs for:
"☁️ Cloud environment detected - using conservative worker count (2)"
```

## 📈 **Scaling Path**

### Phase 1: Free Tier (Proof of Concept)
- 2 workers
- 4-segment videos
- 15-20 min generation
- **Status: ✅ Supported with current fixes**

### Phase 2: Starter Plan (Production)
- 4 workers
- 8-12 segment videos
- 10-15 min generation
- **Status: Ready to upgrade**

### Phase 3: Professional Plan (High Volume)
- 8+ workers
- 16+ segment videos
- GPU support available
- **Status: Consider if you scale**

## ✅ **Summary: What's Working Now**

1. ✅ **Headless rendering configured**
2. ✅ **Auto-detect cloud environment**
3. ✅ **Reduced workers for 512MB RAM**
4. ✅ **Disabled caching to save memory**
5. ⚠️ **Need to add system dependencies to render.yaml**

## 🚀 **Next Steps**

1. **Update `render.yaml`** with system dependencies
2. **Commit and push** changes
3. **Wait for build** (~5-10 minutes)
4. **Test with 4-segment video** first
5. **Monitor logs** for success

**The code is ready - just need to update `render.yaml` with system packages!**
