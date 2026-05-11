import telebot
from telebot import types
import os
import random
import time

API_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(API_TOKEN)

ADMIN_KEY = "Eshu2005aru"
GROUP_ID = -1003746627836  # replace

# ===== DATA =====
question_bank = {}
used_questions = set()
user_state = {}
user_step = {}
selected_chapters = {}

# ===== SCORE =====
user_scores = {}
poll_correct_answers = {}

# ===== ADMIN CONTROL =====
poll_answers_count = {}
poll_active = {}
MIN_RESPONSES = 3
admin_chat_id = None

# ===== LOAD QUESTIONS =====
def load_questions():
    with open("questions/biology.txt", "r", encoding="utf-8") as f:
        text = f.read()

    current_chapter = ""

    for block in text.split("\n\n"):
        lines = block.strip().split("\n")

        for line in lines:
            if line.startswith("#chapter:"):
                current_chapter = line.split(":")[1].strip()

        if "Answer:" in block:
            question_bank.setdefault("biology", {}).setdefault(current_chapter, []).append(block)

load_questions()

# ===== ADMIN LOGIN =====
@bot.message_handler(commands=['admin'])
def admin(message):
    msg = bot.send_message(message.chat.id, "🔑 Enter Admin Key:")
    bot.register_next_step_handler(msg, check_admin)

def check_admin(message):
    global admin_chat_id

    if message.text == ADMIN_KEY:
        admin_chat_id = message.chat.id
        user_step[message.chat.id] = "subject"
        show_subject(message.chat.id)
    else:
        bot.send_message(message.chat.id, "❌ Wrong key")

# ===== SUBJECT =====
def show_subject(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Biology")
    bot.send_message(chat_id, "📚 Choose Subject:", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "subject")
def handle_subject(message):
    chat_id = message.chat.id
    user_state[chat_id] = {}
    user_step[chat_id] = "mode"

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Mix 🎯", "Chapter-wise 📂")

    bot.send_message(chat_id, "Choose Mode:", reply_markup=markup)

# ===== MODE =====
@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "mode")
def handle_mode(message):
    chat_id = message.chat.id

    if message.text == "Mix 🎯":
        user_state[chat_id]['chapters'] = list(question_bank["biology"].keys())
        user_step[chat_id] = "count"

        msg = bot.send_message(chat_id, "🔢 Enter number of questions:")
        bot.register_next_step_handler(msg, save_count)

    elif message.text == "Chapter-wise 📂":
        user_step[chat_id] = "chapter"
        selected_chapters[chat_id] = set()
        show_chapters(chat_id)

# ===== CHAPTER =====
def show_chapters(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for ch in question_bank["biology"]:
        markup.add(ch)
    markup.add("DONE ✅")

    bot.send_message(chat_id, "Select chapters then DONE:", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "chapter")
def select_chapter(message):
    chat_id = message.chat.id

    if message.text == "DONE ✅":
        user_state[chat_id]['chapters'] = list(selected_chapters[chat_id])
        user_step[chat_id] = "count"

        msg = bot.send_message(chat_id, "🔢 Enter number of questions:")
        bot.register_next_step_handler(msg, save_count)
    else:
        selected_chapters[chat_id].add(message.text)
        bot.send_message(chat_id, f"✅ Added: {message.text}")

# ===== COUNT =====
def save_count(message):
    chat_id = message.chat.id
    user_state[chat_id]['count'] = int(message.text)
    user_step[chat_id] = "timer"

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("10", "20", "30", "60")

    bot.send_message(chat_id, "⏱️ Select timer:", reply_markup=markup)

# ===== TIMER =====
@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "timer")
def save_timer(message):
    chat_id = message.chat.id
    user_state[chat_id]['timer'] = int(message.text)
    user_step[chat_id] = "start"

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("START QUIZ 🚀")

    bot.send_message(chat_id, "Ready?", reply_markup=markup)

# ===== RANDOM =====
def get_questions(chapters, count):
    pool = []
    for ch in chapters:
        pool.extend(question_bank["biology"].get(ch, []))

    available = [q for q in pool if q not in used_questions]

    if len(available) < count:
        used_questions.clear()
        available = pool

    selected = random.sample(available, min(count, len(available)))

    for q in selected:
        used_questions.add(q)

    return selected

