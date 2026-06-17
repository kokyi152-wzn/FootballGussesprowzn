import os
import asyncio
import logging
import requests
from datetime import datetime, timedelta
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def home():
    return "Football Prediction Bot is running!"

@app.route('/health')
def health():
    return "OK", 200

# ---------- Telegram Config ----------
TOKEN = os.environ.get("TELEGRAM_TOKEN")
BOT_USERNAME = os.environ.get("BOT_USERNAME")
ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_ID", "").split(",") if id.strip()] if os.environ.get("ADMIN_ID") else []
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

if not TOKEN or not BOT_USERNAME or not FOOTBALL_API_KEY:
    logger.error("Missing required environment variables!")
    exit(1)

if not WEBHOOK_URL:
    logger.error("WEBHOOK_URL not set!")
    exit(1)

BASE_URL = "https://api.football-data.org/v4"
HEADERS = {'X-Auth-Token': FOOTBALL_API_KEY}

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ---------- Helper Functions ----------
def fetch_data(endpoint):
    try:
        url = f"{BASE_URL}/{endpoint}"
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"API Error: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Request Error: {e}")
        return None

def get_league_id(league_name):
    leagues = {
        'premier league': 2021, 'laliga': 2014, 'bundesliga': 2002,
        'serie a': 2019, 'ligue 1': 2015, 'champions league': 2001,
        'europa league': 2000, 'eredivisie': 2003, 'primeira liga': 2017
    }
    return leagues.get(league_name.lower())

def format_match(match):
    home = match.get('homeTeam', {}).get('name', 'N/A')
    away = match.get('awayTeam', {}).get('name', 'N/A')
    date = match.get('utcDate', 'N/A')
    score_home = match.get('score', {}).get('fullTime', {}).get('home', '-')
    score_away = match.get('score', {}).get('fullTime', {}).get('away', '-')
    status = match.get('status', 'SCHEDULED')
    
    status_map = {
        'SCHEDULED': '⏳ စောင့်ဆိုင်းနေသည်',
        'LIVE': '🔴 တိုက်ရိုက်ထုတ်လွှင့်နေသည်',
        'IN_PLAY': '🔴 တိုက်ရိုက်ထုတ်လွှင့်နေသည်',
        'PAUSED': '⏸️ ခဏရပ်ထားသည်',
        'FINISHED': '✅ ပြီးဆုံးသည်',
        'POSTPONED': '📅 ရွှေ့ဆိုင်းထားသည်',
        'CANCELLED': '❌ ဖျက်သိမ်းထားသည်'
    }
    status_text = status_map.get(status, status)
    
    try:
        dt = datetime.fromisoformat(date.replace('Z', '+00:00'))
        date_str = dt.strftime('%Y-%m-%d %H:%M')
    except:
        date_str = date
    
    if status == 'FINISHED':
        return f"⚽ **{home}** {score_home} - {score_away} **{away}**\n📅 {date_str}\n📊 {status_text}"
    else:
        return f"⚽ **{home}** vs **{away}**\n📅 {date_str}\n📊 {status_text}"

def calculate_prediction(home_team, away_team):
    import random
    random.seed(home_team + away_team)
    home_win = random.randint(30, 60)
    draw = random.randint(20, 40)
    away_win = 100 - home_win - draw
    
    result = ""
    if home_win >= 70:
        result = f"🔥 **{home_team}** အနိုင်ရနိုင်ခြေ မြင့်မားနေပါသည်။"
    elif away_win >= 70:
        result = f"🔥 **{away_team}** အနိုင်ရနိုင်ခြေ မြင့်မားနေပါသည်။"
    elif draw >= 40:
        result = "🤝 သရေကျနိုင်ခြေ မြင့်မားနေပါသည်။"
    else:
        result = "⚖️ ပွဲချင်းပြိုင်နိုင်ခြေ မျှမျှတတ ရှိနေပါသည်။"
    
    return {'home_win': home_win, 'draw': draw, 'away_win': away_win, 'result': result}

# ---------- Telegram Command Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_admin(user_id):
        await show_admin_menu(update, context)
    else:
        await update.message.reply_text(
            "⚽ **ဘောလုံးခန့်မှန်းချက် Bot မှ ကြိုဆိုပါတယ်။**\n\n"
            "Command များ:\n"
            "🔹 /predict [အသင်း၁] [အသင်း၂] - ပွဲစဉ်ခန့်မှန်းချက်\n"
            "🔹 /today - ယနေ့ပွဲစဉ်များ\n"
            "🔹 /league [လိဂ်အမည်] - လိဂ်တစ်ခုရဲ့ ပွဲစဉ်များ\n"
            "🔹 /teams - အသင်းများစာရင်း\n"
            "🔹 /leagues - ရရှိနိုင်သော လိဂ်များ",
            parse_mode="Markdown"
        )

