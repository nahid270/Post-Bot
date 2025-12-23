# -*- coding: utf-8 -*-

import os
import io
import re
import json
import asyncio
import logging
import aiohttp
import requests 
from threading import Thread

# --- Third-party Library Imports ---
from PIL import Image, ImageDraw, ImageFont, ImageFilter
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

# ---- GLOBAL STATE ----
user_conversations = {}
user_ad_links = {}

USER_AD_LINKS_FILE = "user_ad_links.json"
DEFAULT_AD_LINK = "https://www.google.com"

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
                return {int(k): v for k, v in json.load(f).items()}
        except Exception as e:
            logger.error(f"Load JSON Error: {e}")
    return {}

# Load saved data
user_ad_links = load_json(USER_AD_LINKS_FILE)

# ---- FLASK KEEP-ALIVE ----
app = Flask(__name__)
@app.route('/')
def home(): return "🤖 Bot is Running Smoothly!"
def run_flask(): app.run(host='0.0.0.0', port=8080)

# ---- BOT INIT ----
try:
    bot = Client("moviebot", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)
except Exception as e:
    logger.critical(f"Bot Init Error: {e}")
    exit(1)

# ---- FONTS ----
try:
    FONT_BOLD = ImageFont.truetype("Poppins-Bold.ttf", 32)
    FONT_REGULAR = ImageFont.truetype("Poppins-Regular.ttf", 24)
    FONT_SMALL = ImageFont.truetype("Poppins-Regular.ttf", 18)
except:
    logger.warning("⚠️ Fonts not found, using default system fonts.")
    FONT_BOLD = FONT_REGULAR = FONT_SMALL = ImageFont.load_default()

# ---- HELPER: UPLOAD IMAGE TO CATBOX (For Manual Posts) ----
def upload_to_catbox(file_path):
    try:
        url = "https://catbox.moe/user/api.php"
        with open(file_path, "rb") as f:
            data = {"reqtype": "fileupload", "userhash": ""}
            files = {"fileToUpload": f}
            response = requests.post(url, data=data, files=files)
            if response.status_code == 200:
                return response.text.strip()
    except Exception as e:
        logger.error(f"Upload Error: {e}")
    return None

# ---- TMDB FUNCTIONS (ASYNC) ----
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

# ---- DPASTE FUNCTION (ASYNC) ----
async def create_paste_link(content):
    if not content: return None
    url = "https://dpaste.com/api/"
    data = {"content": content, "syntax": "html", "expiry_days": 14, "title": "Blogger Code"}
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    link = await fetch_url(url, method="POST", data=data, headers=headers)
    if link and "dpaste.com" in link:
        return link.strip()
    return None

