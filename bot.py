import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from groq import Groq
import feedparser
import time
import threading
import requests
import datetime
import re
import io
import random
import base64
import json
import logging
import pytz
from bs4 import BeautifulSoup
import os

# ────────────────────────────────────────────────
#                SETTINGS
# ────────────────────────────────────────────────

TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")

CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1003783912194"))  # значение по умолчанию, если не задан

if not TOKEN:
    raise ValueError("BOT_TOKEN не задан в переменных окружения")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY не задан в переменных окружения")
if not CLOUDFLARE_API_TOKEN:
    raise ValueError("CLOUDFLARE_API_TOKEN не задан")
if not CLOUDFLARE_ACCOUNT_ID:
    raise ValueError("CLOUDFLARE_ACCOUNT_ID не задан")

LAST_PINNED_SUMMARY_ID = None
LAST_PINNED_FILE = "last_pinned_summary.json"

bot = telebot.TeleBot(TOKEN)
groq_client = Groq(api_key=GROQ_API_KEY)
# Logging
logging.basicConfig(
    filename='bot_log.txt',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8',
)

RSS_FEEDS = [
    ('Investing.com News', 'https://www.investing.com/rss/news.rss'),
    ('MarketWatch Top Stories', 'https://feeds.marketwatch.com/marketwatch/topstories/'),
    ('Bloomberg Markets/News', 'https://feeds.bloomberg.com/markets/news.rss'),

    ('Tesla News - Google', 'https://news.google.com/rss/search?q=tesla+news+-inurl:(youtube+OR+reddit)&hl=en-US&gl=US&ceid=US:en'),
    ('SpaceX News - Google', 'https://news.google.com/rss/search?q=spacex+news+-inurl:(youtube+OR+reddit)&hl=en-US&gl=US&ceid=US:en'),
    ('Neuralink News - Google', 'https://news.google.com/rss/search?q=neuralink+news+-inurl:(youtube+OR+reddit)&hl=en-US&gl=US&ceid=US:en'),
    ('xAI News - Google', 'https://news.google.com/rss/search?q=xai+elon+musk+OR+x.ai+news+-inurl:(youtube+OR+reddit)&hl=en-US&gl=US&ceid=US:en'),
]

KEYWORDS = [
    'ai', 'artificial intelligence', 'machine learning',
    'minerals', 'mining', 'gold', 'gold price', 'silver',
    'stocks', 'shares', 'equity', 'stock market', 'exchange', 'commodities', 'commodity prices', 'commodity',
    'geopolitics', 'china', 'US', 'United States', 'united states',
    'market', 'economy', 'fed', 'inflation',
    'tesla', 'nvidia', 'spacex', 'neuralink', 'Elon Musk', 'apple',
    'bitcoin', 'altcoins'
]

SENT_FILE = "sent_news.json"
LAST_NOTIF_FILE = "last_notification_id.json"
LAST_SENT_SUMMARIES_FILE = "last_sent_summaries.json"

sent_news = set()
daily_news = []
last_check_time = datetime.datetime.now(datetime.timezone.utc)
last_notification_message_id = None
last_sent_summaries = {'morning': None, 'noon': None, 'evening': None}


# ────────────────────────────────────────────────
#                LOAD / SAVE FUNCTIONS
# ────────────────────────────────────────────────
# (все функции load/save остались без изменений)


def load_sent_news():
    global sent_news
    try:
        with open(SENT_FILE, 'r', encoding='utf-8') as f:
            sent_news = set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        sent_news = set()
    logging.info(f"Loaded {len(sent_news)} already sent news items")


