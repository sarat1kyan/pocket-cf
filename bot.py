import logging
import asyncio
import csv
import io
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import aiohttp

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import BadRequest

from config import config, ConfigurationError
from cloudflare_api import cf_api
from analytics import (
    timeseries_from_graphql,
    format_timeseries_summary_for_html,
    colos_from_graphql,
    format_colos_for_html,
    format_security_for_html,
)
from utils import make_pre_table, num, validate_ip_or_cidr, sanitize_string, validate_hours
from status_monitor import CloudflareStatusMonitor
from origin_monitor import OriginMonitor
from origin_served_monitor import OriginServedMonitor

# Configure logging with better formatting
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# -------- thresholds (tune to your traffic)
MITIGATIONS_24H_THRESHOLD = 30_000
ORIGIN_SERVED_24H_MIN = 2_500_000  # requests with cacheStatus != HIT

NOT_ALLOWED_TEXT = "⛔ You’re not allowed to use this bot. Ask your manager for permission."

# ========================= ADMIN GATE (GLOBAL) =========================
def is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in set(getattr(config, "ADMIN_USER_IDS", []))
    except Exception:
        return False

def admins_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = (update.effective_user.id if update.effective_user else 0)
        if not is_admin(uid):
            # Answer callbacks with an alert and drop everything.
            if update.callback_query:
                try:
                    await update.callback_query.answer(NOT_ALLOWED_TEXT, show_alert=True)
                except Exception:
                    pass
            # Also send a message into chat (useful for command tries).
            if update.effective_chat:
                try:
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=NOT_ALLOWED_TEXT)
                except Exception:
                    pass
            return
        return await func(update, context)
    return wrapper

# Optional: audit of admin actions (set AUDIT_CHAT_ID in config or env to enable)
async def audit(context: ContextTypes.DEFAULT_TYPE, update: Update, action: str, details: str = ""):
    audit_chat = getattr(config, "AUDIT_CHAT_ID", None)
    if not audit_chat:
        return
    u = update.effective_user
    who = f"{u.id} (@{getattr(u, 'username', '-')})"
    zone = context.chat_data.get("zone_name") or context.chat_data.get("zone_id") or getattr(config, "CLOUDFLARE_ZONE_ID", "-")
    text = f"🧾 <b>{action}</b>\n👤 <code>{who}</code>\n🌐 <code>{zone}</code>\n{details}"
    try:
        await context.bot.send_message(int(audit_chat), text, parse_mode=ParseMode.HTML)
    except Exception:
        pass

# ========================= ZONE CONTEXT =========================
def get_active_zone(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, str]:
    zid = context.chat_data.get("zone_id") or config.CLOUDFLARE_ZONE_ID
    zname = context.chat_data.get("zone_name") or "default"
    return {"id": zid, "name": zname}

def set_active_zone(context: ContextTypes.DEFAULT_TYPE, zid: str, name: str):
    context.chat_data["zone_id"] = zid
    context.chat_data["zone_name"] = name

# ========================= MENUS =========================
def main_menu_kb(zname: str = ""):
    title = f"🌐 {zname}" if zname else "🌐 Zone"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(title, callback_data="zones:1"), InlineKeyboardButton("🔁 Refresh", callback_data="refresh")],
        [InlineKeyboardButton("📊 Traffic", callback_data="traffic:24"),
         InlineKeyboardButton("🌍 Colos", callback_data="colos:24"),
         InlineKeyboardButton("🛡️ Security", callback_data="security:24")],
        [InlineKeyboardButton("📤 Export", callback_data="export:24"),
         InlineKeyboardButton("🤖 BFM", callback_data="bfm"),
         InlineKeyboardButton("🧭 DNS", callback_data="dns:1")],
        [InlineKeyboardButton("🧱 Rate-limit", callback_data="rl:menu"),
         InlineKeyboardButton("⚙️ Advanced", callback_data="admin:help")],
        [InlineKeyboardButton("🔔 Origin Alerts", callback_data="origin_alerts:menu")]
    ])

def back_menu_kb(section: str, hours: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱ 1h", callback_data=f"{section}:1"),
         InlineKeyboardButton("🕓 24h", callback_data=f"{section}:24"),
         InlineKeyboardButton("📅 7d", callback_data=f"{section}:168")],
        [InlineKeyboardButton("🏠 Home", callback_data="home"),
         InlineKeyboardButton("🔁 Refresh", callback_data=f"{section}:{hours}")],
    ])

# ========================= BASIC COMMANDS (ALL ADMIN-GATED) =========================
@admins_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    txt = (
        "👋 <b>Welcome to Cloudflare Control Bot!</b>\n\n"
        "⚠️ <b>Disclaimer:</b> This is <b>NOT</b> an official Cloudflare product. "
        "It was created by someone who wanted such a tool and decided to share it with the community.\n\n"
        "🔗 <b>Creator's Socials:</b>\n"
        "• GitHub: <a href=\"https://github.com/sarat1kyan\">@sarat1kyan</a>\n"
        "• Reddit: <a href=\"https://www.reddit.com/user/saratikyan/\">u/saratikyan</a>\n\n"
        "💡 <b>Getting Started:</b>\n"
        "Most features can be managed using the buttons below. For advanced management, "
        "you can use commands or click the <b>⚙️ Advanced</b> button for more information.\n\n"
        "<i>Tip: Tap 🌐 to switch zones.</i>"
    )
    await update.message.reply_text(txt, reply_markup=main_menu_kb(z.get("name")), parse_mode=ParseMode.HTML, disable_web_page_preview=True)

@admins_only
async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    text = make_pre_table(
        [[chat.id, chat.type, getattr(chat, 'title', '-') or '-', getattr(update.effective_user, 'username', '-')]],
        ["chat_id", "type", "title", "from_user"]
    )
    await update.message.reply_text(
        f"🆔 <b>Chat info</b>\n{text}\n<i>Use /zones to switch zone via the picker.</i>",
        parse_mode=ParseMode.HTML
    )