# ---- HTML GENERATOR ----
def generate_html_code(data, links, ad_link):
    title = data.get("title") or data.get("name")
    overview = data.get("overview", "")
    
    # Handle Manual vs TMDB Poster
    if data.get('manual_poster_url'):
        poster = data.get('manual_poster_url')
    else:
        poster = f"https://image.tmdb.org/t/p/w500{data.get('poster_path')}" if data.get('poster_path') else ""
    
    style_html = """
    <style>
        .dl-container { font-family: 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; }
        .dl-instruction-box {
            background-color: #fff8e1; border-left: 5px solid #ffc107; padding: 15px; margin: 20px 0;
            border-radius: 5px; color: #333; box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .dl-instruction-title { font-weight: bold; font-size: 18px; margin-bottom: 10px; color: #d32f2f; }
        .dl-highlight { background-color: #ffe0b2; padding: 0 5px; border-radius: 3px; font-weight: bold; }
        .dl-download-block { margin-bottom: 20px; text-align: center; border: 1px solid #eee; padding: 10px; border-radius: 8px; }
        .dl-download-button {
            background: #007bff; color: white; border: none; padding: 12px 25px; width: 100%;
            border-radius: 5px; font-size: 16px; cursor: pointer; font-weight: bold;
            transition: background 0.3s;
        }
        .dl-download-button:hover { background: #0056b3; }
        .dl-timer-display {
            display: none;
            background: #f8d7da; color: #721c24; padding: 10px; border-radius: 5px;
            font-weight: bold; margin-top: 10px;
        }
        .dl-real-download-link {
            display: none !important;
            background: #28a745; color: white !important; text-decoration: none; padding: 12px 25px;
            text-align: center; border-radius: 5px; margin-top: 10px; font-weight: bold;
        }
        .dl-real-download-link:hover { background: #218838; }
    </style>
    """

    instruction_html = """
    <div class="dl-instruction-box">
        <div class="dl-instruction-title">⚠️ ডাউনলোড করার নিয়মাবলী:</div>
        <ul style="margin:0; padding-left:20px;">
            <li>১️⃣ প্রথমে আপনার পছন্দের <b>Download</b> বাটনে ক্লিক করুন।</li>
            <li>২️⃣ একটি <span class="dl-highlight">বিজ্ঞাপন (Ad)</span> ওপেন হবে, সেটি কেটে দিন।</li>
            <li>৩️⃣ আবার একই বাটনে ক্লিক করুন, তখন <span class="dl-highlight">১০ সেকেন্ডের টাইমার</span> শুরু হবে।</li>
            <li>৪️⃣ সময় শেষ হলে <b>Go to Link</b> বাটন আসবে, সেখানে ক্লিক করুন।</li>
        </ul>
    </div>
    """

    links_html = ""
    for link in links:
        links_html += f"""
        <div class="dl-download-block">
            <button class="dl-download-button" data-url="{link['url']}" data-click-count="0">
                ⬇️ {link['label']}
            </button>
            <div class="dl-timer-display">
                ⏳ Please Wait: <span class="timer-count">10</span>s
            </div>
            <a href="#" class="dl-real-download-link" target="_blank">
                ✅ Go to Link ({link['label']})
            </a>
        </div>"""

    return f"""
    <!-- Bot Generated Post -->
    {style_html}
    <div class="dl-container">
        <div style="text-align:center;">
            <img src="{poster}" style="max-width:100%; width:250px; border-radius:10px; box-shadow: 0 4px 8px rgba(0,0,0,0.2);">
            <h2 style="color: #333; margin-top: 15px;">{title}</h2>
            <p style="text-align: left; color: #555;">{overview}</p>
        </div>
        {instruction_html}
        <div id="dl-container">
            {links_html}
        </div>
    </div>
    <script>
    const AD_LINK = "{ad_link}";
    document.querySelectorAll('.dl-download-button').forEach(btn => {{
        btn.onclick = function() {{
            let count = parseInt(this.getAttribute('data-click-count'));
            let timerDisplay = this.nextElementSibling;
            let realLink = timerDisplay.nextElementSibling;
            let timerSpan = timerDisplay.querySelector('.timer-count');

            if(count === 0) {{
                window.open(AD_LINK, '_blank');
                this.setAttribute('data-click-count', '1');
                this.innerText = "🔄 Click Again to Start Timer";
                this.style.background = "#ff9800";
            }} else {{
                this.style.display = 'none'; 
                timerDisplay.style.display = 'block';
                let timeLeft = 10;
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
    <!-- Bot Generated Post End -->
    """

# ---- IMAGE & CAPTION GENERATOR ----
def generate_formatted_caption(data):
    title = data.get("title") or data.get("name") or "N/A"
    
    # Manual data handling
    if data.get('is_manual'):
        year = "Manual"
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
        # Determine Poster URL
        if data.get('manual_poster_url'):
            poster_url = data.get('manual_poster_url')
        else:
            poster_url = f"https://image.tmdb.org/t/p/w500{data['poster_path']}" if data.get('poster_path') else None
        
        if not poster_url: return None

        # Download Poster
        poster_bytes = requests.get(poster_url, timeout=10).content
        poster_img = Image.open(io.BytesIO(poster_bytes)).convert("RGBA").resize((400, 600))
        
        # Create Background
        bg_img = Image.new('RGBA', (1280, 720), (10, 10, 20))
        
        # Determine Backdrop
        backdrop = None
        if data.get('backdrop_path'):
            try:
                bd_url = f"https://image.tmdb.org/t/p/w1280{data['backdrop_path']}"
                bd_bytes = requests.get(bd_url, timeout=10).content
                backdrop = Image.open(io.BytesIO(bd_bytes)).convert("RGBA").resize((1280, 720))
            except: pass
        
        # If no backdrop (or Manual mode), use blurred poster as backdrop
        if not backdrop:
            backdrop = poster_img.resize((1280, 720))
            
        backdrop = backdrop.filter(ImageFilter.GaussianBlur(10))
        bg_img = Image.alpha_composite(backdrop, Image.new('RGBA', (1280, 720), (0, 0, 0, 150))) # Dark overlay

        # Paste Poster
        bg_img.paste(poster_img, (50, 60), poster_img)
        draw = ImageDraw.Draw(bg_img)
        
        # Text Drawing
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
        return img_buffer
    except Exception as e:
        logger.error(f"Img Gen Error: {e}")
        return None

