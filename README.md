# 🤖 Cloudflare Telegram Bot

A powerful (Non-Official) Telegram bot that transforms your Cloudflare management into a real-time control panel with analytics, security controls, DNS management, and instant cache operations - all from your phone.

![Cloudflare](https://img.shields.io/badge/Cloudflare-F38020?style=for-the-badge&logo=Cloudflare&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)

## 🚀 Features

### 📊 Real-time Analytics
- **Traffic Overview**: Requests, bandwidth, and visits with timeseries data
- **Colo Performance**: Top data centers by request volume  
- **Security Events**: WAF actions and mitigated threats
- **Cache Status**: Hit/miss ratios and origin load

### 🛡️ Security Management
- **IP Access Rules**: Allow/block/challenge IPs and CIDRs
- **Custom Firewall**: Create rules with Cloudflare Expressions
- **WAF Bypass**: Skip WAF for specific paths/conditions
- **Bot Protection**: Toggle Bot Fight Mode & Super BFM instantly

### 🌐 DNS Control
- **Full CRUD**: Create, read, update, delete DNS records
- **Bulk Operations**: List and manage multiple records
- **Proxy Toggle**: Orange-cloud proxy on/off per record

### ⚡ Performance
- **Cache Purge**: Everything or selective URL purging
- **Instant Actions**: Sub-second rule deployment
- **Adaptive Analytics**: Uses Cloudflare's latest GraphQL schema

### 🔔 Smart Alerts
- **Traffic Anomalies**: Unusual request patterns
- **Security Thresholds**: High mitigation volumes
- **Origin Health**: Cache effectiveness monitoring
- **Cloudflare Status**: Real-time monitoring of Cloudflare status page for new incidents
- **Origin Monitoring**: Track origin server health and get alerts on 5xx errors
- **Origin Served Alerts**: Monitor cache misses and alert on low request volumes

## 🛠️ Setup

### Prerequisites
- Python 3.8+
- Cloudflare zone with API access
- Telegram bot token from [@BotFather](https://t.me/BotFather)

### Installation

#### Quick Start (Recommended)

Use the automated setup script for the easiest installation:

**Linux/macOS:**
```bash
git clone https://github.com/sarat1kyan/cloudflare-telegram-bot.git
cd cloudflare-telegram-bot
chmod +x setup.sh
./setup.sh
```

**Windows:**
```bash
git clone https://github.com/sarat1kyan/cloudflare-telegram-bot.git
cd cloudflare-telegram-bot
setup.bat
```

The setup script will:
- Check Python installation
- Install all dependencies automatically
- Guide you through configuration with a beautiful UI
- Validate all inputs (tokens, IDs, etc.)
- Test your configuration against Telegram and Cloudflare APIs
- Create a `.env` file with your settings
- Optionally create a systemd service file (Linux)

**Alternative: Manual Installation**

1. **Clone & Install Dependencies**
```bash
git clone https://github.com/sarat1kyan/cloudflare-telegram-bot.git
cd cloudflare-telegram-bot
pip install -r requirements.txt
```

2. **Run Installation Script**
```bash
python install.py
```

The script will:
- Guide you through configuration with a beautiful UI
- Validate all inputs (tokens, IDs, etc.)
- Test your configuration against Telegram and Cloudflare APIs
- Create a `.env` file with your settings

#### Manual Configuration

If you prefer to configure manually:

1. **Clone & Install**
```bash
git clone https://github.com/sarat1kyan/cloudflare-telegram-bot.git
cd cloudflare-telegram-bot
pip install -r requirements.txt
```

2. **Create `.env` file**
```env
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_here
ADMIN_USER_IDS=123456789,987654321  # Your Telegram user IDs
ALERT_CHAT_ID=-1001234567890        # Optional: group chat for alarms

# Cloudflare  
CLOUDFLARE_API_TOKEN=your_api_token_here
CLOUDFLARE_ZONE_ID=your_zone_id_here
```

3. **Cloudflare API Token**
Create token with these permissions:
- **Zone.Zone** - Read
- **Zone.Analytics** - Read  
- **Zone.DNS** - Edit
- **Zone.Firewall Services** - Edit
- **Zone.Cache Purge** - Purge

**⚠️ IMPORTANT**: After setting permissions, you MUST configure the token scope:
- Under "Zone Resources", select **"Include - Specific zone"**
- Select your zone from the dropdown
- **"Read all resources" alone is NOT sufficient** - you need specific zone scope

📖 **See [API_TOKEN_SETUP.md](API_TOKEN_SETUP.md) for detailed step-by-step instructions**

4.1 **Run the Bot | Verbose Debug Mode**
```bash
nohup python bot.py > output.log 2>&1 &
```

4.2 **For Production run the bot as a service**

## 📋 Command Reference (Buttons will do the same)

### 📊 Analytics Commands
| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Main menu with inline keyboard | `/start` |
| `/status` | Zone overview & plan details | `/status` |
| `/verify` | Data accuracy check | `/verify 24` |
| `/whoami` | Show current chat context | `/whoami` |

### 🛡️ Security Commands (Admin Only)
| Command | Description | Example |
|---------|-------------|---------|
| `/ip_list` | List access rules | `/ip_list block` |
| `/ip_allow` | Whitelist IP/CIDR | `/ip_allow 192.168.1.1 trusted-vpn` |
| `/ip_block` | Block IP/CIDR | `/ip_block 10.0.0.0/8 bad-actor` |
| `/ip_delete` | Remove rule by ID/IP | `/ip_delete 10.0.0.0/8` |
| `/rule_block` | Block with expression | `/rule_block (http.request.uri.path contains "/wp-admin") -- block wp-admin` |
| `/rule_bypass_waf` | Skip WAF for matches | `/rule_bypass_waf (http.request.uri.path contains "/api/") -- bypass api` |
| `/rules` | List firewall rules | `/rules` |

### 🌐 DNS Commands (Admin Only)  
| Command | Description | Example |
|---------|-------------|---------|
| `/dns_list` | List all records | `/dns_list api` |
| `/dns_add` | Create record | `/dns_add A subdomain 192.168.1.1 300 true` |
| `/dns_upd` | Update record | `/dns_upd rec123 content=192.168.1.2 proxied=false` |
| `/dns_del` | Delete record | `/dns_del rec123` |

### ⚡ Performance Commands (Admin Only)
| Command | Description | Example |
|---------|-------------|---------|
| `/cache_purge` | Purge cache | `/cache_purge all` |
| `/cache_purge` | Purge URLs | `/cache_purge https://site.com/page1` |
| `/toggle_bfm` | Bot Fight Mode | `/toggle_bfm on` |
| `/toggle_sbfm` | Super BFM | `/toggle_sbfm off` |

### 🔔 Alert Commands
| Command | Description | Example |
|---------|-------------|---------|
| `/alarms_on` | Enable monitoring | `/alarms_on` |
| `/alarms_off` | Disable monitoring | `/alarms_off` |

### 🌐 Origin Monitoring Commands (Admin Only)
| Command | Description | Example |
|---------|-------------|---------|
| `/origin_add` | Add origin URL to monitor | `/origin_add https://example.com/api/health 60 10` |
| `/origin_remove` | Remove origin from monitoring | `/origin_remove https://example.com/api/health` |
| `/origin_list` | List all monitored origins | `/origin_list` |
| `/origin_check` | Manually check origin health | `/origin_check https://example.com/api/health` |

**Origin Monitoring Features:**
- ✅ **Full URL support** - Monitor specific paths (e.g., `https://example.com/api/health`)
- ✅ **Smart error detection** - Ignores non-critical 404s (favicon, robots.txt, etc.)
- ✅ **Configurable intervals** - Set custom check intervals per origin
- ✅ **Failure tracking** - Tracks consecutive failures and success rates
- ✅ **Automatic alerts** - Sends Telegram alerts on critical errors
- ✅ **Statistics** - Shows success rate and check history

**Examples:**
```bash
# Monitor homepage
/origin_add https://example.com

# Monitor API endpoint
/origin_add https://example.com/api/health 120 15

# Monitor specific admin path
/origin_add https://example.com/payment/admin 60 10

# Check status manually
/origin_check https://example.com/api/health
```

**Note:** Only 5xx server errors trigger alerts. 4xx client errors (404, 403, etc.) are ignored as they indicate client-side issues, not server problems.

### 🔔 Monitor Origin Served Requests
The bot can monitor requests served by origin (cache misses) and alert when they drop below configured thresholds. This helps detect:
- Unusually high cache hit rates (good!)
- Reduced traffic patterns
- Potential origin server issues

**Setup:**
```bash
# Set thresholds for different time periods
/origin_alert_set 30m 1000    # Alert if < 1000 requests in last 30 minutes
/origin_alert_set 6h 5000     # Alert if < 5000 requests in last 6 hours
/origin_alert_set 24h 20000   # Alert if < 20000 requests in last 24 hours

# Enable alerts
/origin_alert_enable

# Check current status
/origin_alert_status

# Manually check against thresholds
/origin_alert_check
```

**Features:**
- ✅ Configurable thresholds for 30m, 6h, and 24h periods
- ✅ Automatic alerts when requests drop below threshold
- ✅ Recovery notifications when requests return to normal
- ✅ Interactive button menu for easy management
- ✅ Persistent state across bot restarts

**Access via UI:**
Click the "🔔 Origin Alerts" button in the main menu to access the interactive management interface.

### 📡 Cloudflare Status Monitoring
The bot automatically monitors the Cloudflare status page (https://www.cloudflarestatus.com/) and sends alerts when new incidents are posted. No configuration needed - it works automatically once the bot is running!

## 🎯 Usage Examples

### 🔒 Block Suspicious IP
```bash
/ip_block 45.155.205.233 bruteforce-attempt
```

### 🚀 Deploy WAF Bypass for API
```bash
/rule_bypass_waf (http.request.uri.path contains "/api/") -- bypass api paths
```

### 📝 Add DNS Record
```bash
/dns_add CNAME cdn mysite.workers.dev 1 true
```

### 🧹 Emergency Cache Purge
```bash
/cache_purge all
```

### 🌐 Monitor Origin Health
```bash
# Monitor homepage (default: 60s interval, 10s timeout)
/origin_add https://example.com

# Monitor API endpoint with custom settings
/origin_add https://example.com/api/health 120 15

# Monitor specific admin path
/origin_add https://example.com/payment/admin 60 10

# Check status manually
/origin_check https://example.com/api/health

# List all monitored origins with statistics
/origin_list

# Remove origin from monitoring
/origin_remove https://example.com/api/health
```

**Smart Error Handling:**
- ✅ 404 errors for `/favicon.ico`, `/robots.txt` are automatically ignored
- ✅ Only critical errors (5xx, connection failures) trigger alerts
- ✅ Success rate tracking shows reliability over time

### 🔔 Monitor Origin Served Requests
The bot can monitor requests served by origin (cache misses) and alert when they drop below configured thresholds. This helps detect:
- Unusually high cache hit rates (good!)
- Reduced traffic patterns
- Potential origin server issues

**Setup:**
```bash
# Set thresholds for different time periods
/origin_alert_set 30m 1000    # Alert if < 1000 requests in last 30 minutes
/origin_alert_set 6h 5000     # Alert if < 5000 requests in last 6 hours
/origin_alert_set 24h 20000   # Alert if < 20000 requests in last 24 hours

# Enable alerts
/origin_alert_enable

# Check current status
/origin_alert_status

# Manually check against thresholds
/origin_alert_check
```

**Features:**
- ✅ Configurable thresholds for 30m, 6h, and 24h periods
- ✅ Automatic alerts when requests drop below threshold
- ✅ Recovery notifications when requests return to normal
- ✅ Interactive button menu for easy management
- ✅ Persistent state across bot restarts

**Access via UI:**
Click the "🔔 Origin Alerts" button in the main menu to access the interactive management interface.

## 🏗️ Architecture

```
┌──────────────────┐      ┌────────────────────┐    ┌─────────────────┐
│     Telegram     │      │      PocketCF      │    │   Cloudflare    │
│     --------     │      │      --------      │    │   ----------    │
│     Commands     │ ◄──► │     bot.py         │◄──►│   REST API      │
│     Callbacks    │      │     - Handlers     │    │   - DNS         │
│     Inline UI    │      │     - Admin gate   │    │   - Firewall    │
└──────────────────┘      │     - Analytics    │    │   - Analytics   │
                          │                    │    │                 │
                          │  cloudflare_api.py │    │   GraphQL API   │
                          │   - REST wrapper   │    │   - Adaptive    │
                          │   - GraphQL client │    │   - Real-time   │
                          └────────────────────┘    └─────────────────┘
```

## 🔧 Advanced Configuration

### Multiple Zones
Edit `config.py` to support multiple zones:
```python
ZONES = {
    "production": "zone_id_1",
    "staging": "zone_id_2" 
}
```

### Custom Alert Thresholds
```python
# In bot.py - modify these constants
MITIGATIONS_24H_THRESHOLD = 50_000    # Alert if > 50k mitigations
ORIGIN_SERVED_24H_MIN = 1_000_000     # Alert if < 1M origin requests
```

### Deployment Options

**Local Development**
```bash
python bot.py
```

**Docker**
```dockerfile
FROM python:3.9-slim
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["python", "bot.py"]
```

**Systemd Service**
```ini
[Unit]
Description=Cloudflare Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/cloudflare-bot
ExecStart=/usr/bin/python3 bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

## 🛡️ Security Notes

- **Admin-Only**: Write commands require `ADMIN_USER_IDS` authorization
- **API Scoping**: Cloudflare tokens use principle of least privilege
- **Input Validation**: All user inputs are sanitized before API calls
- **No Data Storage**: The bot doesn't persist any sensitive information

## 🐛 Troubleshooting

### Common Issues

**Bot doesn't start**
- Check `TELEGRAM_BOT_TOKEN` format
- Verify Python version >= 3.8
- Ensure all dependencies installed

**API calls fail**  
- Validate `CLOUDFLARE_API_TOKEN` permissions
- Check `CLOUDFLARE_ZONE_ID` format
- Verify zone exists in account

**No analytics data**
- Ensure zone has traffic
- Check token has Analytics read permissions
- Wait a few minutes after zone creation

### Debug Mode
Enable verbose logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)  
4. Push branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⚠️ Disclaimer

**This is a non-official, community-created project**

---

## 🏷️ Project Status

| Aspect | Status |
|--------|--------|
| **Official Cloudflare Product** | ❌ No |
| **Created by Cloudflare** | ❌ No |  
| **Supported by Cloudflare** | ❌ No |
| **Community Project** | ✅ Yes |
| **Open Source** | ✅ Yes |
| **Use at Your Own Risk** | ✅ Yes |

## 📝 Important Notice

This Telegram bot is **my personal project** that I built to manage my own Cloudflare zones more efficiently. I'm sharing the code publicly in case others find it useful, but please understand:

### 🛑 Not Official
- **NOT developed, endorsed, or supported by Cloudflare**
- **NOT an official Cloudflare product or service**
- **NOT affiliated with Cloudflare, Inc. in any way**

### 🔧 Personal Project
- Built for **my own use cases** and specific workflows
- Shared **as-is** for educational and community purposes
- **No guarantees** of functionality, security, or maintenance
- **No SLA** or official support channels

### ⚠️ Use Responsibility
- **Test thoroughly** before using in production
- **Review all code** for security and compatibility
- **Monitor carefully** when making configuration changes
- **You are responsible** for any changes made to your Cloudflare account

## 🔗 Official Resources

For official Cloudflare tools and services, please visit:
- 🌐 [Cloudflare Official Website](https://www.cloudflare.com)
- 📚 [Cloudflare API Documentation](https://api.cloudflare.com)
- 🛠️ [Cloudflare Dashboard](https://dash.cloudflare.com)

## 📞 Support

**This project has no official support.** For issues:
- 📋 Create a [GitHub Issue](https://github.com/sarat1kyan/pocket-cf/issues)
- 🔍 Search existing discussions
- 📖 Review the code and documentation

**For official Cloudflare support:**
- 🎫 Contact [Cloudflare Support](https://support.cloudflare.com)
- 💬 Join [Cloudflare Community](https://community.cloudflare.com)

---

*This project is maintained by an individual developer in their spare time. Cloudflare® is a registered trademark of Cloudflare, Inc. This project is not affiliated with Cloudflare, Inc.*
---

## 🙏 Acknowledgments

**⭐ Star this repo if you found it helpful!**
[![BuyMeACoffee](https://raw.githubusercontent.com/pachadotdev/buymeacoffee-badges/main/bmc-donate-yellow.svg)](https://www.buymeacoffee.com/saratikyan)
[![Report Bug](https://img.shields.io/badge/Report-Bug-red.svg)](https://github.com/sarat1kyan/pocket-cf/issues)

> **Note**: Always test management commands in staging before production use. The bot has immediate effect on your Cloudflare configuration.
