import logging
import random
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import os  # لإضافة المتغيرات البيئية

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# المتغيرات البيئية (سيتم تعبئتها من لوحة التحكم)
# ------------------------------------------------------------
TOKEN = os.environ.get("TOKEN")  # سيتم جلب التوكن من المتغيرات البيئية
CHANNEL_ID = os.environ.get("CHANNEL_ID")  # سيتم جلب معرف القناة من المتغيرات البيئية
if CHANNEL_ID:
    CHANNEL_ID = int(CHANNEL_ID)  # تحويل النص إلى رقم

# ------------------------------------------------------------
# قاعدة البيانات (SQLite)
# ------------------------------------------------------------
def init_db():
    conn = sqlite3.connect('roulette.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS judgments
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  text TEXT UNIQUE,
                  added_by INTEGER,
                  chat_id INTEGER,
                  date TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS players
                 (chat_id INTEGER,
                  user_id INTEGER,
                  username TEXT,
                  first_name TEXT,
                  points INTEGER DEFAULT 0,
                  wins INTEGER DEFAULT 0,
                  judge_count INTEGER DEFAULT 0,
                  PRIMARY KEY (chat_id, user_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS rounds
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  chat_id INTEGER,
                  winner_id INTEGER,
                  judge_id INTEGER,
                  judgment TEXT,
                  date TIMESTAMP)''')
    conn.commit()
    conn.close()

def add_judgment(chat_id, text, added_by):
    conn = sqlite3.connect('roulette.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO judgments (text, added_by, chat_id, date) VALUES (?,?,?,?)",
                  (text, added_by, chat_id, datetime.now()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_judgments(chat_id):
    conn = sqlite3.connect('roulette.db')
    c = conn.cursor()
    c.execute("SELECT text FROM judgments WHERE chat_id=? OR chat_id=0 ORDER BY RANDOM()", (chat_id,))
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows] if rows else ["لا توجد أحكام بعد، أضف واحدة باستخدام /addjudgment"]

def add_player(chat_id, user_id, username, first_name):
    conn = sqlite3.connect('roulette.db')
    c = conn.cursor()
    c.execute('''INSERT OR IGNORE INTO players (chat_id, user_id, username, first_name)
                 VALUES (?,?,?,?)''', (chat_id, user_id, username, first_name))
    c.execute('''UPDATE players SET username=?, first_name=? WHERE chat_id=? AND user_id=?''',
              (username, first_name, chat_id, user_id))
    conn.commit()
    conn.close()

def get_players(chat_id):
    conn = sqlite3.connect('roulette.db')
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name FROM players WHERE chat_id=?", (chat_id,))
    rows = c.fetchall()
    conn.close()
    return [{"user_id": r[0], "username": r[1], "first_name": r[2]} for r in rows]

def update_points_after_round(chat_id, winner_id, judge_id, judgment_text):
    conn = sqlite3.connect('roulette.db')
    c = conn.cursor()
    c.execute("UPDATE players SET points = points + 1, wins = wins + 1 WHERE chat_id=? AND user_id=?", (chat_id, winner_id))
    c.execute("UPDATE players SET points = points + 1, judge_count = judge_count + 1 WHERE chat_id=? AND user_id=?", (chat_id, judge_id))
    c.execute("INSERT INTO rounds (chat_id, winner_id, judge_id, judgment, date) VALUES (?,?,?,?,?)",
              (chat_id, winner_id, judge_id, judgment_text, datetime.now()))
    conn.commit()
    conn.close()

def get_leaderboard(chat_id, limit=10):
    conn = sqlite3.connect('roulette.db')
    c = conn.cursor()
    c.execute('''SELECT user_id, username, first_name, points, wins, judge_count
                 FROM players WHERE chat_id=? ORDER BY points DESC LIMIT ?''', (chat_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows

def get_group_stats(chat_id):
    conn = sqlite3.connect('roulette.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM rounds WHERE chat_id=?", (chat_id,))
    total_rounds = c.fetchone()[0]
    c.execute('''SELECT judgment, COUNT(*) as cnt FROM rounds WHERE chat_id=? 
                 GROUP BY judgment ORDER BY cnt DESC LIMIT 1''', (chat_id,))
    top_judgment = c.fetchone()
    conn.close()
    return {"total_rounds": total_rounds, "top_judgment": top_judgment[0] if top_judgment else "لا يوجد"}

def mention(user_id, name="مستخدم"):
    return f'<a href="tg://user?id={user_id}">{name}</a>'

# ------------------------------------------------------------
# معالج الأزرار
# ------------------------------------------------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id
    user = update.effective_user

    if data == 'join':
        add_player(chat_id, user.id, user.username, user.first_name)
        await query.edit_message_text(f"✅ {mention(user.id, user.first_name)} انضم إلى اللعبة!", parse_mode="HTML")

    elif data == 'roll':
        players = get_players(chat_id)
        if len(players) < 1:
            await query.edit_message_text("⚠️ لا يوجد مشاركون بعد. استخدم /join أولاً.")
            return
        winner = random.choice(players)
        await query.edit_message_text(
            f"🎲 **الفائز:** {mention(winner['user_id'], winner['first_name'])} 🎉",
            parse_mode="HTML"
        )

    elif data == 'judge':
        players = get_players(chat_id)
        if len(players) < 2:
            await query.edit_message_text("⚠️ نحتاج عضوين على الأقل لروليت الأحكام.")
            return
        p_list = players.copy()
        winner = random.choice(p_list)
        p_list.remove(winner)
        judge = random.choice(p_list)
        judgments = get_judgments(chat_id)
        judgment = random.choice(judgments)
        update_points_after_round(chat_id, winner['user_id'], judge['user_id'], judgment)

        # إنشاء نص التقرير
        report = (
            f"⚖️ **جولة جديدة في المجموعة!**\n\n"
            f"🏆 **الفائز:** {mention(winner['user_id'], winner['first_name'])}\n"
            f"👨‍⚖️ **الحكم:** {mention(judge['user_id'], judge['first_name'])}\n"
            f"📜 **الحكم:** {judgment}"
        )

        # إرسال التقرير إلى القناة إذا تم تحديد معرف قناة
        if CHANNEL_ID:
            try:
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=report,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"فشل إرسال التقرير إلى القناة: {e}")

        # الرد في المجموعة
        await query.edit_message_text(
            f"⚖️ **روليت الأحكام!**\n\n"
            f"🏆 **الفائز:** {mention(winner['user_id'], winner['first_name'])}\n"
            f"👨‍⚖️ **الحكم:** {mention(judge['user_id'], judge['first_name'])}\n"
            f"📜 **الحكم:** {judgment}",
            parse_mode="HTML"
        )

    elif data == 'leaderboard':
        lb = get_leaderboard(chat_id)
        if not lb:
            await query.edit_message_text("🏆 لا يوجد لاعبين بعد.")
            return
        text = "🏆 **ترتيب اللاعبين:**\n"
        for i, row in enumerate(lb, 1):
            user_id, username, first_name, points, wins, judge_cnt = row
            name = first_name if first_name else (username if username else f"User{user_id}")
            text += f"{i}. {name} – {points} نقطة (فوز {wins}, تحكيم {judge_cnt})\n"
        await query.edit_message_text(text, parse_mode="Markdown")

    elif data == 'stats':
        stats = get_group_stats(chat_id)
        await query.edit_message_text(
            f"📊 **إحصائيات المجموعة:**\n"
            f"عدد الجولات: {stats['total_rounds']}\n"
            f"أكثر حكم تكرر: {stats['top_judgment']}",
            parse_mode="Markdown"
        )

    elif data == 'list_judgments':
        judgments = get_judgments(chat_id)
        if not judgments:
            await query.edit_message_text("📋 لا توجد أحكام بعد. أضف واحدة باستخدام /addjudgment")
            return
        text = "📋 **قائمة الأحكام:**\n"
        for i, j in enumerate(judgments[:20], 1):
            text += f"{i}. {j}\n"
        if len(judgments) > 20:
            text += "...(المزيد)"
        await query.edit_message_text(text, parse_mode="Markdown")

# ------------------------------------------------------------
# الأوامر النصية
# ------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎲 روليت عادي", callback_data='roll')],
        [InlineKeyboardButton("⚖️ روليت أحكام", callback_data='judge')],
        [InlineKeyboardButton("📋 انضم للعبة", callback_data='join')],
        [InlineKeyboardButton("🏆 ترتيب اللاعبين", callback_data='leaderboard')],
        [InlineKeyboardButton("📊 إحصائيات", callback_data='stats')],
        [InlineKeyboardButton("📜 عرض الأحكام", callback_data='list_judgments')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🎉 **بوت الروليت الاحترافي**\nاختر ما تريد:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def add_judgment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("استخدم الأمر بالشكل: /addjudgment نص الحكم")
        return
    judgment_text = ' '.join(context.args)
    if add_judgment(chat_id, judgment_text, user.id):
        await update.message.reply_text(f"✅ تم إضافة الحكم: \"{judgment_text}\"")
    else:
        await update.message.reply_text("⚠️ هذا الحكم موجود مسبقاً.")

async def leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    conn = sqlite3.connect('roulette.db')
    c = conn.cursor()
    c.execute("DELETE FROM players WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"👋 تمت إزالتك من قائمة اللاعبين.")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        await update.message.reply_text("هذا الأمر يعمل فقط في المجموعات.")
        return
    member = await chat.get_member(user.id)
    if member.status not in ["administrator", "creator"]:
        await update.message.reply_text("⚠️ أنت لست مشرفاً.")
        return
    conn = sqlite3.connect('roulette.db')
    c = conn.cursor()
    c.execute("DELETE FROM players WHERE chat_id=?", (chat.id,))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ تم مسح قائمة اللاعبين.")

def insert_default_judgments():
    conn = sqlite3.connect('roulette.db')
    c = conn.cursor()
    defaults = [
        "🎤 الحكم يطلب من الفائز أن يغني أغنية",
        "😂 الحكم يأمر الفائز بإلقاء نكتة",
        "💪 الحكم يتحدى الفائز في تمرين رياضي (10 ضغط)",
        "📸 الحكم يلتقط صورة سيلفي مع الفائز",
        "🍻 الحكم يقدم مشروبًا للفائز (افتراضي)",
        "🤝 الحكم يصافح الفائز بحرارة",
        "👏 الحكم يصفق للفائز ويطلب من الجميع التصفيق",
        "🎁 الحكم يعطي الفائز هدية رمزية",
        "📝 الحكم يطلب من الفائز كتابة قصيدة قصيرة",
        "🕺 الحكم والفائز يرقصان معًا لمدة 10 ثوانٍ"
    ]
    for text in defaults:
        try:
            c.execute("INSERT OR IGNORE INTO judgments (text, added_by, chat_id, date) VALUES (?,0,0,?)", (text, datetime.now()))
        except:
            pass
    conn.commit()
    conn.close()

# ------------------------------------------------------------
# التشغيل الرئيسي
# ------------------------------------------------------------
def main():
    init_db()
    insert_default_judgments()

    app = Application.builder().token(TOKEN).build()

    # الأوامر النصية
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addjudgment", add_judgment_cmd))
    app.add_handler(CommandHandler("leave", leave))
    app.add_handler(CommandHandler("reset", reset))

    # معالج الأزرار
    app.add_handler(CallbackQueryHandler(button_handler))

    print("✅ البوت الاحترافي يعمل الآن...")
    app.run_polling()

if __name__ == "__main__":
    main()