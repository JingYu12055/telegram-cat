"""
範例 Telegram 機器人 — 智慧寵物「貓貓」

功能：
- 寵物互動：/feed /drink /sleep，會記錄上次時間，若長時間沒做會發提醒
- 隨機笑話：/joke
- 排程提醒：/remind HH:MM 內容（單次提醒，若時間已過，會排到隔天同時間）
- 天氣查詢：/weather 城市（整合 OpenWeather API）
- 搜尋：/google 關鍵字（回傳搜尋連結） /wiki 主題（回傳維基摘要）

說明：
- 使用 python-telegram-bot v20 (async API)
- 使用 APScheduler 的 AsyncIO 排程器做背景提醒
- 狀態儲存在本機 JSON 檔 state.json

安裝套件：
    pip install python-telegram-bot>=20.0 apscheduler requests

設定環境變數：
    TELEGRAM_TOKEN - 你的 Bot Token
    OPENWEATHER_API_KEY - 你的 OpenWeather API Key（若沒有，可留空再填入程式）

範例：
    export TELEGRAM_TOKEN="你的_token"
    export OPENWEATHER_API_KEY="你的_openweather_key"
    python telegram_bot.py

"""

import os
import json
import logging
from datetime import datetime, timedelta, time as dtime
from typing import Dict, Any

import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# -------------------- 設定 --------------------
PET_NAME = "貓貓"  # 寵物名字
STATE_FILE = "state.json"
OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY', "")

# 提醒閾值（小時）
FEED_THRESHOLD_HOURS = 6
DRINK_THRESHOLD_HOURS = 4
SLEEP_THRESHOLD_HOURS = 18

# 日誌
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# 初始化排程器
scheduler = AsyncIOScheduler()

# 內建笑話清單（可擴充）
JOKES = [
    "為什麼電腦很會唱歌？因為有很多記憶體（memory）！",
    "為什麼貓咪不喜歡上網？因為牠怕抓不到滑鼠。",
    "有一天一隻喵說："嗨！"，另一隻喵問：你喵什麼？",
    "為什麼程序員喜歡夏天？因為可以穿短路（short-circuit）！",
]

# -------------------- 狀態儲存／讀取 --------------------

def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        state = {
            "last_feed": None,
            "last_drink": None,
            "last_sleep": None,
            "users": {},  # 可擴充儲存每個使用者的資料
            "reminders": [],  # 儲存已登記的提醒 (供重啟時恢復)
        }
        save_state(state)
        return state
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


state = load_state()


# -------------------- 工具函式 --------------------

def iso_now() -> str:
    return datetime.utcnow().isoformat()


def parse_iso(dt_str: str):
    if not dt_str:
        return None
    return datetime.fromisoformat(dt_str)


def time_since_hours(dt_str: str) -> float:
    dt = parse_iso(dt_str)
    if not dt:
        return float('inf')
    delta = datetime.utcnow() - dt
    return delta.total_seconds() / 3600.0


# -------------------- Handlers --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = f"嗨，{user.first_name or '朋友'}！我是你的智慧寵物 {PET_NAME} 🐾
試試 /feed /drink /sleep /joke /weather /remind /google /wiki"
    keyboard = [[InlineKeyboardButton("給我一個笑話", callback_data='joke_cb')]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "指令清單：
"
        "/feed - 餵食貓貓
"
        "/drink - 給貓貓喝水
"
        "/sleep - 讓貓貓睡覺
"
        "/joke - 隨機笑話
"
        "/remind HH:MM 內容 - 安排單次提醒
"
        "/weather 城市 - 查詢天氣（OpenWeather）
"
        "/google 關鍵字 - 傳回 Google 搜尋連結
"
        "/wiki 主題 - 傳回維基百科摘要"
    )


async def joke_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import random
    await update.message.reply_text(random.choice(JOKES))


async def feed_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state['last_feed'] = iso_now()
    save_state(state)
    await update.message.reply_text(f"你餵了 {PET_NAME}！牠開心地吃光了 🍽️")


async def drink_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state['last_drink'] = iso_now()
    save_state(state)
    await update.message.reply_text(f"你給了 {PET_NAME} 水喝！牠咕嚕咕嚕喝完了 💧")