# ---- BOT COMMANDS ----

@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    user_conversations.pop(message.from_user.id, None)
    await message.reply_text(
        "🎬 **Movie & Series Bot (Final v3)**\n\n"
        "⚡ `/post <Name>` - Auto Post (TMDB)\n"
        "✍️ `/manual` - Manual Post (Custom)\n"
        "🛠 `/mysettings` - View Settings\n"
        "⚙️ `/setadlink <URL>` - Set Ad Link\n\n"
    )

@bot.on_message(filters.command("mysettings") & filters.private)
async def mysettings_cmd(client, message):
    uid = message.from_user.id
    my_ad_link = user_ad_links.get(uid, "❌ Not Set (Using Default)")
    await message.reply_text(f"⚙️ **MY SETTINGS**\n🔗 Ad Link: `{my_ad_link}`", disable_web_page_preview=True)

@bot.on_message(filters.command("setadlink") & filters.private)
async def set_ad(client, message):
    if len(message.command) > 1:
        link = message.command[1]
        if link.startswith("http"):
            user_ad_links[message.from_user.id] = link
            save_json(USER_AD_LINKS_FILE, user_ad_links)
            await message.reply_text("✅ **Ad Link Saved!**")
        else:
            await message.reply_text("⚠️ Invalid Link. Must start with http/https.")

# ---- MANUAL POST COMMAND ----
@bot.on_message(filters.command("manual") & filters.private)
async def manual_post_cmd(client, message):
    uid = message.from_user.id
    user_conversations[uid] = {
        "details": {"is_manual": True}, 
        "links": [], 
        "state": "manual_title"
    }
    await message.reply_text("✍️ **Manual Post Started**\n\nপ্রথমে আপনার মুভি বা সিরিজের **টাইটেল (Title)** লিখুন:")

# ---- AUTO POST COMMAND ----
@bot.on_message(filters.command("post") & filters.private)
async def post_cmd(client, message):
    if len(message.command) < 2:
        return await message.reply_text("⚠️ Usage: `/post Avatar`")
    
    query = message.text.split(" ", 1)[1]
    msg = await message.reply_text(f"🔎 Searching for `{query}`...")
    
    results = await search_tmdb(query)
    if not results:
        return await msg.edit_text("❌ No results found.")
    
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
        await cb.message.edit_text(f"✅ Selected: **{details.get('title') or details.get('name')}**\n\n🗣️ Enter **Language** (e.g. Hindi):")
    except Exception as e:
        logger.error(f"Select Error: {e}")