@admins_only
async def test_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test and diagnose configuration issues."""
    msg = await update.message.reply_text("⏳ <i>Testing configuration…</i>", parse_mode=ParseMode.HTML)
    
    issues = []
    info = []
    
    # Check Telegram token
    if config.TELEGRAM_BOT_TOKEN:
        token_len = len(config.TELEGRAM_BOT_TOKEN)
        if token_len < 40:
            issues.append(f"Telegram token seems short ({token_len} chars)")
        else:
            info.append(f"✅ Telegram token: {token_len} chars")
    else:
        issues.append("Telegram token is missing")
    
    # Check Cloudflare token
    if config.CLOUDFLARE_API_TOKEN:
        token_len = len(config.CLOUDFLARE_API_TOKEN)
        token_preview = config.CLOUDFLARE_API_TOKEN[:10] + "..." + config.CLOUDFLARE_API_TOKEN[-5:] if token_len > 15 else config.CLOUDFLARE_API_TOKEN[:10] + "..."
        if token_len < 40:
            issues.append(f"Cloudflare token seems short ({token_len} chars)")
        else:
            info.append(f"✅ Cloudflare token: {token_len} chars ({token_preview})")
        
        # Test token
        try:
            import requests
            test_headers = {
                "Authorization": f"Bearer {config.CLOUDFLARE_API_TOKEN}",
                "Content-Type": "application/json"
            }
            test_resp = requests.get("https://api.cloudflare.com/client/v4/user/tokens/verify", headers=test_headers, timeout=10)
            if test_resp.status_code == 200:
                token_data = test_resp.json()
                if token_data.get("success"):
                    info.append("✅ Cloudflare token is valid")
                    result = token_data.get("result", {})
                    if result.get("status") == "active":
                        info.append("✅ Token status: Active")
                    else:
                        issues.append(f"Token status: {result.get('status', 'unknown')}")
                else:
                    issues.append("❌ Cloudflare token validation failed")
            elif test_resp.status_code == 401:
                issues.append("❌ Cloudflare token is invalid (401 Unauthorized)")
                issues.append("  → Token may be expired, incorrect, or for wrong account")
            else:
                issues.append(f"❌ Token test returned status {test_resp.status_code}")
        except Exception as e:
            issues.append(f"❌ Error testing token: {str(e)[:100]}")
    else:
        issues.append("Cloudflare token is missing")
    
    # Check Zone ID
    if config.CLOUDFLARE_ZONE_ID:
        zone_len = len(config.CLOUDFLARE_ZONE_ID)
        if zone_len == 32:
            info.append(f"✅ Zone ID: {zone_len} chars (correct format)")
        else:
            issues.append(f"Zone ID length is {zone_len} (expected 32)")
        
        # Test zone access
        if config.CLOUDFLARE_API_TOKEN:
            try:
                import requests
                test_headers = {
                    "Authorization": f"Bearer {config.CLOUDFLARE_API_TOKEN}",
                    "Content-Type": "application/json"
                }
                test_resp = requests.get(f"https://api.cloudflare.com/client/v4/zones/{config.CLOUDFLARE_ZONE_ID}", headers=test_headers, timeout=10)
                if test_resp.status_code == 200:
                    zone_data = test_resp.json()
                    if zone_data.get("success"):
                        zone_name = zone_data.get("result", {}).get("name", "Unknown")
                        info.append(f"✅ Zone accessible: {zone_name}")
                    else:
                        issues.append("❌ Zone API returned success=false")
                elif test_resp.status_code == 403:
                    issues.append("❌ Zone access forbidden (403) - check token permissions")
                    issues.append("  → Token needs Zone.Zone (Read) permission")
                    issues.append("  → Token must be scoped to 'Include - Specific zone'")
                    issues.append("  → Or use 'Include - All zones' if you have access")
                elif test_resp.status_code == 404:
                    issues.append("❌ Zone not found (404) - check Zone ID")
                else:
                    issues.append(f"❌ Zone test returned status {test_resp.status_code}")
            except Exception as e:
                issues.append(f"❌ Error testing zone: {str(e)[:100]}")
    else:
        issues.append("Zone ID is missing")
    
    # Build response
    response = "🔍 <b>Configuration Test</b>\n\n"
    if info:
        response += "\n".join(info) + "\n\n"
    if issues:
        response += "<b>⚠️ Issues Found:</b>\n" + "\n".join(f"• {i}" for i in issues)
    else:
        response += "✅ <b>No issues detected!</b>"
    
    await msg.edit_text(response, parse_mode=ParseMode.HTML)

@admins_only
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    msg = await update.message.reply_text("⏳ <i>Fetching zone…</i>", parse_mode=ParseMode.HTML)
    zd = cf_api.get_zone_details(zone_id=z["id"])
    if not zd:
        await msg.edit_text(
            "❌ <b>Failed to fetch zone details.</b>\n\n"
            "<i>Possible causes:</i>\n"
            "• Zone ID is incorrect\n"
            "• API token lacks Zone.Zone (Read) permission\n"
            "• Zone doesn't exist or you don't have access\n\n"
            "<i>Check your .env file and API token permissions.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    res = zd.get("result", {}) or {}
    if not res:
        await msg.edit_text(
            "❌ <b>Invalid response from Cloudflare API.</b>\n\n"
            "<i>Check your API token permissions and zone ID.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    name = res.get("name") or res.get("id")
    plan = (res.get("plan") or {}).get("name") or "-"
    status_ = res.get("status") or "-"
    created = res.get("created_on") or "-"
    txt = (f"✅ <b>Zone:</b> <code>{name}</code>\n"
           f"🧾 <b>Plan:</b> <code>{plan}</code>\n"
           f"📡 <b>Status:</b> <code>{status_}</code>\n"
           f"📅 <b>Created:</b> <code>{created}</code>")
    set_active_zone(context, z["id"], name)
    await msg.edit_text(txt, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(name))

@admins_only
async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if context.args:
        is_valid, hours = validate_hours(context.args[0])
        if not is_valid:
            await update.message.reply_text("❌ Invalid hours. Must be between 1 and 168.", parse_mode=ParseMode.HTML)
            return
    else:
        hours = 24
    a = cf_api.get_http_requests_fixed(hours=hours, zone_id=z["id"])
    zones = (a or {}).get("data", {}).get("viewer", {}).get("zones", [])
    groups = zones[0].get("httpRequestsAdaptiveGroups", []) if zones else []
    req = sum((g.get("count") or 0) for g in groups)
    byt = sum(((g.get("sum") or {}).get("edgeResponseBytes") or 0) for g in groups)
    vis = sum(((g.get("sum") or {}).get("visits") or 0) for g in groups)
    txt = (f"🔎 <b>Verify — last {hours}h</b> (zone <code>{z['id']}</code>)\n"
           f"<pre>Adaptive totals\n"
           f"  Requests  {req:,}\n  Transfer  {byt:,} bytes\n  Visits    {vis:,}</pre>")
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML)

# ========================= ZONES UI =========================
def _zones_keyboard(page: int, zones: List[Dict[str, Any]]):
    per = 6
    start = (page-1)*per
    chunk = zones[start:start+per]
    rows = [[InlineKeyboardButton(z.get("name"), callback_data=f"zone:{z.get('id')}")] for z in chunk]
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"zones:{page-1}"))
    if start + per < len(zones):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"zones:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="home")])
    return InlineKeyboardMarkup(rows)

@admins_only
async def zones_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = cf_api.list_zones(page=1, per_page=100)
    if not data:
        await update.message.reply_text("❌ Failed to list zones.", parse_mode=ParseMode.HTML); return
    zones = data.get("result") or []
    if not zones:
        await update.message.reply_text("ℹ️ No zones.", parse_mode=ParseMode.HTML); return
    await update.message.reply_text("🌐 <b>Select a zone</b>", parse_mode=ParseMode.HTML, reply_markup=_zones_keyboard(1, zones))

# ========================= CALLBACKS (ADMIN-GATED) =========================
@admins_only
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.answer(cache_time=1)
    except BadRequest:
        pass
    data = (q.data or "").strip()
    z = get_active_zone(context)

    if data == "home":
        await q.edit_message_text("🏠 <b>Home</b> — choose an option:", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(z.get("name"))); return
    if data == "refresh":
        data = "traffic:24"

    if data == "admin" or data.startswith("admin:"):
        await q.edit_message_text(_admin_help(), parse_mode=ParseMode.HTML,
                                  reply_markup=InlineKeyboardMarkup([
                                      [InlineKeyboardButton("🧱 Rate-limit", callback_data="rl:menu"),
                                       InlineKeyboardButton("🤖 BFM", callback_data="bfm")],
                                      [InlineKeyboardButton("🧭 DNS list", callback_data="dns:24"),
                                       InlineKeyboardButton("🔔 Origin Alerts", callback_data="origin_alerts:menu")],
                                      [InlineKeyboardButton("🏠 Home", callback_data="home")]
                                  ]))
        return
    
    if data.startswith("origin_alerts:"):
        await render_origin_alerts_menu(q, context, data)
        return

    if data.startswith("bfm:") or data.startswith("sbfm:"):
        val = data.split(":")[1].lower() == "on"
        ok = cf_api.set_bfm(val, zone_id=z["id"]) if data.startswith("bfm:") else cf_api.set_sbfm(val, zone_id=z["id"])
        name = "Bot Fight Mode" if data.startswith("bfm:") else "Super BFM"
        await q.edit_message_text(f"{'✅' if ok else '❌'} {name} {'ON' if val else 'OFF'} · <code>{z['name'] or z['id']}</code>",
                                  parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(z.get("name")))
        return

    if data.startswith("zones:"):
        page = int((data.split(":")[1] or "1"))
        allz = (cf_api.list_zones(page=1, per_page=100) or {}).get("result") or []
        await q.edit_message_text("🌐 <b>Select a zone</b>", parse_mode=ParseMode.HTML, reply_markup=_zones_keyboard(page, allz)); return
    if data.startswith("zone:"):
        zid = data.split(":")[1]
        zd = cf_api.get_zone_details(zone_id=zid)
        name = (zd or {}).get("result", {}).get("name") or zid
        set_active_zone(context, zid, name)
        await q.edit_message_text(f"✅ Switched to <code>{name}</code>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(name)); return

    if data.startswith("ipblock:") or data.startswith("ipchal:"):
        ip = data.split(":", 1)[1]
        mode = "block" if data.startswith("ipblock:") else "challenge"
        target = "ip_range" if "/" in ip else "ip"
        ok = bool(cf_api.create_access_rule(mode=mode, target=target, value=ip, notes=f"quick-{mode}", zone_id=z["id"]))
        await q.edit_message_text(f"{'✅' if ok else '❌'} {mode.title()} {ip}", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(z.get("name")))
        return

    try:
        section, hours_s = data.split(":")
        hours = int(hours_s)
    except Exception:
        section, hours = data, 24

    if section == "traffic":
        await render_traffic(q, context, hours)
    elif section == "colos":
        await render_colos(q, context, hours)
    elif section == "security":
        await render_security(q, context, hours)
    elif section == "dns":
        await render_dns(q, context, hours)
    elif section == "export":
        await render_export(q, context, hours)
    elif section == "rl":
        await render_rl_menu(q, context)
    elif section == "bfm":
        await render_bfm(q, context)
    else:
        await q.edit_message_text("🆕 <i>Coming Soon</i>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(z.get("name")))

# ========================= RENDERERS =========================
async def render_traffic(q, context, hours: int):
    z = get_active_zone(context)
    await q.edit_message_text(f"⏳ <i>Loading traffic for <code>{z['name'] or z['id']}</code> (last {hours}h)…</i>", parse_mode=ParseMode.HTML)
    try:
        gql = cf_api.get_http_requests_fixed(hours=hours, zone_id=z["id"])
        if not gql:
            await q.edit_message_text(
                "❌ <b>Failed to fetch traffic.</b>\n\n"
                "<i>Possible causes:</i>\n"
                "• Zone not found or invalid\n"
                "• API token lacks Analytics permissions\n"
                "• No traffic data available for this period",
                parse_mode=ParseMode.HTML,
                reply_markup=back_menu_kb("traffic", hours)
            )
            return
        ts = timeseries_from_graphql(gql)
        if not ts:
            await q.edit_message_text("ℹ️ <i>No traffic data in window.</i>", parse_mode=ParseMode.HTML, reply_markup=back_menu_kb("traffic", hours)); return
        summary = format_timeseries_summary_for_html(ts)
        await q.edit_message_text(f"📊 <b>Traffic — last {hours}h</b> · <code>{z['name'] or z['id']}</code>\n{summary}", parse_mode=ParseMode.HTML, reply_markup=back_menu_kb("traffic", hours))
    except Exception as e:
        logger.error(f"Error rendering traffic: {e}", exc_info=True)
        await q.edit_message_text(
            f"❌ <b>Error loading traffic:</b>\n<code>{str(e)[:200]}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_menu_kb("traffic", hours)
        )

async def render_colos(q, context, hours: int):
    z = get_active_zone(context)
    await q.edit_message_text(f"⏳ <i>Loading colos for <code>{z['name'] or z['id']}</code> (last {hours}h)…</i>", parse_mode=ParseMode.HTML)
    try:
        gql = cf_api.get_analytics_by_colo(hours=hours, zone_id=z["id"])
        if not gql:
            await q.edit_message_text(
                "❌ <b>Failed to fetch colos.</b>\n\n"
                "<i>Possible causes:</i>\n"
                "• Zone not found or invalid\n"
                "• API token lacks Analytics permissions\n"
                "• No colo data available for this period",
                parse_mode=ParseMode.HTML,
                reply_markup=back_menu_kb("colos", hours)
            )
            return
        rows = colos_from_graphql(gql, top_n=12)
        if not rows:
            await q.edit_message_text("ℹ️ <i>No colo data in window.</i>", parse_mode=ParseMode.HTML, reply_markup=back_menu_kb("colos", hours)); return
        table_html = format_colos_for_html(rows)
        await q.edit_message_text(f"🌍 <b>Top Colos — last {hours}h</b> · <code>{z['name'] or z['id']}</code>\n{table_html}", parse_mode=ParseMode.HTML, reply_markup=back_menu_kb("colos", hours))
    except Exception as e:
        logger.error(f"Error rendering colos: {e}", exc_info=True)
        await q.edit_message_text(
            f"❌ <b>Error loading colos:</b>\n<code>{str(e)[:200]}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_menu_kb("colos", hours)
        )

async def render_security(q, context, hours: int):
    z = get_active_zone(context)
    await q.edit_message_text(f"⏳ <i>Loading security for <code>{z['name'] or z['id']}</code> (last {hours}h)…</i>", parse_mode=ParseMode.HTML)
    try:
        gql = cf_api.get_security_events(hours=hours, limit=200, zone_id=z["id"])
        if not gql:
            await q.edit_message_text(
                "❌ <b>Failed to fetch security events.</b>\n\n"
                "<i>Possible causes:</i>\n"
                "• Zone not found or invalid\n"
                "• API token lacks Analytics permissions\n"
                "• No security events in this period",
                parse_mode=ParseMode.HTML,
                reply_markup=back_menu_kb("security", hours)
            )
            return
        html_events = format_security_for_html(gql, top_n=15)

        ips = cf_api.get_top_mitigated_ips(hours=hours, limit=6, zone_id=z["id"])
        ip_rows, ip_buttons = [], []
        try:
            zones = (ips or {}).get("data", {}).get("viewer", {}).get("zones", [])
            groups = zones[0].get("firewallEventsAdaptiveGroups", []) if zones else []
            for g in groups[:6]:
                ip = (g.get("dimensions") or {}).get("clientIP") or "-"
                cnt = g.get("count") or 0
                ip_rows.append([ip, num(cnt)])
                ip_buttons.append([InlineKeyboardButton(f"🚫 Block {ip}", callback_data=f"ipblock:{ip}"),
                                   InlineKeyboardButton(f"⚠️ Challenge {ip}", callback_data=f"ipchal:{ip}")])
        except Exception:
            pass

        extra = ""
        kb_rows = []
        if ip_rows:
            extra = "\n<b>Top Mitigated IPs</b>\n" + make_pre_table(ip_rows, ["IP", "Count"])
            kb_rows += ip_buttons
        kb_rows.append([InlineKeyboardButton("🏠 Home", callback_data="home"),
                        InlineKeyboardButton("🔁 Refresh", callback_data=f"security:{hours}")])

        await q.edit_message_text(f"🛡️ <b>Top Security Events — last {hours}h</b> · <code>{z['name'] or z['id']}</code>\n{html_events}{extra}",
                                  parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb_rows))
    except Exception as e:
        logger.error(f"Error rendering security: {e}", exc_info=True)
        await q.edit_message_text(
            f"❌ <b>Error loading security events:</b>\n<code>{str(e)[:200]}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_menu_kb("security", hours)
        )

async def render_dns(q, context, hours: int):
    z = get_active_zone(context)
    await q.edit_message_text(f"⏳ <i>Loading DNS (last {hours}h)…</i>", parse_mode=ParseMode.HTML)
    until = datetime.now(timezone.utc); since = until - timedelta(hours=hours)
    data = cf_api.get_dns_analytics_report(since=since, until=until, zone_id=z["id"])
    if not data:
        await q.edit_message_text("❌ <b>Failed to fetch DNS analytics.</b>", parse_mode=ParseMode.HTML, reply_markup=back_menu_kb("dns", hours)); return
    res = (data or {}).get("result", {}) or {}; totals = res.get("totals") or {}
    query_count = totals.get("queryCount") or 0; resp_time = totals.get("responseTimeAvg") or 0
    await q.edit_message_text(
        f"🧭 <b>DNS — last {hours}h</b> · <code>{z['name'] or z['id']}</code>\n<pre>Queries          {query_count:,}\nAvg Response ms  {resp_time:.2f}</pre>",
        parse_mode=ParseMode.HTML, reply_markup=back_menu_kb("dns", hours)
    )

async def render_export(q, context, hours: int):
    fake_update = Update(update_id=0)
    fake_update._effective_chat = q.message.chat
    fake_update._effective_user = q.from_user
    class _Proxy: pass
    p = _Proxy(); p.message = q.message
    await export_cmd(fake_update, context, hours_override=hours)
    try:
        await q.delete_message()
    except Exception:
        pass

async def render_bfm(q, context):
    z = get_active_zone(context)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 BFM On", callback_data="bfm:on"), InlineKeyboardButton("🤖 BFM Off", callback_data="bfm:off")],
        [InlineKeyboardButton("🛡️ Super BFM On", callback_data="sbfm:on"), InlineKeyboardButton("🛡️ Super BFM Off", callback_data="sbfm:off")],
        [InlineKeyboardButton("🏠 Home", callback_data="home")],
    ])
    await q.edit_message_text(f"🤖 <b>Bot Fight Mode</b> · <code>{z['name'] or z['id']}</code>", parse_mode=ParseMode.HTML, reply_markup=kb)

async def render_rl_menu(q, context):
    z = get_active_zone(context)
    rules = cf_api.list_ratelimit_rules(zone_id=z["id"])
    if not rules:
        await q.edit_message_text("🧱 <b>Rate-limit</b>\n<i>No rules found.</i>\nUse /rl_add_path or /rl_add_asn.", parse_mode=ParseMode.HTML,
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="home")]]))
        return
    rows = []
    for r in rules:
        rl = r.get("ratelimit") or {}
        rows.append([
            r.get("id"),
            (r.get("action") or "-"),
            rl.get("requests_per_period"),
            rl.get("period"),
            rl.get("mitigation_timeout"),
            (r.get("expression") or "")[:40] + ("…" if len(r.get("expression",""))>40 else "")
        ])
    await q.edit_message_text("🧱 <b>Rate-limit rules</b>\n" + make_pre_table(rows, ["ID","Action","Req","Period","Timeout","Expr"]),
                              parse_mode=ParseMode.HTML,
                              reply_markup=InlineKeyboardMarkup([
                                  [InlineKeyboardButton("🔁 Refresh", callback_data="rl:menu"),
                                   InlineKeyboardButton("🏠 Home", callback_data="home")]
                              ]))

async def render_origin_alerts_menu(q, context, data: str):
    """Render origin served alerts management menu."""
    global origin_served_monitor
    if not origin_served_monitor:
        await q.edit_message_text("❌ Origin served monitor not initialized.", parse_mode=ParseMode.HTML,
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="home")]]))
        return
    
    if data == "origin_alerts:menu":
        # Show main menu
        thresholds = origin_served_monitor.get_thresholds()
        enabled = origin_served_monitor.alerts_enabled
        
        status_icon = "✅" if enabled else "❌"
        status_text = "Enabled" if enabled else "Disabled"
        
        message = f"🔔 <b>Origin Served Requests Alerts</b>\n\n"
        message += f"<b>Status:</b> {status_icon} {status_text}\n\n"
        message += f"<b>Current Thresholds:</b>\n"
        message += f"• 30 minutes: <code>{thresholds.get('30m', 0):,}</code> requests\n"
        message += f"• 6 hours: <code>{thresholds.get('6h', 0):,}</code> requests\n"
        message += f"• 24 hours: <code>{thresholds.get('24h', 0):,}</code> requests\n\n"
        message += f"<i>Alerts trigger when origin-served requests drop below threshold.</i>"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Enable", callback_data="origin_alerts:enable"),
             InlineKeyboardButton("❌ Disable", callback_data="origin_alerts:disable")],
            [InlineKeyboardButton("⏱️ Set 30m", callback_data="origin_alerts:set:30m"),
             InlineKeyboardButton("⏱️ Set 6h", callback_data="origin_alerts:set:6h"),
             InlineKeyboardButton("⏱️ Set 24h", callback_data="origin_alerts:set:24h")],
            [InlineKeyboardButton("📊 Check Now", callback_data="origin_alerts:check"),
             InlineKeyboardButton("📋 Status", callback_data="origin_alerts:status")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")]
        ])
        await q.edit_message_text(message, parse_mode=ParseMode.HTML, reply_markup=kb)
    
    elif data == "origin_alerts:enable":
        origin_served_monitor.enable_alerts()
        await q.answer("✅ Alerts enabled", show_alert=False)
        await render_origin_alerts_menu(q, context, "origin_alerts:menu")
    
    elif data == "origin_alerts:disable":
        origin_served_monitor.disable_alerts()
        await q.answer("❌ Alerts disabled", show_alert=False)
        await render_origin_alerts_menu(q, context, "origin_alerts:menu")
    
    elif data == "origin_alerts:check":
        await q.edit_message_text("⏳ <i>Checking origin served requests...</i>", parse_mode=ParseMode.HTML)
        results = await origin_served_monitor.check_thresholds()
        
        if not results:
            message = "ℹ️ <b>No thresholds configured</b>\n\n"
            message += "Set thresholds using the buttons below, or use commands for advanced management. "
            message += "Click <b>⚙️ Advanced</b> in the main menu for more information."
        else:
            message = "📊 <b>Origin Served Requests Status</b>\n\n"
            for period, result in results.items():
                count = result['count']
                threshold = result['threshold']
                is_below = result['is_below']
                status_icon = "❌" if is_below else "✅"
                period_name = {'30m': '30 minutes', '6h': '6 hours', '24h': '24 hours'}.get(period, period)
                message += f"{status_icon} <b>{period_name}:</b> <code>{count:,}</code> / <code>{threshold:,}</code>\n"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 Refresh", callback_data="origin_alerts:check"),
             InlineKeyboardButton("🔙 Back", callback_data="origin_alerts:menu")]
        ])
        await q.edit_message_text(message, parse_mode=ParseMode.HTML, reply_markup=kb)
    
    elif data == "origin_alerts:status":
        thresholds = origin_served_monitor.get_thresholds()
        enabled = origin_served_monitor.alerts_enabled
        alert_state = origin_served_monitor.alert_state
        
        message = f"📋 <b>Origin Alerts Status</b>\n\n"
        message += f"<b>Alerts:</b> {'✅ Enabled' if enabled else '❌ Disabled'}\n\n"
        message += f"<b>Thresholds & Current State:</b>\n"
        
        periods = {'30m': '30 minutes', '6h': '6 hours', '24h': '24 hours'}
        for period, period_name in periods.items():
            threshold = thresholds.get(period, 0)
            is_alerting = alert_state.get(period, False)
            alert_status = "⚠️ Alerting" if is_alerting else "✅ Normal"
            message += f"• {period_name}: <code>{threshold:,}</code> - {alert_status}\n"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="origin_alerts:menu")]
        ])
        await q.edit_message_text(message, parse_mode=ParseMode.HTML, reply_markup=kb)
    
    elif data.startswith("origin_alerts:set:"):
        period = data.split(":")[-1]
        period_name = {'30m': '1 hour', '6h': '6 hours', '24h': '24 hours'}.get(period, period)
        await q.edit_message_text(
            f"⏱️ <b>Set {period_name} Threshold</b>\n\n"
            f"<i>Use the command below to set the threshold, or click <b>⚙️ Advanced</b> in the main menu for more management options:</i>\n\n"
            f"<code>/origin_alert_set {period} &lt;min_requests&gt;</code>\n\n"
            f"<b>Example:</b>\n"
            f"<code>/origin_alert_set {period} 1000</code>\n\n"
            f"<i>This sets the minimum number of origin-served requests expected in the last {period_name}.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="origin_alerts:menu")]
            ])
        )

# ========================= EXPORT (ADMIN-GATED) =========================
@admins_only
async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, hours_override: Optional[int] = None):
    z = get_active_zone(context)
    if hours_override is not None:
        hours = hours_override
    elif context.args:
        is_valid, hours = validate_hours(context.args[0])
        if not is_valid:
            await update.message.reply_text("❌ Invalid hours. Must be between 1 and 168.", parse_mode=ParseMode.HTML)
            return
    else:
        hours = 24
    gql = cf_api.get_http_requests_fixed(hours=hours, zone_id=z["id"])
    ts = timeseries_from_graphql(gql) if gql else []
    if not ts:
        await update.message.reply_text("ℹ️ No data to export.", parse_mode=ParseMode.HTML); return
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["datetime","requests","bytes","visits"])
    for row in ts:
        w.writerow([row.get("datetime"), row.get("count"), row.get("bytes"), row.get("visits")])
    data = io.BytesIO(buf.getvalue().encode("utf-8"))
    filename = f"cf-timeseries-{z.get('name') or z.get('id')}-{hours}h.csv"
    await update.message.reply_document(document=InputFile(data, filename=filename), caption=f"📤 Exported {hours}h for {z.get('name') or z.get('id')}")
    buf.close()

# ========================= ADMIN HELP =========================
def _admin_help() -> str:
    return (
        "⚙️ <b>Advanced Management</b>\n\n"
        "Most features can be managed using the buttons in the main menu. "
        "For advanced control, you can use commands directly.\n\n"
        "<b>📊 Analytics & Status:</b>\n"
        "• <code>/status</code> — Zone overview\n"
        "• <code>/verify [hours]</code> — Data accuracy check\n"
        "• <code>/zones</code> — Zone picker\n"
        "• <code>/export &lt;hours&gt;</code> — CSV time series export\n\n"
        "<b>🛡️ Security & Access Rules:</b>\n"
        "• <code>/ip_list [mode]</code> — List access rules\n"
        "• <code>/ip_allow &lt;ip|cidr&gt; [notes]</code> — Whitelist IP\n"
        "• <code>/ip_block &lt;ip|cidr&gt; [notes]</code> — Block IP\n"
        "• <code>/ip_delete &lt;id|ip|cidr&gt;</code> — Remove rule\n"
        "• <code>/rule_block &lt;expr&gt; -- &lt;desc&gt;</code> — Block with expression\n"
        "• <code>/rule_bypass_waf &lt;expr&gt; -- &lt;desc&gt;</code> — Bypass WAF\n"
        "• <code>/rules</code> — List firewall rules\n\n"
        "<b>🌐 DNS Management:</b>\n"
        "• <code>/dns_list [name]</code> — List DNS records\n"
        "• <code>/dns_add TYPE NAME CONTENT [TTL] [proxied]</code> — Add record\n"
        "• <code>/dns_upd ID field=value ...</code> — Update record\n"
        "• <code>/dns_del ID</code> — Delete record\n\n"
        "<b>⚡ Cache & Performance:</b>\n"
        "• <code>/cache_purge all|&lt;url1&gt; [&lt;url2&gt;...]</code> — Purge cache\n"
        "• <code>/toggle_bfm on|off</code> — Bot Fight Mode\n"
        "• <code>/toggle_sbfm on|off</code> — Super Bot Fight Mode\n\n"
        "<b>🧱 Rate Limiting:</b>\n"
        "• <code>/rl_list</code> — List rate limit rules\n"
        "• <code>/rl_add_path /api/ 100 60 600 block</code> — Add path rule\n"
        "• <code>/rl_add_asn 13335 200 60 600 block path=/wp-login.php</code> — Add ASN rule\n"
        "• <code>/rl_del ID</code> — Delete rule\n\n"
        "<b>🔔 Origin Monitoring:</b>\n"
        "• <code>/origin_add &lt;url&gt; [interval] [timeout]</code> — Monitor origin health\n"
        "• <code>/origin_remove &lt;url&gt;</code> — Stop monitoring\n"
        "• <code>/origin_list</code> — List monitored origins\n"
        "• <code>/origin_check &lt;url&gt;</code> — Manual health check\n"
        "• <code>/origin_alert_set &lt;30m|6h|24h&gt; &lt;min_requests&gt;</code> — Set threshold\n"
        "• <code>/origin_alert_enable</code> / <code>/origin_alert_disable</code> — Toggle alerts\n"
        "• <code>/origin_alert_status</code> — Show status\n"
        "• <code>/origin_alert_check</code> — Manual check\n\n"
        "<i>💡 Tip: Use buttons in the main menu for quick access to most features!</i>"
    )

def _deny_if_not_admin(func):
    # legacy decorator retained for clarity, but not used — global admin gate covers everything now
    return admins_only(func)

# ========================= ADMIN COMMANDS (ALL HAVE @admins_only) =========================
# --- IP Access Rules
@admins_only
async def ip_allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /ip_allow <ip|cidr> [notes]", parse_mode=ParseMode.HTML)
        return
    z = get_active_zone(context)
    value = context.args[0].strip()
    
    # Validate IP/CIDR
    is_valid, error_msg = validate_ip_or_cidr(value)
    if not is_valid:
        await update.message.reply_text(f"❌ {error_msg}", parse_mode=ParseMode.HTML)
        return
    
    notes = sanitize_string(" ".join(context.args[1:]) if len(context.args) > 1 else "", max_length=500)
    target = "ip_range" if "/" in value else "ip"
    resp = cf_api.create_access_rule(mode="whitelist", target=target, value=value, notes=notes, zone_id=z["id"])
    await audit(context, update, "IP Allow", f"<code>{value}</code>")
    await update.message.reply_text("✅ Allow created." if resp else "❌ Failed.", parse_mode=ParseMode.HTML)

@admins_only
async def ip_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /ip_block <ip|cidr> [notes]", parse_mode=ParseMode.HTML)
        return
    z = get_active_zone(context)
    value = context.args[0].strip()
    
    # Validate IP/CIDR
    is_valid, error_msg = validate_ip_or_cidr(value)
    if not is_valid:
        await update.message.reply_text(f"❌ {error_msg}", parse_mode=ParseMode.HTML)
        return
    
    notes = sanitize_string(" ".join(context.args[1:]) if len(context.args) > 1 else "", max_length=500)
    target = "ip_range" if "/" in value else "ip"
    resp = cf_api.create_access_rule(mode="block", target=target, value=value, notes=notes, zone_id=z["id"])
    await audit(context, update, "IP Block", f"<code>{value}</code>")
    await update.message.reply_text("✅ Block created." if resp else "❌ Failed.", parse_mode=ParseMode.HTML)

@admins_only
async def ip_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if not context.args:
        await update.message.reply_text("Usage: /ip_delete <id|ip|cidr>", parse_mode=ParseMode.HTML); return
    token = context.args[0]

    def looks_like_id(s: str) -> bool:
        return bool(re.fullmatch(r"[a-f0-9]{32}", s))

    rule_id = token if looks_like_id(token) else None
    if not rule_id:
        for page in range(1, 11):
            data = cf_api.list_access_rules(page=page, per_page=50, configuration_value=token, zone_id=z["id"])
            if not data: break
            for it in (data.get("result") or []):
                cfg = (it.get("configuration") or {})
                if str(cfg.get("value")) == token:
                    rule_id = it.get("id"); break
            if rule_id: break

    if not rule_id:
        await update.message.reply_text("❌ Not found.", parse_mode=ParseMode.HTML); return

    ok = cf_api.delete_access_rule(rule_id, zone_id=z["id"])
    await audit(context, update, "IP Rule Delete", f"<code>{rule_id}</code>")
    await update.message.reply_text("🗑️ Deleted." if ok else "❌ Delete failed.", parse_mode=ParseMode.HTML)

@admins_only
async def ip_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    mode = context.args[0] if context.args else None
    data = cf_api.list_access_rules(page=1, per_page=100, mode=mode, zone_id=z["id"])
    if not data:
        await update.message.reply_text("❌ Failed to list access rules.", parse_mode=ParseMode.HTML); return
    rows = []
    for r in (data.get("result") or []):
        cfg = r.get("configuration") or {}
        rows.append([r.get("id"), r.get("mode"), cfg.get("target"), cfg.get("value"), (r.get("notes") or "-")[:30]])
    if not rows:
        await update.message.reply_text("<i>No rules.</i>", parse_mode=ParseMode.HTML); return
    await update.message.reply_text(make_pre_table(rows, ["ID", "Mode", "Target", "Value", "Notes"]), parse_mode=ParseMode.HTML)

# --- Firewall filters/rules
def _split_expr_desc(args: List[str]) -> tuple[str, str]:
    joined = " ".join(args)
    if " -- " in joined:
        expr, desc = joined.split(" -- ", 1)
    else:
        expr, desc = joined, ""
    return expr.strip(), desc.strip()

@admins_only
async def rules_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    data = cf_api.list_firewall_rules(zone_id=z["id"])
    if not data:
        await update.message.reply_text("❌ Failed to list firewall rules.", parse_mode=ParseMode.HTML); return
    rows = []
    for r in (data.get("result") or []):
        filt = (r.get("filter") or {})
        rows.append([r.get("id"), r.get("action"), "yes" if r.get("paused") else "no", (r.get("description") or "-")[:34], filt.get("expression", "")[:34]])
    if not rows:
        await update.message.reply_text("<i>No firewall rules.</i>", parse_mode=ParseMode.HTML); return
    await update.message.reply_text(make_pre_table(rows, ["ID", "Action", "Paused", "Desc", "Expr"]), parse_mode=ParseMode.HTML)

@admins_only
async def rule_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if not context.args:
        await update.message.reply_text("Usage: /rule_block <expression> -- <description>", parse_mode=ParseMode.HTML)
        return
    expr, desc = _split_expr_desc(context.args)
    expr = sanitize_string(expr, max_length=1000)
    desc = sanitize_string(desc, max_length=500)
    f = cf_api.create_filter(expr, desc or "rule_block", zone_id=z["id"])
    if not f or not (f.get("result") or []):
        await update.message.reply_text("❌ Filter create failed.", parse_mode=ParseMode.HTML); return
    filter_id = (f["result"][0] or {}).get("id")
    r = cf_api.create_firewall_rule(filter_id, action="block", description=desc or "rule_block", zone_id=z["id"])
    await audit(context, update, "FW Rule Block", f"<code>{expr}</code>")
    await update.message.reply_text("✅ Created blocking rule." if r else "❌ Rule create failed.", parse_mode=ParseMode.HTML)

@admins_only
async def rule_bypass_waf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if not context.args:
        await update.message.reply_text("Usage: /rule_bypass_waf <expression> -- <description>", parse_mode=ParseMode.HTML)
        return
    expr, desc = _split_expr_desc(context.args)
    expr = sanitize_string(expr, max_length=1000)
    desc = sanitize_string(desc, max_length=500)
    f = cf_api.create_filter(expr, desc or "bypass_waf", zone_id=z["id"])
    if not f or not (f.get("result") or []):
        await update.message.reply_text("❌ Filter create failed.", parse_mode=ParseMode.HTML); return
    filter_id = (f["result"][0] or {}).get("id")
    r = cf_api.create_firewall_rule(filter_id, action="bypass", description=desc or "bypass_waf", products=["waf"], zone_id=z["id"])
    await audit(context, update, "FW Rule Bypass WAF", f"<code>{expr}</code>")
    await update.message.reply_text("✅ Created WAF-bypass rule." if r else "❌ Rule create failed.", parse_mode=ParseMode.HTML)

# --- Cache purge
@admins_only
async def cache_purge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if not context.args:
        await update.message.reply_text("Usage: /cache_purge all|<url1> <url2> ...", parse_mode=ParseMode.HTML); return
    if len(context.args) == 1 and context.args[0].lower() == "all":
        ok = cf_api.purge_cache_everything(zone_id=z["id"])
        await audit(context, update, "Cache Purge", "everything")
        await update.message.reply_text("🧹 Purge everything: ✅" if ok else "🧹 Purge everything: ❌", parse_mode=ParseMode.HTML)
    else:
        ok = cf_api.purge_cache_files(context.args, zone_id=z["id"])
        await audit(context, update, "Cache Purge Files", "<br>".join(context.args))
        await update.message.reply_text("🧹 Purge files: ✅" if ok else "🧹 Purge files: ❌", parse_mode=ParseMode.HTML)

# --- DNS CRUD
@admins_only
async def dns_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    name = context.args[0] if context.args else None
    data = cf_api.list_dns_records(name=name, page=1, per_page=100, zone_id=z["id"])
    if not data:
        await update.message.reply_text("❌ Failed to list DNS records.", parse_mode=ParseMode.HTML); return
    rows = []
    for it in (data.get("result") or []):
        rows.append([it.get("id"), it.get("type"), it.get("name"), (it.get("content") or "")[:32], it.get("ttl"), "on" if it.get("proxied") else "off"])
    if not rows:
        await update.message.reply_text("<i>No DNS records.</i>", parse_mode=ParseMode.HTML); return
    await update.message.reply_text(make_pre_table(rows, ["ID", "Type", "Name", "Content", "TTL", "Proxy"]), parse_mode=ParseMode.HTML)

@admins_only
async def dns_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /dns_add <TYPE> <NAME> <CONTENT> [TTL] [proxied]", parse_mode=ParseMode.HTML); return
    typ, name, content = context.args[:3]
    ttl = int(context.args[3]) if len(context.args) >= 4 else 1
    proxied = None
    if len(context.args) >= 5:
        proxied = context.args[4].lower() in ("1", "true", "yes", "on")
    r = cf_api.create_dns_record(typ.upper(), name, content, ttl=ttl, proxied=proxied if proxied is not None else True, zone_id=z["id"])
    await audit(context, update, "DNS Add", f"<code>{typ} {name} -> {content}</code>")
    await update.message.reply_text("✅ DNS record created." if r else "❌ Failed to create DNS record.", parse_mode=ParseMode.HTML)

@admins_only
async def dns_upd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /dns_upd <ID> field=value ...", parse_mode=ParseMode.HTML); return
    rid = context.args[0]
    fields = {}
    for pair in context.args[1:]:
        if "=" not in pair: continue
        k, v = pair.split("=", 1)
        if k == "ttl":
            fields[k] = int(v)
        elif k == "proxied":
            fields[k] = v.lower() in ("1", "true", "yes", "on")
        else:
            fields[k] = v
    r = cf_api.update_dns_record(rid, zone_id=z["id"], **fields)
    await audit(context, update, "DNS Update", f"<code>{rid}</code> {fields}")
    await update.message.reply_text("✅ DNS record updated." if r else "❌ DNS update failed.", parse_mode=ParseMode.HTML)

@admins_only
async def dns_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if not context.args:
        await update.message.reply_text("Usage: /dns_del <ID>", parse_mode=ParseMode.HTML); return
    ok = cf_api.delete_dns_record(context.args[0], zone_id=z["id"])
    await audit(context, update, "DNS Delete", f"<code>{context.args[0]}</code>")
    await update.message.reply_text("🗑️ Deleted." if ok else "❌ Delete failed.", parse_mode=ParseMode.HTML)

# --- BFM toggles (commands)
@admins_only
async def toggle_bfm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if not context.args or context.args[0].lower() not in ("on","off"):
        await update.message.reply_text("Usage: /toggle_bfm on|off", parse_mode=ParseMode.HTML); return
    ok = cf_api.set_bfm(context.args[0].lower() == "on", zone_id=z["id"])
    await audit(context, update, "Toggle BFM", context.args[0].lower())
    await update.message.reply_text("🤖 Bot Fight Mode: ✅" if ok else "🤖 Bot Fight Mode: ❌", parse_mode=ParseMode.HTML)

@admins_only
async def toggle_sbfm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if not context.args or context.args[0].lower() not in ("on","off"):
        await update.message.reply_text("Usage: /toggle_sbfm on|off", parse_mode=ParseMode.HTML); return
    ok = cf_api.set_sbfm(context.args[0].lower() == "on", zone_id=z["id"])
    await audit(context, update, "Toggle Super BFM", context.args[0].lower())
    await update.message.reply_text("🛡️ Super BFM: ✅" if ok else "🛡️ Super BFM: ❌", parse_mode=ParseMode.HTML)

# --- RATE LIMIT BUILDER (commands)
def _parse_action(arg: Optional[str]) -> str:
    if not arg: return "block"
    a = arg.lower()
    return a if a in ("block","challenge") else "block"

@admins_only
async def rl_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    rules = cf_api.list_ratelimit_rules(zone_id=z["id"])
    if not rules:
        await update.message.reply_text("ℹ️ No rate-limit rules found.", parse_mode=ParseMode.HTML); return
    rows = []
    for r in rules:
        rl = r.get("ratelimit") or {}
        rows.append([
            r.get("id"),
            (r.get("action") or "-"),
            rl.get("requests_per_period"),
            rl.get("period"),
            rl.get("mitigation_timeout"),
            (r.get("expression") or "")[:40] + ("…" if len(r.get("expression",""))>40 else "")
        ])
    await update.message.reply_text(make_pre_table(rows, ["ID","Action","Req","Period","Timeout","Expr"]), parse_mode=ParseMode.HTML)

@admins_only
async def rl_add_path(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /rl_add_path <path> <threshold> <period_s> [timeout_s] [action]", parse_mode=ParseMode.HTML); return
    path = context.args[0]
    thr = int(context.args[1]); per = int(context.args[2])
    timeout = int(context.args[3]) if len(context.args) >= 4 else 600
    action = _parse_action(context.args[4] if len(context.args) >= 5 else None)
    expr = f'(http.request.uri.path contains "{path}")'
    r = cf_api.add_ratelimit_rule(expr, thr, per, mitigation_timeout=timeout, action=action, zone_id=z["id"], description=f"Path {path}")
    await audit(context, update, "RL Add Path", f"<code>{path}</code> thr={thr} per={per}s act={action}")
    await update.message.reply_text("✅ Added rate limit." if r else "❌ Failed to add rule.", parse_mode=ParseMode.HTML)

@admins_only
async def rl_add_asn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /rl_add_asn <asn> <threshold> <period_s> [timeout_s] [action] [path=/foo]", parse_mode=ParseMode.HTML); return
    asn = context.args[0]
    thr = int(context.args[1]); per = int(context.args[2])
    timeout = int(context.args[3]) if len(context.args) >= 4 else 600
    action = _parse_action(context.args[4] if len(context.args) >= 5 else None)
    path_filter = None
    for a in context.args[5:]:
        if a.startswith("path="): path_filter = a.split("=",1)[1]
    expr = f'(ip.geoip.asnum eq {asn})'
    if path_filter:
        expr = f'({expr} and http.request.uri.path contains "{path_filter}")'
    r = cf_api.add_ratelimit_rule(expr, thr, per, mitigation_timeout=timeout, action=action, zone_id=z["id"], description=f"ASN {asn}"+(f" path={path_filter}" if path_filter else ""))
    await audit(context, update, "RL Add ASN", f"asn={asn} thr={thr} per={per}s act={action} path={path_filter or '-'}")
    await update.message.reply_text("✅ Added rate limit." if r else "❌ Failed to add rule.", parse_mode=ParseMode.HTML)

@admins_only
async def rl_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if not context.args:
        await update.message.reply_text("Usage: /rl_del <rule_id>", parse_mode=ParseMode.HTML); return
    ok = cf_api.delete_ratelimit_rule(context.args[0], zone_id=z["id"])
    await audit(context, update, "RL Delete", f"<code>{context.args[0]}</code>")
    await update.message.reply_text("🗑️ Deleted." if ok else "❌ Delete failed.", parse_mode=ParseMode.HTML)

# ========================= ORIGIN MONITORING =========================
# Global origin monitor instance (will be initialized in main)
origin_monitor: Optional[OriginMonitor] = None
origin_served_monitor: Optional[OriginServedMonitor] = None

async def _send_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, parse_mode: str = ParseMode.HTML):
    """Helper function to safely send a reply message."""
    if update.message:
        return await update.message.reply_text(text, parse_mode=parse_mode)
    elif update.effective_chat:
        return await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode=parse_mode)
    else:
        logger.warning("Cannot send reply: no message or chat available")
        return None

@admins_only
async def origin_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add an origin URL to monitor (supports full URLs with paths)."""
    global origin_monitor
    if not origin_monitor:
        await _send_reply(update, context, "❌ Origin monitor not initialized.", ParseMode.HTML)
        return
    
    if not context.args:
        await _send_reply(
            update, context,
            "Usage: /origin_add <url> [check_interval] [timeout]\n\n"
            "Examples:\n"
            "• <code>/origin_add https://example.com</code>\n"
            "• <code>/origin_add https://example.com/api/health</code>\n"
            "• <code>/origin_add example.com 60 10</code>\n"
            "• <code>/origin_add https://example.com/payment/admin 120 15</code>\n\n"
            "Parameters:\n"
            "• url: Full URL or domain (paths supported)\n"
            "• check_interval: Seconds between checks (default: 60)\n"
            "• timeout: Request timeout in seconds (default: 10)",
            ParseMode.HTML
        )
        return
    
    url = context.args[0].strip()
    try:
        check_interval = int(context.args[1]) if len(context.args) > 1 else 60
        timeout = int(context.args[2]) if len(context.args) > 2 else 10
    except ValueError:
        await _send_reply(update, context, "❌ Invalid interval or timeout value. Must be integers.", ParseMode.HTML)
        return
    
    user_id = update.effective_user.id if update.effective_user else 0
    success = origin_monitor.add_origin(url, user_id, check_interval, timeout)
    
    if success:
        # Get normalized URL for display
        try:
            normalized = origin_monitor._normalize_url(url)
        except:
            normalized = url
        await _send_reply(
            update, context,
            f"✅ Added origin monitoring for <code>{normalized}</code>\n"
            f"Check interval: {check_interval}s\n"
            f"Timeout: {timeout}s\n\n"
            f"<i>Note: Only 5xx server errors trigger alerts. 4xx client errors are ignored.</i>",
            ParseMode.HTML
        )
    else:
        await _send_reply(update, context, "❌ Failed to add origin monitoring. Check URL format.", ParseMode.HTML)

