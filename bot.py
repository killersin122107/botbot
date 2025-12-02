import os
import asyncio
import json
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from app.database import engine, create_db_and_tables
from app.models import Site, Check
from app.checker import background_checker
from sqlmodel import Session, select
import logging

load_dotenv()
TOKEN = os.environ.get("TELEGRAM_TOKEN")
SUBSCRIBERS_FILE = os.environ.get('SUBSCRIBERS_FILE', 'subscribers.json')

# Simple utility to persist subscribers
def load_subscribers():
    try:
        with open(SUBSCRIBERS_FILE, 'r') as f:
            data = json.load(f)
            return set(data.get('subscribers', []))
    except Exception:
        return set()

def save_subscribers(subs):
    with open(SUBSCRIBERS_FILE, 'w') as f:
        json.dump({"subscribers": list(subs)}, f)

subscribers = load_subscribers()

# DB util

def db_session():
    return Session(engine)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! I'm the Site Checker Bot. Commands: /sites /add <url> [name] [interval_sec] [traffic_bytes] [purpose] /delete <id> /checks <id> /recommend /subscribe /unsubscribe"
    )


async def cmd_sites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_session() as session:
        sites = session.exec(select(Site)).all()
    if not sites:
        await update.message.reply_text("No sites configured")
        return
    lines = []
    for s in sites:
        tb = f"{s.traffic_bytes} bytes" if s.traffic_bytes else "-"
        pr = s.purpose or '-'
        lines.append(f"{s.id}: {s.name or s.url} - interval {s.interval_seconds}s - traffic: {tb} - {pr}")
    await update.message.reply_text("\n".join(lines))


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /add <url> [name] [interval_sec]")
        return
    url = context.args[0]
    name = context.args[1] if len(context.args) > 1 else None
    interval = int(context.args[2]) if len(context.args) > 2 else 10
    traffic_bytes = None
    purpose = None
    if len(context.args) > 3:
        # third arg is traffic bytes (optional)
        raw = context.args[3].replace(',', '')
        try:
            traffic_bytes = int(raw)
        except Exception:
            traffic_bytes = None
    if len(context.args) > 4:
        purpose = ' '.join(context.args[4:])
    with db_session() as session:
        s = Site(url=url, name=name, interval_seconds=interval, traffic_bytes=traffic_bytes, purpose=purpose)
        session.add(s)
        session.commit()
        session.refresh(s)
    await update.message.reply_text(f"Added site {s.id}: {s.url}")


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /delete <id>")
        return
    site_id = int(context.args[0])
    with db_session() as session:
        s = session.get(Site, site_id)
        if not s:
            await update.message.reply_text("Site not found")
            return
        # delete checks
        checks_for_site = session.exec(select(Check).where(Check.site_id == site_id)).all()
        for c in checks_for_site:
            session.delete(c)
        session.delete(s)
        session.commit()
    await update.message.reply_text("Deleted site")


async def cmd_checks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /checks <site_id>")
        return
    site_id = int(context.args[0])
    with db_session() as session:
        cs = session.exec(select(Check).where(Check.site_id == site_id).order_by(Check.timestamp.desc()).limit(10)).all()
    if not cs:
        await update.message.reply_text("No checks for site")
        return
    lines = []
    for c in cs:
        t = c.timestamp.isoformat()
        if c.ok:
            lines.append(f"{t} OK {c.status_code} {int(c.response_time_ms or 0)} ms")
        else:
            lines.append(f"{t} FAIL {c.error}")
    await update.message.reply_text("\n".join(lines))


async def cmd_recommend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_session() as session:
        sites = session.exec(select(Site)).all()
        checks = session.exec(select(Check).order_by(Check.timestamp.desc()).limit(500)).all()
    if not sites:
        await update.message.reply_text("No sites configured")
        return
    # compute metrics similar to /recommendation
    metrics = {}
    for s in sites:
        site_checks = [c for c in checks if c.site_id == s.id]
        total = len(site_checks)
        ok_count = sum(1 for c in site_checks if c.ok)
        uptime = ok_count / total if total else 0
        latencies = [c.response_time_ms for c in site_checks if c.ok and c.response_time_ms]
        avg_latency = sum(latencies) / len(latencies) if latencies else None
        metrics[s.id] = {"site": s, "total": total, "uptime": uptime, "avg_latency": avg_latency}
    best = None
    best_score = -1
    for mid, m in metrics.items():
        uptime_score = m['uptime']
        lat_score = 1 - min((m['avg_latency'] or 2000) / 2000.0, 1.0)
        score = uptime_score * 0.6 + lat_score * 0.4
        if score > best_score:
            best_score = score
            best = m
    if not best:
        await update.message.reply_text("Not enough data to recommend")
        return
    s = best['site']
    await update.message.reply_text(f"Recommended: {s.id} - {s.name or s.url}\nScore: {best_score:.2f} (uptime {(best['uptime']*100):.0f}%, avg_latency {(best['avg_latency'] or 0):.0f} ms)")


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subscribers.add(chat_id)
    save_subscribers(subscribers)
    await update.message.reply_text("Subscribed to site alerts.")


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in subscribers:
        subscribers.remove(chat_id)
        save_subscribers(subscribers)
    await update.message.reply_text("Unsubscribed from site alerts.")


