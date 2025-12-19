"""
Origin Served Requests Monitor
Monitors requests served by origin (cache misses) and alerts when below threshold.
"""

import asyncio
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from pathlib import Path

from cloudflare_api import cf_api
from config import config

logger = logging.getLogger(__name__)

class OriginServedMonitor:
    """Monitor requests served by origin (cache misses)."""
    
    def __init__(self, bot, alert_chat_id: Optional[str] = None):
        self.bot = bot
        self.alert_chat_id = alert_chat_id
        self.state_file = Path("origin_served_monitor_state.json")
        self.check_interval = 300  # Check every 5 minutes
        self.alerts_enabled = False
        self.thresholds: Dict[str, int] = {
            '30m': 0,  # Minimum requests in last 30 minutes
            '6h': 0,   # Minimum requests in last 6 hours
            '24h': 0   # Minimum requests in last 24 hours
        }
        self.alert_state: Dict[str, bool] = {
            '30m': False,  # True if currently in alert state
            '6h': False,
            '24h': False
        }
        self._load_state()
    
    def _load_state(self):
        """Load monitoring state from file."""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    self.alerts_enabled = data.get('alerts_enabled', False)
                    self.thresholds = data.get('thresholds', {'30m': 0, '6h': 0, '24h': 0})
                    self.alert_state = data.get('alert_state', {'30m': False, '6h': False, '24h': False})
                    self.check_interval = data.get('check_interval', 300)
        except Exception as e:
            logger.warning(f"Failed to load origin served monitor state: {e}")
    
    def _save_state(self):
        """Save monitoring state to file."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump({
                    'alerts_enabled': self.alerts_enabled,
                    'thresholds': self.thresholds,
                    'alert_state': self.alert_state,
                    'check_interval': self.check_interval
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save origin served monitor state: {e}")
    
    def set_threshold(self, period: str, min_requests: int) -> bool:
        """Set minimum request threshold for a time period.
        
        Args:
            period: '30m', '6h', or '24h'
            min_requests: Minimum number of requests expected
        """
        if period not in ['30m', '6h', '24h']:
            return False
        
        self.thresholds[period] = max(0, int(min_requests))
        self._save_state()
        logger.info(f"Set {period} threshold to {min_requests} requests")
        return True
    
    def get_thresholds(self) -> Dict[str, int]:
        """Get current thresholds."""
        return self.thresholds.copy()
    
    def enable_alerts(self) -> bool:
        """Enable origin served monitoring alerts."""
        self.alerts_enabled = True
        self._save_state()
        logger.info("Origin served monitoring alerts enabled")
        return True
    
    def disable_alerts(self) -> bool:
        """Disable origin served monitoring alerts."""
        self.alerts_enabled = False
        self._save_state()
        logger.info("Origin served monitoring alerts disabled")
        return True
    
    def get_origin_served_count(self, hours: float) -> Optional[int]:
        """Get count of requests served by origin (cache misses) for given hours."""
        try:
            # Convert hours to integer (round up for fractional hours like 0.5)
            hours_int = max(1, int(hours) if hours >= 1 else 1)
            # Get cache status breakdown
            gql = cf_api.get_http_by_cache_status(hours=hours_int, zone_id=config.CLOUDFLARE_ZONE_ID)
            if not gql:
                logger.warning(f"Failed to get cache status data for {hours}h")
                return None
            
            zones = gql.get("data", {}).get("viewer", {}).get("zones", [])
            if not zones:
                return None
            
            groups = zones[0].get("httpRequestsAdaptiveGroups", [])
            
            # Sum all requests that are NOT cache hits (MISS, BYPASS, DYNAMIC, etc.)
            origin_served = 0
            for group in groups:
                cache_status = (group.get("dimensions", {}) or {}).get("cacheStatus", "")
                count = group.get("count", 0)
                
                # Count everything except HIT as origin-served
                if cache_status and cache_status.upper() != "HIT":
                    origin_served += count
            
            return origin_served
        except Exception as e:
            logger.error(f"Error getting origin served count for {hours}h: {e}", exc_info=True)
            return None
    
    async def check_thresholds(self) -> Dict[str, Dict]:
        """Check all thresholds and return results."""
        results = {}
        
        if not self.alerts_enabled:
            return results
        
        # Check each time period (in hours)
        periods = {
            '30m': 1,    # Use 1 hour for 30m (minimum granularity)
            '6h': 6,      # 6 hours
            '24h': 24     # 24 hours
        }
        
        for period, hours in periods.items():
            threshold = self.thresholds.get(period, 0)
            if threshold <= 0:
                continue  # Skip if threshold not set
            
            count = self.get_origin_served_count(hours)
            if count is None:
                continue  # Skip if data unavailable
            
            is_below = count < threshold
            was_alerting = self.alert_state.get(period, False)
            
            results[period] = {
                'count': count,
                'threshold': threshold,
                'is_below': is_below,
                'was_alerting': was_alerting,
                'hours': hours
            }
            
            # Update alert state
            if is_below and not was_alerting:
                # Just dropped below threshold - send alert
                self.alert_state[period] = True
                await self._send_alert(period, count, threshold, hours)
            elif not is_below and was_alerting:
                # Recovered - send recovery notification
                self.alert_state[period] = False
                await self._send_recovery(period, count, threshold, hours)
            elif is_below:
                # Still below threshold - might send periodic reminder
                pass
        
        self._save_state()
        return results
    
    async def _send_alert(self, period: str, count: int, threshold: int, hours: float):
        """Send alert when requests drop below threshold."""
        try:
            period_display = {
                '30m': '30 minutes',
                '6h': '6 hours',
                '24h': '24 hours'
            }.get(period, period)
            
            message = f"⚠️ <b>Origin Served Requests Alert</b>\n\n"
            message += f"<b>Period:</b> Last {period_display}\n"
            message += f"<b>Requests Served by Origin:</b> <code>{count:,}</code>\n"
            message += f"<b>Threshold:</b> <code>{threshold:,}</code>\n"
            message += f"<b>Status:</b> ❌ <b>Below Threshold</b>\n\n"
            message += f"<i>Origin requests are lower than expected. This may indicate:</i>\n"
            message += f"• High cache hit rate (good!)\n"
            message += f"• Reduced traffic\n"
            message += f"• Potential origin issues\n\n"
            message += f"<i>Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</i>"
            
            await self._send_to_all(message)
            logger.info(f"Sent origin served alert for {period}: {count} < {threshold}")
        except Exception as e:
            logger.error(f"Error sending origin served alert: {e}", exc_info=True)
    
    async def _send_recovery(self, period: str, count: int, threshold: int, hours: float):
        """Send recovery notification when requests return to normal."""
        try:
            period_display = {
                '30m': '30 minutes',
                '6h': '6 hours',
                '24h': '24 hours'
            }.get(period, period)
            
            message = f"✅ <b>Origin Served Requests Recovered</b>\n\n"
            message += f"<b>Period:</b> Last {period_display}\n"
            message += f"<b>Requests Served by Origin:</b> <code>{count:,}</code>\n"
            message += f"<b>Threshold:</b> <code>{threshold:,}</code>\n"
            message += f"<b>Status:</b> ✅ <b>Above Threshold</b>\n\n"
            message += f"<i>Origin requests have returned to normal levels.</i>\n\n"
            message += f"<i>Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</i>"
            
            await self._send_to_all(message)
            logger.info(f"Sent origin served recovery for {period}: {count} >= {threshold}")
        except Exception as e:
            logger.error(f"Error sending origin served recovery: {e}", exc_info=True)
    
    async def _send_to_all(self, message: str):
        """Send message to alert chat and all admins."""
        from config import config
        
        # Send to alert chat if configured
        if self.alert_chat_id:
            try:
                await self.bot.send_message(
                    chat_id=int(self.alert_chat_id),
                    text=message,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Failed to send to alert chat: {e}")
        
        # Send to all admin users
        for admin_id in config.ADMIN_USER_IDS:
            try:
                await self.bot.send_message(
                    chat_id=admin_id,
                    text=message,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Failed to send to admin {admin_id}: {e}")
    
    async def run_loop(self):
        """Run the monitoring loop."""
        logger.info("Starting Origin Served Requests monitor...")
        while True:
            try:
                if self.alerts_enabled:
                    await self.check_thresholds()
            except Exception as e:
                logger.error(f"Error in origin served monitor loop: {e}", exc_info=True)
            
            await asyncio.sleep(self.check_interval)

