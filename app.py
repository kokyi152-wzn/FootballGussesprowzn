import os
import logging
import requests
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from pymongo import MongoClient

# ---------- Flask app ----------
app = Flask(__name__)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
        mongo_client = MongoClient(
            MONGO_URI,
            tls=True,
            tlsAllowInvalidCertificates=True,
            serverSelectionTimeoutMS=10000
        )
        mongo_client.admin.command('ping')
        db = mongo_client["football_bot"]
        predictions_col = db["predictions"]
        users_col = db["users"]
        logger.info("✅ MongoDB connected")
    except Exception as e:
        logger.warning(f"MongoDB connection failed: {e}")
        mongo_client = None
else:
    mongo_client = None

# ---------- Telegram Config ----------
TOKEN = os.environ.get("TELEGRAM_TOKEN")
BOT_USERNAME = os.environ.get("BOT_USERNAME")
ADMIN_IDS = [int(id.strip()) for id in os.environ.get("ADMIN_ID", "").split(",") if id.strip()] if os.environ.get("ADMIN_ID") else []
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

if not TOKEN or not BOT_USERNAME or not FOOTBALL_API_KEY:
    logger.error("Missing required environment variables!")
    exit(1)

# Telegram Bot object (synchronous)
bot = telegram.Bot(token=TOKEN)

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

# ========== COMMAND HANDLERS (Synchronous) ==========

