import os
from typing import Dict, Any

class _Config:
    # Telegram Bot Configuration
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '0123456789:XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX')
    ADMIN_USER_IDS = [int(x) for x in os.getenv('ADMIN_USER_IDS', '0123456789').split(',') if x]
    ALERT_CHAT_ID = os.getenv('ALERT_CHAT_ID', '-4891041946')    
    # Cloudflare API Configuration
    CLOUDFLARE_API_TOKEN = os.getenv('CLOUDFLARE_API_TOKEN', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX')
    CLOUDFLARE_ACCOUNT_ID = os.getenv('CLOUDFLARE_ACCOUNT_ID', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX')
    CLOUDFLARE_ZONE_ID = os.getenv('CLOUDFLARE_ZONE_ID', 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX')
    
    # Monitoring Configuration
    CHECK_INTERVAL = 300  # 5 minutes
    ALERT_THRESHOLDS = {
        'requests_per_second': 1000,
        'bandwidth_mbps': 100,
        'error_rate': 0.05,  # 5%
        'threats_count': 10
    }
    
    # Logging
    LOG_RETENTION_DAYS = 30

    # UI defaults
    DEFAULT_HOURS = 24

config = _Config()

