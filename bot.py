import logging, asyncio, csv, io, re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import BadRequest, Forbidden

from config import config
from cloudflare_api import cf_api
from analytics import (
    timeseries_from_graphql,
    format_timeseries_summary_for_html,
    colos_from_graphql,
    format_colos_for_html,
    format_security_for_html,
)
from utils import make_pre_table, num

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# -------- thresholds (tune to your traffic)
MITIGATIONS_24H_THRESHOLD = 30_000
ORIGIN_SERVED_24H_MIN = 2_500_000  # requests with cacheStatus != HIT

# runtime alarm control (optional)
_alarm_task: Optional[asyncio.Task] = None

def is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in set(getattr(config, "ADMIN_USER_IDS", []))
    except Exception:
        return False

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
         InlineKeyboardButton("⚙️ Admin", callback_data="admin:help")]
    ])

def back_menu_kb(section: str, hours: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱ 1h", callback_data=f"{section}:1"),
         InlineKeyboardButton("🕓 24h", callback_data=f"{section}:24"),
         InlineKeyboardButton("📅 7d", callback_data=f"{section}:168")],
        [InlineKeyboardButton("🏠 Home", callback_data="home"),
         InlineKeyboardButton("🔁 Refresh", callback_data=f"{section}:{hours}")],
    ])

# ========================= BASIC COMMANDS =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    txt = (
        "👋 <b>Cloudflare Control Bot</b>\n"
        "Use the inline menu below, or commands:\n\n"
        "<b>Read</b>: /status /verify /zones /export &lt;hours&gt;\n"
        "<b>Manage</b> (admins): /ip_* /rule_* /dns_* /cache_purge /rl_* /toggle_bfm /toggle_sbfm\n"
        "<i>Tip: Tap 🌐 to switch zones.</i>"
    )
    await update.message.reply_text(txt, reply_markup=main_menu_kb(z.get("name")), parse_mode=ParseMode.HTML)

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

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    msg = await update.message.reply_text("⏳ <i>Fetching zone…</i>", parse_mode=ParseMode.HTML)
    zd = cf_api.get_zone_details(zone_id=z["id"])
    if not zd:
        await msg.edit_text("❌ <b>Failed to fetch zone details.</b>", parse_mode=ParseMode.HTML)
        return
    res = zd.get("result", {}) or {}
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

async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    hours = int(context.args[0]) if context.args else 24
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

async def zones_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = cf_api.list_zones(page=1, per_page=100)
    if not data:
        await update.message.reply_text("❌ Failed to list zones.", parse_mode=ParseMode.HTML); return
    zones = data.get("result") or []
    if not zones:
        await update.message.reply_text("ℹ️ No zones.", parse_mode=ParseMode.HTML); return
    await update.message.reply_text("🌐 <b>Select a zone</b>", parse_mode=ParseMode.HTML, reply_markup=_zones_keyboard(1, zones))

