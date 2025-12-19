"""
Cloudflare Status Page Monitor
Monitors https://www.cloudflarestatus.com/ for new incidents and posts alerts to Telegram.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from pathlib import Path
import json

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class CloudflareStatusMonitor:
    """Monitor Cloudflare status page for new incidents."""
    
    STATUS_URL = "https://www.cloudflarestatus.com/"
    API_URL = "https://status.cloudflare.com/api/v2/incidents.json"
    CHECK_INTERVAL = 300  # 5 minutes
    
    def __init__(self, bot, alert_chat_id: Optional[str] = None):
        self.bot = bot
        self.alert_chat_id = alert_chat_id
        self.seen_incidents: Set[str] = set()
        self.state_file = Path("status_monitor_state.json")
        self._load_state()
    
    def _load_state(self):
        """Load previously seen incidents from state file."""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    self.seen_incidents = set(data.get('seen_incidents', []))
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")
    
    def _save_state(self):
        """Save seen incidents to state file."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump({'seen_incidents': list(self.seen_incidents)}, f)
        except Exception as e:
            logger.warning(f"Failed to save state: {e}")
    
    def _parse_incidents_from_html(self) -> List[Dict]:
        """Parse incidents from the status page HTML."""
        try:
            response = requests.get(self.STATUS_URL, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            incidents = []
            # Look for incident containers
            incident_elements = soup.find_all(['div', 'section'], class_=re.compile(r'incident|status', re.I))
            
            for elem in incident_elements:
                try:
                    # Try to extract incident information
                    title_elem = elem.find(['h1', 'h2', 'h3', 'h4'], class_=re.compile(r'title|name', re.I))
                    if not title_elem:
                        title_elem = elem.find(['h1', 'h2', 'h3', 'h4'])
                    
                    status_elem = elem.find(['span', 'div'], class_=re.compile(r'status|state', re.I))
                    date_elem = elem.find(['time', 'span'], class_=re.compile(r'date|time', re.I))
                    
                    if title_elem:
                        title = title_elem.get_text(strip=True)
                        status = status_elem.get_text(strip=True) if status_elem else "Unknown"
                        date = date_elem.get_text(strip=True) if date_elem else ""
                        
                        # Create a unique ID from title and date
                        incident_id = f"{title}_{date}"
                        
                        incidents.append({
                            'id': incident_id,
                            'title': title,
                            'status': status,
                            'date': date,
                            'description': elem.get_text(separator=' ', strip=True)[:500]
                        })
                except Exception as e:
                    logger.debug(f"Error parsing incident element: {e}")
                    continue
            
            return incidents
        except Exception as e:
            logger.error(f"Error fetching status page: {e}")
            return []
    
    def _fetch_incidents_from_api(self) -> List[Dict]:
        """Fetch incidents from the status API."""
        try:
            response = requests.get(self.API_URL, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            incidents = []
            for incident in data.get('incidents', []):
                incident_id = incident.get('id', '')
                name = incident.get('name', 'Unknown')
                status = incident.get('status', 'unknown')
                created_at = incident.get('created_at', '')
                updated_at = incident.get('updated_at', '')
                
                # Get latest update
                updates = incident.get('incident_updates', [])
                latest_update = updates[0] if updates else {}
                body = latest_update.get('body', '')
                
                incidents.append({
                    'id': incident_id,
                    'title': name,
                    'status': status,
                    'date': created_at,
                    'updated': updated_at,
                    'description': body[:500],
                    'url': f"https://www.cloudflarestatus.com/incidents/{incident_id}"
                })
            
            return incidents
        except requests.exceptions.ConnectionError as e:
            # DNS/network errors are common and not critical - just log as warning
            logger.debug(f"Status API connection error (non-critical): {e}")
            return []
        except Exception as e:
            logger.warning(f"Error fetching status from API: {e}")
            return []
    
    def _format_incident_message(self, incident: Dict) -> str:
        """Format incident for Telegram message."""
        status_emoji = {
            'investigating': '🔍',
            'identified': '🔎',
            'monitoring': '👀',
            'resolved': '✅',
            'scheduled': '📅',
            'in progress': '⚙️',
            'completed': '✅',
            'completed': '✅',
        }
        
        status = incident.get('status', 'unknown').lower()
        emoji = status_emoji.get(status, '⚠️')
        
        message = f"{emoji} <b>Cloudflare Status Update</b>\n\n"
        message += f"<b>Title:</b> {incident.get('title', 'Unknown')}\n"
        message += f"<b>Status:</b> {incident.get('status', 'Unknown')}\n"
        
        if incident.get('date'):
            message += f"<b>Date:</b> {incident.get('date')}\n"
        
        if incident.get('description'):
            desc = incident.get('description', '')[:300]
            message += f"\n<b>Details:</b>\n{desc}\n"
        
        if incident.get('url'):
            message += f"\n<a href=\"{incident['url']}\">View on Status Page</a>"
        
        return message
    
    async def check_for_new_incidents(self):
        """Check for new incidents and send alerts."""
        try:
            # Try API first, fallback to HTML parsing
            incidents = self._fetch_incidents_from_api()
            if not incidents:
                incidents = self._parse_incidents_from_html()
            
            new_incidents = []
            for incident in incidents:
                incident_id = incident.get('id', '')
                if incident_id and incident_id not in self.seen_incidents:
                    new_incidents.append(incident)
                    self.seen_incidents.add(incident_id)
            
            if new_incidents:
                self._save_state()
                for incident in new_incidents:
                    await self._send_alert(incident)
            
            return len(new_incidents)
        except Exception as e:
            logger.error(f"Error checking incidents: {e}", exc_info=True)
            return 0
    
    async def _send_alert(self, incident: Dict):
        """Send alert to Telegram."""
        try:
            message = self._format_incident_message(incident)
            
            # Send to alert chat if configured
            if self.alert_chat_id:
                try:
                    await self.bot.send_message(
                        chat_id=int(self.alert_chat_id),
                        text=message,
                        parse_mode='HTML',
                        disable_web_page_preview=False
                    )
                    logger.info(f"Sent status alert to {self.alert_chat_id}")
                except Exception as e:
                    logger.error(f"Failed to send alert to chat {self.alert_chat_id}: {e}")
            
            # Also send to all admin users
            from config import config
            for admin_id in config.ADMIN_USER_IDS:
                try:
                    await self.bot.send_message(
                        chat_id=admin_id,
                        text=message,
                        parse_mode='HTML',
                        disable_web_page_preview=False
                    )
                    logger.info(f"Sent status alert to admin {admin_id}")
                except Exception as e:
                    logger.error(f"Failed to send alert to admin {admin_id}: {e}")
        except Exception as e:
            logger.error(f"Error sending alert: {e}", exc_info=True)
    
    async def run_loop(self):
        """Run the monitoring loop."""
        logger.info("Starting Cloudflare Status monitor...")
        while True:
            try:
                await self.check_for_new_incidents()
            except Exception as e:
                logger.error(f"Error in status monitor loop: {e}", exc_info=True)
            
            await asyncio.sleep(self.CHECK_INTERVAL)

