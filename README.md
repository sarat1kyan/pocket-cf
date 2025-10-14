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

## 🛠️ Setup

### Prerequisites
- Python 3.8+
- Cloudflare zone with API access
- Telegram bot token from [@BotFather](https://t.me/BotFather)

### Installation

1. **Clone & Install**
```bash
git clone https://github.com/yourusername/cloudflare-telegram-bot.git
cd cloudflare-telegram-bot
pip install -r requirements.txt
```

2. **Configuration**
Create `.env` file:
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

## 🏗️ Architecture

```
┌──────────────────┐      ┌────────────────────┐    ┌─────────────────┐
│     Telegram     │      │     Python Bot     │    │   Cloudflare    │
│     --------     │      │     ----------     │    │   ----------    │
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
