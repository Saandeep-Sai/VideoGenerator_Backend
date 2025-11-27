# 🎬 YouTube Shorts Systemd Timer Setup

## 🧠 Why This Change?

**Problem**: Long-running Python process causes memory leaks and OOM kills on E2.Micro
**Solution**: One-shot systemd timer that runs → generates → exits → frees RAM

## 🚀 Quick Setup

### 1. Deploy Timer
```bash
chmod +x deploy_systemd_timer.sh
./deploy_systemd_timer.sh
```

### 2. Verify Installation
```bash
# Check timer status
sudo systemctl status youtube-shorts-scheduler.timer

# View next scheduled runs
systemctl list-timers --all | grep youtube

# Test manual run
sudo systemctl start youtube-shorts-scheduler.service
```

### 3. Monitor Logs
```bash
# Follow live logs
sudo journalctl -u youtube-shorts-scheduler.service -f

# View recent logs
sudo journalctl -u youtube-shorts-scheduler.service --since "1 hour ago"
```

## ⏰ Schedule

- **09:00 UTC** (Daily)
- **18:00 UTC** (Daily)

## 🔧 Management Commands

```bash
# Start/Stop timer
sudo systemctl start youtube-shorts-scheduler.timer
sudo systemctl stop youtube-shorts-scheduler.timer

# Manual execution
sudo systemctl start youtube-shorts-scheduler.service

# View status
sudo systemctl status youtube-shorts-scheduler.timer
sudo systemctl status youtube-shorts-scheduler.service

# Disable timer
sudo systemctl disable youtube-shorts-scheduler.timer
```

## 📊 Resource Limits

- **Memory**: 650MB max (E2.Micro safe)
- **CPU**: 80% quota
- **OOM Policy**: Kill on memory exhaustion

## ✅ Benefits

- ✅ No memory leaks (process exits after each run)
- ✅ No OOM kills (resource limits enforced)
- ✅ Reliable scheduling (systemd handles timing)
- ✅ Better logging (journald integration)
- ✅ Automatic restart on failure
- ✅ E2.Micro optimized