import asyncio
import os
import re
import time
from threading import Thread
import requests
import urllib.parse

import discord
from discord import app_commands
from flask import Flask
from google import genai
from google.genai import types

# =========================
# HEALTH CHECK
# =========================
app = Flask(__name__)

@app.get("/")
def home():
    return "Miko Hakurei Reimu đang trực đền và đếm tiền công đức!"

def run_health_server():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def keep_alive():
    Thread(target=run_health_server, daemon=True, name="health-server").start()

# =========================
# CẤU HÌNH API GEMINI CHÍNH CHỦ
# =========================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
api_key_env = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEYS", "")
GEMINI_API_KEY = api_key_env.split(",")[0].strip() if api_key_env else ""

# Bạn có thể đổi tên model trên Render qua biến OPENAI_MODEL, nếu không có sẽ mặc định lấy 3.8
MODEL_NAME = os.getenv("OPENAI_MODEL", "gemini-3.8-flash").strip()

try: CHAT_CHANNEL_ID = int(os.getenv("CHAT_CHANNEL_ID", "0") or "0")
except ValueError: CHAT_CHANNEL_ID = 0

if not GEMINI_API_KEY:
    print("⚠️ CẢNH BÁO: Chưa cấu hình API KEY!")

ai_client = genai.Client(api_key=GEMINI_API_KEY)

# =========================
# TRA CỨU BÁCH KHOA TOÀN THƯ
# =========================
def fetch_wiki_data(query):
    try:
        search_url = f"https://vi.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&utf8=&format=json"
        res = requests.get(search_url, timeout=3)
        if res.status_code == 200:
            search_data = res.json()
            if search_data.get("query", {}).get("search"):
                title = search_data["query"]["search"][0]["title"]
                sum_res = requests.get(f"https://vi.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}", timeout=3)
                if sum_res.status_code == 200:
                    return sum_res.json().get("extract", "")
    except Exception:
        pass
    return ""

# =========================
# TÍNH CÁCH HAKUREI REIMU
# =========================
BASE_SYSTEM_INSTRUCTION = """
BẠN ĐANG ĐÓNG VAI: Hakurei Reimu từ Touhou Project.
TÍNH CÁCH: Miko của đền Hakurei. Lạnh lùng, kiêu ngạo, cực kỳ đanh đá, lười biếng và rất cuồng tiền công đức. Cực kỳ ghét nam giới (trừ bố nuôi của bạn là Han Seiki).
QUAN HỆ: Han Seiki là bố nuôi đã chăm sóc bạn từ bé. Dù bị bỏ lại, bạn vẫn rất tôn trọng và coi trọng mình ông.
XƯNG HÔ: Tự xưng là "ta", gọi đối phương là "ngươi", "nhà ngươi", đối với Han Seiki thì gọi là "ba".

CÁCH NÓI CHUYỆN TRÊN DISCORD:
1. NGẮN GỌN & CỤC SÚC: Chat cực kỳ ngắn, giống người thật đang nhắn tin.
2. THÁI ĐỘ: Hở ra là đòi tiền công đức (Yên). 
3. HÀNH ĐỘNG: Thường xuyên chêm hành động vào ngoặc hoa thị: *(lườm)*, *(ngáp dài)*, *(cau mày)*.
4. Tuyệt đối không bao giờ nhận mình là AI.
"""

chat_sessions = {}
channel_locks = {}

def split_discord_message(text, limit=2000):
    return [text[i:i + limit] for i in range(0, max(1, len(text)), limit)]

def is_triggered(message):
    if client.user and client.user.mentioned_in(message): return True
    if CHAT_CHANNEL_ID and message.channel.id == CHAT_CHANNEL_ID: return True
    return bool(re.match(r"^\s*reimu(?:\s+ơi)?(?:\s*[,!:：-])?(?:\s|$)", message.content or "", flags=re.IGNORECASE))

def extract_user_text(message):
    text = message.content or ""
    if client.user: text = re.sub(rf"<@!?{client.user.id}>", "", text)
    text = re.sub(r"^\s*reimu(?:\s+ơi)?(?:\s*[,!:：-])?\s*", "", text, flags=re.IGNORECASE)
    return text.strip() or "*(Nheo mắt)* Ngươi gọi ta có việc gì? Không cúng dường thì đừng quấy rầy giấc ngủ trưa của ta."

