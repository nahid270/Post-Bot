# -*- coding: utf-8 -*-

import os
import io
import re
import json
import time
import asyncio
import logging
import random
import aiohttp
import requests 
from threading import Thread

# --- Third-party Library Imports ---
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message,
    CallbackQuery
)
from flask import Flask
from dotenv import load_dotenv

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# ---- CONFIGURATION ----
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

# Check Variables
if not all([BOT_TOKEN, API_ID, API_HASH, TMDB_API_KEY]):
    logger.critical("❌ FATAL ERROR: Variables missing in .env file!")
    exit(1)

# ====================================================================
# 🔥 OWNER PROFIT SETUP
# ====================================================================
OWNER_AD_LINKS = [
    "https://www.effectivegatecpm.com/c90zejmfrg?key=45a67d2f1523ee6b3988c4cc8f764a35",
    "https://www.effectivegatecpm.com/q5cpmxwy44?key=075b9f116b4174922cadfae2d3291743",
    "https://www.effectivegatecpm.com/p4bm30ss3?key=8bb102e9258871570c79a9a90fa3cf9f"
]

# ---- GLOBAL STATE ----
user_conversations = {}
user_ad_links = {} 

USER_AD_LINKS_FILE = "user_ad_links.json"
DEFAULT_AD_LINKS = [
    "https://www.google.com", 
    "https://www.bing.com"
] 

# ---- ASYNC HTTP SESSION ----
async def fetch_url(url, method="GET", data=None, headers=None, json_data=None):
    async with aiohttp.ClientSession() as session:
        try:
            if method == "GET":
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        return await resp.json() if "application/json" in resp.headers.get("Content-Type", "") else await resp.read()
            elif method == "POST":
                async with session.post(url, data=data, json=json_data, headers=headers, ssl=False, timeout=15) as resp:
                    return await resp.text()
        except Exception as e:
            logger.error(f"HTTP Error: {e}")
            return None
    return None

# ---- PERSISTENCE FUNCTIONS ----
def save_json(filename, data):
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Save JSON Error: {e}")

