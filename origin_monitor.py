"""
Origin Health Monitor
Monitors origin server health by testing HTTP connections and alerting on errors.
"""

import asyncio
import logging
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from pathlib import Path
from urllib.parse import urlparse, urljoin
import aiohttp
import time

logger = logging.getLogger(__name__)

class OriginMonitor:
    """Monitor origin server health."""
    
    # Note: Only 5xx server errors trigger alerts
    # 4xx client errors (404, 403, etc.) are ignored as they're not server problems
    
    def __init__(self, bot, alert_chat_id: Optional[str] = None):
        self.bot = bot
        self.alert_chat_id = alert_chat_id
        self.tracked_origins: Dict[str, Dict] = {}  # URL -> config
        self.state_file = Path("origin_monitor_state.json")
        self.check_interval = 60  # 1 minute default
        self.timeout = 10  # 10 seconds timeout
        self._load_state()
    
    def _load_state(self):
        """Load tracked origins from state file."""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    self.tracked_origins = data.get('tracked_origins', {})
                    self.check_interval = data.get('check_interval', 60)
                    self.timeout = data.get('timeout', 10)
        except Exception as e:
            logger.warning(f"Failed to load origin monitor state: {e}")
    
    def _save_state(self):
        """Save tracked origins to state file."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump({
                    'tracked_origins': self.tracked_origins,
                    'check_interval': self.check_interval,
                    'timeout': self.timeout
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save origin monitor state: {e}")
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL to a standard format."""
        url = url.strip()
        # Don't lowercase the entire URL - preserve path case
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"
        # Ensure URL is properly formatted
        parsed = urlparse(url)
        if not parsed.netloc:
            raise ValueError(f"Invalid URL format: {url}")
        # Reconstruct URL with proper scheme
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.query:
            normalized += f"?{parsed.query}"
        if parsed.fragment:
            normalized += f"#{parsed.fragment}"
        return normalized
    
    def add_origin(self, url: str, user_id: int, check_interval: int = 60, timeout: int = 10) -> bool:
        """Add an origin to monitor.
        
        Args:
            url: Full URL to monitor (e.g., https://example.com/api/health or https://example.com)
            user_id: Telegram user ID who added this origin
            check_interval: How often to check (in seconds)
            timeout: Request timeout (in seconds)
        
        Note: Only 5xx server errors will trigger alerts. 4xx client errors are ignored.
        """
        try:
            # Normalize URL
            normalized_url = self._normalize_url(url)
            
            self.tracked_origins[normalized_url] = {
                'url': normalized_url,
                'user_id': user_id,
                'check_interval': check_interval,
                'timeout': timeout,
                'last_check': None,
                'last_status': None,
                'consecutive_failures': 0,
                'enabled': True,
                'total_checks': 0,
                'successful_checks': 0
            }
            self._save_state()
            logger.info(f"Added origin monitoring for {normalized_url}")
            return True
        except Exception as e:
            logger.error(f"Error adding origin {url}: {e}")
            return False
    
    def remove_origin(self, url: str) -> bool:
        """Remove an origin from monitoring."""
        try:
            normalized_url = self._normalize_url(url)
            
            if normalized_url in self.tracked_origins:
                del self.tracked_origins[normalized_url]
                self._save_state()
                logger.info(f"Removed origin monitoring for {normalized_url}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error removing origin {url}: {e}")
            return False
    
    def list_origins(self) -> List[Dict]:
        """List all tracked origins."""
        return list(self.tracked_origins.values())
    
    def _is_critical_error(self, status_code: int, url: str, config: Dict) -> bool:
        """Determine if an error status code is critical and should trigger an alert.
        
        Only 5xx server errors are considered critical. 4xx client errors are ignored.
        """
        # Only 5xx server errors are critical
        if 500 <= status_code < 600:
            return True
        
        # 4xx errors are not critical (client errors, not server problems)
        # Connection errors and timeouts are handled separately and are always critical
        return False
    
    async def check_origin(self, url: str) -> Dict:
        """Check a single origin's health."""
        config = self.tracked_origins.get(url)
        if not config:
            # Try to find by normalized URL
            try:
                normalized = self._normalize_url(url)
                config = self.tracked_origins.get(normalized)
                if config:
                    url = normalized
                else:
                    return {'error': 'Origin not found'}
            except Exception:
                return {'error': 'Origin not found'}
        
        start_time = time.time()
        status_code = None
        error = None
        is_error = False
        is_critical = False
        
        try:
            timeout = aiohttp.ClientTimeout(total=config.get('timeout', self.timeout))
            headers = {
                'User-Agent': 'PocketCF-OriginMonitor/1.0',
                'Accept': '*/*'
            }
            
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                try:
                    async with session.get(url, allow_redirects=True, ssl=True) as response:
                        status_code = response.status
                        response_time = time.time() - start_time
                        
                        config['last_check'] = datetime.now(timezone.utc).isoformat()
                        config['last_status'] = status_code
                        config['total_checks'] = config.get('total_checks', 0) + 1
                        
                        # Determine if this is a critical error (only 5xx)
                        is_critical = self._is_critical_error(status_code, url, config)
                        
                        if is_critical:
                            # 5xx server error - critical
                            is_error = True
                            config['consecutive_failures'] = config.get('consecutive_failures', 0) + 1
                        elif 400 <= status_code < 500:
                            # 4xx client error - not critical, don't alert
                            is_error = False
                            config['consecutive_failures'] = 0
                            logger.debug(f"4xx error {status_code} for {url} - not critical, ignoring")
                        else:
                            # 2xx or 3xx - success
                            is_error = False
                            config['consecutive_failures'] = 0
                            if 200 <= status_code < 400:
                                config['successful_checks'] = config.get('successful_checks', 0) + 1
                        
                        return {
                            'url': url,
                            'status_code': status_code,
                            'response_time': response_time,
                            'is_error': is_error,
                            'is_critical': is_critical,
                            'consecutive_failures': config['consecutive_failures']
                        }
                except asyncio.TimeoutError:
                    error = "Request timeout"
                    is_error = True
                    is_critical = True
                    config['consecutive_failures'] = config.get('consecutive_failures', 0) + 1
                except aiohttp.ClientConnectorError as e:
                    error = f"Connection error: {str(e)[:100]}"
                    is_error = True
                    is_critical = True
                    config['consecutive_failures'] = config.get('consecutive_failures', 0) + 1
                except aiohttp.ClientError as e:
                    error = f"Client error: {str(e)[:100]}"
                    is_error = True
                    is_critical = True
                    config['consecutive_failures'] = config.get('consecutive_failures', 0) + 1
        except Exception as e:
            error = f"Unexpected error: {str(e)[:100]}"
            is_error = True
            is_critical = True
            config['consecutive_failures'] = config.get('consecutive_failures', 0) + 1
        
        config['last_check'] = datetime.now(timezone.utc).isoformat()
        config['last_status'] = f"Error: {error}" if error else None
        config['total_checks'] = config.get('total_checks', 0) + 1
        
        return {
            'url': url,
            'status_code': status_code,
            'error': error,
            'is_error': is_error,
            'is_critical': is_critical,
            'consecutive_failures': config['consecutive_failures']
        }
    
    async def check_all_origins(self):
        """Check all tracked origins."""
        results = []
        for url, config in self.tracked_origins.items():
            if not config.get('enabled', True):
                continue
            
            # Check if it's time to check this origin
            last_check = config.get('last_check')
            check_interval = config.get('check_interval', self.check_interval)
            
            if last_check:
                try:
                    last_check_dt = datetime.fromisoformat(last_check.replace('Z', '+00:00'))
                    time_since_check = (datetime.now(timezone.utc) - last_check_dt).total_seconds()
                    if time_since_check < check_interval:
                        continue
                except Exception:
                    pass
            
            result = await self.check_origin(url)
            results.append(result)
            
            # Send alert only if critical error detected
            if result.get('is_critical'):
                await self._send_alert(url, result)
        
        self._save_state()
        return results
    
    async def _send_alert(self, url: str, result: Dict):
        """Send alert when critical origin error is detected."""
        try:
            config = self.tracked_origins.get(url)
            if not config:
                return
            
            status_code = result.get('status_code', 'N/A')
            error = result.get('error', '')
            consecutive = result.get('consecutive_failures', 0)
            response_time = result.get('response_time', 0)
            
            # Only alert on first failure or every 5 consecutive failures
            if consecutive > 0 and (consecutive == 1 or consecutive % 5 == 0):
                message = f"🚨 <b>Origin Health Alert</b>\n\n"
                message += f"<b>URL:</b> <code>{url}</code>\n"
                if status_code:
                    message += f"<b>Status Code:</b> <code>{status_code}</code> (5xx Server Error)\n"
                if response_time:
                    message += f"<b>Response Time:</b> {response_time:.2f}s\n"
                if error:
                    message += f"<b>Error:</b> <code>{error}</code>\n"
                message += f"<b>Consecutive Failures:</b> {consecutive}\n"
                message += f"\n<i>Note: Only 5xx server errors trigger alerts. 4xx client errors are ignored.</i>\n"
                
                # Add statistics if available
                total_checks = config.get('total_checks', 0)
                successful = config.get('successful_checks', 0)
                if total_checks > 0:
                    success_rate = (successful / total_checks) * 100
                    message += f"<b>Success Rate:</b> {success_rate:.1f}% ({successful}/{total_checks})\n"
                
                message += f"\n<i>Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</i>"
                
                # Send to alert chat if configured
                if self.alert_chat_id:
                    try:
                        await self.bot.send_message(
                            chat_id=int(self.alert_chat_id),
                            text=message,
                            parse_mode='HTML'
                        )
                    except Exception as e:
                        logger.error(f"Failed to send origin alert to chat: {e}")
                
                # Send to the user who added this origin
                user_id = config.get('user_id')
                if user_id:
                    try:
                        await self.bot.send_message(
                            chat_id=user_id,
                            text=message,
                            parse_mode='HTML'
                        )
                        logger.info(f"Sent origin alert for {url} to user {user_id}")
                    except Exception as e:
                        logger.error(f"Failed to send origin alert to user {user_id}: {e}")
        except Exception as e:
            logger.error(f"Error sending origin alert: {e}", exc_info=True)
    
    async def run_loop(self):
        """Run the monitoring loop."""
        logger.info("Starting Origin Health monitor...")
        while True:
            try:
                await self.check_all_origins()
            except Exception as e:
                logger.error(f"Error in origin monitor loop: {e}", exc_info=True)
            
            await asyncio.sleep(min(30, self.check_interval))  # Check at least every 30 seconds

