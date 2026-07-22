"""
Weekly Email Analytics Report
==============================

Generates and sends a comprehensive HTML email report with:
- Channel overview (views, watch time, subscribers)
- Top/bottom performing videos
- Visual theme performance breakdown
- Hook archetype performance breakdown
- Voice performance comparison

Designed to run after sync_analytics.py (Sunday 2AM IST).
"""

import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class WeeklyReportGenerator:
    """Generates and sends weekly analytics reports via SMTP."""

    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_email = os.getenv("SMTP_EMAIL", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.recipient_email = os.getenv("REPORT_RECIPIENT_EMAIL", "")
        self.channel_name = "Code Tapasya"

    @property
    def is_configured(self) -> bool:
        """Check if SMTP credentials are fully configured."""
        return all([
            self.smtp_host,
            self.smtp_port,
            self.smtp_email,
            self.smtp_password,
            self.recipient_email,
        ])

    def generate_and_send(self) -> bool:
        """
        Main entry point: gather data, build report, send email.
        
        Returns:
            True if email sent successfully, False otherwise.
        """
        if not self.is_configured:
            logger.warning("⚠️ SMTP not configured — skipping weekly email report. "
                         "Set SMTP_HOST, SMTP_PORT, SMTP_EMAIL, SMTP_PASSWORD, REPORT_RECIPIENT_EMAIL in .env")
            return False

        try:
            logger.info("📊 Generating weekly analytics report...")

            # Gather all data
            channel_data = self._gather_channel_data()
            video_data = self._gather_video_data()
            theme_performance = self._gather_metadata_performance("visual_theme")
            hook_performance = self._gather_metadata_performance("hook_archetype")
            voice_performance = self._gather_metadata_performance("voice")

            # Build HTML email
            html_content = self._build_html_report(
                channel_data=channel_data,
                video_data=video_data,
                theme_performance=theme_performance,
                hook_performance=hook_performance,
                voice_performance=voice_performance,
            )

            # Send email
            success = self._send_email(html_content)
            if success:
                logger.info("✅ Weekly analytics report sent successfully!")
            return success

        except Exception as e:
            logger.error(f"❌ Failed to generate/send weekly report: {e}", exc_info=True)
            return False

    def _gather_channel_data(self) -> Dict[str, Any]:
        """Fetch channel-level analytics for the past 7 days."""
        try:
            from analytics.youtube_oauth_analytics import YouTubeAnalyticsFetcher
            fetcher = YouTubeAnalyticsFetcher()
            if not fetcher.is_connected:
                logger.warning("YouTube Analytics not connected")
                return {}

            overview = fetcher.get_channel_overview(days=7) or {}
            prev_overview = fetcher.get_channel_overview(days=14) or {}

            # Calculate week-over-week changes
            if prev_overview and overview:
                prev_views = max(prev_overview.get("total_views", 0) - overview.get("total_views", 0), 1)
                current_views = overview.get("total_views", 0)
                overview["views_change_pct"] = round(
                    ((current_views - prev_views) / max(prev_views, 1)) * 100, 1
                )
            return overview

        except Exception as e:
            logger.error(f"Failed to gather channel data: {e}")
            return {}

    def _gather_video_data(self) -> List[Dict[str, Any]]:
        """Fetch stats for recent videos, sorted by views."""
        try:
            from analytics.youtube_oauth_analytics import YouTubeAnalyticsFetcher
            fetcher = YouTubeAnalyticsFetcher()
            if not fetcher.is_connected:
                return []

            recent = fetcher.get_recent_videos(max_results=28)
            enriched = []

            for video in recent:
                stats = fetcher.get_video_statistics(video["video_id"])
                analytics = fetcher.get_video_analytics(video["video_id"], days=7)

                entry = {
                    "video_id": video["video_id"],
                    "title": video.get("title", "Untitled"),
                    "published_at": video.get("published_at", ""),
                    "views": stats.get("view_count", 0) if stats else 0,
                    "likes": stats.get("like_count", 0) if stats else 0,
                    "comments": stats.get("comment_count", 0) if stats else 0,
                    "retention": analytics.get("avg_view_percentage", 0) if analytics else 0,
                }
                enriched.append(entry)

            # Sort by views descending
            enriched.sort(key=lambda x: x["views"], reverse=True)
            return enriched

        except Exception as e:
            logger.error(f"Failed to gather video data: {e}")
            return []

    def _gather_metadata_performance(self, field_name: str) -> Dict[str, Dict[str, Any]]:
        """
        Aggregate video performance by a metadata field stored in Firestore.
        
        Args:
            field_name: e.g., 'visual_theme', 'hook_archetype', 'voice'
        
        Returns:
            Dict mapping field values to {avg_views, count, total_views}
        """
        try:
            import firebase_admin
            from firebase_admin import firestore

            if not firebase_admin._apps:
                return {}

            db = firestore.client()

            # Query videos with the metadata field
            videos_ref = db.collection("generated_videos")
            docs = videos_ref.where(field_name, "!=", "").limit(100).stream()

            performance = {}
            for doc in docs:
                data = doc.to_dict()
                field_val = data.get(field_name, "unknown")
                views = data.get("youtube_views", data.get("views", 0))

                if field_val not in performance:
                    performance[field_val] = {"total_views": 0, "count": 0}

                performance[field_val]["total_views"] += views
                performance[field_val]["count"] += 1

            # Calculate averages
            for key in performance:
                count = performance[key]["count"]
                performance[key]["avg_views"] = round(
                    performance[key]["total_views"] / max(count, 1)
                )

            return performance

        except Exception as e:
            logger.debug(f"Metadata performance query for '{field_name}' failed: {e}")
            return {}

    def _build_html_report(
        self,
        channel_data: Dict,
        video_data: List[Dict],
        theme_performance: Dict,
        hook_performance: Dict,
        voice_performance: Dict,
    ) -> str:
        """Build a clean, responsive HTML email report."""

        now = datetime.now(timezone.utc)
        week_start = (now - timedelta(days=7)).strftime("%B %d")
        week_end = now.strftime("%B %d, %Y")

        # --- Channel Overview Section ---
        views = channel_data.get("total_views", 0)
        watch_time = channel_data.get("watch_time_minutes", 0)
        net_subs = channel_data.get("net_subscribers", 0)
        retention = channel_data.get("avg_view_percentage", 0)
        views_change = channel_data.get("views_change_pct", 0)
        views_arrow = "📈" if views_change >= 0 else "📉"

        # --- Top/Bottom Videos ---
        top_5 = video_data[:5] if video_data else []
        bottom_3 = video_data[-3:] if len(video_data) > 5 else []

        # Build top videos HTML
        top_videos_html = ""
        for i, v in enumerate(top_5, 1):
            medal = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i - 1]
            top_videos_html += f"""
            <tr>
                <td style="padding: 8px 12px; border-bottom: 1px solid #2a2a3e;">{medal}</td>
                <td style="padding: 8px 12px; border-bottom: 1px solid #2a2a3e; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{v['title'][:50]}</td>
                <td style="padding: 8px 12px; border-bottom: 1px solid #2a2a3e; text-align: right;">{v['views']:,}</td>
                <td style="padding: 8px 12px; border-bottom: 1px solid #2a2a3e; text-align: right;">{v['retention']:.0f}%</td>
                <td style="padding: 8px 12px; border-bottom: 1px solid #2a2a3e; text-align: right;">{v['likes']:,}</td>
            </tr>"""

        # Build bottom videos HTML
        bottom_videos_html = ""
        for v in bottom_3:
            bottom_videos_html += f"""
            <tr>
                <td style="padding: 8px 12px; border-bottom: 1px solid #2a2a3e;">⚠️</td>
                <td style="padding: 8px 12px; border-bottom: 1px solid #2a2a3e; max-width: 300px;">{v['title'][:50]}</td>
                <td style="padding: 8px 12px; border-bottom: 1px solid #2a2a3e; text-align: right;">{v['views']:,}</td>
                <td style="padding: 8px 12px; border-bottom: 1px solid #2a2a3e; text-align: right;">{v['retention']:.0f}%</td>
                <td style="padding: 8px 12px; border-bottom: 1px solid #2a2a3e; text-align: right;">{v['likes']:,}</td>
            </tr>"""

        # Build metadata performance sections
        def _build_perf_section(title: str, data: Dict, emoji: str) -> str:
            if not data:
                return f"""
                <div style="margin-bottom: 24px;">
                    <h3 style="color: #a78bfa; margin-bottom: 12px;">{emoji} {title}</h3>
                    <p style="color: #666;">No data yet — will populate after new videos are generated.</p>
                </div>"""

            # Sort by avg views descending
            sorted_items = sorted(data.items(), key=lambda x: x[1].get("avg_views", 0), reverse=True)
            best_key = sorted_items[0][0] if sorted_items else ""

            rows = ""
            for key, metrics in sorted_items:
                badge = " ← BEST" if key == best_key else ""
                badge_style = "color: #10b981; font-weight: bold;" if badge else ""
                rows += f"""
                <tr>
                    <td style="padding: 8px 12px; border-bottom: 1px solid #2a2a3e;">{key}</td>
                    <td style="padding: 8px 12px; border-bottom: 1px solid #2a2a3e; text-align: right;">{metrics.get('avg_views', 0):,}</td>
                    <td style="padding: 8px 12px; border-bottom: 1px solid #2a2a3e; text-align: right;">{metrics.get('count', 0)}</td>
                    <td style="padding: 8px 12px; border-bottom: 1px solid #2a2a3e; text-align: right;"><span style="{badge_style}">{badge}</span></td>
                </tr>"""

            return f"""
            <div style="margin-bottom: 24px;">
                <h3 style="color: #a78bfa; margin-bottom: 12px;">{emoji} {title}</h3>
                <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                    <thead>
                        <tr style="background: #1e1e2e;">
                            <th style="padding: 10px 12px; text-align: left; border-bottom: 2px solid #a78bfa;">Name</th>
                            <th style="padding: 10px 12px; text-align: right; border-bottom: 2px solid #a78bfa;">Avg Views</th>
                            <th style="padding: 10px 12px; text-align: right; border-bottom: 2px solid #a78bfa;">Videos</th>
                            <th style="padding: 10px 12px; text-align: right; border-bottom: 2px solid #a78bfa;"></th>
                        </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>"""

        theme_section = _build_perf_section("Visual Themes", theme_performance, "🎨")
        hook_section = _build_perf_section("Hook Archetypes", hook_performance, "🎣")
        voice_section = _build_perf_section("Voice Performance", voice_performance, "🎙️")

        # --- Full HTML Email ---
        html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin: 0; padding: 0; background-color: #0a0a1a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #e0e0e0;">
    <div style="max-width: 680px; margin: 0 auto; padding: 24px;">
        
        <!-- Header -->
        <div style="text-align: center; padding: 32px 0; border-bottom: 2px solid #a78bfa;">
            <h1 style="color: #a78bfa; margin: 0; font-size: 28px;">📊 {self.channel_name}</h1>
            <p style="color: #888; margin-top: 8px; font-size: 16px;">Weekly Analytics Report</p>
            <p style="color: #666; margin-top: 4px; font-size: 14px;">{week_start} – {week_end}</p>
        </div>

        <!-- Channel Overview -->
        <div style="margin-top: 32px;">
            <h2 style="color: #a78bfa; margin-bottom: 16px;">📈 Channel Overview (Last 7 Days)</h2>
            <div style="display: flex; flex-wrap: wrap; gap: 12px;">
                <div style="background: #1e1e2e; border-radius: 12px; padding: 20px; flex: 1; min-width: 140px; text-align: center;">
                    <div style="font-size: 28px; font-weight: bold; color: #a78bfa;">{views:,}</div>
                    <div style="color: #888; font-size: 12px; margin-top: 4px;">Total Views {views_arrow} {views_change:+.1f}%</div>
                </div>
                <div style="background: #1e1e2e; border-radius: 12px; padding: 20px; flex: 1; min-width: 140px; text-align: center;">
                    <div style="font-size: 28px; font-weight: bold; color: #10b981;">{watch_time:,.0f}</div>
                    <div style="color: #888; font-size: 12px; margin-top: 4px;">Watch Time (min)</div>
                </div>
                <div style="background: #1e1e2e; border-radius: 12px; padding: 20px; flex: 1; min-width: 140px; text-align: center;">
                    <div style="font-size: 28px; font-weight: bold; color: {'#10b981' if net_subs >= 0 else '#ef4444'};">{net_subs:+d}</div>
                    <div style="color: #888; font-size: 12px; margin-top: 4px;">Net Subscribers</div>
                </div>
                <div style="background: #1e1e2e; border-radius: 12px; padding: 20px; flex: 1; min-width: 140px; text-align: center;">
                    <div style="font-size: 28px; font-weight: bold; color: #f59e0b;">{retention:.1f}%</div>
                    <div style="color: #888; font-size: 12px; margin-top: 4px;">Avg Retention</div>
                </div>
            </div>
        </div>

        <!-- Top Performers -->
        <div style="margin-top: 32px;">
            <h2 style="color: #a78bfa; margin-bottom: 16px;">🏆 Top 5 Performers</h2>
            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                <thead>
                    <tr style="background: #1e1e2e;">
                        <th style="padding: 10px 12px; text-align: left; border-bottom: 2px solid #a78bfa; width: 40px;">#</th>
                        <th style="padding: 10px 12px; text-align: left; border-bottom: 2px solid #a78bfa;">Title</th>
                        <th style="padding: 10px 12px; text-align: right; border-bottom: 2px solid #a78bfa;">Views</th>
                        <th style="padding: 10px 12px; text-align: right; border-bottom: 2px solid #a78bfa;">Retention</th>
                        <th style="padding: 10px 12px; text-align: right; border-bottom: 2px solid #a78bfa;">Likes</th>
                    </tr>
                </thead>
                <tbody>{top_videos_html or '<tr><td colspan="5" style="padding: 12px; color: #666;">No video data yet</td></tr>'}</tbody>
            </table>
        </div>

        <!-- Bottom Performers -->
        {"" if not bottom_videos_html else f'''
        <div style="margin-top: 32px;">
            <h2 style="color: #ef4444; margin-bottom: 16px;">📉 Needs Improvement (Bottom 3)</h2>
            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                <thead>
                    <tr style="background: #1e1e2e;">
                        <th style="padding: 10px 12px; text-align: left; border-bottom: 2px solid #ef4444; width: 40px;"></th>
                        <th style="padding: 10px 12px; text-align: left; border-bottom: 2px solid #ef4444;">Title</th>
                        <th style="padding: 10px 12px; text-align: right; border-bottom: 2px solid #ef4444;">Views</th>
                        <th style="padding: 10px 12px; text-align: right; border-bottom: 2px solid #ef4444;">Retention</th>
                        <th style="padding: 10px 12px; text-align: right; border-bottom: 2px solid #ef4444;">Likes</th>
                    </tr>
                </thead>
                <tbody>{bottom_videos_html}</tbody>
            </table>
        </div>'''}

        <!-- Metadata Performance Sections -->
        <div style="margin-top: 32px;">
            <h2 style="color: #a78bfa; margin-bottom: 16px;">🔬 Content Strategy Analytics</h2>
            {theme_section}
            {hook_section}
            {voice_section}
        </div>

        <!-- Footer -->
        <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #2a2a3e; text-align: center;">
            <p style="color: #666; font-size: 12px;">
                Generated by {self.channel_name} Analytics Engine<br>
                {now.strftime('%Y-%m-%d %H:%M UTC')}
            </p>
        </div>
    </div>