def save_sent_news():
    try:
        with open(SENT_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(sent_news), f, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Error saving sent_news: {e}")


def load_last_notification_id():
    global last_notification_message_id
    try:
        with open(LAST_NOTIF_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            last_notification_message_id = data.get("message_id")
        if last_notification_message_id:
            logging.info(f"Loaded last notification ID: {last_notification_message_id}")
    except Exception:
        last_notification_message_id = None


def save_last_notification_id():
    global last_notification_message_id
    if last_notification_message_id is None:
        return
    try:
        with open(LAST_NOTIF_FILE, 'w', encoding='utf-8') as f:
            json.dump({"message_id": last_notification_message_id}, f)
    except Exception as e:
        logging.warning(f"Failed to save last_notification_message_id: {e}")


def load_last_sent_summaries():
    global last_sent_summaries
    try:
        with open(LAST_SENT_SUMMARIES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            last_sent_summaries = data
        logging.info(f"Loaded last summary dates: {last_sent_summaries}")
    except Exception:
        last_sent_summaries = {'morning': None, 'noon': None, 'evening': None}


def load_last_pinned_id():
    global LAST_PINNED_SUMMARY_ID
    try:
        with open(LAST_PINNED_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            LAST_PINNED_SUMMARY_ID = data.get("pinned_message_id")
        if LAST_PINNED_SUMMARY_ID:
            logging.info(f"Loaded last pinned summary id: {LAST_PINNED_SUMMARY_ID}")
    except Exception:
        LAST_PINNED_SUMMARY_ID = None


def save_last_pinned_id():
    global LAST_PINNED_SUMMARY_ID
    if LAST_PINNED_SUMMARY_ID is None:
        return
    try:
        with open(LAST_PINNED_FILE, 'w', encoding='utf-8') as f:
            json.dump({"pinned_message_id": LAST_PINNED_SUMMARY_ID}, f)
    except Exception as e:
        logging.warning(f"Failed to save last pinned id: {e}")


def save_last_sent_summaries():
    try:
        with open(LAST_SENT_SUMMARIES_FILE, 'w', encoding='utf-8') as f:
            json.dump(last_sent_summaries, f)
    except Exception as e:
        logging.warning(f"Failed to save last_sent_summaries: {e}")


def fetch_feed(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/rss+xml, application/xml, text/xml;q=0.9',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logging.error(f"Error fetching {url}: {e}")
        return ""


def escape_md_v2(text):
    if not text:
        return ''
    chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(chars)}])', r'\\\1', text)


def get_article_image(entry):
    if 'media_content' in entry:
        for media in entry.media_content:
            if 'url' in media and media.get('medium') == 'image':
                return media['url']
            elif 'url' in media:
                return media['url']

    if 'media_thumbnail' in entry and entry.media_thumbnail:
        return entry.media_thumbnail[0].get('url')

    if 'enclosures' in entry:
        for enc in entry.enclosures:
            if enc.get('type', '').startswith('image/') and 'url' in enc:
                return enc['url']

    for field in ('content', 'description', 'summary'):
        value = entry.get(field)
        if not value:
            continue
        if isinstance(value, list):
            for item in value:
                text = item.get('value', '')
                if not text:
                    continue
                m = re.search(r'<img[^>]+src=["\'](.*?)["\']', text, re.IGNORECASE)
                if m:
                    return m.group(1)
        elif isinstance(value, str):
            m = re.search(r'<img[^>]+src=["\'](.*?)["\']', value, re.IGNORECASE)
            if m:
                return m.group(1)
    return None


def generate_cloudflare_image(prompt):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/@cf/stabilityai/stable-diffusion-xl-base-1.0"
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"prompt": prompt, "num_steps": 20, "guidance": 7.5}

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=90)
        if r.status_code != 200:
            logging.error(f"Cloudflare error {r.status_code}: {r.text[:200]}")
            return None

        if 'image/' in r.headers.get('Content-Type', ''):
            return r.content

        data = r.json()
        if data.get("success") and "result" in data:
            result = data["result"]
            if isinstance(result, dict) and "image" in result:
                return base64.b64decode(result["image"])
            if isinstance(result, str):
                return base64.b64decode(result)
        return None
    except Exception as e:
        logging.error(f"Cloudflare exception: {e}")
        return None


def download_image(url):
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
            return r.content
        return None
    except Exception as e:
        logging.error(f"Error downloading image {url}: {e}")
        return None