# ========================= CALLBACKS =========================
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.answer(cache_time=1)
    except BadRequest:
        pass
    data = (q.data or "").strip()
    z = get_active_zone(context)

    # ----- direct routes w/out numeric suffix
    if data == "home":
        await q.edit_message_text("🏠 <b>Home</b> — choose an option:", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(z.get("name"))); return
    if data == "refresh":
        data = "traffic:24"

    # admin menu callbacks (fix for admin:help)
    if data == "admin" or data.startswith("admin:"):
        await q.edit_message_text(_admin_help(), parse_mode=ParseMode.HTML,
                                  reply_markup=InlineKeyboardMarkup([
                                      [InlineKeyboardButton("🧱 Rate-limit", callback_data="rl:menu"),
                                       InlineKeyboardButton("🤖 BFM", callback_data="bfm")],
                                      [InlineKeyboardButton("🧭 DNS list", callback_data="dns:24"),
                                       InlineKeyboardButton("🏠 Home", callback_data="home")]
                                  ]))
        return

    # BFM quick toggles via callback
    if data.startswith("bfm:") or data.startswith("sbfm:"):
        if not is_admin(q.from_user.id):
            await q.edit_message_text("⛔ <b>Admins only.</b>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(z.get("name"))); return
        val = data.split(":")[1].lower() == "on"
        ok = cf_api.set_bfm(val, zone_id=z["id"]) if data.startswith("bfm:") else cf_api.set_sbfm(val, zone_id=z["id"])
        name = "Bot Fight Mode" if data.startswith("bfm:") else "Super BFM"
        await q.edit_message_text(f"{'✅' if ok else '❌'} {name} {'ON' if val else 'OFF'} · <code>{z['name'] or z['id']}</code>",
                                  parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(z.get("name")))
        return

    # Zone paging and switching
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

    # quick IP actions from security view
    if data.startswith("ipblock:") or data.startswith("ipchal:"):
        if not is_admin(q.from_user.id):
            await q.edit_message_text("⛔ <b>Admins only.</b>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(z.get("name"))); return
        ip = data.split(":", 1)[1]
        mode = "block" if data.startswith("ipblock:") else "challenge"
        target = "ip_range" if "/" in ip else "ip"
        ok = bool(cf_api.create_access_rule(mode=mode, target=target, value=ip, notes=f"quick-{mode}", zone_id=z["id"]))
        await q.edit_message_text(f"{'✅' if ok else '❌'} {mode.title()} {ip}", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(z.get("name")))
        return

    # parse generic section:hours
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
        await q.edit_message_text("🤷 <i>Unknown action</i>", parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(z.get("name")))

# ========================= RENDERERS =========================
async def render_traffic(q, context, hours: int):
    z = get_active_zone(context)
    await q.edit_message_text(f"⏳ <i>Loading traffic for <code>{z['name'] or z['id']}</code> (last {hours}h)…</i>", parse_mode=ParseMode.HTML)
    gql = cf_api.get_http_requests_fixed(hours=hours, zone_id=z["id"])
    if not gql:
        await q.edit_message_text("❌ <b>Failed to fetch traffic.</b>", parse_mode=ParseMode.HTML, reply_markup=back_menu_kb("traffic", hours)); return
    ts = timeseries_from_graphql(gql)
    if not ts:
        await q.edit_message_text("ℹ️ <i>No traffic data in window.</i>", parse_mode=ParseMode.HTML, reply_markup=back_menu_kb("traffic", hours)); return
    summary = format_timeseries_summary_for_html(ts)
    await q.edit_message_text(f"📊 <b>Traffic — last {hours}h</b> · <code>{z['name'] or z['id']}</code>\n{summary}", parse_mode=ParseMode.HTML, reply_markup=back_menu_kb("traffic", hours))

async def render_colos(q, context, hours: int):
    z = get_active_zone(context)
    await q.edit_message_text(f"⏳ <i>Loading colos for <code>{z['name'] or z['id']}</code> (last {hours}h)…</i>", parse_mode=ParseMode.HTML)
    gql = cf_api.get_analytics_by_colo(hours=hours, zone_id=z["id"])
    if not gql:
        await q.edit_message_text("❌ <b>Failed to fetch colos.</b>", parse_mode=ParseMode.HTML, reply_markup=back_menu_kb("colos", hours)); return
    rows = colos_from_graphql(gql, top_n=12)
    if not rows:
        await q.edit_message_text("ℹ️ <i>No colo data in window.</i>", parse_mode=ParseMode.HTML, reply_markup=back_menu_kb("colos", hours)); return
    table_html = format_colos_for_html(rows)
    await q.edit_message_text(f"🌍 <b>Top Colos — last {hours}h</b> · <code>{z['name'] or z['id']}</code>\n{table_html}", parse_mode=ParseMode.HTML, reply_markup=back_menu_kb("colos", hours))

async def render_security(q, context, hours: int):
    z = get_active_zone(context)
    await q.edit_message_text(f"⏳ <i>Loading security for <code>{z['name'] or z['id']}</code> (last {hours}h)…</i>", parse_mode=ParseMode.HTML)
    gql = cf_api.get_security_events(hours=hours, limit=200, zone_id=z["id"])
    if not gql:
        await q.edit_message_text("❌ <b>Failed to fetch security events.</b>", parse_mode=ParseMode.HTML, reply_markup=back_menu_kb("security", hours)); return
    html_events = format_security_for_html(gql, top_n=15)

    # Top mitigated IPs + quick actions (block/challenge)
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
    # call the /export logic and delete the inline message
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

# ========================= EXPORT =========================
async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, hours_override: Optional[int] = None):
    z = get_active_zone(context)
    hours = hours_override if hours_override is not None else (int(context.args[0]) if context.args else 24)
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
        "<b>Admin cheatsheet</b>\n"
        "• <code>/ip_list [mode]</code> — list access rules (whitelist|block|challenge|js_challenge)\n"
        "• <code>/ip_allow &lt;ip|cidr&gt; [notes...]</code>\n"
        "• <code>/ip_block &lt;ip|cidr&gt; [notes...]</code>\n"
        "• <code>/ip_delete &lt;id|ip|cidr&gt;</code>\n"
        "• <code>/rule_block &lt;expr&gt; -- &lt;desc&gt;</code>\n"
        "• <code>/rule_bypass_waf &lt;expr&gt; -- &lt;desc&gt;</code>\n"
        "• <code>/rules</code> — list firewall rules\n"
        "• <code>/dns_list [name]</code> | <code>/dns_add TYPE NAME CONTENT [TTL] [proxied]</code>\n"
        "• <code>/dns_upd ID field=value ...</code> | <code>/dns_del ID</code>\n"
        "• <code>/cache_purge all|&lt;url1&gt; [&lt;url2&gt;...]</code>\n"
        "• <code>/rl_list</code> | <code>/rl_add_path /api/ 100 60 600 block</code>\n"
        "• <code>/rl_add_asn 13335 200 60 600 block path=/wp-login.php</code> | <code>/rl_del ID</code>\n"
        "• <code>/toggle_bfm on|off</code>, <code>/toggle_sbfm on|off</code>\n"
        "• <code>/export &lt;hours&gt;</code> — CSV time series\n"
        "• <code>/zones</code> — zone picker\n"
    )

