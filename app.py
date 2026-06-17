import os
import asyncio
import logging
import requests
import secrets
from datetime import datetime, timedelta
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from pymongo import MongoClient
from bson import ObjectId

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def home():
    return "Football Prediction Bot with MongoDB is running!"

@app.route('/health')
def health():
    return "OK", 200

# ---------- MongoDB Connection ----------
MONGO_URI = os.environ.get("MONGO_URI")
if not MONGO_URI:
    logger.error("MONGO_URI environment variable not set!")
    exit(1)

try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    mongo_client.admin.command('ping')
    logger.info("MongoDB connected successfully")
except Exception as e:
    logger.error(f"MongoDB connection failed: {e}")
    exit(1)

db = mongo_client["football_prediction_bot"]
users_collection = db["users"]
predictions_collection = db["predictions"]
matches_collection = db["matches"]
stats_collection = db["stats"]

# ---------- Database Helper Functions ----------
def add_user(user_id, username=None, first_name=None, last_name=None):
    """User ကို Database ထဲထည့်ခြင်း"""
    if not users_collection.find_one({"user_id": user_id}):
        users_collection.insert_one({
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "first_seen": datetime.now(),
            "last_active": datetime.now(),
            "predictions_count": 0,
            "is_admin": user_id in [int(id.strip()) for id in os.environ.get("ADMIN_ID", "").split(",") if id.strip()]
        })
        return True
    else:
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"last_active": datetime.now(), "username": username, "first_name": first_name}}
        )
        return False

def save_prediction(user_id, home_team, away_team, home_win, draw, away_win, result_text):
    """ခန့်မှန်းချက်ကို Database ထဲသိမ်းခြင်း"""
    pred_data = {
        "user_id": user_id,
        "home_team": home_team,
        "away_team": away_team,
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "result_text": result_text,
        "timestamp": datetime.now()
    }
    result = predictions_collection.insert_one(pred_data)
    
    # Update user's prediction count
    users_collection.update_one(
        {"user_id": user_id},
        {"$inc": {"predictions_count": 1}}
    )
    
    # Update total stats
    stats_collection.update_one(
        {"_id": "total_predictions"},
        {"$inc": {"count": 1}},
        upsert=True
    )
    
    return result.inserted_id

def get_user_stats(user_id):
    """User တစ်ယောက်ရဲ့ ခန့်မှန်းချက်စာရင်းအင်းကိုယူခြင်း"""
    total = predictions_collection.count_documents({"user_id": user_id})
    recent = predictions_collection.find({"user_id": user_id}).sort("timestamp", -1).limit(5)
    return total, list(recent)

def get_global_stats():
    """Global စာရင်းအင်းကိုယူခြင်း"""
    total_users = users_collection.count_documents({})
    total_preds = stats_collection.find_one({"_id": "total_predictions"})
    total_preds_count = total_preds["count"] if total_preds else 0
    return total_users, total_preds_count

def get_all_users():
    """User အားလုံးကိုယူခြင်း (Admin အတွက်)"""
    return list(users_collection.find({}, {"user_id": 1, "username": 1, "first_name": 1, "predictions_count": 1}))

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
    user = update.effective_user
    user_id = user.id
    
    # Add user to database
    add_user(user_id, user.username, user.first_name, user.last_name)
    
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
            "🔹 /mystats - ကျွန်ုပ်၏ ခန့်မှန်းချက်စာရင်းအင်း",
            parse_mode="Markdown"
        )

async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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
    
    # Save prediction to database
    result_text = f"🏠 {home_team} အနိုင် {prediction['home_win']}%\n🤝 သရေ {prediction['draw']}%\n✈️ {away_team} အနိုင် {prediction['away_win']}%\n📊 {prediction['result']}"
    save_prediction(user_id, home_team, away_team, prediction['home_win'], prediction['draw'], prediction['away_win'], result_text)
    
    output = f"⚽ **{home_team}** vs **{away_team}**\n\n"
    output += f"🏠 **{home_team}** အနိုင်ရနိုင်ခြေ: {prediction['home_win']}%\n"
    output += f"🤝 သရေကျနိုင်ခြေ: {prediction['draw']}%\n"
    output += f"✈️ **{away_team}** အနိုင်ရနိုင်ခြေ: {prediction['away_win']}%\n\n"
    output += f"📊 {prediction['result']}"
    
    await msg.edit_text(output, parse_mode="Markdown")

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

# ========== MY STATS ==========
async def mystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    total, recent = get_user_stats(user_id)
    
    text = f"📊 **ကျွန်ုပ်၏ ခန့်မှန်းချက်စာရင်းအင်း**\n\n"
    text += f"📝 စုစုပေါင်း ခန့်မှန်းချက်များ: {total}\n\n"
    
    if recent:
        text += "🕐 **မကြာသေးမီက ခန့်မှန်းချက်များ**\n"
        for pred in recent:
            text += f"• {pred['home_team']} vs {pred['away_team']}\n"
            text += f"  {pred['result_text'][:50]}...\n\n"
    else:
        text += "❌ ခန့်မှန်းချက် မရှိသေးပါ။"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ========== ADMIN COMMANDS ==========
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin အတွက်သာ။")
        return
    
    total_users, total_preds = get_global_stats()
    all_users = get_all_users()
    
    text = f"📊 **Admin စာရင်းအင်း**\n\n"
    text += f"👥 စုစုပေါင်း သုံးစွဲသူများ: {total_users}\n"
    text += f"📝 စုစုပေါင်း ခန့်မှန်းချက်များ: {total_preds}\n\n"
    text += "👤 **သုံးစွဲသူများစာရင်း**\n"
    for user in all_users[:10]:
        text += f"• {user.get('first_name', 'N/A')} (@{user.get('username', 'N/A')}) - {user.get('predictions_count', 0)} ကြိမ်\n"
    
    if len(all_users) > 10:
        text += f"\n... နှင့် နောက်ထပ် {len(all_users) - 10} ဦး"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin အတွက်သာ။")
        return
    
    all_users = get_all_users()
    text = "👤 **သုံးစွဲသူအားလုံး**\n\n"
    for user in all_users:
        text += f"• {user.get('first_name', 'N/A')} (@{user.get('username', 'N/A')}) - ID: {user['user_id']} - {user.get('predictions_count', 0)} ကြိမ်\n"
        if len(text) > 4000:
            text += "... စာရင်းရှည်နေပါသည်။"
            break
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ---------- Admin Menu ----------
async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("⚽ ယနေ့ပွဲစဉ်များ", callback_data="admin_today")],
        [InlineKeyboardButton("🏆 လိဂ်များ", callback_data="admin_leagues")],
        [InlineKeyboardButton("📊 စာရင်းအင်း", callback_data="admin_stats")],
        [InlineKeyboardButton("👤 သုံးစွဲသူများ", callback_data="admin_users")],
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
    elif data == "admin_stats":
        await admin_stats(update, context)
    elif data == "admin_users":
        await admin_users(update, context)

# ---------- Build Application ----------
telegram_app = Application.builder().token(TOKEN).build()

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("predict", predict))
telegram_app.add_handler(CommandHandler("today", today))
telegram_app.add_handler(CommandHandler("league", league))
telegram_app.add_handler(CommandHandler("teams", teams))
telegram_app.add_handler(CommandHandler("leagues", leagues))
telegram_app.add_handler(CommandHandler("mystats", mystats))
telegram_app.add_handler(CommandHandler("admin_stats", admin_stats))
telegram_app.add_handler(CommandHandler("admin_users", admin_users))
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