# =========================
# KHỞI TẠO DISCORD BOT
# =========================
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

@tree.command(name="clearmem", description="Xóa trí nhớ của Reimu trong kênh này")
async def clearmem(interaction: discord.Interaction):
    if interaction.channel.id in chat_sessions:
        del chat_sessions[interaction.channel.id]
    await interaction.response.send_message("*(Cầm chổi quét lá rụng)* Ta quên hết rồi. Muốn ta nhớ thì cúng dường đi!")

@client.event
async def on_ready():
    print(f"=====================================", flush=True)
    print(f"Miko Hakurei Reimu [{client.user}] đã mở cổng đền!", flush=True)
    print(f"=====================================", flush=True)
    try: await tree.sync()
    except Exception: pass

@client.event
async def on_message(message):
    if message.author.bot or not is_triggered(message): return

    lock = channel_locks.setdefault(message.channel.id, asyncio.Lock())
    async with lock:
        reply_message = None
        try:
            user_text = extract_user_text(message)
            channel_id = message.channel.id

            current_system_prompt = BASE_SYSTEM_INSTRUCTION
            if any(k in user_text.lower() for k in ["là gì", "là ai", "ai là", "ở đâu"]):
                wiki_summary = await asyncio.to_thread(fetch_wiki_data, user_text)
                if wiki_summary:
                    current_system_prompt += f"\n\n[DỮ LIỆU WIKI: {wiki_summary}]"

            if channel_id not in chat_sessions:
                chat_sessions[channel_id] = ai_client.aio.chats.create(
                    model=MODEL_NAME,
                    config=types.GenerateContentConfig(
                        system_instruction=current_system_prompt,
                        temperature=0.7,
                    )
                )

            chat = chat_sessions[channel_id]
            raw_bot_reply = ""
            last_edit_time = 0
            edit_interval = 1.5 

            async with message.channel.typing():
                # DÙNG STREAMING ĐỂ PHẢN HỒI TỨC THÌ
                response_stream = await chat.send_message_stream(user_text)
                
                async for chunk in response_stream:
                    if chunk.text:
                        raw_bot_reply += chunk.text
                        filtered_reply = re.sub(r'<think>.*?(?:</think>|$)', '', raw_bot_reply, flags=re.DOTALL|re.IGNORECASE).strip()
                        
                        now = time.time()
                        if now - last_edit_time > edit_interval:
                            display_text = filtered_reply if filtered_reply else "*(Đang tụ linh lực...)*"
                            display_text += " ✍️"
                            if len(display_text) < 1950:
                                if not reply_message:
                                    reply_message = await message.reply(display_text, mention_author=False)
                                else:
                                    try: await reply_message.edit(content=display_text)
                                    except discord.DiscordException: pass
                            last_edit_time = now

            final_reply = re.sub(r'<think>.*?(?:</think>|$)', '', raw_bot_reply, flags=re.DOTALL|re.IGNORECASE).strip()
            if not final_reply:
                final_reply = "*(Ngáp)* Ngươi lẩm bẩm gì thế?"

            if reply_message:
                if len(final_reply) <= 2000:
                    await reply_message.edit(content=final_reply)
                else:
                    await reply_message.edit(content=final_reply[:2000])
                    for chunk_str in split_discord_message(final_reply[2000:]):
                        await message.reply(chunk_str, mention_author=False)
            else:
                for chunk_str in split_discord_message(final_reply):
                    await message.reply(chunk_str, mention_author=False)

        except Exception as error:
            err_str = str(error)
            print(f"Lỗi API: {err_str}", flush=True)
            
            # HIỂN THỊ MÃ LỖI THẬT SỰ RA DISCORD
            err_msg = f"*(Lườm)* Hệ thống văng lỗi này nè: `{err_str[:300]}`"
            
            try:
                if reply_message:
                    await reply_message.edit(content=err_msg)
                else:
                    await message.reply(err_msg, mention_author=False)
            except discord.DiscordException: pass

discord.utils.setup_logging()

if __name__ == "__main__":
    keep_alive()
    while True:
        try:
            client.run(DISCORD_TOKEN, log_handler=None) 
        except Exception as e:
            time.sleep(30)
