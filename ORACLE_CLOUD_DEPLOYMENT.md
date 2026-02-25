# Oracle Cloud Deployment Guide

Complete step-by-step guide to deploy the Video Generator API on Oracle Cloud Infrastructure (OCI).

---

## 📋 Prerequisites

### Local Requirements

- Git installed
- SSH key pair (for connecting to Oracle instance)
- Oracle Cloud account with active instance

### Oracle Cloud Instance Requirements

- **Recommended**: VM.Standard.E2.1.Micro (Always Free Tier)
- **OS**: Ubuntu 20.04 LTS or later
- **RAM**: 1GB minimum (E2 Micro provides this)
- **Storage**: 50GB minimum
- **Network**: Public IP with ports 22 (SSH) and 10000 (API) open

---

## 🔐 Step 1: Prepare Oracle Cloud Instance

### 1.1 SSH into Your Instance

```bash
ssh -i /path/to/your-ssh-key.key ubuntu@<your-oracle-instance-ip>
```

Replace:

- `/path/to/your-ssh-key.key` with your actual SSH key path
- `<your-oracle-instance-ip>` with your instance's public IP

### 1.2 Update System Packages

```bash
sudo apt update && sudo apt upgrade -y
```

### 1.3 Install System Dependencies

```bash
# Install Python 3.10+ and pip
sudo apt install -y python3.10 python3.10-venv python3-pip

# Install Git
sudo apt install -y git

# Install FFmpeg (required for video processing)
sudo apt install -y ffmpeg

# Install LaTeX (required for Manim mathematical text rendering)
sudo apt install -y texlive texlive-latex-extra texlive-fonts-extra texlive-latex-recommended texlive-science texlive-fonts-recommended

# Install system libraries for Cairo (Manim dependency)
sudo apt install -y libcairo2-dev libpango1.0-dev ffmpeg

# Install additional dependencies
sudo apt install -y build-essential libssl-dev libffi-dev python3-dev
```

---

## 📦 Step 2: Clone and Setup Project

### 2.1 Clone Repository

```bash
cd ~
git clone https://github.com/yourusername/Video_Generator.git
cd Video_Generator/backend
```

### 2.2 Create Python Virtual Environment

```bash
python3.10 -m venv .venv
source .venv/bin/activate
```

### 2.3 Install Python Packages

**Required for OpenRouter Integration:**

The project uses OpenRouter API for AI-powered script generation. Install required packages:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Key packages for OpenRouter:**

- `openai` - OpenRouter uses OpenAI-compatible API
- `requests` - For HTTP requests
- `python-dotenv` - For environment variable management

**If you need to install OpenRouter dependencies separately:**

```bash
pip install openai>=1.0.0
pip install requests
pip install python-dotenv
```

**Complete package installation:**

```bash
# Core dependencies
pip install fastapi uvicorn pydantic
pip install google-generativeai  # For Gemini API
pip install openai  # For OpenRouter API
pip install edge-tts  # For text-to-speech
pip install manim  # For video rendering
pip install pydub  # For audio processing
pip install psutil  # For system monitoring
```

---

## 🔑 Step 3: Configure Environment Variables

### 3.1 Create .env File

```bash
nano .env
```

### 3.2 Add Required Environment Variables

```env
# OpenRouter API Configuration
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_API_KEY_2=your_second_openrouter_key_here  # Optional for rotation
OPENROUTER_API_KEY_3=your_third_openrouter_key_here   # Optional for rotation

# Gemini API Configuration
GEMINI_API_KEY=your_gemini_api_key_here

# Firebase Configuration (if using)
FIREBASE_CREDENTIALS_PATH=/path/to/firebase/credentials.json

# Server Configuration
PORT=10000
HOST=0.0.0.0

# Optional: Model Configuration
NARRATION_MODEL=meta-llama/llama-3.3-70b-instruct
SCRIPT_MODEL=qwen/qwen-2.5-coder-32b-instruct
```

**Save and exit:** Press `Ctrl+X`, then `Y`, then `Enter`

### 3.3 Verify Environment Variables

```bash
cat .env  # Check file contents
```

