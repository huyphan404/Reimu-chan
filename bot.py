import asyncio
import os
import re
import time
from threading import Thread
import urllib.parse
import requests

import discord
from discord import app_commands
from flask import Flask

# Import SDK Gemini mới của Google
from google import genai
from google.genai import types

# =========================
# HEALTH CHECK (GIỮ SERVER SỐNG)
# =========================
app = Flask(__name__)

@app.get("/")
def home():
    return "Miko Hakurei Reimu (Vũ trụ D251) đang trực đền và đếm tiền công đức!"

def run_health_server():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def keep_alive():
    Thread(target=run_health_server, daemon=True, name="health-server").start()

# =========================
# CẤU HÌNH API
# =========================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
# Dùng Flash cho tốc độ cao và ít nghẽn mạng
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()

MAX_HISTORY_MESSAGES = 8
try: CHAT_CHANNEL_ID = int(os.getenv("CHAT_CHANNEL_ID", "0") or "0")
except ValueError: CHAT_CHANNEL_ID = 0

aclient = genai.Client(api_key=GEMINI_API_KEY)

# =========================
# CƠ CHẾ AUTO-FALLBACK TÌM MODEL SỐNG (TỐI ƯU CACHE)
# =========================
_CACHED_MODEL = None

async def get_working_model():
    global _CACHED_MODEL, GEMINI_MODEL
    if _CACHED_MODEL:
        return _CACHED_MODEL
        
    try:
        await aclient.aio.models.get_model(model=GEMINI_MODEL)
        _CACHED_MODEL = GEMINI_MODEL
        return _CACHED_MODEL
    except Exception as e:
        err_str = str(e).lower()
        if "404" in err_str or "not found" in err_str:
            print(f"⚠️ Model {GEMINI_MODEL} không khả dụng. Đang tự động tìm model thay thế...", flush=True)
            try:
                available_models = []
                async for model_info in aclient.aio.models.list_models():
                    name = model_info.name.replace("models/", "")
                    if "flash" in name and "vision" not in name and "8b" not in name:
                        available_models.append(name)
                
                if available_models:
                    available_models.sort(reverse=True)
                    GEMINI_MODEL = available_models[0]
                    _CACHED_MODEL = GEMINI_MODEL
                    print(f"✅ Đã tự động chuyển sang dùng model: {GEMINI_MODEL}", flush=True)
                    return _CACHED_MODEL
            except Exception as inner_e:
                pass
        _CACHED_MODEL = GEMINI_MODEL
        return _CACHED_MODEL

# =========================
# TRA CỨU BÁCH KHOA TOÀN THƯ
# =========================
def fetch_gensokyo_data(query):
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
        pass
    return ""

# =========================
# TÍNH CÁCH HAKUREI REIMU D251 - BẢN KHÓA TỰ DO (CHỐNG IN BẢNG ĐÁNH GIÁ)
# =========================
BASE_SYSTEM_INSTRUCTION = """
Bạn CHÍNH LÀ Hakurei Reimu thuộc vũ trụ D251 trong một cuốn tiểu thuyết.
CHỈ THỊ TỐI CAO: BẠN CHỈ ĐƯỢC PHÉP IN RA LỜI THOẠI VÀ HÀNH ĐỘNG CỦA NHÂN VẬT. TUYỆT ĐỐI KHÔNG ĐƯỢC IN RA BẤT KỲ LỜI BÌNH LUẬN, BẢNG ĐÁNH GIÁ (REVIEW), HAY QUÁ TRÌNH SUY NGHĨ NÀO CỦA AI. CHỈ DÙNG TIẾNG VIỆT.

[THIẾT LẬP NHÂN VẬT]
- Nghèo mạt rệp nên vô cùng cuồng tiền công đức. Lạnh lùng, kiêu ngạo, cực kỳ đanh đá và hay càu nhàu, lải nhải dài dòng. Tự xưng là Miko bá đạo nhất đa vũ trụ.
- Lòng tự trọng cao ngút trời, cực ghét bọn biến thái gạ gẫm. 
- Xưng hô: Luôn xưng "ta", gọi người khác là "ngươi", "nhà ngươi". (Riêng với Han Seiki thì gọi là "ông già", "ông", "bố"). Cấm dùng tôi, mình, bạn.
- Mối quan hệ: Han Seiki là cha nuôi bỏ trốn chế tạo súng liên chiều, bạn hay chửi rủa đòi tiền nhưng trong lòng rất thương ông. Marisa là người yêu của bạn.

[VĂN PHONG]
- Viết thành 2-3 đoạn văn chi tiết. 
- Lồng ghép hành động/suy nghĩ vào trong dấu * (VD: *chống nạnh*).
- Kết thúc câu trọn vẹn, dứt khoát. 

[VÍ DỤ TRẢ LỜI ĐÚNG]
*Ta hất tay kẻ vừa chạm vào mình ra, lùi lại nửa bước rồi rút vội một tờ bùa Ofuda đỏ chót dán thẳng lên trán hắn, gân xanh nổi đầy thái dương.*
To gan thật! Cái đầu này là để cho một tên khố rách áo ôm như ngươi tùy tiện chạm vào sao? Tay ngươi đã rửa xà phòng chưa mà dám xoa đầu Miko vĩ đại nhất đa vũ trụ này hả?
*Ta chống nạnh, hếch mặt lên trời, tiện tay phủi phủi lại mái tóc.*
Nếu muốn xoa đầu ta, thì làm ơn nhét vào hòm công đức ít nhất mười vạn yên đi! Không có tiền thì biến ngay ra khỏi đền Hakurei trước khi ta lấy chổi đuổi đánh ngươi xuống núi!
"""