@admins_only
async def origin_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove an origin URL from monitoring."""
    global origin_monitor
    if not origin_monitor:
        await _send_reply(update, context, "❌ Origin monitor not initialized.", ParseMode.HTML)
        return
    
    if not context.args:
        await _send_reply(update, context, "Usage: /origin_remove <url>\nExample: /origin_remove https://example.com/api/health", ParseMode.HTML)
        return
    
    url = context.args[0].strip()
    success = origin_monitor.remove_origin(url)
    
    if success:
        await _send_reply(update, context, f"✅ Removed origin monitoring for <code>{url}</code>", ParseMode.HTML)
    else:
        await _send_reply(update, context, f"❌ Origin <code>{url}</code> not found in monitoring list.", ParseMode.HTML)

@admins_only
async def origin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all monitored origins."""
    global origin_monitor
    if not origin_monitor:
        await _send_reply(update, context, "❌ Origin monitor not initialized.", ParseMode.HTML)
        return
    
    origins = origin_monitor.list_origins()
    if not origins:
        await _send_reply(update, context, "ℹ️ No origins being monitored.", ParseMode.HTML)
        return
    
    rows = []
    for orig in origins:
        url = orig.get('url', 'Unknown')
        # Truncate long URLs for display
        display_url = url[:40] + "..." if len(url) > 40 else url
        status = orig.get('last_status', 'Never checked')
        failures = orig.get('consecutive_failures', 0)
        enabled = "✅" if orig.get('enabled', True) else "❌"
        total = orig.get('total_checks', 0)
        successful = orig.get('successful_checks', 0)
        success_rate = f"{(successful/total*100):.0f}%" if total > 0 else "N/A"
        rows.append([enabled, display_url, str(status), str(failures), success_rate])
    
    table = make_pre_table(rows, ["Status", "URL", "Last Status", "Failures", "Success %"])
    await _send_reply(update, context, f"🌐 <b>Monitored Origins</b>\n{table}", ParseMode.HTML)