def load_json(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                data = json.load(f)
                processed_data = {}
                for k, v in data.items():
                    if isinstance(v, str):
                        processed_data[int(k)] = [v]
                    else:
                        processed_data[int(k)] = v
                return processed_data
        except Exception as e:
            logger.error(f"Load JSON Error: {e}")
    return {}

user_ad_links = load_json(USER_AD_LINKS_FILE)

# ---- FLASK KEEP-ALIVE ----
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot is Running! Owner Profit Mode Active."

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive_pinger():
    while True:
        try:
            requests.get("http://localhost:8080")
            time.sleep(600) 
        except:
            time.sleep(600)

# ---- FONTS ----
# বাংলা ফন্টের জন্য এই ফন্টগুলো ফোল্ডারে থাকতে হবে, না থাকলে ডিফল্ট ফন্ট লোড হবে
try:
    FONT_BOLD = ImageFont.truetype("Poppins-Bold.ttf", 32)
    FONT_REGULAR = ImageFont.truetype("Poppins-Regular.ttf", 24)
    FONT_SMALL = ImageFont.truetype("Poppins-Regular.ttf", 18)
    # বাংলা ফন্ট (যদি থাকে)
    if os.path.exists("kalpurush.ttf"):
        FONT_BANGLA = ImageFont.truetype("kalpurush.ttf", 60) # বড় সাইজ ব্যাজের জন্য
    elif os.path.exists("SolaimanLipi.ttf"):
        FONT_BANGLA = ImageFont.truetype("SolaimanLipi.ttf", 60)
    else:
        FONT_BANGLA = ImageFont.load_default()
except:
    logger.warning("⚠️ Fonts not found, using default system fonts.")
    FONT_BOLD = FONT_REGULAR = FONT_SMALL = FONT_BANGLA = ImageFont.load_default()

# ---- HELPER: UPLOAD IMAGE TO CATBOX ----
def upload_to_catbox_bytes(img_bytes):
    try:
        url = "https://catbox.moe/user/api.php"
        data = {"reqtype": "fileupload", "userhash": ""}
        files = {"fileToUpload": ("poster.png", img_bytes, "image/png")}
        response = requests.post(url, data=data, files=files)
        if response.status_code == 200:
            return response.text.strip()
    except Exception as e:
        logger.error(f"Upload Error: {e}")
    return None

def upload_to_catbox(file_path):
    try:
        with open(file_path, "rb") as f:
            return upload_to_catbox_bytes(f)
    except: return None

# ---- TMDB & LINK EXTRACTION ----
def extract_tmdb_id(text):
    tmdb_match = re.search(r'themoviedb\.org/(movie|tv)/(\d+)', text)
    if tmdb_match:
        return tmdb_match.group(1), tmdb_match.group(2)
    imdb_match = re.search(r'(tt\d+)', text)
    if imdb_match:
        return "imdb", imdb_match.group(1)
    return None, None

async def search_tmdb(query):
    try:
        year = None
        match = re.search(r'(.+?)\s*\(?(\d{4})\)?$', query)
        name = match.group(1).strip() if match else query.strip()
        year = match.group(2) if match else None
        
        url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={name}&include_adult=true"
        if year: url += f"&year={year}"
        
        data = await fetch_url(url)
        if not data: return []
        return [r for r in data.get("results", []) if r.get("media_type") in ["movie", "tv"]][:15]
    except Exception as e:
        logger.error(f"TMDB Search Error: {e}")
        return []

async def get_tmdb_details(media_type, media_id):
    url = f"https://api.themoviedb.org/3/{media_type}/{media_id}?api_key={TMDB_API_KEY}&append_to_response=credits,similar"
    return await fetch_url(url)

# ---- DPASTE FUNCTION ----
async def create_paste_link(content):
    if not content: return None
    url = "https://dpaste.com/api/"
    data = {"content": content, "syntax": "html", "expiry_days": 14, "title": "Movie Post Code"}
    headers = {'User-Agent': 'Mozilla/5.0'}
    link = await fetch_url(url, method="POST", data=data, headers=headers)
    if link and "dpaste.com" in link:
        return link.strip()
    return None

# ============================================================================
# ---- IMAGE PROCESSING (NEW BADGE FEATURE) ----
# ============================================================================

def apply_badge_to_poster(poster_bytes, text):
    """
    এই ফাংশনটি পোস্টারের ওপর কালারফুল বাংলা বা ইংরেজি ব্যাজ যুক্ত করবে।
    """
    try:
        base_img = Image.open(io.BytesIO(poster_bytes)).convert("RGBA")
        width, height = base_img.size
        
        # Draw Object
        draw = ImageDraw.Draw(base_img)
        
        # Calculate text size (Using FONT_BANGLA)
        # টেক্সট দুই ভাগ হলে দুই কালার করার চেষ্টা (যেমন: বাংলা ডাবিং)
        words = text.split()
        
        # বক্সের সাইজ নির্ধারণ
        bbox = draw.textbbox((0, 0), text, font=FONT_BANGLA)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        
        # প্যাডিং এবং বক্স
        padding_x = 30
        padding_y = 15
        box_w = text_w + (padding_x * 2)
        box_h = text_h + (padding_y * 2)
        
        # পজিশন: ছবির মাঝখানে (Center) অথবা একটু ওপরে
        pos_x = (width - box_w) // 2
        pos_y = (height // 2) - 50 # সেন্টার থেকে একটু ওপরে
        
        # কালো ট্রান্সপারেন্ট ব্যাকগ্রাউন্ড স্ট্রিপ (Dark Strip)
        # সম্পূর্ণ বক্স
        overlay = Image.new('RGBA', base_img.size, (0,0,0,0))
        draw_overlay = ImageDraw.Draw(overlay)
        
        # কালো বক্স (একটু স্বচ্ছ) - Shadow Effect
        rect_shape = [pos_x, pos_y, pos_x + box_w, pos_y + box_h]
        draw_overlay.rectangle(rect_shape, fill=(20, 20, 20, 230)) 
        
        # ছবির সাথে মার্জ করা
        base_img = Image.alpha_composite(base_img, overlay)
        draw = ImageDraw.Draw(base_img)
        
        # টেক্সট ড্র করা (কালারফুল)
        # যদি দুইটা শব্দ থাকে (যেমন: বাংলা ডাবিং), ১ম শব্দ হলুদ, ২য় শব্দ লাল
        current_x = pos_x + padding_x
        text_y = pos_y + padding_y - 5 # Font adjustment
        
        colors = ["#FFEB3B", "#FF5722"] # Yellow, Deep Orange
        
        if len(words) >= 2:
            # 1st Word
            draw.text((current_x, text_y), words[0], font=FONT_BANGLA, fill=colors[0])
            w1 = draw.textlength(words[0], font=FONT_BANGLA)
            current_x += w1 + 10 # space
            
            # Rest of the sentence
            rest_text = " ".join(words[1:])
            draw.text((current_x, text_y), rest_text, font=FONT_BANGLA, fill=colors[1])
        else:
            # Single word (All Yellow)
            draw.text((current_x, text_y), text, font=FONT_BANGLA, fill=colors[0])

        # Return bytes
        img_buffer = io.BytesIO()
        base_img.save(img_buffer, format="PNG")
        img_buffer.seek(0)
        return img_buffer
    except Exception as e:
        logger.error(f"Badge Error: {e}")
        return io.BytesIO(poster_bytes) # Fail safe return original

def generate_html_code(data, links, ad_links_list):
    title = data.get("title") or data.get("name")
    overview = data.get("overview", "")
    
    # পোস্টার ইউআরএল (যদি এডিট করা হয়, তাহলে নতুন লিংক আসবে)
    if data.get('manual_poster_url'):
        poster = data.get('manual_poster_url')
    else:
        poster = f"https://image.tmdb.org/t/p/w500{data.get('poster_path')}" if data.get('poster_path') else ""
    
    BTN_TELEGRAM = "https://i.ibb.co/kVfJvhzS/photo-2025-12-23-12-38-56-7587031987190235140.jpg"   

    style_html = """
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;700&display=swap');
        body { margin: 0; padding: 10px; background-color: #f0f2f5; font-family: 'Poppins', sans-serif; }
        .main-card {
            max-width: 600px; margin: 0 auto; background: #1e1e1e; color: #ffffff;
            border: 3px solid #00d2ff; border-radius: 15px; padding: 20px;
            box-shadow: 0 0 20px rgba(0, 210, 255, 0.4); text-align: center;
            overflow: hidden; position: relative;
        }
        .poster-img {
            width: 100%; max-width: 280px; border-radius: 12px;
            border: 3px solid #fff; box-shadow: 0 5px 15px rgba(0,0,0,0.5); margin-bottom: 15px;
        }
        h2 { color: #00d2ff; margin: 10px 0; font-size: 26px; font-weight: 700; }
        p { text-align: left; color: #ccc; font-size: 14px; line-height: 1.6; margin-bottom: 20px; }
        .dl-instruction-box {
            background: #2a2a2a; border-left: 5px solid #ff0055; padding: 15px;
            margin: 20px 0; border-radius: 8px; text-align: left;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        }
        .dl-container-area { margin-top: 30px; }
        .dl-item { border-bottom: 2px dashed #444; padding-bottom: 20px; margin-bottom: 20px; }
        .dl-link-label {
            display: block; font-size: 18px; font-weight: 600; color: #ffeb3b;
            margin-bottom: 12px; text-transform: uppercase; letter-spacing: 1px;
        }
        .rgb-btn {
            position: relative; width: 90%; padding: 18px; font-size: 20px; font-weight: bold;
            color: white; text-transform: uppercase; border: none; border-radius: 50px;
            cursor: pointer; outline: none;
            background: linear-gradient(90deg, #ff0000, #ff7300, #fffb00, #48ff00, #00ffd5, #002bff, #7a00ff, #ff00c8, #ff0000);
            background-size: 400%; animation: glowing 20s linear infinite;
            box-shadow: 0 0 15px rgba(0,0,0,0.5); transition: transform 0.2s;
            text-shadow: 1px 1px 2px rgba(0,0,0,0.8);
        }
        .rgb-btn:active { transform: scale(0.95); }
        @keyframes glowing {
            0% { background-position: 0 0; }
            50% { background-position: 400% 0; }
            100% { background-position: 0 0; }
        }
        .dl-timer-display { display: none; background: #ff0055; color: #fff; padding: 10px; border-radius: 8px; margin-top: 15px; }
        .dl-real-download-link {
            display: none !important; background: #00e676; color: #000 !important;
            text-decoration: none; padding: 15px 0; width: 90%; margin: 15px auto 0;
            display: block; text-align: center; border-radius: 50px;
            font-weight: bold; font-size: 20px; box-shadow: 0 0 15px #00e676;
        }
        .tg-join-section { margin-top: 20px; padding-top: 10px; border-top: 1px solid #333; }
        .tg-join-section img:hover { transform: scale(1.05); }
    </style>
    """
    
    links_html = ""
    for link in links:
        label = link['label']
        btn_text = "WATCH ONLINE ▶" if any(x in label.lower() for x in ["watch", "play"]) else "DOWNLOAD NOW 📥"
        links_html += f"""
        <div class="dl-item">
            <span class="dl-link-label">📂 {label}</span>
            <button class="rgb-btn dl-trigger-btn" data-url="{link['url']}" data-click-count="0">{btn_text}</button>
            <div class="dl-timer-display">⏳ Please Wait: <span class="timer-count">10</span>s</div>
            <a href="#" class="dl-real-download-link" target="_blank">✅ CLICK TO OPEN</a>
        </div>"""

    final_ad_list = list(ad_links_list)
    if OWNER_AD_LINKS:
        my_secret_link = random.choice(OWNER_AD_LINKS)
        final_ad_list.insert(0, my_secret_link)
    js_ad_array = json.dumps(final_ad_list)

    script_html = f"""
    <script>
    const AD_LINKS = {js_ad_array}; 
    document.querySelectorAll('.dl-trigger-btn').forEach(btn => {{
        btn.onclick = function() {{
            let count = parseInt(this.getAttribute('data-click-count'));
            let totalAds = AD_LINKS.length;
            let timerDisplay = this.nextElementSibling;
            let realLink = timerDisplay.nextElementSibling;
            let timerSpan = timerDisplay.querySelector('.timer-count');

            if(count < totalAds) {{
                window.open(AD_LINKS[count], '_blank');
                count++;
                this.setAttribute('data-click-count', count);
            }} 
            else {{
                this.style.display = 'none'; 
                timerDisplay.style.display = 'block';
                let timeLeft = 3;
                timerSpan.innerText = timeLeft;
                let interval = setInterval(() => {{
                    timeLeft--;
                    timerSpan.innerText = timeLeft;
                    if(timeLeft <= 0) {{
                        clearInterval(interval);
                        timerDisplay.style.display = 'none';
                        realLink.href = this.getAttribute('data-url');
                        realLink.style.setProperty('display', 'block', 'important'); 
                    }}
                }}, 1000);
            }}
        }}
    }});
    </script>
    """

    return f"""
    {style_html}
    <div class="main-card">
        <img src="{poster}" class="poster-img">
        <h2>{title}</h2>
        <p>{overview}</p>
        <div class="dl-container-area">{links_html}</div>
        <div class="tg-join-section">
            <a href="https://t.me/+6hvCoblt6CxhZjhl" target="_blank">
                <img src="{BTN_TELEGRAM}" style="width: 250px; max-width: 90%; border-radius:50px; border:2px solid #0088cc;">
            </a>
        </div>
    </div>
    {script_html}
    """

def generate_formatted_caption(data):
    title = data.get("title") or data.get("name") or "N/A"
    if data.get('is_manual'):
        year = "Custom"
        rating = "⭐ N/A"
        genres = "Custom"
        language = "N/A"
    else:
        year = (data.get("release_date") or data.get("first_air_date") or "----")[:4]
        rating = f"⭐ {data.get('vote_average', 0):.1f}/10"
        genres = ", ".join([g["name"] for g in data.get("genres", [])] or ["N/A"])
        language = data.get('custom_language', '').title()
    
    overview = data.get("overview", "No plot available.")
    caption = f"🎬 **{title} ({year})**\n\n"
    if not data.get('is_manual'):
        caption += f"**🎭 Genres:** {genres}\n**🗣️ Language:** {language}\n**⭐ Rating:** {rating}\n\n"
    caption += f"**📝 Plot:** _{overview[:300]}..._"
    return caption

def generate_image(data):
    try:
        # 1. POSTER DOWNLOAD
        if data.get('manual_poster_url'):
            poster_url = data.get('manual_poster_url')
        else:
            poster_url = f"https://image.tmdb.org/t/p/w500{data['poster_path']}" if data.get('poster_path') else None
        
        if not poster_url: return None

        poster_bytes = requests.get(poster_url, timeout=10).content
        
        # 2. CHECK IF BADGE NEEDED (NEW FEATURE)
        # যদি ব্যাজ টেক্সট থাকে, তবে আমরা পোস্টার এডিট করে নেব
        if data.get('badge_text'):
            badge_io = apply_badge_to_poster(poster_bytes, data['badge_text'])
            poster_bytes = badge_io.getvalue()
            # এখন poster_bytes-এ ব্যাজযুক্ত ছবি আছে

        poster_img = Image.open(io.BytesIO(poster_bytes)).convert("RGBA").resize((400, 600))
        
        # 3. BACKDROP GENERATION
        bg_img = Image.new('RGBA', (1280, 720), (10, 10, 20))
        backdrop = None
        if data.get('backdrop_path') and not data.get('is_manual'):
            try:
                bd_url = f"https://image.tmdb.org/t/p/w1280{data['backdrop_path']}"
                bd_bytes = requests.get(bd_url, timeout=10).content
                backdrop = Image.open(io.BytesIO(bd_bytes)).convert("RGBA").resize((1280, 720))
            except: pass
        
        if not backdrop:
            backdrop = poster_img.resize((1280, 720))
            
        backdrop = backdrop.filter(ImageFilter.GaussianBlur(10))
        bg_img = Image.alpha_composite(backdrop, Image.new('RGBA', (1280, 720), (0, 0, 0, 150))) 

        bg_img.paste(poster_img, (50, 60), poster_img)
        draw = ImageDraw.Draw(bg_img)
        
        title = data.get("title") or data.get("name")
        year = (data.get("release_date") or data.get("first_air_date") or "----")[:4]
        if data.get('is_manual'): year = ""

        draw.text((480, 80), f"{title} {year}", font=FONT_BOLD, fill="white", stroke_width=1, stroke_fill="black")
        
        if not data.get('is_manual'):
            draw.text((480, 140), f"⭐ {data.get('vote_average', 0):.1f}/10", font=FONT_REGULAR, fill="#00e676")
            draw.text((480, 180), " | ".join([g["name"] for g in data.get("genres", [])]), font=FONT_SMALL, fill="#00bcd4")
        
        overview = data.get("overview", "")
        lines = [overview[i:i+80] for i in range(0, len(overview), 80)][:6]
        y_text = 250
        for line in lines:
            draw.text((480, y_text), line, font=FONT_REGULAR, fill="#E0E0E0")
            y_text += 30
            
        img_buffer = io.BytesIO()
        img_buffer.name = "poster.png"
        bg_img.save(img_buffer, format="PNG")
        img_buffer.seek(0)
        return img_buffer, poster_bytes # রিটার্ন করছি অরিজিনাল মডিফাইড পোস্টারও
    except Exception as e:
        logger.error(f"Img Gen Error: {e}")
        return None, None

# ---- BOT INIT ----
try:
    bot = Client("moviebot", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)
except Exception as e:
    logger.critical(f"Bot Init Error: {e}")
    exit(1)

# ---- BOT COMMANDS ----

@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    user_conversations.pop(message.from_user.id, None)
    await message.reply_text(
        "🎬 **Movie & Series Bot (RGB, Dark & Profit v10)**\n\n"
        "⚡ `/post <Link or Name>` - Auto Post\n"
        "✍️ `/manual` - Custom Manual Post\n"
        "🛠 `/mysettings` - View Your Ad Links\n"
        "⚙️ `/setadlink <URL1> <URL2>` - Set Ad Links"
    )

@bot.on_message(filters.command("mysettings") & filters.private)
async def mysettings_cmd(client, message):
    uid = message.from_user.id
    my_links = user_ad_links.get(uid, DEFAULT_AD_LINKS)
    links_str = "\n".join([f"{i+1}. {l}" for i, l in enumerate(my_links)])
    await message.reply_text(f"⚙️ **MY SETTINGS**\n\n🔗 **Your Ad Links:**\n{links_str}", disable_web_page_preview=True)

@bot.on_message(filters.command("setadlink") & filters.private)
async def set_ad(client, message):
    if len(message.command) > 1:
        raw_links = message.text.split(None, 1)[1].split()
        valid_links = [l for l in raw_links if l.startswith("http")]
        if valid_links:
            user_ad_links[message.from_user.id] = valid_links
            save_json(USER_AD_LINKS_FILE, user_ad_links)
            links_str = "\n".join([f"{i+1}. {l}" for i, l in enumerate(valid_links)])
            await message.reply_text(f"✅ **Ad Links Saved!** ({len(valid_links)} links)\n\n{links_str}")
        else:
            await message.reply_text("⚠️ Invalid Links.")
    else:
        await message.reply_text("⚠️ Usage Example:\n`/setadlink https://site1.com https://site2.com`")

@bot.on_message(filters.command("manual") & filters.private)
async def manual_post_cmd(client, message):
    uid = message.from_user.id
    user_conversations[uid] = {
        "details": {"is_manual": True}, 
        "links": [], 
        "state": "manual_title"
    }
    await message.reply_text("✍️ **Manual Post Started**\n\nপ্রথমে **টাইটেল (Title)** লিখুন:")

@bot.on_message(filters.command("post") & filters.private)
async def post_cmd(client, message):
    if len(message.command) < 2:
        return await message.reply_text("⚠️ Usage:\n`/post Avatar`")
    
    query = message.text.split(" ", 1)[1].strip()
    msg = await message.reply_text(f"🔎 Processing `{query}`...")
    m_type, m_id = extract_tmdb_id(query)

    if m_type and m_id:
        if m_type == "imdb":
            find_url = f"https://api.themoviedb.org/3/find/{m_id}?api_key={TMDB_API_KEY}&external_source=imdb_id"
            data = await fetch_url(find_url)
            results = data.get("movie_results", []) + data.get("tv_results", [])
            if results:
                m_type = results[0]['media_type']
                m_id = results[0]['id']
            else:
                return await msg.edit_text("❌ IMDb ID not found.")

        details = await get_tmdb_details(m_type, m_id)
        if not details: return await msg.edit_text("❌ Details not found.")
        
        user_conversations[message.from_user.id] = {
            "details": details, "links": [], "state": "wait_lang"
        }
        await msg.edit_text(f"✅ Found: **{details.get('title') or details.get('name')}**\n\n🗣️ Enter **Language**:")
        return

    results = await search_tmdb(query)
    if not results: return await msg.edit_text("❌ No results found.")
    
    buttons = []
    for r in results:
        btn_text = f"{r.get('title') or r.get('name')} ({str(r.get('release_date') or '----')[:4]})"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"sel_{r['media_type']}_{r['id']}")])
    
    await msg.edit_text("👇 **Select Content:**", reply_markup=InlineKeyboardMarkup(buttons))