def clean_html(text):
    if not text:
        return ''
    soup = BeautifulSoup(text, 'html.parser')
    cleaned = soup.get_text(separator=' ', strip=True)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def send_news_photo(entry, source_name):
    title = (entry.get('title') or 'No title').strip()
    link = entry.get('link', 'no link')
    published = entry.get('published') or entry.get('updated', 'date unknown')

    desc_raw = ''
    if 'description' in entry:
        desc_raw = entry.description
    elif 'summary' in entry:
        desc_raw = entry.summary
    elif 'content' in entry and isinstance(entry.content, list) and entry.content:
        desc_raw = entry.content[0].get('value', '')

    desc_clean = clean_html(desc_raw)

    if len(desc_clean) > 220:
        desc_short = desc_clean[:220].rsplit(' ', 1)[0] + '…'
    else:
        desc_short = desc_clean

    caption = (
        f"**{escape_md_v2(title)}**\n\n"
        f"{escape_md_v2(desc_short)}\n\n"
        f"[{escape_md_v2(source_name)} • {escape_md_v2(published[:16])}]({escape_md_v2(link)})"
    )

    image_bytes = None
    img_url = get_article_image(entry)
    if img_url:
        image_bytes = download_image(img_url)

    if not image_bytes:
        prompt = f"Professional news illustration: {title}. {desc_short}. Modern style, tech and space theme, high quality, realistic"
        image_bytes = generate_cloudflare_image(prompt)

    try:
        if image_bytes:
            photo = io.BytesIO(image_bytes)
            photo.name = 'news.jpg'
            bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=photo,
                caption=caption,
                parse_mode='MarkdownV2'
            )
        else:
            bot.send_message(
                chat_id=CHANNEL_ID,
                text=caption,
                parse_mode='MarkdownV2',
                disable_web_page_preview=True
            )
        logging.info(f"Sent news: {title}")
        return True

    except telebot.apihelper.ApiTelegramException as e:
        logging.error(f"Telegram error while sending: {e.description}")
        fallback = (
            f"📰 **{escape_md_v2(title)}**\n"
            f"{escape_md_v2(desc_short)}\n\n"
            f"{escape_md_v2(source_name)} • {escape_md_v2(published[:16])}\n"
            f"{escape_md_v2(link)}"
        )
        try:
            bot.send_message(
                CHANNEL_ID,
                fallback,
                parse_mode='MarkdownV2',
                disable_web_page_preview=True
            )
        except Exception as fallback_e:
            logging.error(f"Fallback also failed: {fallback_e}")
        return True

    except Exception as e:
        logging.error(f"Critical error sending news '{title}': {e}")
        return False


def send_or_update_notification(text):
    global last_notification_message_id

    if last_notification_message_id is not None:
        try:
            bot.delete_message(CHANNEL_ID, last_notification_message_id)
            logging.info(f"Deleted old notification #{last_notification_message_id}")
        except Exception as e:
            logging.info(f"Could not delete old notification (possibly already deleted): {e}")

    try:
        msg = bot.send_message(
            CHANNEL_ID,
            text,
            disable_web_page_preview=True
        )
        last_notification_message_id = msg.message_id
        save_last_notification_id()
        logging.info(f"New notification: {text}  (id={msg.message_id})")
    except Exception as e:
        logging.error(f"Failed to send notification '{text}': {e}")


def send_recent_news(initial_run=False):
    total_sent = 0
    max_send = 4 if initial_run else 5

    for source_name, url in RSS_FEEDS:
        content = fetch_feed(url)
        if not content:
            continue
        feed = feedparser.parse(content)
        if not feed.entries:
            continue

        for entry in feed.entries:
            title_lower = (entry.get('title') or '').strip().lower()
            desc_lower = (entry.get('description') or entry.get('summary') or '').strip().lower()
            link = entry.get('link', '')
            unique_key = f"{title_lower}_{link[:120]}"

            if unique_key in sent_news:
                continue

            if any(kw.lower() in title_lower or kw.lower() in desc_lower for kw in KEYWORDS):
                sent_news.add(unique_key)
                daily_news.append({
                    'title': entry.get('title', '').strip(),
                    'desc': (entry.get('description') or entry.get('summary', '')).strip(),
                    'source': source_name,
                    'pub_date': entry.get('published') or entry.get('updated', '')
                })

                if send_news_photo(entry, source_name):
                    total_sent += 1
                    save_sent_news()
                time.sleep(random.uniform(4.5, 8.0))

                if total_sent >= max_send and initial_run:
                    return