@admins_only
async def origin_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually check an origin's health."""
    global origin_monitor
    if not origin_monitor:
        await _send_reply(update, context, "❌ Origin monitor not initialized.", ParseMode.HTML)
        return
    
    if not context.args:
        await _send_reply(update, context, "Usage: /origin_check <url>\nExample: /origin_check https://example.com/api/health", ParseMode.HTML)
        return
    
    url = context.args[0].strip()
    
    # Send initial message
    if update.message:
        msg = await update.message.reply_text(f"⏳ Checking <code>{url}</code>...", parse_mode=ParseMode.HTML)
    elif update.effective_chat:
        msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"⏳ Checking <code>{url}</code>...",
            parse_mode=ParseMode.HTML
        )
    else:
        await _send_reply(update, context, "❌ Cannot check origin: no chat available.", ParseMode.HTML)
        return
    
    result = await origin_monitor.check_origin(url)
    
    if 'error' in result and result['error'] == 'Origin not found':
        await msg.edit_text(
            f"❌ Origin <code>{url}</code> not found in monitoring list.\n\n"
            f"<i>Use /origin_add to add it first, or check the URL format.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    status_code = result.get('status_code', 'N/A')
    response_time = result.get('response_time', 0)
    is_error = result.get('is_error', False)
    is_critical = result.get('is_critical', False)
    error = result.get('error', '')
    
    status_emoji = "❌" if is_critical else ("⚠️" if is_error else "✅")
    message = f"{status_emoji} <b>Origin Health Check</b>\n\n"
    message += f"<b>URL:</b> <code>{url}</code>\n"
    message += f"<b>Status Code:</b> <code>{status_code}</code>\n"
    
    if response_time:
        message += f"<b>Response Time:</b> {response_time:.2f}s\n"
    
    if is_critical:
        message += f"<b>Status:</b> ❌ <b>Critical Error</b>\n"
    elif is_error:
        message += f"<b>Status:</b> ⚠️ <b>Non-Critical Error</b> (ignored)\n"
    else:
        message += f"<b>Status:</b> ✅ <b>Healthy</b>\n"
    
    if error:
        message += f"<b>Error:</b> <code>{error}</code>\n"
    
    if 400 <= status_code < 500:
        message += f"\n<i>Note: 4xx client errors are not considered critical and won't trigger alerts.</i>"
    
    try:
        await msg.edit_text(message, parse_mode=ParseMode.HTML)
    except Exception as e:
        # If edit fails, send as new message
        logger.warning(f"Failed to edit message, sending new: {e}")
        await _send_reply(update, context, message, ParseMode.HTML)

# ========================= ORIGIN SERVED ALERTS =========================
@admins_only
async def origin_alert_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set threshold for origin served requests alerts."""
    global origin_served_monitor
    if not origin_served_monitor:
        await _send_reply(update, context, "❌ Origin served monitor not initialized.", ParseMode.HTML)
        return
    
    if len(context.args) < 2:
        await _send_reply(
            update, context,
            "Usage: /origin_alert_set <period> <min_requests>\n\n"
            "Periods: 30m, 6h, 24h\n\n"
            "Examples:\n"
            "• <code>/origin_alert_set 30m 1000</code>\n"
            "• <code>/origin_alert_set 6h 5000</code>\n"
            "• <code>/origin_alert_set 24h 20000</code>",
            ParseMode.HTML
        )
        return
    
    period = context.args[0].lower()
    if period not in ['30m', '6h', '24h']:
        await _send_reply(update, context, "❌ Invalid period. Use: 30m, 6h, or 24h", ParseMode.HTML)
        return
    
    try:
        min_requests = int(context.args[1])
        if min_requests < 0:
            raise ValueError("Must be non-negative")
    except ValueError:
        await _send_reply(update, context, "❌ Invalid request count. Must be a positive integer.", ParseMode.HTML)
        return
    
    success = origin_served_monitor.set_threshold(period, min_requests)
    if success:
        period_name = {'30m': '30 minutes', '6h': '6 hours', '24h': '24 hours'}.get(period, period)
        await _send_reply(
            update, context,
            f"✅ Set {period_name} threshold to <code>{min_requests:,}</code> requests\n\n"
            f"<i>Alerts will trigger when origin-served requests drop below this threshold.</i>",
            ParseMode.HTML
        )
    else:
        await _send_reply(update, context, "❌ Failed to set threshold.", ParseMode.HTML)

@admins_only
async def origin_alert_enable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable origin served requests alerts."""
    global origin_served_monitor
    if not origin_served_monitor:
        await _send_reply(update, context, "❌ Origin served monitor not initialized.", ParseMode.HTML)
        return
    
    origin_served_monitor.enable_alerts()
    await _send_reply(update, context, "✅ Origin served alerts enabled.", ParseMode.HTML)

@admins_only
async def origin_alert_disable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable origin served requests alerts."""
    global origin_served_monitor
    if not origin_served_monitor:
        await _send_reply(update, context, "❌ Origin served monitor not initialized.", ParseMode.HTML)
        return
    
    origin_served_monitor.disable_alerts()
    await _send_reply(update, context, "❌ Origin served alerts disabled.", ParseMode.HTML)

@admins_only
async def origin_alert_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show origin served alerts status."""
    global origin_served_monitor
    if not origin_served_monitor:
        await _send_reply(update, context, "❌ Origin served monitor not initialized.", ParseMode.HTML)
        return
    
    thresholds = origin_served_monitor.get_thresholds()
    enabled = origin_served_monitor.alerts_enabled
    alert_state = origin_served_monitor.alert_state
    
    message = f"📋 <b>Origin Served Alerts Status</b>\n\n"
    message += f"<b>Alerts:</b> {'✅ Enabled' if enabled else '❌ Disabled'}\n\n"
    message += f"<b>Thresholds:</b>\n"
    
    periods = {'30m': '30 minutes', '6h': '6 hours', '24h': '24 hours'}
    for period, period_name in periods.items():
        threshold = thresholds.get(period, 0)
        is_alerting = alert_state.get(period, False)
        if threshold > 0:
            alert_status = "⚠️ Alerting" if is_alerting else "✅ Normal"
            message += f"• {period_name}: <code>{threshold:,}</code> - {alert_status}\n"
        else:
            message += f"• {period_name}: <i>Not set</i>\n"
    
    await _send_reply(update, context, message, ParseMode.HTML)

@admins_only
async def origin_alert_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually check origin served requests against thresholds."""
    global origin_served_monitor
    if not origin_served_monitor:
        await _send_reply(update, context, "❌ Origin served monitor not initialized.", ParseMode.HTML)
        return
    
    msg = await _send_reply(update, context, "⏳ <i>Checking origin served requests...</i>", ParseMode.HTML)
    if not msg:
        # If _send_reply didn't return a message, create one
        if update.message:
            msg = await update.message.reply_text("⏳ <i>Checking origin served requests...</i>", parse_mode=ParseMode.HTML)
        elif update.effective_chat:
            msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⏳ <i>Checking origin served requests...</i>",
                parse_mode=ParseMode.HTML
            )
        else:
            return
    
    results = await origin_served_monitor.check_thresholds()
    thresholds = origin_served_monitor.get_thresholds()
    
    if not any(thresholds.values()):
        message = "ℹ️ <b>No thresholds configured</b>\n\n"
        message += "Set thresholds using:\n"
        message += "• <code>/origin_alert_set 30m 1000</code>\n"
        message += "• <code>/origin_alert_set 6h 5000</code>\n"
        message += "• <code>/origin_alert_set 24h 20000</code>"
    else:
        message = "📊 <b>Origin Served Requests Check</b>\n\n"
        periods = {'30m': '30 minutes', '6h': '6 hours', '24h': '24 hours'}
        
        for period, period_name in periods.items():
            threshold = thresholds.get(period, 0)
            if threshold <= 0:
                continue
            
            if period in results:
                result = results[period]
                count = result['count']
                is_below = result['is_below']
                status_icon = "❌" if is_below else "✅"
                message += f"{status_icon} <b>{period_name}:</b> <code>{count:,}</code> / <code>{threshold:,}</code>\n"
            else:
                # Get current count
                hours = {'30m': 1, '6h': 6, '24h': 24}.get(period, 0)
                count = origin_served_monitor.get_origin_served_count(hours)
                if count is not None:
                    is_below = count < threshold
                    status_icon = "❌" if is_below else "✅"
                    message += f"{status_icon} <b>{period_name}:</b> <code>{count:,}</code> / <code>{threshold:,}</code>\n"
                else:
                    message += f"⚠️ <b>{period_name}:</b> <i>Data unavailable</i>\n"
    
    try:
        if msg:
            await msg.edit_text(message, parse_mode=ParseMode.HTML)
        else:
            await _send_reply(update, context, message, ParseMode.HTML)
    except Exception as e:
        logger.warning(f"Failed to edit message: {e}")
        await _send_reply(update, context, message, ParseMode.HTML)

# ========================= ERROR HANDLER =========================
async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled exception", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(update.effective_chat.id, "❌ <b>Oops.</b> Something went wrong.", parse_mode=ParseMode.HTML)
    except Exception:
        pass

# ========================= WIRE-UP =========================
def main():
    logger.info("Starting Cloudflare Telegram Bot...")
    
    # Log configuration info (safely, without exposing full tokens)
    logger.info("Configuration check:")
    logger.info("  Telegram token: %s chars", len(config.TELEGRAM_BOT_TOKEN) if config.TELEGRAM_BOT_TOKEN else 0)
    logger.info("  Cloudflare token: %s chars", len(config.CLOUDFLARE_API_TOKEN) if config.CLOUDFLARE_API_TOKEN else 0)
    if config.CLOUDFLARE_API_TOKEN:
        token_preview = config.CLOUDFLARE_API_TOKEN[:8] + "..." + config.CLOUDFLARE_API_TOKEN[-4:] if len(config.CLOUDFLARE_API_TOKEN) > 12 else config.CLOUDFLARE_API_TOKEN[:8] + "..."
        logger.info("  Cloudflare token preview: %s", token_preview)
    logger.info("  Zone ID: %s chars", len(config.CLOUDFLARE_ZONE_ID) if config.CLOUDFLARE_ZONE_ID else 0)
    if config.CLOUDFLARE_ZONE_ID:
        logger.info("  Zone ID preview: %s...", config.CLOUDFLARE_ZONE_ID[:8])
    
    # Validate configuration before starting
    try:
        config.validate()
        logger.info("Configuration validated successfully")
    except ConfigurationError as e:
        logger.error("Configuration validation failed: %s", e)
        logger.error("Please check your .env file or environment variables")
        logger.error("Run /test_config in Telegram for detailed diagnostics")
        sys.exit(1)
    except Exception as e:
        logger.error("Unexpected error during configuration validation: %s", e, exc_info=True)
        sys.exit(1)
    
    # Validate token format
    if not config.TELEGRAM_BOT_TOKEN or len(config.TELEGRAM_BOT_TOKEN) < 10:
        logger.error("Invalid TELEGRAM_BOT_TOKEN. Please check your configuration.")
        sys.exit(1)
    
    if not config.ADMIN_USER_IDS:
        logger.error("No ADMIN_USER_IDS configured. Bot requires at least one admin user ID.")
        sys.exit(1)
    
    logger.info("Connecting to Telegram...")
    try:
        app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    except Exception as e:
        logger.error("Failed to initialize Telegram bot: %s", e)
        logger.error("Please verify your TELEGRAM_BOT_TOKEN is correct")
        sys.exit(1)

    # All commands admin-gated via @admins_only
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("verify", verify))
    app.add_handler(CommandHandler("zones", zones_cmd))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("test_config", test_config))

    app.add_handler(CommandHandler("ip_list", ip_list))
    app.add_handler(CommandHandler("ip_allow", ip_allow))
    app.add_handler(CommandHandler("ip_block", ip_block))
    app.add_handler(CommandHandler("ip_delete", ip_delete))

    app.add_handler(CommandHandler("rules", rules_list))
    app.add_handler(CommandHandler("rule_block", rule_block))
    app.add_handler(CommandHandler("rule_bypass_waf", rule_bypass_waf))

    app.add_handler(CommandHandler("cache_purge", cache_purge))

    app.add_handler(CommandHandler("dns_list", dns_list))
    app.add_handler(CommandHandler("dns_add", dns_add))
    app.add_handler(CommandHandler("dns_upd", dns_upd))
    app.add_handler(CommandHandler("dns_del", dns_del))

    app.add_handler(CommandHandler("rl_list", rl_list))
    app.add_handler(CommandHandler("rl_add_path", rl_add_path))
    app.add_handler(CommandHandler("rl_add_asn", rl_add_asn))
    app.add_handler(CommandHandler("rl_del", rl_del))

    app.add_handler(CommandHandler("toggle_bfm", toggle_bfm))
    app.add_handler(CommandHandler("toggle_sbfm", toggle_sbfm))

    # Origin monitoring commands
    app.add_handler(CommandHandler("origin_add", origin_add))
    app.add_handler(CommandHandler("origin_remove", origin_remove))
    app.add_handler(CommandHandler("origin_list", origin_list))
    app.add_handler(CommandHandler("origin_check", origin_check))
    
    # Origin served alerts commands
    app.add_handler(CommandHandler("origin_alert_set", origin_alert_set))
    app.add_handler(CommandHandler("origin_alert_enable", origin_alert_enable))
    app.add_handler(CommandHandler("origin_alert_disable", origin_alert_disable))
    app.add_handler(CommandHandler("origin_alert_status", origin_alert_status))
    app.add_handler(CommandHandler("origin_alert_check", origin_alert_check))

    # Callbacks (also admin-gated via decorator)
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_error_handler(handle_error)

    # Initialize monitors
    global origin_monitor, origin_served_monitor
    status_monitor = None
    alert_chat_id = config.ALERT_CHAT_ID if config.ALERT_CHAT_ID else None
    
    try:
        # Initialize status monitor
        status_monitor = CloudflareStatusMonitor(app.bot, alert_chat_id)
        logger.info("Cloudflare Status monitor initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize status monitor: {e}")
        status_monitor = None
    
    try:
        # Initialize origin monitor
        origin_monitor = OriginMonitor(app.bot, alert_chat_id)
        logger.info("Origin Health monitor initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize origin monitor: {e}")
        origin_monitor = None
    
    try:
        # Initialize origin served monitor
        origin_served_monitor = OriginServedMonitor(app.bot, alert_chat_id)
        logger.info("Origin Served Requests monitor initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize origin served monitor: {e}")
        origin_served_monitor = None
    
    # Start monitoring tasks in background
    def start_monitors():
        """Start background monitoring tasks in a separate event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        tasks = []
        if status_monitor:
            tasks.append(loop.create_task(status_monitor.run_loop()))
        if origin_monitor:
            tasks.append(loop.create_task(origin_monitor.run_loop()))
        if origin_served_monitor:
            tasks.append(loop.create_task(origin_served_monitor.run_loop()))
        if tasks:
            try:
                loop.run_forever()
            except Exception as e:
                logger.error(f"Monitor task error: {e}", exc_info=True)
            finally:
                loop.close()
    
    # Start monitors in background thread
    if status_monitor or origin_monitor or origin_served_monitor:
        import threading
        monitor_thread = threading.Thread(target=start_monitors, daemon=True)
        monitor_thread.start()
        logger.info("Background monitors started")
    
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
