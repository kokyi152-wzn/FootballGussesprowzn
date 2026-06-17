import os
import asyncio
import logging
import requests
from datetime import datetime, timedelta
from flask import Flask
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

# Football-Data.org API
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY")
BASE_URL = "https://api.football-data.org/v4"

HEADERS = {'X-Auth-Token': FOOTBALL_API_KEY}

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ---------- Helper Functions ----------
def fetch_data(endpoint):
    """Football-Data.org API ကနေ ဒေတာရယူခြင်း"""
    try:
        url = f"{BASE_URL}/{endpoint}"
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"API Error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Request Error: {e}")
        return None

def get_league_id(league_name):
    """လိဂ်အမည်ကို ရှာပြီး ID ပြန်ပေးခြင်း"""
    leagues = {
        'premier league': 2021,
        'laliga': 2014,
        'bundesliga': 2002,
        'serie a': 2019,
        'ligue 1': 2015,
        'champions league': 2001,
        'europa league': 2000,
        'eredivisie': 2003,
        'primeira liga': 2017,
        'belgian pro league': 2004,
        'scottish premiership': 2008,
        'swiss super league': 2009,
        'austrian bundesliga': 2010,
        'polish ekstraklasa': 2011,
        'turkish super lig': 2012,
        'greek super league': 2013,
    }
    return leagues.get(league_name.lower())

def get_team_id(team_name):
    """အသင်းအမည်ကို ရှာပြီး ID ပြန်ပေးခြင်း"""
    try:
        data = fetch_data("teams")
        if data and 'teams' in data:
            for team in data['teams']:
                if team_name.lower() in team['name'].lower():
                    return team['id']
        return None
    except:
        return None

def format_match(match):
    """ပွဲစဉ်တစ်ခုကိ် လှပစွာ ဖော်မတ်လုပ်ခြင်း"""
    home = match.get('homeTeam', {}).get('name', 'N/A')
    away = match.get('awayTeam', {}).get('name', 'N/A')
    date = match.get('utcDate', 'N/A')
    score_home = match.get('score', {}).get('fullTime', {}).get('home', '-')
    score_away = match.get('score', {}).get('fullTime', {}).get('away', '-')
    status = match.get('status', 'SCHEDULED')
    
    # ပွဲအခြေအနေ မြန်မာလို
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
    
    # ရက်စွဲကို ပြောင်းလဲခြင်း
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
    """ရိုးရှင်းတဲ့ ခန့်မှန်းချက် (အသင်းအမည်ပေါ်မူတည်)"""
    # ဒီနေရာမှာ ပိုမိုရှုပ်ထွေးတဲ့ Algorithm ထည့်နိုင်ပါတယ်
    # ဥပမာ - အသင်းအဆင့်၊ ပွဲကြိုစာရင်းအင်းတွေ စသဖြင့်
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
    
    return {
        'home_win': home_win,
        'draw': draw,
        'away_win': away_win,
        'result': result
    }

# ---------- Telegram Commands ----------

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_admin(user_id):
        await show_admin_menu(update, context)
    else:
        await update.message.reply_text(
            "⚽ **ဘောလုံးခန့်မှန်းချက် Bot မှ ကြိုဆိုပါတယ်။**\n\n"
            "ကျွန်ုပ်၏ Command များ:\n"
            "🔹 /predict [အသင်း၁] [အသင်း၂] - ပွဲစဉ်ခန့်မှန်းချက်\n"
            "🔹 /today - ယနေ့ပွဲစဉ်များ\n"
            "🔹 /league [လိဂ်အမည်] - လိဂ်တစ်ခုရဲ့ ပွဲစဉ်များ\n"
            "🔹 /teams - အသင်းများစာရင်း\n"
            "🔹 /leagues - ရရှိနိုင်သော လိဂ်များ\n"
            "🔹 /stats - ခန့်မှန်းချက်စာရင်းအင်း\n\n"
            "လိဂ်အမည်များ:\n"
            "`premier league`, `laliga`, `bundesliga`, `serie a`, `ligue 1`, `champions league`, `europa league`",
            parse_mode="Markdown"
        )

# /predict
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

# /today - ယနေ့ပွဲစဉ်များ
async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ ယနေ့ပွဲစဉ်များကို ရှာဖွေနေပါသည်...")
    
    today_date = datetime.now().strftime('%Y-%m-%d')
    tomorrow_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    data = fetch_data(f"matches?dateFrom={today_date}&dateTo={tomorrow_date}")
    
    if not data or 'matches' not in data:
        await update.message.reply_text("❌ ယနေ့ပွဲစဉ်များ မတွေ့ပါ။")
        return
    
    matches = data['matches']
    if not matches:
        await update.message.reply_text("📅 ယနေ့ပွဲစဉ်များ မရှိပါ။")
        return
    
    text = "📅 **ယနေ့ပွဲစဉ်များ**\n\n"
    for match in matches[:10]:
        text += format_match(match) + "\n\n"
    
    if len(matches) > 10:
        text += f"... နှင့် နောက်ထပ် {len(matches) - 10} ပွဲ"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# /league - လိဂ်တစ်ခုရဲ့ ပွဲစဉ်များ
async def league(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ လိဂ်အမည် ထည့်ပေးပါ။\n"
            "ဥပမာ - `/league premier league`\n\n"
            "ရရှိနိုင်သော လိဂ်များ:\n"
            "`premier league`, `laliga`, `bundesliga`, `serie a`, `ligue 1`, `champions league`"
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

# /teams - အသင်းများစာရင်း
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
    
    if len(data['teams']) > 20:
        text += f"\n... နှင့် နောက်ထပ် {len(data['teams']) - 20} သင်း"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# /leagues - ရရှိနိုင်သော လိဂ်များ
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

# /stats - ခန့်မှန်းချက်စာရင်းအင်း
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 **ခန့်မှန်းချက် စာရင်းအင်း**\n\n"
        "Bot ကို စတင်အသုံးပြုဆဲဖြစ်သောကြောင့် စာရင်းအင်းများ စုဆောင်းနေပါသည်။\n\n"
        "ခန့်မှန်းချက် တိကျမှုကို ပွဲစဉ်များပြီးဆုံးချိန်တွင် အပ်ဒိတ်လုပ်ပါမည်။\n"
        "မကြာမီ ပိုမိုကောင်းမွန်သော စာရင်းအင်းများကို ရရှိပါလိမ့်မည်။"
    )

# ---------- Admin Menu ----------
async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("⚽ ယနေ့ပွဲစဉ်များ", callback_data="admin_today")],
        [InlineKeyboardButton("🏆 လိဂ်များ", callback_data="admin_leagues")],
        [InlineKeyboardButton("📊 စာရင်းအင်း", callback_data="admin_stats")],
        [InlineKeyboardButton("🔄 ဒေတာအပ်ဒိတ်", callback_data="admin_update")],
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
        await stats(update, context)
    elif data == "admin_update":
        await query.edit_message_text("🔄 ဒေတာများ ပြန်လည်အပ်ဒိတ်လုပ်နေပါသည်...")
        # ဒေတာအပ်ဒိတ် လုပ်ဆောင်ချက် ထည့်နိုင်ပါတယ်

# ---------- Main ----------
def main():
    application = Application.builder().token(TOKEN).build()
    
    # Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("predict", predict))
    application.add_handler(CommandHandler("today", today))
    application.add_handler(CommandHandler("league", league))
    application.add_handler(CommandHandler("teams", teams))
    application.add_handler(CommandHandler("leagues", leagues))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="admin_"))
    
    logger.info("Bot started polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
