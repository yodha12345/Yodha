import telebot
from telebot import types
import os
import random
import time
import threading
import sqlite3
from datetime import datetime, timedelta

# Initialize Bot
API_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(API_TOKEN, threaded=True, num_threads=25)

ADMIN_KEY = "Eshu2005aru"
GROUP_ID = -1003746627836 

# ===== 1. DATABASE SYSTEM (Persistent Memory) =====
DB_NAME = "quiz_pro_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # [span_0](start_span)Track used questions for 2-week logic[span_0](end_span)
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (question_hash TEXT PRIMARY KEY, last_used TIMESTAMP)''')
    # [span_1](start_span)Track All-Time Stats[span_1](end_span)
    c.execute('''CREATE TABLE IF NOT EXISTS all_time_stats 
                 (user_id INTEGER PRIMARY KEY, name TEXT, 
                  correct INTEGER DEFAULT 0, wrong INTEGER DEFAULT 0, 
                  skip INTEGER DEFAULT 0, score REAL DEFAULT 0.0)''')
    # Track Weak Points by Subject
    c.execute('''CREATE TABLE IF NOT EXISTS weak_points 
                 (user_id INTEGER, subject TEXT, wrong_count INTEGER DEFAULT 0,
                  PRIMARY KEY (user_id, subject))''')
    conn.commit()
    conn.close()

def save_session_to_db(session_scores, current_sub):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    for uid, stats in session_scores.items():
        # [span_2](start_span)Update All-Time Table[span_2](end_span)
        c.execute('''INSERT INTO all_time_stats (user_id, name, correct, wrong, skip, score)
                     VALUES (?, ?, ?, ?, ?, ?)
                     ON CONFLICT(user_id) DO UPDATE SET
                     name = excluded.name,
                     correct = all_time_stats.correct + excluded.correct,
                     wrong = all_time_stats.wrong + excluded.wrong,
                     skip = all_time_stats.skip + excluded.skip,
                     score = all_time_stats.score + excluded.score''', 
                  (uid, stats['name'], stats['correct'], stats['wrong'], stats['skip'], stats['score']))
        
        # Update Weak Points if they got answers wrong in this session
        if stats['wrong'] > 0:
            c.execute('''INSERT INTO weak_points (user_id, subject, wrong_count) 
                         VALUES (?, ?, ?) 
                         ON CONFLICT(user_id, subject) DO UPDATE SET 
                         wrong_count = weak_points.wrong_count + excluded.wrong_count''', 
                      (uid, current_sub, stats['wrong']))
    conn.commit()
    conn.close()

def get_weak_point(uid):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT subject FROM weak_points WHERE user_id = ? ORDER BY wrong_count DESC LIMIT 1", (uid,))
    row = c.fetchone()
    conn.close()
    return row[0].capitalize() if row else "N/A"

init_db()

# ===== 2. DATA STORAGE & GLOBAL STATE =====
question_bank = {} 
user_state = {}
user_step = {}
selected_chapters = {}
user_scores = {} 
quiz_active = {} 
skipped_this_q = set() 

current_poll_data = {
    "poll_id": None, "message_id": None, "active": False,
    "correct_id": None, "max_answers": 3, "skip_count": 0, 
    "voter_count": 0, "subject": ""
}

# ===== 3. REPORT GENERATOR (Dual Leaderboard) =====
def get_final_report():
    if not user_scores: return "📊 No results to show."
    
    # [span_3](start_span)Session Leaderboard (Examination)[span_3](end_span)
    sorted_session = sorted(user_scores.values(), key=lambda x: x['score'], reverse=True)
    report = "📋 **EXAMINATION LEADERBOARD** 📋\n━━━━━━━━━━━━━━\n"
    
    for i, u in enumerate(sorted_session[:10], 1):
        uid = next(k for k, v in user_scores.items() if v['name'] == u['name'])
        weak_sub = get_weak_point(uid)
        
        total_attempts = u['correct'] + u['wrong']
        accuracy = (u['correct'] / total_attempts * 100) if total_attempts > 0 else 0
        
        report += (f"{i}. 👤 **{u['name']}**\n"
                   f"✅ {u['correct']} | ❌ {u['wrong']} | 🎯 {accuracy:.1f}%\n"
                   f"🏆 Session Score: {u['score']}\n"
                   f"⚠️ Weak Point: {weak_sub}\n"
                   f"━━━━━━━━━━━━━━\n")

    # All-Time Leaderboard
    report += "\n👑 **ALL-TIME HALL OF FAME** 👑\n━━━━━━━━━━━━━━\n"
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT name, score FROM all_time_stats ORDER BY score DESC LIMIT 5")
    for i, row in enumerate(c.fetchall(), 1):
        report += f"{i}. {row[0]} — {row[1]} pts\n"
    conn.close()
    
    return report

# ===== 4. HANDLERS =====
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
            user_scores[uid]["score"] -= 0.5

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    uid = call.from_user.id
    if call.data.startswith("skip_"):
        if str(call.data.split("_")[1]) != str(current_poll_data["poll_id"]):
            return bot.answer_callback_query(call.id, "❌ Question expired.")
        if uid in skipped_this_q:
            return bot.answer_callback_query(call.id, "⚠️ Already skipped!")
        
        if uid not in user_scores:
            user_scores[uid] = {"name": call.from_user.first_name, "correct": 0, "wrong": 0, "skip": 0, "score": 0.0}
            
        skipped_this_q.add(uid)
        user_scores[uid]["skip"] += 1
        current_poll_data["skip_count"] += 1
        bot.answer_callback_query(call.id, "⏩ Skipped!")
    elif call.data == "stop_quiz":
        quiz_active[GROUP_ID] = False
        bot.answer_callback_query(call.id, "🛑 Stopping Quiz...")

# ===== 5. ADMIN & ENGINE =====
def load_questions():
    [span_4](start_span)subjects = ["biology", "math", "reasoning", "physics", "chemistry"][span_4](end_span)
    for sub in subjects:
        try:
            [span_5](start_span)path = f"questions/{sub}.txt"[span_5](end_span)
            if not os.path.exists(path): continue
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            current_chapter = "General" 
            [span_6](start_span)blocks = [b.strip() for b in text.split("\n\n") if b.strip()][span_6](end_span)
            for block in blocks:
                lines = block.split("\n")
                for line in lines:
                    if line.lower().startswith("#chapter:"):
                        current_chapter = line.split(":")[1].strip()
                [span_7](start_span)if "Answer:" in block:[span_7](end_span)
                    question_bank.setdefault(sub, {}).setdefault(current_chapter, []).append(block)
        except: pass

load_questions()

def run_quiz(chat_id):
    global current_poll_data, skipped_this_q
    user_scores.clear()
    data = user_state[chat_id]
    sub = data['subject']
    
    all_pool = []
    for ch in data['chapters']: all_pool.extend(question_bank[sub].get(ch, []))
    selected = random.sample(all_pool, min(data['count'], len(all_pool)))

    bot.send_message(GROUP_ID, f"🔔 **{sub.upper()} EXAMINATION STARTED!**")

    for block in selected:
        if not quiz_active.get(GROUP_ID): break
        
        current_poll_data.update({"skip_count": 0, "voter_count": 0, "active": True, "subject": sub})
        skipped_this_q.clear()
        
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        clean_q = [line for line in lines if not line.lower().startswith("#")][0]
        options = [lines[1][3:], lines[2][3:], lines[3][3:], lines[4][3:]]
        ans = next((l.split(":")[-1].strip() for l in lines if "Answer:" in l), "A")
        correct_idx = ord(ans) - ord("A")

        poll_msg = bot.send_poll(GROUP_ID, clean_q, options, type='quiz', 
                                 correct_option_id=correct_idx, is_anonymous=False, 
                                 [span_8](start_span)open_period=data['timer'])[span_8](end_span)
        
        current_poll_data.update({"poll_id": poll_msg.poll.id, "correct_id": correct_idx})
        skip_btn = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⏩ Skip", callback_data=f"skip_{poll_msg.poll.id}"))
        btn_msg = bot.send_message(GROUP_ID, "Tap to Skip:", reply_markup=skip_btn)

        start_t = time.time()
        while time.time() - start_t < data['timer']:
            if (current_poll_data["voter_count"] + current_poll_data["skip_count"]) >= data['max_answers']: break
            if not quiz_active.get(GROUP_ID): break
            time.sleep(0.5)

        try:
            bot.delete_message(GROUP_ID, btn_msg.message_id)
            [span_9](start_span)bot.stop_poll(GROUP_ID, poll_msg.message_id)[span_9](end_span)
        except: pass
        time.sleep(1.5)

    # Save Session to DB & Publish Report
    save_session_to_db(user_scores, sub)
    bot.send_message(GROUP_ID, get_final_report(), parse_mode="Markdown")
    bot.send_message(GROUP_ID, "🏁 **Exam Finished. Appreciation to all participants!**")

# ===== 6. ADMIN PANEL HANDLERS =====
@bot.message_handler(commands=['admin'])
def admin(message):
    user_step[message.chat.id] = "admin_key"
    bot.send_message(message.chat.id, "🔑 **Enter Admin Key:**")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "admin_key")
def check_key(m):
    [span_10](start_span)if m.text == ADMIN_KEY:[span_10](end_span)
        user_step[m.chat.id] = "subject"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add("Biology", "Math", "Reasoning", "Physics", "Chemistry")
        bot.send_message(m.chat.id, "📚 **Select Subject:**", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "subject")
def sel_sub(m):
    sub = m.text.lower()
    if sub in question_bank:
        user_state[m.chat.id] = {'subject': sub}
        user_step[m.chat.id] = "mode"
        [span_11](start_span)markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add("Mix (All) 🎯", "Chapter-wise 📂")[span_11](end_span)
        bot.send_message(m.chat.id, "🎯 **Select Mode:**", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "mode")
def sel_mode(m):
    sub = user_state[m.chat.id]['subject']
    if "Mix" in m.text:
        user_state[m.chat.id]['chapters'] = list(question_bank[sub].keys())
        user_step[m.chat.id] = "count"
        bot.send_message(m.chat.id, "🔢 **Question Count:**", reply_markup=types.ReplyKeyboardRemove())
    else:
        user_step[m.chat.id] = "chapter"
        selected_chapters[m.chat.id] = set()
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for ch in question_bank[sub]: markup.add(ch)
        markup.add("DONE ✅")
        [span_12](start_span)bot.send_message(m.chat.id, "Select chapters:", reply_markup=markup)[span_12](end_span)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "chapter")
def sel_ch(m):
    if m.text == "DONE ✅":
        user_state[m.chat.id]['chapters'] = list(selected_chapters[m.chat.id])
        user_step[m.chat.id] = "count"
        bot.send_message(m.chat.id, "🔢 **Count:**", reply_markup=types.ReplyKeyboardRemove())
    else:
        selected_chapters[m.chat.id].add(m.text)
        bot.send_message(m.chat.id, f"➕ {m.text}")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "count")
def sel_count(m):
    user_state[m.chat.id]['count'] = int(m.text)
    user_step[m.chat.id] = "timer"
    [span_13](start_span)bot.send_message(m.chat.id, "⏱️ **Global Timer (sec):**")[span_13](end_span)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "timer")
def sel_timer(m):
    user_state[m.chat.id]['timer'] = int(m.text)
    user_step[m.chat.id] = "limit"
    bot.send_message(m.chat.id, "👤 **Answer Limit (Votes + Skips):**")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "limit")
def sel_limit(m):
    user_state[m.chat.id]['max_answers'] = int(m.text)
    user_step[m.chat.id] = "ready"
    bot.send_message(m.chat.id, "✅ Ready!", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("START QUIZ 🚀"))

@bot.message_handler(func=lambda m: m.text == "START QUIZ 🚀" and user_step.get(m.chat.id) == "ready")
def start_trigger(message):
    quiz_active[GROUP_ID] = True
    [span_14](start_span)threading.Thread(target=run_quiz, args=(message.chat.id,)).start()[span_14](end_span)

if __name__ == "__main__":
    bot.infinity_polling(skip_pending=True)
    