def send_and_pin_summary(slot):
    global LAST_PINNED_SUMMARY_ID
    
    slot_titles = {
        'morning': 'Morning Briefing',
        'noon': 'Midday Update',
        'evening': 'Evening Recap',
        'manual': 'Manual Summary'
    }
    slot_title = slot_titles.get(slot, 'Daily Summary')
    today_str = datetime.date.today().strftime("%B %d, %Y")

    if not daily_news:
        text = f"📊 {slot_title} ({today_str})\n\nNo significant news during this period."
    else:
        news_block = ""
        for item in daily_news[-20:]:
            news_block += f"[{item['source']}] {item['title']}\n"

               prompt = f"""You are a concise global markets analyst. Write a very short recap — 2 to 4 bullet points maximum.
Focus exclusively on the MOST important market-moving events/trends from TODAY's news only.
Start directly with bullets. No introductions, no commentary, no extra text.
Use this exact format for each line:
- Event description in one clear sentence.

Be direct, factual, professional. Use numbers and names where relevant.
Date: {today_str}
News headlines:
{news_block}"""

        try:
            resp = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=180,
                temperature=0.65,
            )
                      summary_text = resp.choices[0].message.content.strip()
            # If LLM already gives bullets, we can just use it directly
            text = (
                f"📊 {slot_title} ({today_str}) — Key market-moving events:\n"
                f"\n"
                f"{summary_text}"
            )

            # ─── Превращаем текст в красивые пункты ───
            # Разбиваем по предложениям (очень грубо, но обычно работает для 3–5 предложений)
            sentences = [s.strip() for s in summary_text.replace('\n', ' ').split('.') if s.strip()]
            bullets = [f"* {s.strip()}{'.' if not s.endswith(('.', '!', '?')) else ''}" for s in sentences]

            formatted_summary = "\n".join(bullets) if bullets else summary_text

            text = (
                f"📊 {slot_title} ({today_str}) — Key market-moving events:\n"
                f"\n"
                f"{formatted_summary}"
            )

        except Exception as e:
            logging.error(f"Error generating summary ({slot}): {e}")
            text = (
                f"📊 {slot_title} ({today_str})\n"
                f"\n"
                f"⚠️ Failed to generate summary (Groq API issue)"
            )

    # ─── Отправка и закрепление ───
    if LAST_PINNED_SUMMARY_ID is not None:
        try:
            bot.unpin_chat_message(CHANNEL_ID, LAST_PINNED_SUMMARY_ID)
            logging.info(f"Unpinned old summary #{LAST_PINNED_SUMMARY_ID}")
        except Exception as e:
            logging.info(f"Could not unpin old message (maybe already unpinned or deleted): {e}")

    try:
        msg = bot.send_message(
            chat_id=CHANNEL_ID,
            text=text,
            parse_mode="Markdown",          # ← важно!
            disable_web_page_preview=True
        )
        new_message_id = msg.message_id

        bot.pin_chat_message(
            chat_id=CHANNEL_ID,
            message_id=new_message_id,
            disable_notification=True
        )
        logging.info(f"Pinned new summary #{new_message_id}")

        LAST_PINNED_SUMMARY_ID = new_message_id
        save_last_pinned_id()

    except Exception as e:
        logging.error(f"Failed to send/pin summary: {e}")
        # Fallback — отправляем без закрепления, но красиво
        fallback_text = text + "\n\n*(не удалось закрепить сообщение)*"
        bot.send_message(
            chat_id=CHANNEL_ID,
            text=fallback_text,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

    # чистим новости после успешной отправки
    if daily_news:
        daily_news.clear()
        
def background_checker():
    global last_check_time

    NEGATIVE_KEYWORDS = [
        'stepmother', 'estate', 'robbery', 'war in ukraine',
        'divorce', 'cheated', 'tennis', 'fiancee', 'married','hair',
        'brother',
    ]

    while True:
        logging.info("Background check started")
        time.sleep(random.randint(120, 300))

        now = datetime.datetime.now(datetime.timezone.utc)
        new_news = []

        for source_name, url in RSS_FEEDS:
            content = fetch_feed(url)
            if not content:
                continue
            feed = feedparser.parse(content)

            for entry in feed.entries[:30]:
                title_lower = (entry.get('title') or '').strip().lower()
                desc_lower = (entry.get('description') or entry.get('summary') or '').strip().lower()
                link = entry.get('link', '')
                unique = f"{title_lower}_{link[:120]}"

                if unique in sent_news:
                    continue

                pub_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
                if pub_parsed:
                    pub_time = datetime.datetime(*pub_parsed[:6], tzinfo=datetime.timezone.utc)
                    if pub_time < last_check_time - datetime.timedelta(minutes=90):
                        continue

                has_positive = any(kw.lower() in title_lower or kw.lower() in desc_lower for kw in KEYWORDS)
                has_negative = any(neg.lower() in title_lower or neg.lower() in desc_lower for neg in NEGATIVE_KEYWORDS)

                if has_positive and not has_negative:
                    sent_news.add(unique)
                    daily_news.append({
                        'title': entry.get('title', '').strip(),
                        'desc': (entry.get('description') or entry.get('summary', '')).strip(),
                        'source': source_name,
                        'pub_date': entry.get('published') or entry.get('updated', '')
                    })
                    new_news.append((entry, source_name))

        last_check_time = now

        if new_news:
            logging.info(f"Found {len(new_news)} new news items")
            for entry, source in new_news[:4]:
                send_news_photo(entry, source)
                time.sleep(random.uniform(6, 11))
            save_sent_news()
            count = min(4, len(new_news))
            send_or_update_notification(f"Posted {count} fresh news item{'s' if count != 1 else ''} 📈")
        else:
            logging.info("No new matching news found")


# ────────────────────────────────────────────────
#                SUMMARY SCHEDULER ← ИСПРАВЛЕНО!
# ────────────────────────────────────────────────

def summary_scheduler():
    tz = pytz.timezone('Asia/Bangkok')

    while True:
        now = datetime.datetime.now(tz)
        today = now.date()

        # УТРО 7:30
        if now.hour == 7 and now.minute == 30 and now.second < 30:
            if last_sent_summaries['morning'] != str(today):
                logging.info("Starting morning summary at 7:30")
                send_and_pin_summary('morning')
                last_sent_summaries['morning'] = str(today)
                save_last_sent_summaries()

        # ДЕНЬ 12:45
        if now.hour == 12 and now.minute == 45 and now.second < 30:
            if last_sent_summaries['noon'] != str(today):
                logging.info("Starting midday summary at 12:45")
                send_and_pin_summary('noon')
                last_sent_summaries['noon'] = str(today)
                save_last_sent_summaries()

        # ВЕЧЕР 20:00
        if now.hour == 20 and now.minute == 0 and now.second < 30:
            if last_sent_summaries['evening'] != str(today):
                logging.info("Starting evening summary at 20:00")
                send_and_pin_summary('evening')
                last_sent_summaries['evening'] = str(today)
                save_last_sent_summaries()

        # Проверяем каждые 20–25 секунд — теперь точно не пропустим!
        time.sleep(20 + random.uniform(0, 5))


# ────────────────────────────────────────────────
#                STARTUP
# ────────────────────────────────────────────────

load_sent_news()
load_last_notification_id()
load_last_sent_summaries()
load_last_pinned_id()

print(f"Bot started → posting to channel {CHANNEL_ID}")
logging.info(f"Bot started → channel {CHANNEL_ID}")

try:
    bot.send_message(
        CHANNEL_ID,
        "Bot started and ready to post news about major companies & markets\n"
        "If you see this message — everything is working."
    )
    print("Test message sent")
    logging.info("Test message sent")
except Exception as e:
    print(f"ERROR sending test message: {e}")
    logging.error(f"Test message not sent: {e}")

threading.Thread(target=background_checker, daemon=True).start()
threading.Thread(target=summary_scheduler, daemon=True).start()   # ← теперь работает!

@bot.message_handler(commands=['summary'])
def manual_summary(message):
    if message.chat.type == 'private':
        send_and_pin_summary('manual')
        bot.reply_to(message, "Summary posted and pinned to the channel")
    else:
        bot.reply_to(message, "The /summary command works only in private messages")

print("Running initial fresh news check...")
logging.info("Initial fresh news check")
send_recent_news(initial_run=True)
print("Initial check completed")

bot.infinity_polling(
    timeout=120,
    long_polling_timeout=90,
    interval=5
)