---

## 🔥 Step 4: Configure Firewall Rules

### 4.1 Oracle Cloud Console (Web Interface)

1. Log into Oracle Cloud Console
2. Navigate to **Networking** → **Virtual Cloud Networks**
3. Select your VCN → **Security Lists** → **Default Security List**
4. Click **Add Ingress Rules**
5. Add rule:
   - **Source CIDR**: `0.0.0.0/0`
   - **IP Protocol**: `TCP`
   - **Destination Port Range**: `10000`
   - **Description**: `Video Generator API`

### 4.2 Ubuntu Firewall (UFW)

```bash
# Enable UFW
sudo ufw enable

# Allow SSH
sudo ufw allow 22/tcp

# Allow API port
sudo ufw allow 10000/tcp

# Check status
sudo ufw status
```

### 4.3 iptables Configuration

```bash
# Allow API port
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 10000 -j ACCEPT

# Save iptables rules
sudo netfilter-persistent save
```

---

## 🚀 Step 5: Start the Application

### 5.1 Test Run (Foreground)

```bash
cd ~/Video_Generator/backend
source .venv/bin/activate
python run_api_only.py
```

**Expected output:**

```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:10000
```

Press `Ctrl+C` to stop.

### 5.2 Production Run with systemd

Create a systemd service for auto-restart and background running:

```bash
sudo nano /etc/systemd/system/video-generator-api.service
```

**Add this content:**

```ini
[Unit]
Description=Video Generator API Service
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/Video_Generator/backend
Environment="PATH=/home/ubuntu/Video_Generator/backend/.venv/bin"
ExecStart=/home/ubuntu/Video_Generator/backend/.venv/bin/python run_api_only.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Enable and start the service:**

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable video-generator-api.service

# Start the service
sudo systemctl start video-generator-api.service

# Check status
sudo systemctl status video-generator-api.service
```

---

## 🔍 Step 6: Verify Deployment

### 6.1 Check Service Status

```bash
sudo systemctl status video-generator-api.service
```

### 6.2 Check Logs

```bash
# View real-time logs
sudo journalctl -u video-generator-api.service -f

# View last 100 lines
sudo journalctl -u video-generator-api.service -n 100
```

### 6.3 Test API Endpoint

**From your local machine:**

```bash
curl http://<your-oracle-instance-ip>:10000/health
```

**Expected response:**

```json
{
  "status": "healthy",
  "timestamp": "2026-01-17T10:30:00Z"
}
```

### 6.4 Test Video Generation

```bash
curl -X POST http://<your-oracle-instance-ip>:10000/api/generate-video \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "Introduction to Python",
    "duration": 60,
    "aspect_ratio": "9:16"
  }'
```

---

## 🔧 Step 7: Manage the Service

### Start Service

```bash
sudo systemctl start video-generator-api.service
```

### Stop Service

```bash
sudo systemctl stop video-generator-api.service
```

### Restart Service

```bash
sudo systemctl restart video-generator-api.service
```

### Check Status

```bash
sudo systemctl status video-generator-api.service
```

### View Logs

```bash
# Real-time logs
sudo journalctl -u video-generator-api.service -f

# Last 50 lines
sudo journalctl -u video-generator-api.service -n 50

# Logs from today
sudo journalctl -u video-generator-api.service --since today
```

---

## 🔄 Step 8: Update Deployment

### 8.1 Pull Latest Changes

```bash
cd ~/Video_Generator/backend
git pull origin main
```

### 8.2 Update Dependencies

```bash
source .venv/bin/activate
pip install --upgrade -r requirements.txt
```

### 8.3 Restart Service

```bash
sudo systemctl restart video-generator-api.service
```

### 8.4 Verify Update

```bash
sudo systemctl status video-generator-api.service
sudo journalctl -u video-generator-api.service -n 20
```

---

## 📊 OpenRouter Package Requirements

### Required Packages

OpenRouter uses the OpenAI-compatible API, so you need:

1. **openai** (v1.0.0+)

   ```bash
   pip install openai>=1.0.0
   ```

2. **requests** (for HTTP requests)

   ```bash
   pip install requests
   ```