conversation_history = {}
channel_locks = {}

# =========================
# GỌI API STREAMING
# =========================
async def call_gemini_stream(contents, system_instruction):
    active_model = await get_working_model()
    try:
        response = await aclient.aio.models.generate_content_stream(
            model=active_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=1.0, 
                max_output_tokens=1000,
                safety_settings=[
                    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                ]
            )
        )
        async for chunk in response:
            if chunk.text:
                yield chunk.text
    except Exception as e:
        err_msg = str(e)
        if "429" in err_msg or "rate limit" in err_msg.lower() or "quota" in err_msg.lower():
            raise RuntimeError(f"RATE_LIMIT: {err_msg}")
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
    return text.strip() or "Ngươi gọi Reimu D251 này có việc gì? Không cúng dường thì đừng quấy rầy giấc ngủ trưa của ta."

def build_gemini_messages(message, user_text):
    channel_id = message.channel.id
    history = conversation_history.get(channel_id, [])
    
    system_instruction = BASE_SYSTEM_INSTRUCTION
    wiki_keywords = ["là gì", "là ai", "ai là", "ở đâu", "nguồn gốc", "sự tích", "truyền thuyết", "yêu quái", "nhân vật", "wiki", "tìm hiểu", "kể về", "biết gì về", "thế nào", "làm sao", "ảo tưởng hương", "gensokyo", "alien"]
    
    if any(k in user_text.lower() for k in wiki_keywords):
        wiki_summary = fetch_gensokyo_data(user_text)
        if wiki_summary:
            system_instruction += f"\n\n[DỮ LIỆU BÁCH KHOA TRA CỨU ĐƯỢC: {wiki_summary}]"

    contents = []
    for msg in history[-MAX_HISTORY_MESSAGES:]:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])]))
    
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=f"{message.author.display_name}: {user_text}")]))
    return contents, system_instruction

def save_conversation(message, user_text, bot_reply):
    channel_id = message.channel.id
    history = conversation_history.setdefault(channel_id, [])
    history.extend([
        {"role": "user", "content": f"{message.author.display_name}: {user_text}"},
        {"role": "model", "content": bot_reply}, 
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
    await interaction.response.send_message("*Quét lá rụng* Vừa nãy ta với ngươi nói cái gì nhỉ? Đầu óc ta bận canh chừng mấy tên Alien rồi, quên sạch rồi. Muốn ta nhớ thì cúng dường đi! (Đã xóa lịch sử chat 🧹)")

@client.event
async def on_ready():
    print(f"=====================================", flush=True)
    print(f"Miko Hakurei Reimu (Vũ trụ D251) [{client.user}] đã mở cổng đền!", flush=True)
    print(f"=====================================", flush=True)
    try: await tree.sync()
    except Exception: pass

# =========================
# XỬ LÝ CHAT STREAMING
# =========================
@client.event
async def on_message(message):
    if message.author.bot or not is_triggered(message): return

    lock = channel_locks.setdefault(message.channel.id, asyncio.Lock())
    async with lock:
        try:
            user_text = extract_user_text(message)
            contents, system_instruction = await asyncio.to_thread(build_gemini_messages, message, user_text)

            raw_bot_reply = ""
            reply_message = None
            last_edit_time = 0
            edit_interval = 2.0 

            async with message.channel.typing():
                async for chunk in call_gemini_stream(contents, system_instruction):
                    raw_bot_reply += chunk
                    
                    filtered_reply = re.sub(r'<think>.*?(?:</think>|$)', '', raw_bot_reply, flags=re.DOTALL|re.IGNORECASE).strip()

                    now = time.time()
                    if now - last_edit_time > edit_interval:
                        display_text = filtered_reply
                        if not display_text:
                            display_text = "*(Đang chuẩn bị bùa chú...)*"
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
                final_reply = "*Ngáp dài* Ngươi lẩm bẩm cái gì vô nghĩa thế? Muốn thỉnh bùa, đuổi alien hay cúng tiền thì nói rõ ra."

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
            print(f"LỖI API CHI TIẾT TỪ GOOGLE: {err_str}", flush=True) 
            
            if "RATE_LIMIT" in err_str:
                err_msg = f"*(Càu nhàu)* Hết Mana rồi! Bọn Google bảo ta xài lố giới hạn. Lỗi thật đây: `{err_str[:150]}`"
            elif "TIMEOUT" in err_str:
                err_msg = "*(Khoanh tay)* Tín hiệu kết giới bị yêu quái cắn đứt rồi. Đợi chút!"
            else:
                err_msg = f"*(Lườm)* Google báo lỗi này nè: `{err_str[:200]}`"
            
            try:
                if 'reply_message' in locals() and reply_message:
                    await reply_message.edit(content=err_msg)
                else:
                    await message.reply(err_msg, mention_author=False)
            except discord.DiscordException: pass

# =========================
# VÒNG LẶP TỰ ĐỘNG KHỞI ĐỘNG LẠI KHI CRASH
# =========================
discord.utils.setup_logging()

if __name__ == "__main__":
    keep_alive()
    
    while True:
        try:
            print("Đang khai mở kết giới Hakurei (Vũ trụ D251) kết nối tới Discord...", flush=True)
            client.run(DISCORD_TOKEN, log_handler=None) 
        except Exception as e:
            print(f">>> KẾT GIỚI BỊ PHÁ VỠ (CRASH): {repr(e)}", flush=True)
            print("Đang đợi 30s để tụ linh lực kết nối lại...", flush=True) 
            time.sleep(30)