def handle_start(update):
    try:
        user_id = update.effective_user.id
        logger.info(f"✅ /start from user: {user_id}")
        
        if mongo_client:
            users_col.update_one({"user_id": user_id}, {"$set": {"last_seen": datetime.now()}}, upsert=True)
        
        if is_admin(user_id):
            keyboard = [
                [InlineKeyboardButton("⚽ ယနေ့ပွဲစဉ်များ", callback_data="admin_today")],
                [InlineKeyboardButton("🏆 လိဂ်များစာရင်း", callback_data="admin_leagues")],
                [InlineKeyboardButton("📊 ခန့်မှန်းချက်မှတ်တမ်း", callback_data="admin_history")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            bot.send_message(
                chat_id=user_id,
                text="🤖 **Admin Panel**\n\nအောက်ပါခလုတ်များမှ ရွေးချယ်ပါ။",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        else:
            bot.send_message(
                chat_id=user_id,
                text=(
                    "⚽ **ဘောလုံးခန့်မှန်းချက် Bot**\n\n"
                    "Command များ:\n"
                    "🔹 /predict [အသင်း၁] [အသင်း၂] - ခန့်မှန်းချက်\n"
                    "🔹 /today - ယနေ့ပွဲစဉ်များ\n"
                    "🔹 /league [လိဂ်အမည်] - လိဂ်ပွဲစဉ်များ\n"
                    "🔹 /teams - အသင်းများစာရင်း\n"
                    "🔹 /leagues - လိဂ်များစာရင်း"
                ),
                parse_mode="Markdown"
            )
        logger.info(f"✅ /start completed for user {user_id}")
    except Exception as e:
        logger.exception(f"❌ Error in start handler: {e}")
        try:
            bot.send_message(chat_id=user_id, text="❌ တစ်ခုခုမှားနေတယ်။ နောက်မှထပ်ကြည့်ပါ။")
        except:
            pass

def handle_predict(update, args):
    try:
        user_id = update.effective_user.id
        if len(args) < 2:
            bot.send_message(
                chat_id=user_id,
                text="❌ /predict [အသင်း၁] [အသင်း၂]\nဥပမာ: /predict Arsenal Chelsea"
            )
            return
        
        home_team = ' '.join(args[:-1])
        away_team = args[-1]
        
        msg = bot.send_message(
            chat_id=user_id,
            text=f"⏳ `{home_team}` vs `{away_team}` ကို ခန့်မှန်းနေပါသည်...",
            parse_mode="Markdown"
        )
        
        prediction = calculate_prediction(home_team, away_team)
        
        if mongo_client:
            predictions_col.insert_one({
                "home_team": home_team,
                "away_team": away_team,
                "home_win": prediction['home_win'],
                "draw": prediction['draw'],
                "away_win": prediction['away_win'],
                "timestamp": datetime.now()
            })
        
        result_text = f"⚽ **{home_team}** vs **{away_team}**\n\n"
        result_text += f"🏠 **{home_team}** အနိုင်ရနိုင်ခြေ: {prediction['home_win']}%\n"
        result_text += f"🤝 သရေကျနိုင်ခြေ: {prediction['draw']}%\n"
        result_text += f"✈️ **{away_team}** အနိုင်ရနိုင်ခြေ: {prediction['away_win']}%\n\n"
        result_text += f"📊 {prediction['result']}"
        
        bot.edit_message_text(
            chat_id=user_id,
            message_id=msg.message_id,
            text=result_text,
            parse_mode="Markdown"
        )
        logger.info(f"✅ Prediction completed: {home_team} vs {away_team}")
    except Exception as e:
        logger.exception(f"❌ Error in predict handler: {e}")
        bot.send_message(chat_id=user_id, text="❌ ခန့်မှန်းချက် မအောင်မြင်ပါ။")

def handle_today(update):
    try:
        user_id = update.effective_user.id
        bot.send_message(chat_id=user_id, text="⏳ ယနေ့ပွဲစဉ်များကို ရှာဖွေနေပါသည်...")
        
        today_date = datetime.now().strftime('%Y-%m-%d')
        tomorrow_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        
        data = fetch_data(f"matches?dateFrom={today_date}&dateTo={tomorrow_date}")
        
        if not data or 'matches' not in data:
            bot.send_message(chat_id=user_id, text="❌ ယနေ့ပွဲစဉ်များ မတွေ့ပါ။")
            return
        
        matches = data['matches'][:10]
        if not matches:
            bot.send_message(chat_id=user_id, text="📅 ယနေ့ပွဲစဉ်များ မရှိပါ။")
            return
        
        text = "📅 **ယနေ့ပွဲစဉ်များ**\n\n"
        for match in matches:
            text += format_match(match) + "\n\n"
        
        bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
        logger.info("✅ Today matches sent")
    except Exception as e:
        logger.exception(f"❌ Error in today handler: {e}")
        bot.send_message(chat_id=user_id, text="❌ ပွဲစဉ်များ ရယူရာတွင် အမှားရှိပါသည်။")

def handle_league(update, args):
    try:
        user_id = update.effective_user.id
        if not args:
            bot.send_message(chat_id=user_id, text="❌ /league [လိဂ်အမည်]\nဥပမာ: /league premier league")
            return
        
        league_name = ' '.join(args)
        league_id = get_league_id(league_name)
        
        if not league_id:
            bot.send_message(chat_id=user_id, text=f"❌ `{league_name}` လိဂ်ကို မတွေ့ပါ။", parse_mode="Markdown")
            return
        
        bot.send_message(chat_id=user_id, text=f"⏳ `{league_name}` ပွဲစဉ်များကို ရှာဖွေနေပါသည်...", parse_mode="Markdown")
        
        data = fetch_data(f"competitions/{league_id}/matches")
        
        if not data or 'matches' not in data:
            bot.send_message(chat_id=user_id, text=f"❌ `{league_name}` ပွဲစဉ်များ မတွေ့ပါ။", parse_mode="Markdown")
            return
        
        matches = data['matches'][:10]
        if not matches:
            bot.send_message(chat_id=user_id, text=f"📅 `{league_name}` တွင် ပွဲစဉ်များ မရှိပါ။", parse_mode="Markdown")
            return
        
        text = f"⚽ **{league_name.upper()}**\n\n"
        for match in matches:
            text += format_match(match) + "\n\n"
        
        bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
        logger.info(f"✅ League matches sent: {league_name}")
    except Exception as e:
        logger.exception(f"❌ Error in league handler: {e}")
        bot.send_message(chat_id=user_id, text="❌ လိဂ်ပွဲစဉ်များ ရယူရာတွင် အမှားရှိပါသည်။")

def handle_teams(update):
    try:
        user_id = update.effective_user.id
        bot.send_message(chat_id=user_id, text="⏳ အသင်းများစာရင်းကို ရှာဖွေနေပါသည်...")
        
        data = fetch_data("teams")
        
        if not data or 'teams' not in data:
            bot.send_message(chat_id=user_id, text="❌ အသင်းများစာရင်း မတွေ့ပါ။")
            return
        
        teams_list = data['teams'][:20]
        text = "⚽ **အသင်းများစာရင်း**\n\n"
        for team in teams_list:
            text += f"• {team['name']}\n"
        
        bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
        logger.info("✅ Teams list sent")
    except Exception as e:
        logger.exception(f"❌ Error in teams handler: {e}")
        bot.send_message(chat_id=user_id, text="❌ အသင်းစာရင်း ရယူရာတွင် အမှားရှိပါသည်။")

def handle_leagues(update):
    try:
        user_id = update.effective_user.id
        bot.send_message(chat_id=user_id, text="⏳ လိဂ်များစာရင်းကို ရှာဖွေနေပါသည်...")
        
        data = fetch_data("competitions")
        
        if not data or 'competitions' not in data:
            bot.send_message(chat_id=user_id, text="❌ လိဂ်များစာရင်း မတွေ့ပါ။")
            return
        
        leagues_list = data['competitions'][:20]
        text = "⚽ **ရရှိနိုင်သော လိဂ်များ**\n\n"
        for comp in leagues_list:
            text += f"• {comp['name']} ({comp.get('code', 'N/A')})\n"
        
        bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
        logger.info("✅ Leagues list sent")
    except Exception as e:
        logger.exception(f"❌ Error in leagues handler: {e}")
        bot.send_message(chat_id=user_id, text="❌ လိဂ်စာရင်း ရယူရာတွင် အမှားရှိပါသည်။")

def handle_callback_query(update):
    try:
        query = update.callback_query
        user_id = query.from_user.id
        
        if not is_admin(user_id):
            bot.answer_callback_query(callback_query_id=query.id, text="⛔ Admin အတွက်သာ။")
            return
        
        data = query.data
        logger.info(f"Admin callback: {data}")
        
        if data == "admin_today":
            bot.answer_callback_query(callback_query_id=query.id)
            bot.send_message(chat_id=user_id, text="⏳ ယနေ့ပွဲစဉ်များကို ရှာဖွေနေပါသည်...")
            today_date = datetime.now().strftime('%Y-%m-%d')
            tomorrow_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
            data = fetch_data(f"matches?dateFrom={today_date}&dateTo={tomorrow_date}")
            if not data or 'matches' not in data:
                bot.send_message(chat_id=user_id, text="❌ ယနေ့ပွဲစဉ်များ မတွေ့ပါ။")
                return
            matches = data['matches'][:10]
            if not matches:
                bot.send_message(chat_id=user_id, text="📅 ယနေ့ပွဲစဉ်များ မရှိပါ။")
                return
            text = "📅 **ယနေ့ပွဲစဉ်များ**\n\n"
            for match in matches:
                text += format_match(match) + "\n\n"
            bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
            
        elif data == "admin_leagues":
            bot.answer_callback_query(callback_query_id=query.id)
            bot.send_message(chat_id=user_id, text="⏳ လိဂ်များစာရင်းကို ရှာဖွေနေပါသည်...")
            data = fetch_data("competitions")
            if not data or 'competitions' not in data:
                bot.send_message(chat_id=user_id, text="❌ လိဂ်များစာရင်း မတွေ့ပါ။")
                return
            leagues_list = data['competitions'][:20]
            text = "⚽ **ရရှိနိုင်သော လိဂ်များ**\n\n"
            for comp in leagues_list:
                text += f"• {comp['name']} ({comp.get('code', 'N/A')})\n"
            bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
            
        elif data == "admin_history":
            bot.answer_callback_query(callback_query_id=query.id)
            if not mongo_client:
                bot.send_message(chat_id=user_id, text="❌ MongoDB မရှိပါ။")
                return
            history = list(predictions_col.find().sort("timestamp", -1).limit(10))
            if not history:
                bot.send_message(chat_id=user_id, text="📊 ခန့်မှန်းချက်မှတ်တမ်း မရှိသေးပါ။")
                return
            text = "📊 **နောက်ဆုံး ခန့်မှန်းချက် ၁၀ ခု**\n\n"
            for i, h in enumerate(history, 1):
                dt = h.get('timestamp', datetime.now()).strftime('%Y-%m-%d %H:%M')
                text += f"{i}. {h.get('home_team', 'N/A')} vs {h.get('away_team', 'N/A')}\n"
                text += f"   🏠{h.get('home_win', 0)}% 🤝{h.get('draw', 0)}% ✈️{h.get('away_win', 0)}%\n"
                text += f"   📅 {dt}\n\n"
            bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.exception(f"❌ Error in callback handler: {e}")

# ========== WEBHOOK ROUTE ==========
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, bot)
        
        # Handle different update types
        if update.message:
            if update.message.text:
                text = update.message.text
                if text.startswith('/'):
                    parts = text.split()
                    command = parts[0].lower()
                    args = parts[1:]
                    
                    if command == '/start':
                        handle_start(update)
                    elif command == '/predict':
                        handle_predict(update, args)
                    elif command == '/today':
                        handle_today(update)
                    elif command == '/league':
                        handle_league(update, args)
                    elif command == '/teams':
                        handle_teams(update)
                    elif command == '/leagues':
                        handle_leagues(update)
                    else:
                        bot.send_message(chat_id=update.effective_user.id, text="❌ မသိသော command ပါ။")
        
        elif update.callback_query:
            handle_callback_query(update)
        
        return "ok", 200
    except Exception as e:
        logger.exception(f"Webhook error: {e}")
        return "error", 500

# ========== MAIN ==========
if __name__ == "__main__":
    logger.info("Starting bot in polling mode...")
    # For local testing, use polling with Updater
    from telegram.ext import Updater
    updater = Updater(token=TOKEN, use_context=True)
    # Add handlers... but for simplicity, just use webhook
    app.run(host="0.0.0.0", port=os.environ.get("PORT", 5000), debug=True)
else:
    # Gunicorn mode - webhook only
    logger.info("Running in Gunicorn mode with webhook...")
    # Set webhook
    if WEBHOOK_URL:
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/setWebhook",
                json={"url": WEBHOOK_URL}
            )
            logger.info(f"Webhook set: {response.json()}")
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")
    else:
        logger.warning("WEBHOOK_URL not set!")
    
    logger.info("✅ Bot is running with webhook (synchronous mode)")
