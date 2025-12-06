#!/bin/bash
# Quick fix script to stop duplicate generation

echo "=========================================="
echo "🛠️  STOPPING DUPLICATE VIDEO GENERATION"
echo "=========================================="
echo ""

# Check which services are running
echo "📊 Checking current service status..."
echo ""

echo "1. Old scheduler (SHOULD BE DISABLED):"
systemctl is-active youtube_shorts_scheduler.service 2>/dev/null || echo "   ✅ Not running"
systemctl is-enabled youtube_shorts_scheduler.service 2>/dev/null && echo "   ⚠️  ENABLED - SHOULD BE DISABLED!" || echo "   ✅ Disabled"

echo ""
echo "2. Old standalone service (SHOULD BE DISABLED):"
systemctl is-active youtube_shorts_scheduler_standalone.service 2>/dev/null || echo "   ✅ Not running"
systemctl is-enabled youtube_shorts_scheduler_standalone.service 2>/dev/null && echo "   ⚠️  ENABLED - SHOULD BE DISABLED!" || echo "   ✅ Disabled"

echo ""
echo "3. New oneshot service (SHOULD BE ENABLED):"
systemctl is-enabled youtube-shorts-scheduler.service 2>/dev/null && echo "   ✅ Enabled" || echo "   ⚠️  DISABLED - SHOULD BE ENABLED!"

echo ""
echo "4. Timer (SHOULD BE ENABLED & ACTIVE):"
systemctl is-active youtube-shorts-scheduler.timer 2>/dev/null && echo "   ✅ Active" || echo "   ⚠️  NOT ACTIVE!"
systemctl is-enabled youtube-shorts-scheduler.timer 2>/dev/null && echo "   ✅ Enabled" || echo "   ⚠️  NOT ENABLED!"

echo ""
echo "=========================================="
echo "🔧 APPLYING FIX..."
echo "=========================================="
echo ""

# Stop and disable old services
echo "Stopping old scheduler service..."
sudo systemctl stop youtube_shorts_scheduler.service 2>/dev/null
sudo systemctl disable youtube_shorts_scheduler.service 2>/dev/null
echo "✅ Done"

echo ""
echo "Stopping old standalone service..."
sudo systemctl stop youtube_shorts_scheduler_standalone.service 2>/dev/null
sudo systemctl disable youtube_shorts_scheduler_standalone.service 2>/dev/null
echo "✅ Done"

echo ""
echo "Stopping timer (to restart cleanly)..."
sudo systemctl stop youtube-shorts-scheduler.timer 2>/dev/null
echo "✅ Done"

echo ""
echo "Enabling correct oneshot service..."
sudo systemctl enable youtube-shorts-scheduler.service
echo "✅ Done"

echo ""
echo "Enabling and starting timer..."
sudo systemctl enable youtube-shorts-scheduler.timer
sudo systemctl start youtube-shorts-scheduler.timer
echo "✅ Done"

echo ""
echo "=========================================="
echo "✅ FIX APPLIED"
echo "=========================================="
echo ""

# Show final status
echo "📊 Final Status:"
echo ""
echo "Timer status:"
systemctl status youtube-shorts-scheduler.timer --no-pager | head -n 10

echo ""
echo "Next scheduled runs:"
systemctl list-timers youtube-shorts-scheduler.timer --no-pager

echo ""
echo "=========================================="
echo "✅ DUPLICATE GENERATION FIX COMPLETE"
echo "=========================================="
echo ""
echo "📋 What was fixed:"
echo "   ❌ Disabled: youtube_shorts_scheduler.service (old, causes duplicates)"
echo "   ❌ Disabled: youtube_shorts_scheduler_standalone.service (wrong type)"
echo "   ✅ Enabled: youtube-shorts-scheduler.service (correct oneshot)"
echo "   ✅ Enabled: youtube-shorts-scheduler.timer (4x daily trigger)"
echo ""
echo "📋 Expected behavior:"
echo "   - Timer triggers 4x daily: 03:30, 06:30, 09:30, 12:30 UTC"
echo "   - Each run creates job in 'scheduled-videos' collection"
echo "   - Worker NEVER sees these jobs (different collection)"
echo "   - NO duplicate generation"
echo ""
echo "📋 Monitoring:"
echo "   sudo journalctl -u youtube-shorts-scheduler.service -f"
echo "   sudo journalctl -u youtube-shorts-scheduler.timer -f"
echo ""
echo "📖 See DUPLICATE_GENERATION_FIX.md for details"
echo ""
