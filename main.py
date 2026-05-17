# =========================================================
# YODHA QUIZ BOT - FINAL UPDATED SAFE VERSION
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
# BOT CONFIG
# =========================================================

API_TOKEN = os.getenv("BOT_TOKEN")

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

        paths_to_check = [

            f"questions/{sub}.txt",

            f"questions/{sub.capitalize()}.txt",

            f"questions/{sub.upper()}.txt"
        ]

        target_path = None

        for p in paths_to_check:

            if os.path.exists(p):

                target_path = p

                break

        if not target_path:

            print(f"{sub} file not found")

            continue

        try:

            with open(
                target_path,
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

            print(f"{sub} loaded")

        except Exception as e:

            print("LOAD ERROR:", e)


load_questions()

# =========================================================
# START COMMAND
# =========================================================

@bot.message_handler(commands=['start'])
def start(message):

    bot.reply_to(
        message,
        "👋 Yodha Quiz Bot Online!\nUse /admin"
    )

# =========================================================
# POLL ANSWER HANDLER
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

            current_poll_data[
                "voter_count"
            ] += 1

            voted_users.add(uid)

            if (
                poll_answer.option_ids[0]
                ==
                current_poll_data[
                    "correct_id"
                ]
            ):

                user_scores[uid][
                    "correct"
                ] += 1

                user_scores[uid][
                    "score"
                ] += 1

            else:

                user_scores[uid][
                    "wrong"
                ] += 1

                user_scores[uid][
                    "score"
                ] -= 0.25

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
                "⚠️ Already Responded"
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

        current_poll_data[
            "skip_count"
        ] += 1

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

    if sub in question_bank:

        for ch in data['chapters']:

            all_pool.extend(
                question_bank[sub].get(
                    ch,
                    []
                )
            )

    if not all_pool:

        bot.send_message(
            chat_id,
            "❌ No Questions Found"
        )

        return

    used_hashes = (
        get_used_hashes_30_days()
    )

    fresh_pool = [

        q for q in all_pool

        if hashlib.md5(
            q.encode("utf-8")
        ).hexdigest()
        not in used_hashes
    ]

    if len(fresh_pool) >= data['count']:

        pool_to_use = fresh_pool

    else:

        pool_to_use = all_pool

    selected = random.sample(
        pool_to_use,
        min(
            data['count'],
            len(pool_to_use)
        )
    )

    total_q = len(selected)

    stop_markup = (
        types.InlineKeyboardMarkup()
    )

    stop_markup.add(
        types.InlineKeyboardButton(
            "🛑 STOP QUIZ",
            callback_data="stop_quiz"
        )
    )

    bot.send_message(
        GROUP_ID,
        "🚨 QUIZ CONTROL PANEL",
        reply_markup=stop_markup
    )

    intro = (
        f"📚 Subject: {sub.upper()}\n"
        f"🔢 Questions: {total_q}\n"
        f"⏱ Timer: {data['timer']} sec\n"
        f"👤 Limit: {data['max_answers']}\n"
        f"❌ Negative: -0.25\n\n"
        f"🚀 Starting in 10 seconds..."
    )

    intro_msg = bot.send_message(
        GROUP_ID,
        intro
    )

    time.sleep(10)

    try:

        bot.delete_message(
            GROUP_ID,
            intro_msg.message_id
        )

    except:
        pass

    # =====================================================
    # QUESTION LOOP
    # =====================================================

    for block in selected:

        if not quiz_active.get(
            GROUP_ID
        ):
            break

        try:

            lines = [

                l.strip()

                for l in block.split("\n")

                if l.strip()
            ]

            clean_lines = [

                l for l in lines

                if not l.lower().startswith("#")
            ]

            q_text = ""

            opts_raw = []

            ans_str = "A"

            for line in clean_lines:

                if line.lower().startswith(
                    "answer:"
                ):

                    ans_str = (
                        line.split(":")[-1]
                        .strip()
                        .upper()
                    )

                elif line.startswith((
                    "A.",
                    "B.",
                    "C.",
                    "D.",
                    "A)",
                    "B)",
                    "C)",
                    "D)"
                )):

                    opts_raw.append(line)

                else:

                    if q_text == "":
                        q_text = line
                    else:
                        q_text += "\n" + line

            if len(opts_raw) < 4:

                print("Skipped invalid question")

                continue

            options = []

            for opt in opts_raw[:4]:

                cleaned = (
                    opt[2:]
                    .strip(" .)")
                )

                cleaned = cleaned[:95]

                options.append(cleaned)

            q_text = q_text[:250]

            correct_idx = (
                ord(ans_str) - ord("A")
            )

            if (
                correct_idx < 0
                or
                correct_idx > 3
            ):
                correct_idx = 0

            mark_question_used(block)

            current_poll_data.update({

                "skip_count": 0,

                "voter_count": 0
            })

            skipped_this_q.clear()

            voted_users.clear()

            # SEND POLL

            poll_msg = bot.send_poll(

                GROUP_ID,

                question=q_text,

                options=options,

                type="quiz",

                correct_option_id=correct_idx,

                is_anonymous=False,

                open_period=data['timer']
            )

            print("Poll Sent")

            try:

                bot.send_message(

                    VERIFY_CHANNEL_ID,

                    f"✅ {q_text}\n\nAnswer: {ans_str}"
                )

            except Exception as e:

                print("VERIFY ERROR:", e)

            current_poll_data.update({

                "poll_id": poll_msg.poll.id,

                "correct_id": correct_idx
            })

            # SKIP BUTTON

            skip_markup = (
                types.InlineKeyboardMarkup()
            )

            skip_markup.add(
                types.InlineKeyboardButton(
                    "⏩ Skip",
                    callback_data=f"skip_{poll_msg.poll.id}"
                )
            )

            btn_msg = bot.send_message(
                GROUP_ID,
                "Tap below to skip",
                reply_markup=skip_markup
            )

            start_t = time.time()

            while (
                time.time() - start_t
                <
                data['timer']
            ):

                if not quiz_active.get(
                    GROUP_ID
                ):
                    break

                total_response = (

                    current_poll_data[
                        "voter_count"
                    ]

                    +

                    current_poll_data[
                        "skip_count"
                    ]
                )

                if (
                    total_response
                    >=
                    data['max_answers']
                ):
                    break

                time.sleep(0.5)

            try:

                bot.delete_message(
                    GROUP_ID,
                    btn_msg.message_id
                )

            except:
                pass

            try:

                bot.stop_poll(
                    GROUP_ID,
                    poll_msg.message_id
                )

            except:
                pass

            time.sleep(1.5)

        except Exception as e:

            print("QUESTION ERROR:", e)

            continue

    # =====================================================
    # SAVE SCORE
    # =====================================================

    save_session_to_db(user_scores)

    # =====================================================
    # LEADERBOARD
    # =====================================================

    report = (
        "📊 EXAM LEADERBOARD\n"
        "━━━━━━━━━━━━━━\n"
    )

    sorted_users = sorted(

        user_scores.values(),

        key=lambda x: x['score'],

        reverse=True
    )

    if not sorted_users:

        report += "\nNo Participants\n"

    for i, u in enumerate(
        sorted_users[:10],
        1
    ):

        attended = (
            u['correct']
            +
            u['wrong']
        )

        acc = (
            (
                u['correct']
                /
                attended
            ) * 100
            if attended > 0
            else 0
        )

        report += (

            f"\n{i}. {u['name']}\n"

            f"✅ Correct: {u['correct']}\n"

            f"❌ Wrong: {u['wrong']}\n"

            f"⏩ Skip: {u['skip']}\n"

            f"🎯 Accuracy: {acc:.1f}%\n"

            f"🏆 Score: {u['score']:.2f}\n"

            f"━━━━━━━━━━━━━━"
        )

    bot.send_message(
        GROUP_ID,
        report
    )

# =========================================================
# ADMIN PANEL
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

        user_step[
            m.chat.id
        ] = "subject"

        markup = (
            types.ReplyKeyboardMarkup(
                resize_keyboard=True
            )
        )

        markup.add(
            "Biology",
            "Physics",
            "Chemistry"
        )

        markup.add(
            "Math",
            "Reasoning"
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

    question_bank.clear()

    load_questions()

    if sub in question_bank:

        user_state[m.chat.id] = {

            "subject": sub
        }

        user_step[m.chat.id] = "mode"

        markup = (
            types.ReplyKeyboardMarkup(
                resize_keyboard=True
            )
        )

        markup.add(
            "Mix (All) 🎯",
            "Chapter-wise 📂"
        )

        bot.send_message(
            m.chat.id,
            "🎯 Select Mode",
            reply_markup=markup
        )

    else:

        bot.send_message(
            m.chat.id,
            "❌ No Questions Found"
        )

# =========================================================
# MODE
# =========================================================

@bot.message_handler(
    func=lambda m:
    user_step.get(m.chat.id)
    ==
    "mode"
)
def select_mode(m):

    sub = user_state[
        m.chat.id
    ]['subject']

    if "Mix" in m.text:

        user_state[
            m.chat.id
        ]['chapters'] = list(
            question_bank[sub].keys()
        )

        user_step[m.chat.id] = "count"

        bot.send_message(
            m.chat.id,
            "🔢 Enter Question Count",
            reply_markup=types.ReplyKeyboardRemove()
        )

    else:

        user_step[m.chat.id] = "chapter"

        selected_chapters[
            m.chat.id
        ] = set()

        markup = (
            types.ReplyKeyboardMarkup(
                resize_keyboard=True
            )
        )

        for ch in question_bank[sub]:

            markup.add(ch)

        markup.add("DONE ✅")

        bot.send_message(
            m.chat.id,
            "Select Chapters",
            reply_markup=markup
        )

# =========================================================
# CHAPTER
# =============================
