# =========================================================
# YODHA QUIZ BOT - FINAL SAFE VERSION
# =========================================================

import telebot
from telebot import types
import os
import random
import time
import threading
import sqlite3
import hashlib
from datetime import datetime, timedelta

# =========================================================
# TOKEN CHECK
# =========================================================

API_TOKEN = os.getenv("BOT_TOKEN")

if not API_TOKEN:
    print("❌ BOT_TOKEN not found!")
    exit()

# =========================================================
# BOT CONFIG
# =========================================================

bot = telebot.TeleBot(
    API_TOKEN,
    threaded=True,
    num_threads=25
)

ADMIN_KEY = "Eshu2005aru"

GROUP_ID = -1003746627836
VERIFY_CHANNEL_ID = -1003786586918

DB_NAME = "quiz_pro_data.db"

# =========================================================
# DATABASE
# =========================================================

def init_db():

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS history (
            question_hash TEXT PRIMARY KEY,
            last_used TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS all_time_stats (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            correct INTEGER DEFAULT 0,
            wrong INTEGER DEFAULT 0,
            skip INTEGER DEFAULT 0,
            score REAL DEFAULT 0.0
        )
    """)

    conn.commit()
    conn.close()


def mark_question_used(question_text):

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    q_hash = hashlib.md5(
        question_text.encode("utf-8")
    ).hexdigest()

    c.execute(
        """
        INSERT OR REPLACE INTO history
        (question_hash, last_used)
        VALUES (?, ?)
        """,
        (
            q_hash,
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )
    )

    conn.commit()
    conn.close()


def get_used_hashes_30_days():

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    thirty_days_ago = (
        datetime.now() - timedelta(days=30)
    ).strftime("%Y-%m-%d %H:%M:%S")

    c.execute(
        """
        SELECT question_hash
        FROM history
        WHERE last_used > ?
        """,
        (thirty_days_ago,)
    )

    used = {
        row[0]
        for row in c.fetchall()
    }

    conn.close()

    return used


def save_session_to_db(session_scores):

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    for uid, stats in session_scores.items():

        c.execute(
            """
            INSERT INTO all_time_stats
            (user_id, name, correct, wrong, skip, score)

            VALUES (?, ?, ?, ?, ?, ?)

            ON CONFLICT(user_id)
            DO UPDATE SET

            name = excluded.name,

            correct = all_time_stats.correct + excluded.correct,

            wrong = all_time_stats.wrong + excluded.wrong,

            skip = all_time_stats.skip + excluded.skip,

            score = all_time_stats.score + excluded.score
            """,
            (
                uid,
                stats['name'],
                stats['correct'],
                stats['wrong'],
                stats['skip'],
                stats['score']
            )
        )

    conn.commit()
    conn.close()


init_db()

# =========================================================
# GLOBAL VARIABLES
# =========================================================

question_bank = {}

user_state = {}

user_step = {}

selected_chapters = {}

user_scores = {}

quiz_active = {}

voted_users = set()

skipped_this_q = set()

current_poll_data = {
    "poll_id": None,
    "correct_id": None,
    "skip_count": 0,
    "voter_count": 0
}

# =========================================================
# LOAD QUESTIONS
# =========================================================

def load_questions():

    subjects = [
        "biology",
        "physics",
        "chemistry",
        "math",
        "reasoning"
    ]

    for sub in subjects:

        file_path = f"questions/{sub}.txt"

        if not os.path.exists(file_path):

            print(f"❌ {sub} file not found")

            continue

        try:

            with open(
                file_path,
                "r",
                encoding="utf-8"
            ) as f:

                text = f.read()

            current_chapter = "General"

            blocks = [

                b.strip()

                for b in text.replace(
                    "\r\n",
                    "\n"
                ).split("\n\n")

                if b.strip()
            ]

            for block in blocks:

                lines = [

                    l.strip()

                    for l in block.split("\n")

                    if l.strip()
                ]

                for line in lines:

                    if line.lower().startswith(
                        "#chapter"
                    ):

                        current_chapter = (
                            line.split(":")[-1]
                            .strip()
                        )

                if any(
                    "answer:" in l.lower()
                    for l in lines
                ):

                    question_bank.setdefault(
                        sub,
                        {}
                    ).setdefault(
                        current_chapter,
                        []
                    ).append(block)

            print(f"✅ {sub} loaded")

        except Exception as e:

            print("LOAD ERROR:", e)


load_questions()

# =========================================================
# START
# =========================================================

@bot.message_handler(commands=['start'])
def start(message):

    bot.reply_to(
        message,
        "👋 Yodha Quiz Bot Online!\nUse /admin"
    )

# =========================================================
# POLL ANSWERS
# =========================================================

@bot.poll_answer_handler()
def handle_poll_answer(poll_answer):

    uid = poll_answer.user.id

    if uid not in user_scores:

        user_scores[uid] = {
            "name": poll_answer.user.first_name,
            "correct": 0,
            "wrong": 0,
            "skip": 0,
            "score": 0.0
        }

    if str(poll_answer.poll_id) == str(
        current_poll_data["poll_id"]
    ):

        if (
            uid not in skipped_this_q
            and
            uid not in voted_users
        ):

            current_poll_data["voter_count"] += 1

            voted_users.add(uid)

            if (
                poll_answer.option_ids[0]
                ==
                current_poll_data["correct_id"]
            ):

                user_scores[uid]["correct"] += 1
                user_scores[uid]["score"] += 1

            else:

                user_scores[uid]["wrong"] += 1
                user_scores[uid]["score"] -= 0.25

# =========================================================
# CALLBACKS
# =========================================================

@bot.callback_query_handler(
    func=lambda call: True
)
def handle_callbacks(call):

    uid = call.from_user.id

    if call.data.startswith("skip_"):

        target_pid = (
            call.data.split("_")[1]
        )

        if target_pid != str(
            current_poll_data["poll_id"]
        ):

            return bot.answer_callback_query(
                call.id,
                "❌ Expired"
            )

        if (
            uid in voted_users
            or
            uid in skipped_this_q
        ):

            return bot.answer_callback_query(
                call.id,
                "⚠️ Already responded"
            )

        if uid not in user_scores:

            user_scores[uid] = {
                "name": call.from_user.first_name,
                "correct": 0,
                "wrong": 0,
                "skip": 0,
                "score": 0.0
            }

        skipped_this_q.add(uid)

        user_scores[uid]["skip"] += 1

        current_poll_data["skip_count"] += 1

        bot.answer_callback_query(
            call.id,
            "⏩ Skipped"
        )

    elif call.data == "stop_quiz":

        quiz_active[GROUP_ID] = False

        bot.answer_callback_query(
            call.id,
            "🛑 Quiz Stopping"
        )

# =========================================================
# QUIZ ENGINE
# =========================================================

def run_quiz(chat_id):

    global current_poll_data

    user_scores.clear()

    data = user_state[chat_id]

    sub = data['subject']

    all_pool = []

    for ch in data['chapters']:

        all_pool.extend(
            question_bank[sub].get(ch, [])
        )

    if not all_pool:

        bot.send_message(
            chat_id,
            "❌ No Questions Found"
        )

        return

    selected = random.sample(
        all_pool,
        min(
            data['count'],
            len(all_pool)
        )
    )

    total_q = len(selected)

    bot.send_message(
        GROUP_ID,
        f"🚀 Quiz Starting\n\n"
        f"📚 Subject: {sub.upper()}\n"
        f"🔢 Questions: {total_q}\n"
        f"⏱ Timer: {data['timer']} sec"
    )

    time.sleep(5)

    for block in selected:

        try:

            lines = [

                l.strip()

                for l in block.split("\n")

                if l.strip()
            ]

            q_text = ""
            options = []
            ans_str = "A"

            for line in lines:

                if line.lower().startswith("answer:"):

                    ans_str = (
                        line.split(":")[-1]
                        .strip()
                        .upper()
                    )

                elif line.startswith((
                    "A.",
                    "B.",
                    "C.",
                    "D."
                )):

                    options.append(
                        line[2:].strip()[:95]
                    )

                elif not line.startswith("#"):

                    if q_text == "":
                        q_text = line
                    else:
                        q_text += "\n" + line

            q_text = q_text[:250]

            if len(options) < 4:
                continue

            correct_idx = (
                ord(ans_str) - ord("A")
            )

            poll_msg = bot.send_poll(

                GROUP_ID,

                question=q_text,

                options=options,

                type="quiz",

                correct_option_id=correct_idx,

                is_anonymous=False,

                open_period=data['timer']
            )

            current_poll_data.update({
                "poll_id": poll_msg.poll.id,
                "correct_id": correct_idx,
                "skip_count": 0,
                "voter_count": 0
            })

            time.sleep(data['timer'] + 2)

        except Exception as e:

            print("QUESTION ERROR:", e)

    save_session_to_db(user_scores)

    report = "📊 LEADERBOARD\n\n"

    sorted_users = sorted(
        user_scores.values(),
        key=lambda x: x['score'],
        reverse=True
    )

    for i, u in enumerate(
        sorted_users,
        1
    ):

        report += (
            f"{i}. {u['name']}\n"
            f"🏆 {u['score']:.2f}\n\n"
        )

    bot.send_message(
        GROUP_ID,
        report
    )

# =========================================================
# ADMIN
# =========================================================

@bot.message_handler(commands=['admin'])
def admin(message):

    user_step[
        message.chat.id
    ] = "admin_key"

    bot.send_message(
        message.chat.id,
        "🔑 Enter Admin Key"
    )


@bot.message_handler(
    func=lambda m:
    user_step.get(m.chat.id)
    ==
    "admin_key"
)
def check_key(m):

    if m.text == ADMIN_KEY:

        user_step[m.chat.id] = "subject"

        markup = (
            types.ReplyKeyboardMarkup(
                resize_keyboard=True
            )
        )

        markup.add(
            "Biology",
            "Physics"
        )

        bot.send_message(
            m.chat.id,
            "✅ Access Granted",
            reply_markup=markup
        )

    else:

        bot.send_message(
            m.chat.id,
            "❌ Wrong Key"
        )

# =========================================================
# SUBJECT
# =========================================================

@bot.message_handler(
    func=lambda m:
    user_step.get(m.chat.id)
    ==
    "subject"
)
def select_subject(m):

    sub = m.text.lower()

    if sub not in question_bank:

        return bot.send_message(
            m.chat.id,
            "❌ Subject Not Found"
        )

    user_state[m.chat.id] = {
        "subject": sub,
        "chapters": list(
            question_bank[sub].keys()
        )
    }

    user_step[m.chat.id] = "count"

    bot.send_message(
        m.chat.id,
        "🔢 Enter Question Count",
        reply_markup=types.ReplyKeyboardRemove()
    )

# =========================================================
# COUNT
# =========================================================

@bot.message_handler(
    func=lambda m:
    user_step.get(m.chat.id)
    ==
    "count"
)
def question_count(m):

    try:

        user_state[
            m.chat.id
        ]['count'] = int(m.text)

        user_step[m.chat.id] = "timer"

        bot.send_message(
            m.chat.id,
            "⏱ Enter Timer"
        )

    except:

        bot.send_message(
            m.chat.id,
            "❌ Invalid Number"
        )

# =========================================================
# TIMER
# =========================================================

@bot.message_handler(
    func=lambda m:
    user_step.get(m.chat.id)
    ==
    "timer"
)
def timer(m):

    try:

        user_state[
            m.chat.id
        ]['timer'] = int(m.text)

        user_step[m.chat.id] = "ready"

        markup = (
            types.ReplyKeyboardMarkup(
                resize_keyboard=True
            )
        )

        markup.add("START QUIZ 🚀")

        bot.send_message(
            m.chat.id,
            "✅ Ready",
            reply_markup=markup
        )

    except:

        bot.send_message(
            m.chat.id,
            "❌ Invalid Number"
        )

# =========================================================
# START QUIZ
# =========================================================

@bot.message_handler(
    func=lambda m:
    m.text == "START QUIZ 🚀"
)
def start_quiz(message):

    try:

        threading.Thread(
            target=run_quiz,
            args=(message.chat.id,),
            daemon=True
        ).start()

        bot.send_message(
            message.chat.id,
            "🚀 Quiz Started"
        )

    except Exception as e:

        print("START ERROR:", e)

# =========================================================
# SAFE POLLING
# =========================================================

def start_bot():

    while True:

        try:

            print("🤖 Bot Running")
            print("📡 Starting Polling")

            bot.infinity_polling(
                skip_pending=True,
                timeout=60,
                long_polling_timeout=60
            )

        except Exception as e:

            print("POLLING ERROR:", e)

            time.sleep(5)

# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    start_bot()