3. **python-dotenv** (for environment management)
   ```bash
   pip install python-dotenv
   ```

### Verify OpenRouter Installation

```python
# Test OpenRouter connection
python -c "
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(
    base_url='https://openrouter.ai/api/v1',
    api_key=os.getenv('OPENROUTER_API_KEY')
)
print('✅ OpenRouter client initialized successfully')
"
```

---

## 🛠️ Troubleshooting

### Issue: Port 10000 Not Accessible

**Solution:**

```bash
# Check if service is running
sudo systemctl status video-generator-api.service

# Check if port is listening
sudo netstat -tulpn | grep 10000

# Check firewall
sudo ufw status
sudo iptables -L -n | grep 10000
```

### Issue: OpenRouter API Errors

**Solution:**

```bash
# Verify API key
cat .env | grep OPENROUTER_API_KEY

# Test API key
curl https://openrouter.ai/api/v1/models \
  -H "Authorization: Bearer $OPENROUTER_API_KEY"
```

### Issue: Out of Memory

**Solution:**

```bash
# Check memory usage
free -h

# Reduce batch size in code (already optimized for E2 Micro)
# The pipeline is configured for low-memory environments
```

### Issue: Manim Rendering Fails

**Solution:**

```bash
# Reinstall LaTeX packages
sudo apt install -y texlive-full

# Verify FFmpeg
ffmpeg -version

# Check Manim installation
python -c "import manim; print(manim.__version__)"
```

### Issue: Service Won't Start

**Solution:**

```bash
# Check detailed error logs
sudo journalctl -u video-generator-api.service -n 100 --no-pager

# Test manual run
cd ~/Video_Generator/backend
source .venv/bin/activate
python run_api_only.py
# Look for specific error messages
```

---

## 🎯 Performance Optimization for Oracle E2 Micro

The application is **already optimized** for Oracle E2 Micro instances:

- ✅ Batch size set to 1 (process one segment at a time)
- ✅ Memory limit configured to 800MB (leaving 200MB for system)
- ✅ Max concurrent TTS operations limited to 1
- ✅ Sequential processing to avoid memory spikes
- ✅ Automatic cleanup of temporary files

**Configuration in code:**

```python
batch_size: int = 1  # E2.Micro: Process 1 segment at a time
memory_limit_mb: int = 800  # Leave 200MB for system
max_concurrent_tts: int = 1  # Only 1 TTS at a time
```

---

## 📝 Quick Reference Commands

```bash
# SSH to instance
ssh -i your-key.key ubuntu@your-instance-ip

# Navigate to project
cd ~/Video_Generator/backend

# Activate environment
source .venv/bin/activate

# View logs
sudo journalctl -u video-generator-api.service -f

# Restart service
sudo systemctl restart video-generator-api.service

# Check status
sudo systemctl status video-generator-api.service

# Update code
git pull origin main && pip install -r requirements.txt && sudo systemctl restart video-generator-api.service
```

---

## 🔗 Additional Resources

- **Oracle Cloud Free Tier**: https://www.oracle.com/cloud/free/
- **OpenRouter Documentation**: https://openrouter.ai/docs
- **Gemini API Docs**: https://ai.google.dev/docs
- **Manim Documentation**: https://docs.manim.community/

---

## ✅ Deployment Checklist

- [ ] Oracle Cloud instance created with public IP
- [ ] SSH key configured and tested
- [ ] System packages updated
- [ ] Python 3.10+ installed
- [ ] FFmpeg and LaTeX installed
- [ ] Project cloned from GitHub
- [ ] Virtual environment created
- [ ] All Python packages installed (including OpenRouter dependencies)
- [ ] .env file created with API keys
- [ ] Firewall rules configured (Oracle Console + UFW + iptables)
- [ ] Port 10000 accessible from internet
- [ ] systemd service created and enabled
- [ ] Service running successfully
- [ ] API health check passing
- [ ] Test video generation successful

---

**Deployment completed successfully! 🎉**

Your Video Generator API is now running on Oracle Cloud at:
`http://<your-oracle-instance-ip>:10000`