# ===== SEND POLL =====
def send_poll(block, timer):
    lines = [l.strip() for l in block.split("\n") if l.strip()]

    question = lines[0]
    options = [lines[1][3:], lines[2][3:], lines[3][3:], lines[4][3:]]

    ans = "A"
    for l in lines:
        if "Answer:" in l:
            ans = l.split(":")[-1].strip()

    idx = ord(ans) - ord("A")

    poll = bot.send_poll(
        chat_id=GROUP_ID,
        question=question,
        options=options,
        type="quiz",
        correct_option_id=idx,
        is_anonymous=False,
        open_period=timer
    )

    poll_id = poll.poll.id

    poll_correct_answers[poll_id] = idx
    poll_answers_count[poll_id] = 0
    poll_active[poll_id] = True

    return poll_id

# ===== START QUIZ =====
@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "start")
def start_quiz(message):
    chat_id = message.chat.id
    data = user_state[chat_id]

    questions = get_questions(data['chapters'], data['count'])

    bot.send_message(chat_id, "🚀 Quiz Started!")

    for q in questions:
        poll_id = send_poll(q, data['timer'])
        start = time.time()

        while True:
            if not poll_active.get(poll_id, True):
                break

            if poll_answers_count.get(poll_id, 0) >= MIN_RESPONSES:
                break

            if time.time() - start > data['timer']:
                break

            time.sleep(1)

    bot.send_message(GROUP_ID, "🏁 Quiz Finished!\nType /leaderboard")

# ===== ANSWER TRACKING =====
@bot.poll_answer_handler()
def handle_answer(poll_answer):
    user_id = poll_answer.user.id
    name = poll_answer.user.first_name
    selected = poll_answer.option_ids[0]
    poll_id = poll_answer.poll_id

    if poll_id in poll_answers_count:
        poll_answers_count[poll_id] += 1

        if admin_chat_id:
            bot.send_message(admin_chat_id, f"📊 Answers: {poll_answers_count[poll_id]}")

    if user_id not in user_scores:
        user_scores[user_id] = {
            "name": name,
            "correct": 0,
            "wrong": 0,
            "attempted": 0,
            "score": 0
        }

    user_scores[user_id]["attempted"] += 1

    if poll_id in poll_correct_answers:
        if selected == poll_correct_answers[poll_id]:
            user_scores[user_id]["correct"] += 1
            user_scores[user_id]["score"] += 1
        else:
            user_scores[user_id]["wrong"] += 1
            user_scores[user_id]["score"] -= 0.5

# ===== ADMIN COMMANDS =====
@bot.message_handler(commands=['setmin'])
def set_min(message):
    global MIN_RESPONSES
    try:
        MIN_RESPONSES = int(message.text.split()[1])
        bot.send_message(message.chat.id, f"✅ Min answers set: {MIN_RESPONSES}")
    except:
        bot.send_message(message.chat.id, "Usage: /setmin 5")

@bot.message_handler(commands=['close'])
def close_poll(message):
    for p in poll_active:
        poll_active[p] = False
    bot.send_message(message.chat.id, "⛔ Question closed")

# ===== LEADERBOARD =====
@bot.message_handler(commands=['leaderboard'])
def leaderboard(message):
    if not user_scores:
        return bot.send_message(message.chat.id, "No data")

    sorted_users = sorted(user_scores.values(), key=lambda x: x["score"], reverse=True)

    text = "🏆 FINAL SCORECARD 🏆\n\n"

    for i, u in enumerate(sorted_users[:10], 1):
        acc = (u["correct"] / u["attempted"] * 100) if u["attempted"] else 0

        text += (
            f"{i}. {u['name']}\n"
            f"✔ {u['correct']} ❌ {u['wrong']}\n"
            f"📊 Attempted: {u['attempted']}\n"
            f"🎯 Score: {u['score']}\n"
            f"📈 Accuracy: {acc:.1f}%\n\n"
        )

    bot.send_message(message.chat.id, text)

# ===== RUN =====
print("Bot Running...")

while True:
    try:
        bot.polling(none_stop=True)
    except:
        pass
