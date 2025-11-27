#!/bin/bash
# Deploy YouTube Shorts systemd timer

set -e

echo "🚀 Deploying YouTube Shorts systemd timer..."

# Stop any existing scheduler
sudo systemctl stop youtube-shorts-scheduler.timer 2>/dev/null || true
sudo systemctl stop youtube-shorts-scheduler.service 2>/dev/null || true

# Copy service files
sudo cp youtube-shorts-scheduler.service /etc/systemd/system/
sudo cp youtube-shorts-scheduler.timer /etc/systemd/system/

# Set permissions
sudo chmod 644 /etc/systemd/system/youtube-shorts-scheduler.service
sudo chmod 644 /etc/systemd/system/youtube-shorts-scheduler.timer

# Reload systemd
sudo systemctl daemon-reload

# Enable and start timer
sudo systemctl enable youtube-shorts-scheduler.service
sudo systemctl enable youtube-shorts-scheduler.timer
sudo systemctl start youtube-shorts-scheduler.timer

echo "✅ Timer deployed successfully!"
echo ""
echo "📋 Status:"
sudo systemctl status youtube-shorts-scheduler.timer --no-pager -l

echo ""
echo "⏰ Next scheduled runs:"
systemctl list-timers --all | grep youtube || echo "No timers found"

echo ""
echo "📝 Commands:"
echo "  View logs: sudo journalctl -u youtube-shorts-scheduler.service -f"
echo "  Manual run: sudo systemctl start youtube-shorts-scheduler.service"
echo "  Stop timer: sudo systemctl stop youtube-shorts-scheduler.timer"