# ---- CONVERSATION HANDLER (Merged Auto + Manual) ----
@bot.on_message(filters.private & ~filters.command(["start", "post", "manual", "setadlink", "mysettings"]))
async def text_handler(client, message):
    uid = message.from_user.id
    if uid not in user_conversations: return
    
    convo = user_conversations[uid]
    state = convo.get("state")
    text = message.text.strip() if message.text else ""
    
    # --- MANUAL FLOW HANDLERS ---
    if state == "manual_title":
        convo["details"]["title"] = text
        convo["state"] = "manual_plot"
        await message.reply_text("📝 এবার মুভির **গল্প/Plot** লিখুন:")
        
    elif state == "manual_plot":
        convo["details"]["overview"] = text
        convo["state"] = "manual_poster"
        await message.reply_text("🖼️ এবার একটি **পোস্টার (Photo)** সেন্ড করুন:")
        
    elif state == "manual_poster":
        if not message.photo:
            return await message.reply_text("⚠️ দয়া করে একটি ছবি (Photo) পাঠান।")
        
        msg = await message.reply_text("⏳ Processing Image...")
        try:
            # Download & Upload to Cloud
            photo_path = await message.download()
            img_url = upload_to_catbox(photo_path)
            os.remove(photo_path) # Clean up
            
            if img_url:
                convo["details"]["manual_poster_url"] = img_url
                convo["state"] = "ask_links" # Jump to Link Section
                
                buttons = [
                    [InlineKeyboardButton("➕ Add Links", callback_data=f"lnk_yes_{uid}")],
                    [InlineKeyboardButton("🏁 Finish", callback_data=f"lnk_no_{uid}")]
                ]
                await msg.edit_text("✅ ছবি আপলোড হয়েছে!\n\n🔗 এবার ডাউনলোড লিংক অ্যাড করবেন?", reply_markup=InlineKeyboardMarkup(buttons))
            else:
                await msg.edit_text("❌ ইমেজ আপলোড ফেইল হয়েছে। আবার চেষ্টা করুন।")
        except Exception as e:
            logger.error(f"Manual Poster Error: {e}")
            await msg.edit_text("❌ এরর হয়েছে।")

    # --- AUTO FLOW HANDLERS ---
    elif state == "wait_lang":
        convo["details"]["custom_language"] = text
        convo["state"] = "wait_quality"
        await message.reply_text("💿 Enter **Quality** (e.g. 720p):")
        
    elif state == "wait_quality":
        convo["details"]["custom_quality"] = text
        convo["state"] = "ask_links"
        buttons = [
            [InlineKeyboardButton("➕ Add Links", callback_data=f"lnk_yes_{uid}")],
            [InlineKeyboardButton("🏁 Finish", callback_data=f"lnk_no_{uid}")]
        ]
        await message.reply_text("🔗 Add Download Links?", reply_markup=InlineKeyboardMarkup(buttons))
        
    # --- COMMON LINK HANDLERS ---
    elif state == "wait_link_name":
        convo["temp_name"] = text
        convo["state"] = "wait_link_url"
        await message.reply_text("🔗 Enter **URL** for this button:")
        
    elif state == "wait_link_url":
        if text.startswith("http"):
            convo["links"].append({"label": convo["temp_name"], "url": text})
            convo["state"] = "ask_links"
            buttons = [
                [InlineKeyboardButton("➕ Add Another", callback_data=f"lnk_yes_{uid}")],
                [InlineKeyboardButton("🏁 Finish", callback_data=f"lnk_no_{uid}")]
            ]
            await message.reply_text(f"✅ Added! Total: {len(convo['links'])}", reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await message.reply_text("⚠️ Invalid URL. Try again.")

@bot.on_callback_query(filters.regex("^lnk_"))
async def link_cb(client, cb):
    try:
        action, uid_str = cb.data.rsplit("_", 1)
        uid = int(uid_str)
    except: return
    
    if uid != cb.from_user.id: return await cb.answer("Not for you!", show_alert=True)
    
    if action == "lnk_yes":
        user_conversations[uid]["state"] = "wait_link_name"
        await cb.message.edit_text("📝 বাটনের নাম লিখুন (Example: 720p Download):")
    else:
        await generate_final_post(client, uid, cb.message)

async def generate_final_post(client, uid, message):
    if uid not in user_conversations: return await message.edit_text("❌ Session expired.")
    convo = user_conversations[uid]
    await message.edit_text("⏳ Generating HTML & Image...")
    
    # Image Generation
    loop = asyncio.get_running_loop()
    img_io = await loop.run_in_executor(None, generate_image, convo["details"])
    
    ad_link = user_ad_links.get(uid, DEFAULT_AD_LINK)
    html = generate_html_code(convo["details"], convo["links"], ad_link)
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

if __name__ == "__main__":
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    print("🚀 Bot Started Successfully!")
    bot.run()