async def notify_on_fail(result):
    # when a check result is a fail, notify
    if not result.get('ok'):
        text = f"Site {result.get('site_id')} FAIL: {result.get('error') or 'no details'}"
        # send to subscribers
        for sid in list(subscribers):
            try:
                await app.bot.send_message(chat_id=sid, text=text)
            except Exception as e:
                logging.exception('error sending to subscriber')


async def on_startup_bot(app):
    # start checker in background
    app.checker_task = asyncio.create_task(background_checker(notify_on_fail))


async def on_shutdown_bot(app):
    if getattr(app, 'checker_task', None):
        app.checker_task.cancel()


if __name__ == '__main__':
    # ensure DB is created
    create_db_and_tables()
    if not TOKEN:
        print('Please set TELEGRAM_TOKEN in environment or .env file')
        exit(1)
    # Build application
    application = ApplicationBuilder().token(TOKEN).build()
    # Set a reference for sending messages
    app = application
    # add handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('sites', cmd_sites))
    application.add_handler(CommandHandler('add', cmd_add))
    application.add_handler(CommandHandler('delete', cmd_delete))
    application.add_handler(CommandHandler('checks', cmd_checks))
    application.add_handler(CommandHandler('recommend', cmd_recommend))
    application.add_handler(CommandHandler('subscribe', cmd_subscribe))
    application.add_handler(CommandHandler('unsubscribe', cmd_unsubscribe))

    # schedule background checker that notifies on failures
    application.create_task(background_checker(notify_on_fail))
    # make sure wheel data exists
    if not os.path.exists(DATA_WHEEL_FILE):
        save_wheel_data(load_wheel_data())

    print('Bot is starting...')
    application.run_polling()
    application.create_task(background_checker(notify_on_fail))

    print('Bot is starting...')
    application.run_polling()
        f"{history_display_15}\n--- **🎯 FULL PREDICTION BREAKDOWN 🎯** ---\n{prediction_message}\n\n--- **Statistical Breakdown** ---\nTotal Spins Logged: **{len(data['history'])}**.\nTheoretical Chance per Symbol: **12.5%**\n\n{analysis_msg_from_counts_wheel(data)}\n{url_status}"
    )
    keyboard = [[InlineKeyboardButton("View External Report", url=analysis_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(full_analysis_message, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)

# DB util

def db_session():
    return Session(engine)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! I'm the Site Checker Bot. Commands: /sites /add <url> [name] [interval_sec] [traffic_bytes] [purpose] /delete <id> /checks <id> /recommend /subscribe /unsubscribe"
    )


async def cmd_sites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_session() as session:
        sites = session.exec(select(Site)).all()
    if not sites:
        await update.message.reply_text("No sites configured")
        return
    lines = []
    for s in sites:
        tb = f"{s.traffic_bytes} bytes" if s.traffic_bytes else "-"
        pr = s.purpose or '-'
        lines.append(f"{s.id}: {s.name or s.url} - interval {s.interval_seconds}s - traffic: {tb} - {pr}")
    await update.message.reply_text("\n".join(lines))


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /add <url> [name] [interval_sec]")
        return
    url = context.args[0]
    name = context.args[1] if len(context.args) > 1 else None
    interval = int(context.args[2]) if len(context.args) > 2 else 10
    traffic_bytes = None
    purpose = None
    if len(context.args) > 3:
        # third arg is traffic bytes (optional)
        raw = context.args[3].replace(',', '')
        try:
            traffic_bytes = int(raw)
        except Exception:
            traffic_bytes = None
    if len(context.args) > 4:
        purpose = ' '.join(context.args[4:])
    with db_session() as session:
        s = Site(url=url, name=name, interval_seconds=interval, traffic_bytes=traffic_bytes, purpose=purpose)
        session.add(s)
        session.commit()
        session.refresh(s)
    await update.message.reply_text(f"Added site {s.id}: {s.url}")


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /delete <id>")
        return
    site_id = int(context.args[0])
    with db_session() as session:
        s = session.get(Site, site_id)
        if not s:
            await update.message.reply_text("Site not found")
            return
        # delete checks
        checks_for_site = session.exec(select(Check).where(Check.site_id == site_id)).all()
        for c in checks_for_site:
            session.delete(c)
        session.delete(s)
        session.commit()
    await update.message.reply_text("Deleted site")


async def cmd_checks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /checks <site_id>")
        return
    site_id = int(context.args[0])
    with db_session() as session:
        cs = session.exec(select(Check).where(Check.site_id == site_id).order_by(Check.timestamp.desc()).limit(10)).all()
    if not cs:
        await update.message.reply_text("No checks for site")
        return
    lines = []
    for c in cs:
        t = c.timestamp.isoformat()
        if c.ok:
            lines.append(f"{t} OK {c.status_code} {int(c.response_time_ms or 0)} ms")
        else:
            lines.append(f"{t} FAIL {c.error}")
    await update.message.reply_text("\n".join(lines))


async def cmd_recommend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_session() as session:
        sites = session.exec(select(Site)).all()
        checks = session.exec(select(Check).order_by(Check.timestamp.desc()).limit(500)).all()
    if not sites:
        await update.message.reply_text("No sites configured")
        return
    # compute metrics similar to /recommendation
    metrics = {}
    for s in sites:
        site_checks = [c for c in checks if c.site_id == s.id]
        total = len(site_checks)
        ok_count = sum(1 for c in site_checks if c.ok)
        uptime = ok_count / total if total else 0
        latencies = [c.response_time_ms for c in site_checks if c.ok and c.response_time_ms]
        avg_latency = sum(latencies) / len(latencies) if latencies else None
        metrics[s.id] = {"site": s, "total": total, "uptime": uptime, "avg_latency": avg_latency}
    best = None
    best_score = -1
    for mid, m in metrics.items():
        uptime_score = m['uptime']
        lat_score = 1 - min((m['avg_latency'] or 2000) / 2000.0, 1.0)
        score = uptime_score * 0.6 + lat_score * 0.4
        if score > best_score:
            best_score = score
            best = m
    if not best:
        await update.message.reply_text("Not enough data to recommend")
        return
    s = best['site']
    await update.message.reply_text(f"Recommended: {s.id} - {s.name or s.url}\nScore: {best_score:.2f} (uptime {(best['uptime']*100):.0f}%, avg_latency {(best['avg_latency'] or 0):.0f} ms)")


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subscribers.add(chat_id)
    save_subscribers(subscribers)
    await update.message.reply_text("Subscribed to site alerts.")


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in subscribers:
        subscribers.remove(chat_id)
        save_subscribers(subscribers)
    await update.message.reply_text("Unsubscribed from site alerts.")


async def notify_on_fail(result):
    # when a check result is a fail, notify
    if not result.get('ok'):
        text = f"Site {result.get('site_id')} FAIL: {result.get('error') or 'no details'}"
        # send to subscribers
        for sid in list(subscribers):
            try:
                await app.bot.send_message(chat_id=sid, text=text)
            except Exception as e:
                logging.exception('error sending to subscriber')


async def on_startup_bot(app):
    # start checker in background
    app.checker_task = asyncio.create_task(background_checker(notify_on_fail))


async def on_shutdown_bot(app):
    if getattr(app, 'checker_task', None):
        app.checker_task.cancel()


if __name__ == '__main__':
    # ensure DB is created
    create_db_and_tables()
    if not TOKEN:
        print('Please set TELEGRAM_TOKEN in environment or .env file')
        exit(1)
    # Build application
    application = ApplicationBuilder().token(TOKEN).build()
    # Set a reference for sending messages
    app = application
    # add handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('sites', cmd_sites))
    application.add_handler(CommandHandler('add', cmd_add))
    application.add_handler(CommandHandler('delete', cmd_delete))
    application.add_handler(CommandHandler('checks', cmd_checks))
    application.add_handler(CommandHandler('recommend', cmd_recommend))
    application.add_handler(CommandHandler('subscribe', cmd_subscribe))
    application.add_handler(CommandHandler('unsubscribe', cmd_unsubscribe))

    # schedule background checker that notifies on failures
    application.create_task(background_checker(notify_on_fail))

    print('Bot is starting...')
    application.run_polling()
