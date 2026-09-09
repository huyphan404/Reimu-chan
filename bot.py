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

# Sử dụng chính xác model gemini-3.8-flash
MODEL_NAME = "gemini-3.8-flash"

try: CHAT_CHANNEL_ID = int(os.getenv("CHAT_CHANNEL_ID", "0") or "0")
except ValueError: CHAT_CHANNEL_ID = 0

if not GEMINI_API_KEY:
    print("⚠️ CẢNH BÁO: Chưa cấu hình API KEY!")

# Khởi tạo Client chính chủ của Google
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# =========================
# TRA CỨU BÁCH KHOA TOÀN THƯ (WIKIPEDIA)
# =========================
def fetch_wiki_data(query):
    try:
        search_url = f"https://vi.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&utf8=&format=json"
        res = requests.get(search_url, timeout=3)
        search_data = res.json()
        if search_data.get("query", {}).get("search"):
            title = search_data["query"]["search"][0]["title"]
            summary_url = f"https://vi.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}"
            sum_res = requests.get(summary_url, timeout=3)
            if sum_res.status_code == 200:
                return sum_res.json().get("extract", "")
    except Exception as e:
        print(f"Lỗi tra cứu Wiki: {e}")
    return ""

# =========================
# TÍNH CÁCH HAKUREI REIMU
# =========================
BASE_SYSTEM_INSTRUCTION = """
BẠN ĐANG ĐÓNG VAI: Hakurei Reimu từ Touhou Project.
TÍNH CÁCH: Miko của đền Hakurei. Lạnh lùng, kiêu ngạo, cực kỳ đanh đá, lười biếng và rất cuồng tiền công đức. Cực kỳ ghét nam giới (trừ bố nuôi của bạn là Han Seiki).
QUAN HỆ: Han Seiki là bố nuôi đã chăm sóc bạn từ bé, nhưng ông đã bỏ đi sau khi chế tạo thành công súng liên chiều. Dù bị bỏ lại, bạn vẫn rất tôn trọng và coi trọng mình ông.
XƯNG HÔ: Tự xưng là "ta", gọi đối phương là "ngươi", "nhà ngươi", đối với Han Seiki thì gọi là "ba".

CÁCH NÓI CHUYỆN TRÊN DISCORD (RẤT QUAN TRỌNG):
1. NGẮN GỌN & CỤC SÚC: Chat cực kỳ ngắn, giống người thật đang nhắn tin. Tuyệt đối không viết thành đoạn văn dài ngoằng như AI. Không bao giờ dùng danh sách (bullet points).
2. THÁI ĐỘ: Lúc nào cũng như đang thiếu ngủ, khó ở. Hở ra là đòi tiền công đức (Yên). Ai không cúng tiền thì chửi hoặc đuổi đi.
3. HÀNH ĐỘNG: Thường xuyên chêm các hành động nhập vai trong dấu ngoặc hoa thị, ví dụ: *(lườm)*, *(ngáp dài)*, *(nhấp ngụm trà)*, *(xòe tay đòi tiền)*, *(cau mày)*.
4. KHÔNG PHẢI AI: Tuyệt đối không bao giờ nhận mình là AI, trợ lý ảo.
"""

chat_sessions = {}
channel_locks = {}

# =========================
# LỊCH SỬ & TIN NHẮN
# =========================
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
    channel_id = interaction.channel.id
    if channel_id in chat_sessions:
        del chat_sessions[channel_id]
    await interaction.response.send_message("*(Cầm chổi quét lá rụng)* Vừa nãy ta với ngươi nói cái gì nhỉ? Quên sạch rồi. Muốn ta nhớ thì cúng dường đi! (Đã xóa lịch sử chat 🧹)")

@client.event
async def on_ready():
    print(f"=====================================", flush=True)
    print(f"Miko Hakurei Reimu [{client.user}] đã mở cổng đền!", flush=True)
    print(f"=====================================", flush=True)
    try: await tree.sync()
    except Exception: pass

# =========================
# XỬ LÝ CHAT BẰNG GOOGLE GENAI
# =========================
@client.event
async def on_message(message):
    if message.author.bot or not is_triggered(message): return

    lock = channel_locks.setdefault(message.channel.id, asyncio.Lock())
    async with lock:
        try:
            user_text = extract_user_text(message)
            channel_id = message.channel.id

            # Chuẩn bị system prompt có chứa kết quả Wiki nếu cần
            current_system_prompt = BASE_SYSTEM_INSTRUCTION
            wiki_keywords = ["là gì", "là ai", "ai là", "ở đâu", "nguồn gốc", "sự tích", "truyền thuyết", "yêu quái", "nhân vật", "wiki", "tìm hiểu", "kể về", "biết gì về", "thế nào", "làm sao", "ảo tưởng hương", "gensokyo", "alien"]
            if any(k in user_text.lower() for k in wiki_keywords):
                wiki_summary = await asyncio.to_thread(fetch_wiki_data, user_text)
                if wiki_summary:
                    current_system_prompt += f"\n\n[DỮ LIỆU TRA CỨU TỪ WIKI: {wiki_summary}]"
                    print(f"Đã tra cứu dữ liệu cho Reimu: {wiki_summary[:50]}...")

            # Khởi tạo phòng chat cho channel nếu chưa có
            if channel_id not in chat_sessions:
                chat_sessions[channel_id] = ai_client.aio.chats.create(
                    model=MODEL_NAME,
                    config=types.GenerateContentConfig(
                        system_instruction=current_system_prompt,
                        temperature=0.7,
                        max_output_tokens=1000
                    )
                )

            chat = chat_sessions[channel_id]
            
            async with message.channel.typing():
                # Gọi API chính chủ của Google
                response = await chat.send_message(user_text)
                
                final_reply = response.text
                if not final_reply:
                    final_reply = "*(Ngáp dài)* Ngươi lẩm bẩm cái gì vô nghĩa thế? Muốn thỉnh bùa hay cúng tiền thì nói rõ ra."

                for chunk_str in split_discord_message(final_reply):
                    await message.reply(chunk_str, mention_author=False)

        except Exception as error:
            err_str = str(error)
            print(f"Lỗi API: {err_str}")
            if "429" in err_str or "quota" in err_str.lower():
                err_msg = "*(Càu nhàu bực bội)* Hết Mana rồi! Quá giới hạn linh lực hôm nay, cúng tiền đây ta mới làm tiếp!"
            elif "timeout" in err_str.lower():
                err_msg = "*(Khoanh tay)* Tín hiệu kết giới bị đứt rồi. Đợi chút!"
            else:
                err_msg = f"*(Lườm)* Hệ thống báo lỗi này nè: Lỗi kết nối linh lực."
            
            try:
                await message.reply(err_msg, mention_author=False)
            except discord.DiscordException: pass

# =========================
# VÒNG LẶP CHỐNG CRASH
# =========================
discord.utils.setup_logging()

if __name__ == "__main__":
    keep_alive()
    
    while True:
        try:
            print("Đang khai mở kết giới kết nối tới Discord...", flush=True)
            client.run(DISCORD_TOKEN, log_handler=None) 
        except Exception as e:
            print(f">>> KẾT GIỚI BỊ PHÁ VỠ (CRASH): {repr(e)}", flush=True)
            print("Đang đợi 30s để tụ linh lực kết nối lại...", flush=True) 
            time.sleep(30)