def _deny_if_not_admin(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else 0
        if not is_admin(uid):
            await update.message.reply_text("⛔ <b>Admins only.</b>", parse_mode=ParseMode.HTML)
            return
        return await func(update, context)
    return wrapper

# ========================= ADMIN COMMANDS =========================
# --- IP Access Rules
async def _ip_rule_common(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str, value: str, notes: str):
    z = get_active_zone(context)
    target = "ip_range" if "/" in value else "ip"
    resp = cf_api.create_access_rule(mode=mode, target=target, value=value, notes=notes, zone_id=z["id"])
    if not resp:
        await update.message.reply_text(f"❌ Failed to create access rule ({mode}).", parse_mode=ParseMode.HTML); return
    r = (resp.get("result") or {})
    await update.message.reply_text(
        f"✅ <b>{mode}</b> rule created\n<pre>ID        {r.get('id')}\nTarget    {target}\nValue     {value}\nNotes     {notes or '-'}</pre>",
        parse_mode=ParseMode.HTML
    )

@_deny_if_not_admin
async def ip_allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /ip_allow <ip|cidr> [notes]", parse_mode=ParseMode.HTML); return
    await _ip_rule_common(update, context, "whitelist", context.args[0], " ".join(context.args[1:]) if len(context.args) > 1 else "")

@_deny_if_not_admin
async def ip_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /ip_block <ip|cidr> [notes]", parse_mode=ParseMode.HTML); return
    await _ip_rule_common(update, context, "block", context.args[0], " ".join(context.args[1:]) if len(context.args) > 1 else "")

@_deny_if_not_admin
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
    await update.message.reply_text("🗑️ Deleted." if ok else "❌ Delete failed.", parse_mode=ParseMode.HTML)

@_deny_if_not_admin
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

@_deny_if_not_admin
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

@_deny_if_not_admin
async def rule_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if not context.args:
        await update.message.reply_text("Usage: /rule_block <expression> -- <description>", parse_mode=ParseMode.HTML); return
    expr, desc = _split_expr_desc(context.args)
    f = cf_api.create_filter(expr, desc or "rule_block", zone_id=z["id"])
    if not f or not (f.get("result") or []):
        await update.message.reply_text("❌ Filter create failed.", parse_mode=ParseMode.HTML); return
    filter_id = (f["result"][0] or {}).get("id")
    r = cf_api.create_firewall_rule(filter_id, action="block", description=desc or "rule_block", zone_id=z["id"])
    await update.message.reply_text("✅ Created blocking rule." if r else "❌ Rule create failed.", parse_mode=ParseMode.HTML)

@_deny_if_not_admin
async def rule_bypass_waf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if not context.args:
        await update.message.reply_text("Usage: /rule_bypass_waf <expression> -- <description>", parse_mode=ParseMode.HTML); return
    expr, desc = _split_expr_desc(context.args)
    f = cf_api.create_filter(expr, desc or "bypass_waf", zone_id=z["id"])
    if not f or not (f.get("result") or []):
        await update.message.reply_text("❌ Filter create failed.", parse_mode=ParseMode.HTML); return
    filter_id = (f["result"][0] or {}).get("id")
    r = cf_api.create_firewall_rule(filter_id, action="bypass", description=desc or "bypass_waf", products=["waf"], zone_id=z["id"])
    await update.message.reply_text("✅ Created WAF-bypass rule." if r else "❌ Rule create failed.", parse_mode=ParseMode.HTML)

# --- Cache purge
@_deny_if_not_admin
async def cache_purge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if not context.args:
        await update.message.reply_text("Usage: /cache_purge all|<url1> <url2> ...", parse_mode=ParseMode.HTML); return
    if len(context.args) == 1 and context.args[0].lower() == "all":
        ok = cf_api.purge_cache_everything(zone_id=z["id"])
        await update.message.reply_text("🧹 Purge everything: ✅" if ok else "🧹 Purge everything: ❌", parse_mode=ParseMode.HTML)
    else:
        ok = cf_api.purge_cache_files(context.args, zone_id=z["id"])
        await update.message.reply_text("🧹 Purge files: ✅" if ok else "🧹 Purge files: ❌", parse_mode=ParseMode.HTML)

# --- DNS CRUD
@_deny_if_not_admin
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

@_deny_if_not_admin
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
    await update.message.reply_text("✅ DNS record created." if r else "❌ Failed to create DNS record.", parse_mode=ParseMode.HTML)

@_deny_if_not_admin
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
    await update.message.reply_text("✅ DNS record updated." if r else "❌ DNS update failed.", parse_mode=ParseMode.HTML)

@_deny_if_not_admin
async def dns_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if not context.args:
        await update.message.reply_text("Usage: /dns_del <ID>", parse_mode=ParseMode.HTML); return
    ok = cf_api.delete_dns_record(context.args[0], zone_id=z["id"])
    await update.message.reply_text("🗑️ Deleted." if ok else "❌ Delete failed.", parse_mode=ParseMode.HTML)

# --- BFM toggles (commands)
@_deny_if_not_admin
async def toggle_bfm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if not context.args or context.args[0].lower() not in ("on","off"):
        await update.message.reply_text("Usage: /toggle_bfm on|off", parse_mode=ParseMode.HTML); return
    ok = cf_api.set_bfm(context.args[0].lower() == "on", zone_id=z["id"])
    await update.message.reply_text("🤖 Bot Fight Mode: ✅" if ok else "🤖 Bot Fight Mode: ❌", parse_mode=ParseMode.HTML)

@_deny_if_not_admin
async def toggle_sbfm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if not context.args or context.args[0].lower() not in ("on","off"):
        await update.message.reply_text("Usage: /toggle_sbfm on|off", parse_mode=ParseMode.HTML); return
    ok = cf_api.set_sbfm(context.args[0].lower() == "on", zone_id=z["id"])
    await update.message.reply_text("🛡️ Super BFM: ✅" if ok else "🛡️ Super BFM: ❌", parse_mode=ParseMode.HTML)

# --- RATE LIMIT BUILDER (commands)
def _parse_action(arg: Optional[str]) -> str:
    if not arg: return "block"
    a = arg.lower()
    return a if a in ("block","challenge") else "block"

@_deny_if_not_admin
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

@_deny_if_not_admin
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
    await update.message.reply_text("✅ Added rate limit." if r else "❌ Failed to add rule.", parse_mode=ParseMode.HTML)

@_deny_if_not_admin
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
    await update.message.reply_text("✅ Added rate limit." if r else "❌ Failed to add rule.", parse_mode=ParseMode.HTML)

@_deny_if_not_admin
async def rl_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    z = get_active_zone(context)
    if not context.args:
        await update.message.reply_text("Usage: /rl_del <rule_id>", parse_mode=ParseMode.HTML); return
    ok = cf_api.delete_ratelimit_rule(context.args[0], zone_id=z["id"])
    await update.message.reply_text("🗑️ Deleted." if ok else "❌ Delete failed.", parse_mode=ParseMode.HTML)

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
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Basic
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("verify", verify))
    app.add_handler(CommandHandler("zones", zones_cmd))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CommandHandler("whoami", whoami))

    # Admin write commands
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

    # Callbacks & errors
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_error_handler(handle_error)

    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