async def sleep_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state['last_sleep'] = iso_now()
    save_state(state)
    await update.message.reply_text(f"{PET_NAME} 去睡覺了... 乖乖睡好覺 😴")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # 回傳目前狀態
    lf = state.get('last_feed')
    ld = state.get('last_drink')
    ls = state.get('last_sleep')
    def fmt(t):
        return parse_iso(t).strftime('%Y-%m-%d %H:%M:%S') if t else '從未'

    text = (
        f"{PET_NAME} 狀態：
"
        f"最後餵食：{fmt(lf)}
"
        f"最後喝水：{fmt(ld)}
"
        f"最後睡覺：{fmt(ls)}
"
    )
    await update.message.reply_text(text)


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # /remind HH:MM 內容
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("使用方式：/remind HH:MM 提醒內容")
        return
    time_part = args[0]
    try:
        hh, mm = map(int, time_part.split(':'))
        now = datetime.utcnow()
        # 使用 UTC 處理排程，假設使用者時間為本地（若需轉換，可改成使用者所在時區）
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
    except Exception:
        await update.message.reply_text("時間格式錯誤，請使用 HH:MM（24 小時制）")
        return

    content = ' '.join(args[1:])

    # 排程一個單次提醒
    job_id = f"remind_{len(state.get('reminders', [])) + 1}_{int(target.timestamp())}"
    scheduler.add_job(send_reminder_job, trigger=DateTrigger(run_date=target), args=(update.effective_chat.id, content), id=job_id)

    # 記錄到 state（重啟後目前不會自動還原排程，這裡只是示範儲存）
    state.setdefault('reminders', []).append({
        'job_id': job_id,
        'run_at': target.isoformat(),
        'chat_id': update.effective_chat.id,
        'content': content,
    })
    save_state(state)

    local_time = target.isoformat()  # 因為用 UTC，顯示為 UTC 時間
    await update.message.reply_text(f"已為你安排提醒：{content}
提醒時間 (UTC)：{local_time}")


async def send_reminder_job(chat_id: int, content: str) -> None:
    # 透過 Application 發送訊息：先取得 application
    app = Application.builder().token(os.getenv('TELEGRAM_TOKEN') or '').build()  # 臨時建立 client 用於發送
    # 注意：在 production 中應該取得長期可用的 bot instance，而不是每次建立。
    try:
        await app.bot.send_message(chat_id=chat_id, text=f"🔔 提醒：{content}")
    except Exception as e:
        logger.exception("無法發送提醒：%s", e)


async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not OPENWEATHER_API_KEY:
        await update.message.reply_text("尚未設定 OpenWeather API Key，請設定環境變數 OPENWEATHER_API_KEY")
        return
    args = context.args
    if not args:
        await update.message.reply_text("使用方式：/weather 城市")
        return
    city = ' '.join(args)
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_API_KEY}&units=metric&lang=zh_tw"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if resp.status_code != 200:
            await update.message.reply_text(f"查詢失敗：{data.get('message', '未知錯誤')}")
            return
        desc = data['weather'][0]['description']
        temp = data['main']['temp']
        hum = data['main']['humidity']
        text = f"{city} 天氣：{desc}
溫度：{temp}°C
濕度：{hum}%"
        await update.message.reply_text(text)
    except Exception as e:
        logger.exception("weather error: %s", e)
        await update.message.reply_text("查詢天氣時發生錯誤，請稍後再試。")


async def google_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("使用方式：/google 關鍵字")
        return
    q = '+'.join(context.args)
    url = f"https://www.google.com/search?q={q}"
    await update.message.reply_text(f"Google 搜尋連結：{url}")


async def wiki_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("使用方式：/wiki 主題")
        return
    title = '_'.join(context.args)
    try:
        url = f"https://zh.wikipedia.org/api/rest_v1/page/summary/{title}"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            await update.message.reply_text("找不到該維基條目或發生錯誤。")
            return
        j = resp.json()
        extract = j.get('extract')
        page_url = j.get('content_urls', {}).get('desktop', {}).get('page')
        text = f"{extract}

閱讀更多：{page_url}" if extract else f"找不到摘要，請試試其他關鍵字。
{page_url}"
        await update.message.reply_text(text)
    except Exception as e:
        logger.exception("wiki error: %s", e)
        await update.message.reply_text("查詢維基時發生錯誤，請稍後再試。")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == 'joke_cb':
        import random
        await query.edit_message_text(random.choice(JOKES))


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # 簡單關鍵字自動回覆（例如「你好」）
    text = update.message.text.strip()
    if any(w in text for w in ['你好', '嗨', '哈囉']):
        await update.message.reply_text(f"嗨！我是 {PET_NAME}，要來餵我嗎？試試 /feed /drink /sleep")
    else:
        await update.message.reply_text("我不太懂你的話，但你可以試試 /help 看看我會哪些指令！")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Exception while handling an update: %s", context.error)


# -------------------- 背景提醒任務 --------------------

def schedule_periodic_checks(app: Application) -> None:
    # 每 30 分鐘檢查一次是否需要提醒
    async def check_and_notify():
        try:
            # 檢查餵食
            if time_since_hours(state.get('last_feed')) >= FEED_THRESHOLD_HOURS:
                # 發送提醒給最近互動的使用者；這裡示範發到預設 chat（需改成實際的 chat_id 管理）
                # 若要針對每個使用者，請在 state['users'] 中儲存並逐一通知
                logger.info('需要提醒餵食')
                # 不直接發訊息於此函式，因為沒有 chat_id context；可擴充儲存 default_chat_id
        except Exception:
            logger.exception('check_and_notify error')

    # 加入到排程器（示範使用）
    scheduler.add_job(check_and_notify, 'interval', minutes=30, id='periodic_check')


# -------------------- Main --------------------

def main() -> None:
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        raise RuntimeError('請設定環境變數 TELEGRAM_TOKEN，內容為你的 Bot token')

    app = Application.builder().token(token).build()

    # 註冊 handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('joke', joke_command))
    app.add_handler(CommandHandler('feed', feed_command))
    app.add_handler(CommandHandler('drink', drink_command))
    app.add_handler(CommandHandler('sleep', sleep_command))
    app.add_handler(CommandHandler('status', status_command))
    app.add_handler(CommandHandler('remind', remind_command))
    app.add_handler(CommandHandler('weather', weather_command))
    app.add_handler(CommandHandler('google', google_command))
    app.add_handler(CommandHandler('wiki', wiki_command))

    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_message_handler))

    app.add_error_handler(error_handler)

    # 啟動排程器
    scheduler.start()
    # 若需在排程中呼叫 bot，請在排程函式內使用 app.bot
    # 範例：將周期檢查註冊為 startup job
    app.job_queue.run_once(lambda ctx: schedule_periodic_checks(app), when=1)

    logger.info('Starting bot with polling...')
    app.run_polling()


if __name__ == '__main__':
    main()
