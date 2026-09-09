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
from openai import AsyncOpenAI

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
# CẤU HÌNH API GEMINI (1 KEY DUY NHẤT)
# =========================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Lấy 1 key duy nhất (Hỗ trợ cả tên biến cũ OPENAI_API_KEYS để bạn không phải sửa trên Render)
api_key_env = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEYS", "")
OPENAI_API_KEY = api_key_env.split(",")[0].strip() if api_key_env else "dummy_key"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gemini-2.0-flash").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/").strip().rstrip('/')

MAX_HISTORY_MESSAGES = 8
try: CHAT_CHANNEL_ID = int(os.getenv("CHAT_CHANNEL_ID", "0") or "0")
except ValueError: CHAT_CHANNEL_ID = 0

if OPENAI_API_KEY == "dummy_key":
    print("⚠️ CẢNH BÁO: Chưa cấu hình OPENAI_API_KEY!")

# Khởi tạo Client OpenAI gọi sang Google
openai_client = AsyncOpenAI(
    base_url=OPENAI_BASE_URL,
    api_key=OPENAI_API_KEY,
    timeout=30.0 
)

# =========================
# TRA CỨU BÁCH KHOA TOÀN THƯ (WIKIPEDIA)
# =========================
def fetch_wiki_data(query):
    """Lấy tóm tắt từ Wikipedia tiếng Việt"""
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
4. KHÔNG PHẢI AI: Tuyệt đối không bao giờ nhận mình là AI, trợ lý ảo, hay dùng từ ngữ như "Tôi có thể giúp gì", "Xin lỗi vì sự bất tiện".

VÍ DỤ CÁCH TRẢ LỜI:
User: Chào Reimu!
Reimu: *(Ngáp)* Gì đấy? Ồn ào quá... Có mang tiền công đức tới không thì bảo?
User: Kể chuyện ma đi.
Reimu: *(Lườm)* Ta là vu nữ diệt yêu quái, không phải người kể chuyện mua vui. 10 vạn Yên thì ta kể, không thì biến!
"""

conversation_history = {}
channel_locks = {}

# =========================
# GỌI API
# =========================
async def call_openai_stream(messages):
    try:
        response = await openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            stream=True,
            temperature=0.7,
            max_tokens=1000,
            extra_headers={
                "HTTP-Referer": "https://discord.com",
                "X-OpenRouter-Title": "Reimu Discord Bot" 
            }
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        err_msg = str(e)
        if "429" in err_msg or "rate limit" in err_msg.lower() or "quota" in err_msg.lower():
            raise RuntimeError("RATE_LIMIT")
        elif "timeout" in err_msg.lower(): 
            raise RuntimeError("TIMEOUT")
        raise RuntimeError(f"Lỗi mạng: {err_msg}")

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

def build_openai_messages(message, user_text):
    channel_id = message.channel.id
    history = conversation_history.get(channel_id, [])
    
    system_instruction = BASE_SYSTEM_INSTRUCTION
    wiki_keywords = ["là gì", "là ai", "ai là", "ở đâu", "nguồn gốc", "sự tích", "truyền thuyết", "yêu quái", "nhân vật", "wiki", "tìm hiểu", "kể về", "biết gì về", "thế nào", "làm sao", "ảo tưởng hương", "gensokyo", "alien"]
    if any(k in user_text.lower() for k in wiki_keywords):
        wiki_summary = fetch_wiki_data(user_text)
        if wiki_summary:
            system_instruction += f"\n\n[DỮ LIỆU TRA CỨU TỪ WIKI: {wiki_summary}]"
            print(f"Đã tra cứu dữ liệu cho Reimu: {wiki_summary[:50]}...")

    messages = [{"role": "system", "content": system_instruction}]
    for msg in history[-MAX_HISTORY_MESSAGES:]: messages.append(msg)
    messages.append({"role": "user", "content": f"{message.author.display_name}: {user_text}"})
    return messages

def save_conversation(message, user_text, bot_reply):
    channel_id = message.channel.id
    history = conversation_history.setdefault(channel_id, [])
    history.extend([
        {"role": "user", "content": f"{message.author.display_name}: {user_text}"},
        {"role": "assistant", "content": bot_reply},
    ])
    conversation_history[channel_id] = history[-MAX_HISTORY_MESSAGES:]

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
    if channel_id in conversation_history:
        conversation_history[channel_id] = []
    await interaction.response.send_message("*(Cầm chổi quét lá rụng)* Vừa nãy ta với ngươi nói cái gì nhỉ? Quên sạch rồi. Muốn ta nhớ thì cúng dường đi! (Đã xóa lịch sử chat 🧹)")

@client.event
async def on_ready():
    print(f"=====================================", flush=True)
    print(f"Miko Hakurei Reimu [{client.user}] đã mở cổng đền!", flush=True)
    print(f"=====================================", flush=True)
    try: await tree.sync()
    except Exception: pass

# =========================
# XỬ LÝ CHAT
# =========================
@client.event
async def on_message(message):
    if message.author.bot or not is_triggered(message): return

    lock = channel_locks.setdefault(message.channel.id, asyncio.Lock())
    async with lock:
        try:
            user_text = extract_user_text(message)
            messages = await asyncio.to_thread(build_openai_messages, message, user_text)

            raw_bot_reply = ""
            reply_message = None
            last_edit_time = 0
            edit_interval = 1.5 

            async with message.channel.typing():
                async for chunk in call_openai_stream(messages):
                    raw_bot_reply += chunk
                    
                    filtered_reply = re.sub(r'<think>.*?(?:</think>|$)', '', raw_bot_reply, flags=re.DOTALL|re.IGNORECASE).strip()

                    now = time.time()
                    if now - last_edit_time > edit_interval:
                        display_text = filtered_reply
                        if not display_text:
                            display_text = "*(Đang lục tìm bùa chú...)*"
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
                final_reply = "*(Ngáp dài)* Ngươi lẩm bẩm cái gì vô nghĩa thế? Muốn thỉnh bùa hay cúng tiền thì nói rõ ra."

            if final_reply:
                save_conversation(message, user_text, final_reply)
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
            if "RATE_LIMIT" in err_str:
                err_msg = "*(Càu nhàu bực bội)* Hết Mana rồi! Quá giới hạn linh lực hôm nay, cúng tiền đây ta mới làm tiếp!"
            elif "TIMEOUT" in err_str:
                err_msg = "*(Khoanh tay)* Tín hiệu kết giới bị đứt rồi. Đợi chút!"
            else:
                err_msg = f"*(Lườm)* Hệ thống báo lỗi này nè: `{err_str[:200]}`"
            
            try:
                if 'reply_message' in locals() and reply_message:
                    await reply_message.edit(content=err_msg)
                else:
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