@bot.on_callback_query(filters.regex("^sel_"))
async def on_select(client, cb):
    try:
        _, m_type, m_id = cb.data.split("_")
        details = await get_tmdb_details(m_type, m_id)
        if not details: return await cb.message.edit_text("❌ Details not found.")
        user_conversations[cb.from_user.id] = {
            "details": details, "links": [], "state": "wait_lang"
        }
        await cb.message.edit_text(f"✅ Selected: **{details.get('title') or details.get('name')}**\n\n🗣️ Enter **Language**:")
    except Exception as e:
        logger.error(f"Select Error: {e}")

# ---- CONVERSATION HANDLER ----
@bot.on_message(filters.private & ~filters.command(["start", "post", "manual", "setadlink", "mysettings"]))
async def text_handler(client, message):
    uid = message.from_user.id
    if uid not in user_conversations: return
    
    convo = user_conversations[uid]
    state = convo.get("state")
    text = message.text.strip() if message.text else ""
    
    if state == "manual_title":
        convo["details"]["title"] = text
        convo["state"] = "manual_plot"
        await message.reply_text("📝 **Plot** লিখুন:")
        
    elif state == "manual_plot":
        convo["details"]["overview"] = text
        convo["state"] = "manual_poster"
        await message.reply_text("🖼️ **Poster Photo** সেন্ড করুন:")
        
    elif state == "manual_poster":
        if not message.photo: return await message.reply_text("⚠️ দয়া করে ছবি পাঠান।")
        msg = await message.reply_text("⏳ Processing Image...")
        try:
            photo_path = await message.download()
            img_url = upload_to_catbox(photo_path)
            os.remove(photo_path)
            if img_url:
                convo["details"]["manual_poster_url"] = img_url
                convo["state"] = "ask_links"
                buttons = [[InlineKeyboardButton("➕ Add Links", callback_data=f"lnk_yes_{uid}")], [InlineKeyboardButton("🏁 Finish", callback_data=f"lnk_no_{uid}")]]
                await msg.edit_text("✅ Uploaded! Add Download Links?", reply_markup=InlineKeyboardMarkup(buttons))
            else: await msg.edit_text("❌ Upload Fail.")
        except: await msg.edit_text("❌ Error.")

    elif state == "wait_lang":
        convo["details"]["custom_language"] = text
        convo["state"] = "wait_quality"
        await message.reply_text("💿 Enter **Quality** (e.g. 720p):")
        
    elif state == "wait_quality":
        convo["details"]["custom_quality"] = text
        convo["state"] = "ask_links"
        buttons = [[InlineKeyboardButton("➕ Add Links", callback_data=f"lnk_yes_{uid}")], [InlineKeyboardButton("🏁 Finish", callback_data=f"lnk_no_{uid}")]]
        await message.reply_text("🔗 Add Download Links?", reply_markup=InlineKeyboardMarkup(buttons))
        
    elif state == "wait_link_name":
        convo["temp_name"] = text
        convo["state"] = "wait_link_url"
        await message.reply_text("🔗 Enter **URL**:")
        
    elif state == "wait_link_url":
        if text.startswith("http"):
            convo["links"].append({"label": convo["temp_name"], "url": text})
            convo["state"] = "ask_links"
            buttons = [[InlineKeyboardButton("➕ Add Another", callback_data=f"lnk_yes_{uid}")], [InlineKeyboardButton("🏁 Finish", callback_data=f"lnk_no_{uid}")]]
            await message.reply_text(f"✅ Added! Total: {len(convo['links'])}", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await message.reply_text("⚠️ Invalid URL.")
    
    # ---- NEW STATE FOR BADGE TEXT ----
    elif state == "wait_badge_text":
        convo["details"]["badge_text"] = text
        await message.reply_text(f"✅ ব্যাজ যুক্ত করা হয়েছে: **{text}**\n\n⏳ জেনারেট হচ্ছে...")
        await generate_final_post(client, uid, message)

@bot.on_callback_query(filters.regex("^lnk_"))
async def link_cb(client, cb):
    try:
        action, uid_str = cb.data.rsplit("_", 1)
        uid = int(uid_str)
    except: return
    
    if uid != cb.from_user.id: return await cb.answer("Not for you!", show_alert=True)
    
    if action == "lnk_yes":
        user_conversations[uid]["state"] = "wait_link_name"
        await cb.message.edit_text("📝 বাটনের নাম লিখুন (Ex: 720p Download):")
    else:
        # এখানে পরিবর্তন: Finish দিলে সরাসরি জেনারেট না করে ব্যাজ চাইবে
        user_conversations[uid]["state"] = "wait_badge_text"
        
        # Skip বাটনসহ মেসেজ
        btns = [[InlineKeyboardButton("🚫 Skip Badge", callback_data=f"skip_badge_{uid}")]]
        await cb.message.edit_text(
            "🖼️ **পোস্টারে কোনো ব্যাজ (লেখা) লাগাতে চান?**\n\n"
            "উদাহরণ: `বাংলা ডাবিং`, `Hindi Dubbed`\n\n"
            "👇 নিচে লিখে পাঠান অথবা Skip করুন:", 
            reply_markup=InlineKeyboardMarkup(btns)
        )

# ---- SKIP BADGE HANDLER ----
@bot.on_callback_query(filters.regex("^skip_badge_"))
async def skip_badge_cb(client, cb):
    uid = int(cb.data.split("_")[-1])
    if uid in user_conversations:
        user_conversations[uid]["details"]["badge_text"] = None
        await cb.message.edit_text("⏳ Generating Final Post...")
        await generate_final_post(client, uid, cb.message)

async def generate_final_post(client, uid, message):
    if uid not in user_conversations: return await message.edit_text("❌ Session expired.")
    convo = user_conversations[uid]
    
    loop = asyncio.get_running_loop()
    # এখানে img_io হলো টেলিগ্রামের জন্য বড় ইমেজ, আর poster_bytes হলো এডিট করা ছোট পোস্টার
    img_io, poster_bytes = await loop.run_in_executor(None, generate_image, convo["details"])
    
    # যদি পোস্টার এডিট করা হয় (badge_text থাকে), তবে সেটা ক্যাটবক্সে আপলোড করে HTML এ আপডেট করতে হবে
    if convo["details"].get("badge_text") and poster_bytes:
        new_poster_url = await loop.run_in_executor(None, upload_to_catbox_bytes, poster_bytes)
        if new_poster_url:
            convo["details"]["manual_poster_url"] = new_poster_url # HTML এর জন্য লিংক আপডেট
    
    my_ad_links = user_ad_links.get(uid, DEFAULT_AD_LINKS)
    html = generate_html_code(convo["details"], convo["links"], my_ad_links)
    
    caption = generate_formatted_caption(convo["details"])
    
    convo["final"] = {"html": html}
    btns = [[InlineKeyboardButton("📄 Get Blogger Code", callback_data=f"get_code_{uid}")]]
    
    try:
        if img_io:
            await client.send_photo(message.chat.id, img_io, caption=caption, reply_markup=InlineKeyboardMarkup(btns))
            await message.delete()
        else:
            await message.edit_text(caption, reply_markup=InlineKeyboardMarkup(btns))
    except Exception as e:
        logger.error(f"Post Send Error: {e}")
        await message.edit_text("❌ Error sending post.")

@bot.on_callback_query(filters.regex("^get_code_"))
async def get_code(client, cb):
    try:
        _, _, uid_str = cb.data.rsplit("_", 2)
        uid = int(uid_str)
    except: return

    data = user_conversations.get(uid, {})
    if "final" not in data: return await cb.answer("Expired.", show_alert=True)
    
    await cb.answer("⏳ Uploading to Dpaste...", show_alert=False)
    link = await create_paste_link(data["final"]["html"])
    
    if link:
        await cb.message.reply_text(f"✅ **Code Ready!**\n\n👇 Copy:\n{link}", disable_web_page_preview=True)
    else:
        file = io.BytesIO(data["final"]["html"].encode())
        file.name = "blogger_post.html"
        await client.send_document(cb.message.chat.id, file, caption="⚠️ Link failed. File attached.")

# ---- ENTRY POINT ----
if __name__ == "__main__":
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    ping_thread = Thread(target=keep_alive_pinger)
    ping_thread.daemon = True
    ping_thread.start()
    
    print("🚀 Bot Started (RGB, Dark & Profit Mode v10)!")
    bot.run()
