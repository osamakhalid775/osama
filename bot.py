import logging
import random
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, InlineQueryHandler, MessageHandler, filters
import os
from uuid import uuid4

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# المتغيرات البيئية
# ------------------------------------------------------------
TOKEN = os.environ.get("TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
if CHANNEL_ID:
    CHANNEL_ID = int(CHANNEL_ID)

# ------------------------------------------------------------
# قاعدة البيانات
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

def get_judgments(chat_id=None):
    conn = sqlite3.connect('roulette.db')
    c = conn.cursor()
    if chat_id:
        c.execute("SELECT text FROM judgments WHERE chat_id=? OR chat_id=0 ORDER BY RANDOM()", (chat_id,))
    else:
        c.execute("SELECT text FROM judgments WHERE chat_id=0 ORDER BY RANDOM()")
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
# دالة مساعدة: زر الرجوع
# ------------------------------------------------------------
def back_to_main_keyboard():
    keyboard = [[InlineKeyboardButton("🔝 القائمة الرئيسية", callback_data='back_to_main')]]
    return InlineKeyboardMarkup(keyboard)

# ------------------------------------------------------------
# معالج الأزرار
# ------------------------------------------------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id
    user = update.effective_user

    if data == 'back_to_main':
        keyboard = [
            [InlineKeyboardButton("🎲 روليت عادي", callback_data='roll')],
            [InlineKeyboardButton("⚖️ روليت أحكام", callback_data='judge')],
            [InlineKeyboardButton("📋 انضم للعبة", callback_data='join')],
            [InlineKeyboardButton("🏆 ترتيب اللاعبين", callback_data='leaderboard')],
            [InlineKeyboardButton("📊 إحصائيات", callback_data='stats')],
            [InlineKeyboardButton("📜 عرض الأحكام", callback_data='list_judgments')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🎉 **بوت الروليت الاحترافي**\nاختر ما تريد:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return

    if data == 'join':
        add_player(chat_id, user.id, user.username, user.first_name)
        await query.edit_message_text(
            f"✅ {mention(user.id, user.first_name)} انضم إلى اللعبة!",
            reply_markup=back_to_main_keyboard(),
            parse_mode="HTML"
        )

    elif data == 'roll':
        players = get_players(chat_id)
        if len(players) < 1:
            await query.edit_message_text(
                "⚠️ لا يوجد مشاركون بعد. استخدم /join أولاً.",
                reply_markup=back_to_main_keyboard()
            )
            return
        winner = random.choice(players)
        await query.edit_message_text(
            f"🎲 **الفائز:** {mention(winner['user_id'], winner['first_name'])} 🎉",
            reply_markup=back_to_main_keyboard(),
            parse_mode="HTML"
        )

    elif data == 'judge':
        players = get_players(chat_id)
        if len(players) < 2:
            await query.edit_message_text(
                "⚠️ نحتاج عضوين على الأقل لروليت الأحكام.",
                reply_markup=back_to_main_keyboard()
            )
            return
        p_list = players.copy()
        winner = random.choice(p_list)
        p_list.remove(winner)
        judge = random.choice(p_list)
        judgments = get_judgments(chat_id)
        judgment = random.choice(judgments)
        update_points_after_round(chat_id, winner['user_id'], judge['user_id'], judgment)

        report = (
            f"⚖️ **جولة جديدة في المجموعة!**\n\n"
            f"🏆 **الفائز:** {mention(winner['user_id'], winner['first_name'])}\n"
            f"👨‍⚖️ **الحكم:** {mention(judge['user_id'], judge['first_name'])}\n"
            f"📜 **الحكم:** {judgment}"
        )

        if CHANNEL_ID:
            try:
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=report,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"فشل إرسال التقرير إلى القناة: {e}")

        await query.edit_message_text(
            f"⚖️ **روليت الأحكام!**\n\n"
            f"🏆 **الفائز:** {mention(winner['user_id'], winner['first_name'])}\n"
            f"👨‍⚖️ **الحكم:** {mention(judge['user_id'], judge['first_name'])}\n"
            f"📜 **الحكم:** {judgment}",
            reply_markup=back_to_main_keyboard(),
            parse_mode="HTML"
        )

    elif data == 'leaderboard':
        lb = get_leaderboard(chat_id)
        if not lb:
            await query.edit_message_text(
                "🏆 لا يوجد لاعبين بعد.",
                reply_markup=back_to_main_keyboard()
            )
            return
        text = "🏆 **ترتيب اللاعبين:**\n"
        for i, row in enumerate(lb, 1):
            user_id, username, first_name, points, wins, judge_cnt = row
            name = first_name if first_name else (username if username else f"User{user_id}")
            text += f"{i}. {name} – {points} نقطة (فوز {wins}, تحكيم {judge_cnt})\n"
        await query.edit_message_text(
            text,
            reply_markup=back_to_main_keyboard(),
            parse_mode="Markdown"
        )

    elif data == 'stats':
        stats = get_group_stats(chat_id)
        await query.edit_message_text(
            f"📊 **إحصائيات المجموعة:**\n"
            f"عدد الجولات: {stats['total_rounds']}\n"
            f"أكثر حكم تكرر: {stats['top_judgment']}",
            reply_markup=back_to_main_keyboard(),
            parse_mode="Markdown"
        )

    elif data == 'list_judgments':
        judgments = get_judgments(chat_id)
        if not judgments:
            await query.edit_message_text(
                "📋 لا توجد أحكام بعد. أضف واحدة باستخدام /addjudgment",
                reply_markup=back_to_main_keyboard()
            )
            return
        text = "📋 **قائمة الأحكام:**\n"
        for i, j in enumerate(judgments[:20], 1):
            text += f"{i}. {j}\n"
        if len(judgments) > 20:
            text += "...(المزيد)"
        await query.edit_message_text(
            text,
            reply_markup=back_to_main_keyboard(),
            parse_mode="Markdown"
        )

# ------------------------------------------------------------
# معالج Inline Mode (محسّن مع صور مصغرة)
# ------------------------------------------------------------
async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query
    judgments = get_judgments()  # الأحكام الافتراضية فقط

    # قاعدة بيانات للصور المصغرة (thumbnails) - روابط لأيقونات إيموجي عالية الجودة
    thumb_urls = {
        "🎲": "https://cdn.jsdelivr.net/npm/emoji-datasource-twitter@7.0.1/img/twitter/64/1f3b2.png",  # لعبة النرد
        "⚖️": "https://cdn.jsdelivr.net/npm/emoji-datasource-twitter@7.0.1/img/twitter/64/2696.png",  # ميزان
        "📋": "https://cdn.jsdelivr.net/npm/emoji-datasource-twitter@7.0.1/img/twitter/64/1f4cb.png",  # لوحة
        "🏆": "https://cdn.jsdelivr.net/npm/emoji-datasource-twitter@7.0.1/img/twitter/64/1f3c6.png",  # كأس
        "📊": "https://cdn.jsdelivr.net/npm/emoji-datasource-twitter@7.0.1/img/twitter/64/1f4ca.png",  # رسم بياني
        "📜": "https://cdn.jsdelivr.net/npm/emoji-datasource-twitter@7.0.1/img/twitter/64/1f4dc.png",  # لفافة
        "❓": "https://cdn.jsdelivr.net/npm/emoji-datasource-twitter@7.0.1/img/twitter/64/2753.png",  # علامة استفهام
        "💬": "https://cdn.jsdelivr.net/npm/emoji-datasource-twitter@7.0.1/img/twitter/64/1f4ac.png",  # فقاعة كلام
        "🔍": "https://cdn.jsdelivr.net/npm/emoji-datasource-twitter@7.0.1/img/twitter/64/1f50d.png",  # عدسة مكبرة
    }

    # قائمة الأوامر الرئيسية بتصميم جذاب
    main_commands = [
        {
            "title": "🎲 روليت عادي",
            "desc": "اختيار فائز عشوائي من المسجلين",
            "cmd": "/roll",
            "emoji": "🎲"
        },
        {
            "title": "⚖️ روليت أحكام",
            "desc": "اختيار فائز + حكم + حكم عشوائي",
            "cmd": "/judge",
            "emoji": "⚖️"
        },
        {
            "title": "📋 انضم للعبة",
            "desc": "تسجيل اسمك في قائمة اللاعبين",
            "cmd": "/join",
            "emoji": "📋"
        },
        {
            "title": "🏆 ترتيب اللاعبين",
            "desc": "عرض أفضل 10 لاعبين حسب النقاط",
            "cmd": "/leaderboard",
            "emoji": "🏆"
        },
        {
            "title": "📊 إحصائيات المجموعة",
            "desc": "عدد الجولات وأكثر حكم تكرر",
            "cmd": "/stats",
            "emoji": "📊"
        },
        {
            "title": "📜 قائمة الأحكام",
            "desc": "عرض جميع الأحكام المتاحة",
            "cmd": "/list",
            "emoji": "📜"
        },
        {
            "title": "❓ مساعدة",
            "desc": "عرض معلومات عن البوت وكيفية الاستخدام",
            "cmd": "/start",
            "emoji": "❓"
        }
    ]

    # تحويل الأوامر إلى نتائج Inline مع صور مصغرة
    command_results = []
    for cmd in main_commands:
        result = InlineQueryResultArticle(
            id=str(uuid4()),
            title=cmd['title'],
            description=cmd['desc'],
            input_message_content=InputTextMessageContent(cmd['cmd']),
        )
        # إضافة صورة مصغرة إذا كان لدينا رابط لهذا الإيموجي
        if cmd['emoji'] in thumb_urls:
            result.thumbnail_url = thumb_urls[cmd['emoji']]
            result.thumbnail_width = 64
            result.thumbnail_height = 64
        command_results.append(result)

    if not query:
        # إذا لم يكتب المستخدم شيئًا، نعرض الأوامر فقط
        results = command_results
    else:
        # البحث في الأحكام
        filtered = [j for j in judgments if query.lower() in j.lower()]
        judgment_results = []
        for j in filtered[:10]:
            result = InlineQueryResultArticle(
                id=str(uuid4()),
                title=j[:50],
                description="انقر لإرسال هذا الحكم",
                input_message_content=InputTextMessageContent(j),
            )
            # إضافة صورة مصغرة للأحكام (فقاعة كلام)
            if "💬" in thumb_urls:
                result.thumbnail_url = thumb_urls["💬"]
                result.thumbnail_width = 64
                result.thumbnail_height = 64
            judgment_results.append(result)

        # دمج الأوامر مع نتائج البحث (الأوامر أولاً)
        results = command_results + judgment_results

        if not judgment_results:
            # إذا لم توجد نتائج بحث، نضيف رسالة توضيحية
            not_found = InlineQueryResultArticle(
                id=str(uuid4()),
                title=f"🔍 لا توجد نتائج لـ \"{query}\"",
                description="يمكنك إضافة حكم جديد باستخدام /addjudgment",
                input_message_content=InputTextMessageContent(
                    f"لم أجد حكماً يحتوي على: {query}\n\nيمكنك إضافة حكم جديد عبر:\n/addjudgment {query}"
                ),
            )
            if "🔍" in thumb_urls:
                not_found.thumbnail_url = thumb_urls["🔍"]
                not_found.thumbnail_width = 64
                not_found.thumbnail_height = 64
            results.append(not_found)

    await update.inline_query.answer(results, cache_time=1)

# ------------------------------------------------------------
# معالج الرسائل النصية في القنوات (للمشرفين فقط)
# ------------------------------------------------------------
async def channel_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # التأكد من أن التحديث هو channel_post
    if not update.channel_post:
        return
    
    chat = update.effective_chat
    user = update.effective_user  # قد يكون None إذا لم يكن البوت مشرفًا
    
    # إذا لم يكن هناك مستخدم (أي رسالة من القناة نفسها)، نتجاهل
    if not user:
        return
    
    # التحقق من أن المستخدم مشرف في القناة
    try:
        member = await chat.get_member(user.id)
        if member.status not in ["administrator", "creator"]:
            return
    except:
        return  # لا يمكن التحقق، نتجاهل
    
    text = update.channel_post.text
    if not text:
        return
    
    # معالجة الأوامر النصية
    if text.startswith('/join'):
        await context.bot.send_message(
            chat_id=chat.id,
            text="⚠️ لا يمكن استخدام أوامر اللعبة في القناة. يرجى استخدام المجموعة المخصصة للعب.",
            reply_to_message_id=update.channel_post.message_id
        )
    elif text.startswith('/roll') or text.startswith('/judge'):
        await context.bot.send_message(
            chat_id=chat.id,
            text="⚠️ هذه الأوامر لا تعمل في القناة. استخدم المجموعة المخصصة.",
            reply_to_message_id=update.channel_post.message_id
        )
    # يمكن إضافة معالجة لأوامر أخرى بنفس الطريقة

# ------------------------------------------------------------
# الأوامر النصية الأساسية
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
        await update.message.reply_text(
            "استخدم الأمر بالشكل: /addjudgment نص الحكم",
            reply_markup=back_to_main_keyboard()
        )
        return
    judgment_text = ' '.join(context.args)
    if add_judgment(chat_id, judgment_text, user.id):
        await update.message.reply_text(
            f"✅ تم إضافة الحكم: \"{judgment_text}\"",
            reply_markup=back_to_main_keyboard()
        )
    else:
        await update.message.reply_text(
            "⚠️ هذا الحكم موجود مسبقاً.",
            reply_markup=back_to_main_keyboard()
        )

async def leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    conn = sqlite3.connect('roulette.db')
    c = conn.cursor()
    c.execute("DELETE FROM players WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    conn.commit()
    conn.close()
    await update.message.reply_text(
        "👋 تمت إزالتك من قائمة اللاعبين.",
        reply_markup=back_to_main_keyboard()
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        await update.message.reply_text(
            "هذا الأمر يعمل فقط في المجموعات.",
            reply_markup=back_to_main_keyboard()
        )
        return
    member = await chat.get_member(user.id)
    if member.status not in ["administrator", "creator"]:
        await update.message.reply_text(
            "⚠️ أنت لست مشرفاً.",
            reply_markup=back_to_main_keyboard()
        )
        return
    conn = sqlite3.connect('roulette.db')
    c = conn.cursor()
    c.execute("DELETE FROM players WHERE chat_id=?", (chat.id,))
    conn.commit()
    conn.close()
    await update.message.reply_text(
        "✅ تم مسح قائمة اللاعبين.",
        reply_markup=back_to_main_keyboard()
    )

# الأوامر النصية الإضافية (مرآة للأزرار)
async def join_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    add_player(chat_id, user.id, user.username, user.first_name)
    await update.message.reply_text(
        f"✅ {mention(user.id, user.first_name)} انضم إلى اللعبة!",
        reply_markup=back_to_main_keyboard(),
        parse_mode="HTML"
    )

async def roll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    players = get_players(chat_id)
    if len(players) < 1:
        await update.message.reply_text(
            "⚠️ لا يوجد مشاركون بعد. استخدم /join أولاً.",
            reply_markup=back_to_main_keyboard()
        )
        return
    winner = random.choice(players)
    await update.message.reply_text(
        f"🎲 **الفائز:** {mention(winner['user_id'], winner['first_name'])} 🎉",
        reply_markup=back_to_main_keyboard(),
        parse_mode="HTML"
    )

async def judge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    players = get_players(chat_id)
    if len(players) < 2:
        await update.message.reply_text(
            "⚠️ نحتاج عضوين على الأقل لروليت الأحكام.",
            reply_markup=back_to_main_keyboard()
        )
        return
    p_list = players.copy()
    winner = random.choice(p_list)
    p_list.remove(winner)
    judge = random.choice(p_list)
    judgments = get_judgments(chat_id)
    judgment = random.choice(judgments)
    update_points_after_round(chat_id, winner['user_id'], judge['user_id'], judgment)

    report = (
        f"⚖️ **جولة جديدة في المجموعة!**\n\n"
        f"🏆 **الفائز:** {mention(winner['user_id'], winner['first_name'])}\n"
        f"👨‍⚖️ **الحكم:** {mention(judge['user_id'], judge['first_name'])}\n"
        f"📜 **الحكم:** {judgment}"
    )

    if CHANNEL_ID:
        try:
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=report,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"فشل إرسال التقرير إلى القناة: {e}")

    await update.message.reply_text(
        f"⚖️ **روليت الأحكام!**\n\n"
        f"🏆 **الفائز:** {mention(winner['user_id'], winner['first_name'])}\n"
        f"👨‍⚖️ **الحكم:** {mention(judge['user_id'], judge['first_name'])}\n"
        f"📜 **الحكم:** {judgment}",
        reply_markup=back_to_main_keyboard(),
        parse_mode="HTML"
    )

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    lb = get_leaderboard(chat_id)
    if not lb:
        await update.message.reply_text(
            "🏆 لا يوجد لاعبين بعد.",
            reply_markup=back_to_main_keyboard()
        )
        return
    text = "🏆 **ترتيب اللاعبين:**\n"
    for i, row in enumerate(lb, 1):
        user_id, username, first_name, points, wins, judge_cnt = row
        name = first_name if first_name else (username if username else f"User{user_id}")
        text += f"{i}. {name} – {points} نقطة (فوز {wins}, تحكيم {judge_cnt})\n"
    await update.message.reply_text(
        text,
        reply_markup=back_to_main_keyboard(),
        parse_mode="Markdown"
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    stats = get_group_stats(chat_id)
    await update.message.reply_text(
        f"📊 **إحصائيات المجموعة:**\n"
        f"عدد الجولات: {stats['total_rounds']}\n"
        f"أكثر حكم تكرر: {stats['top_judgment']}",
        reply_markup=back_to_main_keyboard(),
        parse_mode="Markdown"
    )

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    judgments = get_judgments(chat_id)
    if not judgments:
        await update.message.reply_text(
            "📋 لا توجد أحكام بعد. أضف واحدة باستخدام /addjudgment",
            reply_markup=back_to_main_keyboard()
        )
        return
    text = "📋 **قائمة الأحكام:**\n"
    for i, j in enumerate(judgments[:20], 1):
        text += f"{i}. {j}\n"
    if len(judgments) > 20:
        text += "...(المزيد)"
    await update.message.reply_text(
        text,
        reply_markup=back_to_main_keyboard(),
        parse_mode="Markdown"
    )

# ------------------------------------------------------------
# إدراج الأحكام الافتراضية
# ------------------------------------------------------------
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

    # الأوامر النصية الإضافية
    app.add_handler(CommandHandler("join", join_command))
    app.add_handler(CommandHandler("roll", roll_command))
    app.add_handler(CommandHandler("judge", judge_command))
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("list", list_command))

    # معالج الأزرار
    app.add_handler(CallbackQueryHandler(button_handler))

    # معالج Inline Mode
    app.add_handler(InlineQueryHandler(inline_query_handler))

    # معالج رسائل القناة (للمشرفين فقط)
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL & filters.TEXT, channel_message_handler))

    print("✅ البوت الاحترافي يعمل الآن...")
    app.run_polling()

if __name__ == "__main__":
    main()