</body>
</html>"""

        return html

    def _send_email(self, html_content: str) -> bool:
        """Send the HTML report via SMTP with robust error handling."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"📊 {self.channel_name} — Weekly Report ({datetime.now().strftime('%b %d')})"
        msg["From"] = self.smtp_email
        msg["To"] = self.recipient_email

        # Plain text fallback
        plain_text = (
            f"{self.channel_name} Weekly Analytics Report\n"
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            "Open this email in an HTML-capable client for the full report."
        )
        msg.attach(MIMEText(plain_text, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(self.smtp_email, self.smtp_password)
                server.sendmail(self.smtp_email, self.recipient_email, msg.as_string())
            logger.info(f"📧 Report emailed to {self.recipient_email}")
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"❌ SMTP auth failed — check SMTP_EMAIL and SMTP_PASSWORD: {e}")
            return False
        except smtplib.SMTPRecipientsRefused as e:
            logger.error(f"❌ Recipient refused — check REPORT_RECIPIENT_EMAIL: {e}")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"❌ SMTP error: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Email send failed: {e}", exc_info=True)
            return False

    def send_test_email(self) -> bool:
        """Send a test email to verify SMTP configuration."""
        if not self.is_configured:
            print("❌ SMTP not configured. Set env vars: SMTP_HOST, SMTP_PORT, SMTP_EMAIL, SMTP_PASSWORD, REPORT_RECIPIENT_EMAIL")
            return False

        test_html = f"""
        <html>
        <body style="background: #0a0a1a; color: #e0e0e0; font-family: sans-serif; padding: 40px; text-align: center;">
            <h1 style="color: #a78bfa;">✅ SMTP Test Successful!</h1>
            <p>{self.channel_name} analytics email is working.</p>
            <p style="color: #888;">Sent at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
        </body>
        </html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"✅ {self.channel_name} — Email Test"
        msg["From"] = self.smtp_email
        msg["To"] = self.recipient_email
        msg.attach(MIMEText(test_html, "html"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(self.smtp_email, self.smtp_password)
                server.sendmail(self.smtp_email, self.recipient_email, msg.as_string())
            print(f"✅ Test email sent to {self.recipient_email}")
            return True
        except Exception as e:
            print(f"❌ Test failed: {e}")
            return False


# CLI support
if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from dotenv import load_dotenv
    load_dotenv(override=True)

    logging.basicConfig(level=logging.INFO)

    generator = WeeklyReportGenerator()

    if "--test" in sys.argv:
        generator.send_test_email()
    else:
        generator.generate_and_send()
