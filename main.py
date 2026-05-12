import telebot
from telebot import types
import os
import random
import time
import threading
import sqlite3
import hashlib
from datetime import datetime, timedelta

# Initialize Bot
API_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(API_TOKEN, threaded=True, num_threads=25)

ADMIN_KEY = "Eshu2005aru"
GROUP_ID = -1003746627836 
VERIFY_CHANNEL_ID = -1003786586918 # Replace with your Private Channel ID

# ===== 1. DATABASE SYSTEM =====
DB_NAME = "quiz_pro_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (question_hash TEXT PRIMARY KEY, last_used TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS all_time_stats 
                 (user_id INTEGER PRIMARY KEY, name TEXT, 
                  correct INTEGER DEFAULT 0, wrong INTEGER DEFAULT 0, 
                  skip INTEGER DEFAULT 0, score REAL DEFAULT 0.0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS weak_points 
                 (user_id INTEGER, chapter TEXT, wrong_count INTEGER DEFAULT 0,
                  last_update DATE, PRIMARY KEY (user_id, chapter))''')
    conn.commit()
    conn.close()

def save_session_to_db(session_scores, chapters_map):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    for uid, stats in session_scores.items():
        c.execute('''INSERT INTO all_time_stats (user_id, name, correct, wrong, skip, score)
                     VALUES (?, ?, ?, ?, ?, ?)
                     ON CONFLICT(user_id) DO UPDATE SET
                     name = excluded.name,
                     correct = all_time_stats.correct + excluded.correct,
                     wrong = all_time_stats.wrong + excluded.wrong,
                     skip = all_time_stats.skip + excluded.skip,
                     score = all_time_stats.score + excluded.score''', 
                  (uid, stats['name'], stats['correct'], stats['wrong'], stats['skip'], stats['score']))
        if uid in chapters_map:
            for chapter, wrong_count in chapters_map[uid].items():
                c.execute('''INSERT INTO weak_points (user_id, chapter, wrong_count, last_update) 
                             VALUES (?, ?, ?, ?) 
                             ON CONFLICT(user_id, chapter) DO UPDATE SET 
                             wrong_count = weak_points.wrong_count + excluded.wrong_count,
                             last_update = excluded.last_update''', (uid, chapter, wrong_count, today))
    conn.commit()
    conn.close()

def get_top_weak_chapters(uid):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT chapter FROM weak_points WHERE user_id = ? ORDER BY wrong_count DESC LIMIT 2", (uid,))
    rows = c.fetchall()
    conn.close()
    return ", ".join([r[0] for r in rows]) if rows else "N/A"

init_db()

# ===== 2. GLOBAL STATE =====
question_bank = {} 
user_state = {}
user_step = {}
user_scores = {} 
quiz_active = {} 
skipped_this_q = set() 
wrong_chapters_tracker = {} 

current_poll_data = {"poll_id": None, "correct_id": None, "max_answers": 3, "skip_count": 0, "voter_count": 0, "chapter": ""}

# ===== 3. HANDLERS =====
@bot.poll_answer_handler()
def handle_poll_answer(poll_answer):
    uid = poll_answer.user.id
    if uid not in user_scores:
        user_scores[uid] = {"name": poll_answer.user.first_name, "correct": 0, "wrong": 0, "skip": 0, "score": 0.0}
    if str(poll_answer.poll_id) == str(current_poll_data["poll_id"]):
        current_poll_data["voter_count"] += 1
        if poll_answer.option_ids[0] == current_poll_data["correct_id"]:
            user_scores[uid]["correct"] += 1
            user_scores[uid]["score"] += 1.0
        else:
            user_scores[uid]["wrong"] += 1
            user_scores[uid]["score"] -= 0.25 # -0.25 Logic
            ch = current_poll_data["chapter"]
            wrong_chapters_tracker.setdefault(uid, {}).setdefault(ch, 0)
            wrong_chapters_tracker[uid][ch] += 1

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    if call.data.startswith("skip_"):
        target_pid = call.data.split("_")[1]
        if target_pid != str(current_poll_data["poll_id"]):
            return bot.answer_callback_query(call.id, "❌ Question expired.")
        if call.from_user.id in skipped_this_q:
            return bot.answer_callback_query(call.id, "⚠️ Already skipped!")
        uid = call.from_user.id
        if uid not in user_scores:
            user_scores[uid] = {"name": call.from_user.first_name, "correct": 0, "wrong": 0, "skip": 0, "score": 0.0}
        skipped_this_q.add(uid)
        user_scores[uid]["skip"] += 1
        current_poll_data["skip_count"] += 1
        bot.answer_callback_query(call.id, "⏩ Skipped!")
    elif call.data == "stop_quiz":
        quiz_active[GROUP_ID] = False
        bot.answer_callback_query(call.id, "🛑 Stopping Quiz...")

# ===== 4. QUIZ ENGINE =====
def load_questions():
    subjects = ["biology", "math", "reasoning", "physics", "chemistry"]
    for sub in subjects:
        try:
            path = f"questions/{sub}.txt"
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                current_ch = sub.capitalize()
                for block in [b.strip() for b in text.split("\n\n") if b.strip()]:
                    lines = block.split("\n")
                    for l in lines:
                        if l.lower().startswith("#chapter:"): current_ch = l.split(":")[1].strip()
                    if "Answer:" in block:
                        question_bank.setdefault(sub, {}).setdefault(current_ch, []).append(block)
        except: pass

load_questions()

def run_quiz(chat_id):
    global current_poll_data, skipped_this_q, wrong_chapters_tracker
    user_scores.clear()
    wrong_chapters_tracker.clear()
    data = user_state[chat_id]
    sub = data['subject']
    all_pool = []
    for ch in data['chapters']: all_pool.extend(question_bank[sub].get(ch, []))
    selected = random.sample(all_pool, min(data['count'], len(all_pool)))

    bot.send_message(GROUP_ID, f"🚀 **{sub.upper()} EXAM STARTED**")
    
    # STOP BUTTON FOR ADMIN
    stop_markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🛑 STOP QUIZ", callback_data="stop_quiz"))
    bot.send_message(chat_id, "Admin Emergency Stop:", reply_markup=stop_markup)

    for block in selected:
        if not quiz_active.get(GROUP_ID): break
        current_poll_data.update({"skip_count": 0, "voter_count": 0})
        skipped_this_q.clear()
        
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        ch_name = sub.capitalize()
        for l in lines:
            if l.lower().startswith("#chapter:"): ch_name = l.split(":")[1].strip()
        
        current_poll_data["chapter"] = ch_name
        clean_q = [line for line in lines if not line.lower().startswith("#")][0]
        options = [lines[1][3:], lines[2][3:], lines[3][3:], lines[4][3:]]
        ans_letter = next((l.split(":")[-1].strip() for l in lines if "Answer:" in l), "A")
        correct_idx = ord(ans_letter) - ord("A")

        # VERIFICATION CHANNEL
        bot.send_message(VERIFY_CHANNEL_ID, f"✅ Verification: {clean_q} | Ans: {ans_letter}")

        poll = bot.send_poll(GROUP_ID, clean_q, options, type='quiz', correct_option_id=correct_idx, is_anonymous=False, open_period=data['timer'])
        current_poll_data["poll_id"] = poll.poll.id
        current_poll_data["correct_id"] = correct_idx

        skip_btn = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⏩ Skip", callback_data=f"skip_{poll.poll.id}"))
        btn_msg = bot.send_message(GROUP_ID, "Tap to Skip:", reply_markup=skip_btn)

        start_t = time.time()
        while time.time() - start_t < data['timer']:
            if (current_poll_data["voter_count"] + current_poll_data["skip_count"]) >= data['max_answers']: break
            if not quiz_active.get(GROUP_ID): break
            time.sleep(0.5)

        try:
            bot.delete_message(GROUP_ID, btn_msg.message_id)
            bot.stop_poll(GROUP_ID, poll.message_id)
        except: pass
        time.sleep(2)

    save_session_to_db(user_scores, wrong_chapters_tracker)
    
    # Combined Report
    report = f"📊 **EXAM REPORT** 📊\n━━━━━━━━━━━━━━\n"
    sorted_u = sorted(user_scores.values(), key=lambda x: x['score'], reverse=True)
    for i, u in enumerate(sorted_u[:10], 1):
        uid = next(k for k, v in user_scores.items() if v['name'] == u['name'])
        total_att = u['correct'] + u['wrong']
        acc = (u['correct'] / total_att * 100) if total_att > 0 else 0
        report += (f"{i}. 👤 **{u['name']}**\n"
                   f"✅ {u['correct']} | ❌ {u['wrong']} | ⏩ {u['skip']}\n"
                   f"📝 Attended: {total_att} | 🎯 {acc:.1f}%\n"
                   f"🏆 Score: {u['score']:.2f} | 💡 Weak: {get_top_weak_chapters(uid)}\n"
                   f"━━━━━━━━━━━━━━\n")
    
    # All-Time Leaderboard Fetch
    report += "\n👑 **ALL-TIME HALL OF FAME** 👑\n━━━━━━━━━━━━━━\n"
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT name, score FROM all_time_stats ORDER BY score DESC LIMIT 5")
    for i, row in enumerate(c.fetchall(), 1):
        report += f"{i}. {row[0]} — {row[1]:.2f} pts\n"
    conn.close()

    bot.send_message(GROUP_ID, report, parse_mode="Markdown")

# [ADMIN HANDLERS REDACTED FOR SPACE - KEEP YOUR EXISTING ONES]

if __name__ == "__main__":
    print("🤖 Bot is starting up...")
    bot.infinity_polling(skip_pending=True)
