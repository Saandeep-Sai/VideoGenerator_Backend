#!/bin/bash
# Deploy Analytics Sync systemd timer

set -e

echo "📊 Deploying Analytics Sync systemd timer..."

# Stop any existing
sudo systemctl stop analytics-sync.timer 2>/dev/null || true
sudo systemctl stop analytics-sync.service 2>/dev/null || true

# Copy service files
sudo cp analytics-sync.service /etc/systemd/system/
sudo cp analytics-sync.timer /etc/systemd/system/

# Set permissions
sudo chmod 644 /etc/systemd/system/analytics-sync.service
sudo chmod 644 /etc/systemd/system/analytics-sync.timer

# Reload systemd
sudo systemctl daemon-reload

# Enable and start timer
sudo systemctl enable analytics-sync.service
sudo systemctl enable analytics-sync.timer
sudo systemctl start analytics-sync.timer

echo "✅ Analytics sync timer deployed!"
echo ""
echo "📋 Status:"
sudo systemctl status analytics-sync.timer --no-pager -l

echo ""
echo "⏰ Next scheduled run:"
systemctl list-timers --all | grep analytics || echo "No timers found"

echo ""
echo "📝 Commands:"
echo "  View logs:    sudo journalctl -u analytics-sync.service -f"
echo "  Manual run:   sudo systemctl start analytics-sync.service"
echo "  Stop timer:   sudo systemctl stop analytics-sync.timer"
echo "  Check status: sudo systemctl status analytics-sync.timer"