async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "❌ အသင်းနှစ်သင်းစလုံးရဲ့ နာမည်ကို ထည့်ပေးပါ။\n"
            "ဥပမာ - `/predict Arsenal Chelsea`"
        )
        return
    
    home_team = ' '.join(args[:-1])
    away_team = args[-1]
    
    msg = await update.message.reply_text(f"⏳ `{home_team}` vs `{away_team}` ကို ခန့်မှန်းနေပါသည်...", parse_mode="Markdown")
    
    prediction = calculate_prediction(home_team, away_team)
    
    result_text = f"⚽ **{home_team}** vs **{away_team}**\n\n"
    result_text += f"🏠 **{home_team}** အနိုင်ရနိုင်ခြေ: {prediction['home_win']}%\n"
    result_text += f"🤝 သရေကျနိုင်ခြေ: {prediction['draw']}%\n"
    result_text += f"✈️ **{away_team}** အနိုင်ရနိုင်ခြေ: {prediction['away_win']}%\n\n"
    result_text += f"📊 {prediction['result']}"
    
    await msg.edit_text(result_text, parse_mode="Markdown")

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ ယနေ့ပွဲစဉ်များကို ရှာဖွေနေပါသည်...")
    
    today_date = datetime.now().strftime('%Y-%m-%d')
    tomorrow_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    data = fetch_data(f"matches?dateFrom={today_date}&dateTo={tomorrow_date}")
    
    if not data or 'matches' not in data:
        await update.message.reply_text("❌ ယနေ့ပွဲစဉ်များ မတွေ့ပါ။")
        return
    
    matches = data['matches'][:10]
    if not matches:
        await update.message.reply_text("📅 ယနေ့ပွဲစဉ်များ မရှိပါ။")
        return
    
    text = "📅 **ယနေ့ပွဲစဉ်များ**\n\n"
    for match in matches:
        text += format_match(match) + "\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def league(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ လိဂ်အမည် ထည့်ပေးပါ။\n"
            "ဥပမာ - `/league premier league`"
        )
        return
    
    league_name = ' '.join(context.args)
    league_id = get_league_id(league_name)
    
    if not league_id:
        await update.message.reply_text(f"❌ `{league_name}` လိဂ်ကို မတွေ့ပါ။", parse_mode="Markdown")
        return
    
    await update.message.reply_text(f"⏳ `{league_name}` ပွဲစဉ်များကို ရှာဖွေနေပါသည်...", parse_mode="Markdown")
    
    data = fetch_data(f"competitions/{league_id}/matches")
    
    if not data or 'matches' not in data:
        await update.message.reply_text(f"❌ `{league_name}` ပွဲစဉ်များ မတွေ့ပါ။", parse_mode="Markdown")
        return
    
    matches = data['matches'][:10]
    if not matches:
        await update.message.reply_text(f"📅 `{league_name}` တွင် ပွဲစဉ်များ မရှိပါ။", parse_mode="Markdown")
        return
    
    text = f"⚽ **{league_name.upper()}**\n\n"
    for match in matches:
        text += format_match(match) + "\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def teams(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ အသင်းများစာရင်းကို ရှာဖွေနေပါသည်...")
    
    data = fetch_data("teams")
    
    if not data or 'teams' not in data:
        await update.message.reply_text("❌ အသင်းများစာရင်း မတွေ့ပါ။")
        return
    
    teams_list = data['teams'][:20]
    text = "⚽ **အသင်းများစာရင်း**\n\n"
    for team in teams_list:
        text += f"• {team['name']}\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def leagues(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ လိဂ်များစာရင်းကို ရှာဖွေနေပါသည်...")
    
    data = fetch_data("competitions")
    
    if not data or 'competitions' not in data:
        await update.message.reply_text("❌ လိဂ်များစာရင်း မတွေ့ပါ။")
        return
    
    leagues_list = data['competitions'][:20]
    text = "⚽ **ရရှိနိုင်သော လိဂ်များ**\n\n"
    for comp in leagues_list:
        text += f"• {comp['name']} ({comp.get('code', 'N/A')})\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ---------- Admin Menu ----------
async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("⚽ ယနေ့ပွဲစဉ်များ", callback_data="admin_today")],
        [InlineKeyboardButton("🏆 လိဂ်များ", callback_data="admin_leagues")],
    ]
    await update.message.reply_text(
        "🤖 **Admin Panel**\n\nအောက်ပါခလုတ်များမှ ရွေးချယ်ပါ။",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.edit_message_text("⛔ Admin အတွက်သာ။")
        return
    
    data = query.data
    if data == "admin_today":
        await today(update, context)
    elif data == "admin_leagues":
        await leagues(update, context)

# ---------- Build Application ----------
telegram_app = Application.builder().token(TOKEN).build()

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("predict", predict))
telegram_app.add_handler(CommandHandler("today", today))
telegram_app.add_handler(CommandHandler("league", league))
telegram_app.add_handler(CommandHandler("teams", teams))
telegram_app.add_handler(CommandHandler("leagues", leagues))
telegram_app.add_handler(CallbackQueryHandler(admin_callback, pattern="admin_"))

# ---------- Webhook ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, telegram_app.bot)
        asyncio.run_coroutine_threadsafe(telegram_app.process_update(update), loop)
        return "ok", 200
    except Exception as e:
        logger.exception("Webhook error")
        return "error", 500

def start_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

async def set_webhook():
    await telegram_app.bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook set to {WEBHOOK_URL}")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(telegram_app.initialize())
    loop.run_until_complete(set_webhook())
    import threading
    threading.Thread(target=start_flask, daemon=True).start()
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        loop.run_until_complete(telegram_app.shutdown())
