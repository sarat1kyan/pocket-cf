import os
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    env_path = Path('.env')
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    # python-dotenv not installed, will use environment variables only
    pass

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Raised when configuration is invalid or missing required values."""
    pass


class _Config:
    """Configuration manager for the Cloudflare Telegram Bot."""
    
    def _strip_quotes(self, value: str) -> str:
        """Remove surrounding quotes from environment variable values."""
        if not value:
            return value
        value = value.strip()
        # Remove surrounding single or double quotes
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            return value[1:-1]
        return value
    
    def __init__(self):
        # Telegram Bot Configuration
        self.TELEGRAM_BOT_TOKEN = self._strip_quotes(os.getenv('TELEGRAM_BOT_TOKEN', ''))
        admin_ids_str = self._strip_quotes(os.getenv('ADMIN_USER_IDS', ''))
        self.ADMIN_USER_IDS: List[int] = []
        if admin_ids_str:
            try:
                self.ADMIN_USER_IDS = [int(x.strip()) for x in admin_ids_str.split(',') if x.strip()]
            except ValueError as e:
                logger.warning(f"Invalid ADMIN_USER_IDS format: {e}")
        self.ALERT_CHAT_ID = self._strip_quotes(os.getenv('ALERT_CHAT_ID', ''))
        
        # Cloudflare API Configuration
        self.CLOUDFLARE_API_TOKEN = self._strip_quotes(os.getenv('CLOUDFLARE_API_TOKEN', ''))
        self.CLOUDFLARE_ACCOUNT_ID = self._strip_quotes(os.getenv('CLOUDFLARE_ACCOUNT_ID', ''))
        self.CLOUDFLARE_ZONE_ID = self._strip_quotes(os.getenv('CLOUDFLARE_ZONE_ID', ''))
        
        # Monitoring Configuration
        self.CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '300'))
        self.ALERT_THRESHOLDS = {
            'requests_per_second': 1000,
            'bandwidth_mbps': 100,
            'error_rate': 0.05,  # 5%
            'threats_count': 10
        }
        
        # Logging
        self.LOG_RETENTION_DAYS = int(os.getenv('LOG_RETENTION_DAYS', '30'))
        
        # UI defaults
        self.DEFAULT_HOURS = int(os.getenv('DEFAULT_HOURS', '24'))
    
    def validate(self) -> None:
        """Validate that all required configuration values are present."""
        errors: List[str] = []
        
        if not self.TELEGRAM_BOT_TOKEN or self.TELEGRAM_BOT_TOKEN.startswith('0123456789'):
            errors.append("TELEGRAM_BOT_TOKEN is required and must be a valid token")
        
        if not self.ADMIN_USER_IDS:
            errors.append("ADMIN_USER_IDS is required (comma-separated list of Telegram user IDs)")
        
        if not self.CLOUDFLARE_API_TOKEN:
            errors.append("CLOUDFLARE_API_TOKEN is required")
        elif len(self.CLOUDFLARE_API_TOKEN) < 20:
            errors.append(f"CLOUDFLARE_API_TOKEN appears to be too short (length: {len(self.CLOUDFLARE_API_TOKEN)})")
        elif len(self.CLOUDFLARE_API_TOKEN) < 40:
            logger.warning(f"CLOUDFLARE_API_TOKEN seems short (length: {len(self.CLOUDFLARE_API_TOKEN)}). Cloudflare tokens are usually 40+ characters.")
        
        if not self.CLOUDFLARE_ZONE_ID:
            errors.append("CLOUDFLARE_ZONE_ID is required")
        elif len(self.CLOUDFLARE_ZONE_ID) < 20:
            errors.append(f"CLOUDFLARE_ZONE_ID appears to be too short (length: {len(self.CLOUDFLARE_ZONE_ID)})")
        elif len(self.CLOUDFLARE_ZONE_ID) != 32:
            logger.warning(f"CLOUDFLARE_ZONE_ID length is {len(self.CLOUDFLARE_ZONE_ID)}. Zone IDs are typically 32 characters.")
        
        if errors:
            raise ConfigurationError("Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors))
    
    def is_valid(self) -> bool:
        """Check if configuration is valid without raising an exception."""
        try:
            self.validate()
            return True
        except ConfigurationError:
            return False


config = _Config()

