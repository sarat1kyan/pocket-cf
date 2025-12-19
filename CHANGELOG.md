# Changelog

## New Features & Fixes

### 🔧 Fixed Issues

1. **Environment Variable Loading**
   - Fixed `config.py` to properly load `.env` files using `python-dotenv`
   - Previously, the bot only read from system environment variables
   - Now automatically loads `.env` file if present

### ✨ New Features

#### 1. Cloudflare Status Page Monitoring
   - **Automatic monitoring** of https://www.cloudflarestatus.com/
   - Sends alerts to Telegram when new incidents are posted
   - Monitors both API and HTML page for maximum reliability
   - Tracks seen incidents to avoid duplicate alerts
   - No configuration needed - works automatically once bot is running

#### 2. Origin Health Monitoring
   - **Track origin server health** via HTTP connection testing
   - **Automatic alerts** on 4xx and 5xx HTTP status codes
   - **Configurable check intervals** and timeouts per origin
   - **Consecutive failure tracking** to reduce alert spam
   - **Telegram commands** to manage monitored origins:
     - `/origin_add <domain> [interval] [timeout]` - Add origin to monitor
     - `/origin_remove <domain>` - Remove origin from monitoring
     - `/origin_list` - List all monitored origins
     - `/origin_check <domain>` - Manually check origin health

#### 3. Comprehensive Setup Scripts
   - **Linux/macOS**: `setup.sh` - Automated installation script
   - **Windows**: `setup.bat` - Automated installation script
   - Both scripts:
     - Check Python installation
     - Install all dependencies automatically
     - Run configuration wizard
     - Optionally create systemd service (Linux)

### 📦 Updated Dependencies

Added to `requirements.txt`:
- `python-dotenv` - For loading `.env` files
- `beautifulsoup4` - For parsing Cloudflare status page HTML
- `aiohttp` - For async HTTP requests in origin monitoring
- `lxml` - For BeautifulSoup HTML parsing

### 📝 Updated Documentation

- Updated README.md with new features
- Added origin monitoring command examples
- Added Cloudflare status monitoring information
- Updated setup instructions with new automated scripts
- Updated `env.example` with better formatting and comments

### 🏗️ Architecture Changes

- Added `status_monitor.py` - Cloudflare status page monitoring module
- Added `origin_monitor.py` - Origin health monitoring module
- Updated `bot.py` to integrate both monitors as background tasks
- Monitors run in separate thread to avoid blocking bot operations

### 🔒 Security & Reliability

- All new commands are admin-gated (require admin permissions)
- State persistence for monitors (survives bot restarts)
- Error handling and logging for all monitoring operations
- Graceful degradation if monitors fail to initialize

## Migration Guide

### For Existing Users

1. **Update dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **No configuration changes needed** - existing `.env` files will work as-is

3. **New features are opt-in:**
   - Cloudflare status monitoring starts automatically
   - Origin monitoring requires adding origins via `/origin_add` command

### For New Users

1. **Use the automated setup script:**
   ```bash
   ./setup.sh  # Linux/macOS
   # or
   setup.bat   # Windows
   ```

2. **Or follow manual installation** in README.md

## Breaking Changes

None - all changes are backward compatible.

## Known Issues

- Cloudflare status page HTML parsing may need updates if page structure changes
- Origin monitoring uses separate event loop which may cause minor resource overhead

