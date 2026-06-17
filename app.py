import os
import asyncio
import logging
import requests
from datetime import datetime, timedelta
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def home():
    return "Football Prediction Bot is running!"

@app.route('/health')
def health():
    return "OK", 200

# ---------- MongoDB ----------
MONGO_URI = os.environ.get("MONGO_URI")
if MONGO_URI:
    try:
        mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        mongo_client.admin.command('ping')
        db = mongo_client["football_bot"]
        predictions_col = db["predictions"]
        users_col = db["users"]
        logger.info("✅ MongoDB connected successfully")
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        mongo_client = None
        predictions_col = None
        users_col = None
else:
    logger.warning("MONGO_URI not set - running without database")
    mongo_client = None
    predictions_col = None
    users_col = None

def save_prediction(home_team, away_team, home_win, draw, away_win, user_id):
    """ခန့်မှန်းချက်ကို MongoDB မှာ သိမ်းမယ်"""
    if predictions_col is None:
        return
    try:
        predictions_col.insert_one({
            "home_team": home_team,
            "away_team": away_team,
            "home_win": home_win,
            "draw": draw,
            "away_win": away_win,
            "user_id": user_id,
            "created_at": datetime.now()
        })
    except Exception as e:
        logger.error(f"Save prediction error: {e}")

def get_user_stats(user_id):
    """သုံးစွဲသူရဲ့ ခန့်မှန်းချက်စာရင်းအင်းကို ရယူမယ်"""
    if predictions_col is None:
        return None
    try:
        count = predictions_col.count_documents({"user_id": user_id})
        return count
    except:
        return None

def get_all_stats():
    """စုစုပေါင်း ခန့်မှန်းချက်စာရင်းအင်း"""
    if predictions_col is None:
        return None
    try:
        total = predictions_col.count_documents({})
        return total
    except:
        return None

def add_user(user_id, username=None):
    """သုံးစွဲသူကို MongoDB မှာ သိမ်းမယ်"""
    if users_col is None:
        return
    try:
        if not users_col.find_one({"user_id": user_id}):
            users_col.insert_one({
                "user_id": user_id,
                "username": username,
                "first_seen": datetime.now()
            })
    except Exception as e:
        logger.error(f"Add user error: {e}")

# ---------- Telegram Config ----------
TOKEN = os.environ.get("TELEGRAM_TOKEN")
BOT_USERNAME = os.environ.get("BOT_USERNAME")
ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_ID", "").split(",") if id.strip()] if os.environ.get("ADMIN_ID") else []
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

if not TOKEN or not BOT_USERNAME or not FOOTBALL_API_KEY or not WEBHOOK_URL:
    logger.error("Missing required environment variables!")
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
    username = update.effective_user.username
    add_user(user_id, username)
    
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
            "🔹 /leagues - ရရှိနိုင်သော လိဂ်များ\n"
            "🔹 /mystats - သင်၏ ခန့်မှန်းချက်စာရင်းအင်း",
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
    user_id = update.effective_user.id
    
    msg = await update.message.reply_text(f"⏳ `{home_team}` vs `{away_team}` ကို ခန့်မှန်းနေပါသည်...", parse_mode="Markdown")
    
    prediction = calculate_prediction(home_team, away_team)
    
    # Save to MongoDB
    save_prediction(home_team, away_team, prediction['home_win'], prediction['draw'], prediction['away_win'], user_id)
    
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

async def mystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    count = get_user_stats(user_id)
    
    if count is None:
        await update.message.reply_text("📊 သင်၏ ခန့်မှန်းချက်စာရင်းအင်းကို ရယူနိုင်ခြင်း မရှိပါ။ MongoDB မချိတ်ဆက်ထားလို့ဖြစ်နိုင်ပါသည်။")
        return
    
    await update.message.reply_text(
        f"📊 **သင်၏ ခန့်မှန်းချက်စာရင်းအင်း**\n\n"
        f"🔹 စုစုပေါင်း ခန့်မှန်းချက်: {count} ကြိမ်\n\n"
        f"ဆက်လက်ခန့်မှန်းချင်ပါက `/predict` ကိုသုံးပါ။",
        parse_mode="Markdown"
    )

# ---------- Admin Menu ----------
async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_preds = get_all_stats()
    total_users = users_col.count_documents({}) if users_col else 0
    
    keyboard = [
        [InlineKeyboardButton("⚽ ယနေ့ပွဲစဉ်များ", callback_data="admin_today")],
        [InlineKeyboardButton("🏆 လိဂ်များ", callback_data="admin_leagues")],
        [InlineKeyboardButton("📊 စုစုပေါင်းစာရင်းအင်း", callback_data="admin_stats")],
    ]
    await update.message.reply_text(
        f"🤖 **Admin Panel**\n\n"
        f"👥 အသုံးပြုသူဦးရေ: {total_users}\n"
        f"📊 စုစုပေါင်းခန့်မှန်းချက်: {total_preds if total_preds else 0}\n\n"
        f"အောက်ပါခလုတ်များမှ ရွေးချယ်ပါ။",
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
    elif data == "admin_stats":
        total_preds = get_all_stats()
        total_users = users_col.count_documents({}) if users_col else 0
        await query.edit_message_text(
            f"📊 **စုစုပေါင်းစာရင်းအင်း**\n\n"
            f"👥 အသုံးပြုသူဦးရေ: {total_users}\n"
            f"📊 စုစုပေါင်းခန့်မှန်းချက်: {total_preds if total_preds else 0}",
            parse_mode="Markdown"
        )

# ---------- Build Application ----------
telegram_app = Application.builder().token(TOKEN).build()

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("predict", predict))
telegram_app.add_handler(CommandHandler("today", today))
telegram_app.add_handler(CommandHandler("league", league))
telegram_app.add_handler(CommandHandler("teams", teams))
telegram_app.add_handler(CommandHandler("leagues", leagues))
telegram_app.add_handler(CommandHandler("mystats", mystats))
telegram_app.add_handler(CallbackQueryHandler(admin_callback, pattern="admin_"))

# ---------- Webhook Route ----------
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

# ---------- Setup Webhook at Startup ----------
def setup_webhook():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(telegram_app.initialize())
        loop.run_until_complete(telegram_app.bot.set_webhook(WEBHOOK_URL))
        logger.info(f"✅ Webhook set to {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"Webhook setup failed: {e}")

# ---------- Flask Thread ----------
def start_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, use_reloader=False, debug=False)

# ---------- Main ----------
if __name__ == "__main__":
    setup_webhook()
    import threading
    threading.Thread(target=start_flask, daemon=True).start()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        loop.run_until_complete(telegram_app.shutdown())
else:
    # Gunicorn mode
    logger.info("Running in Gunicorn mode - setting up webhook...")
    setup_webhook()
