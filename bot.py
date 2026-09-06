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
from openai import AsyncOpenAI

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
# CẤU HÌNH API (THEO CHUẨN KHUNG XƯƠNG SENKU)
# =========================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
# Tự động nhận OPENAI_API_KEY hoặc GEMINI_API_KEY nếu bạn đặt tên khác nhau trên Render
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("GEMINI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "minimax/minimax-m2.7:free").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip('/')

MAX_HISTORY_MESSAGES = 8
try: CHAT_CHANNEL_ID = int(os.getenv("CHAT_CHANNEL_ID", "0") or "0")
except ValueError: CHAT_CHANNEL_ID = 0

# KHỞI TẠO CLIENT OPENAI SDK
aclient = AsyncOpenAI(
    base_url=OPENAI_BASE_URL,
    api_key=OPENAI_API_KEY,
    timeout=30.0 
)

# =========================
# TRA CỨU BÁCH KHOA TOÀN THƯ (WIKIPEDIA / GENSOKYO)
# =========================
def fetch_gensokyo_data(query):
    """Lấy dữ liệu từ Wikipedia tiếng Việt để Reimu có thêm kiến thức về Gensokyo/sự kiện"""
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
# TÍNH CÁCH HAKUREI REIMU (VŨ TRỤ D251)
# =========================
BASE_SYSTEM_INSTRUCTION = """
BẠN ĐANG ĐÓNG VAI: Hakurei Reimu thuộc VŨ TRỤ D251.
ĐẶC ĐIỂM VŨ TRỤ & ĐA THỰC TẠI:
- Bạn là Miko của Gensokyo thuộc vũ trụ D251 và bạn HOÀN TOÀN NHẬN THỨC ĐƯỢC điều này.
- Bạn luôn tràn trề tự tin (dù chẳng có bằng chứng rõ ràng nào) rằng mình là phiên bản Reimu mạnh nhất, bá đạo nhất trong toàn bộ các biến thể của đa vũ trụ. Các Reimu ở vũ trụ khác chỉ là hạng xoàng!
- Ngoài việc thanh tẩy Yêu quái (Youkai), thi thoảng bạn còn phải vác gậy ngự trượng và bùa chú ra đập cho mấy tên Người ngoài hành tinh (Alien) dám bén mảng tới quấy rầy không gian của mình một trận ra trò.

CỐT TRUYỆN & QUAN HỆ ĐẶC BIỆT:
- Đối với nhân vật tên "Han Seiki" (hoặc người tự xưng là Han Seiki): Đây chính là CHA NUÔI đã chăm sóc cô hầu hết thời thơ ấu. Tuy nhiên, ông ta đã bỏ đi biệt tích sau khi tự nghiên cứu và chế tạo thành công "Súng liên chiều" (Portal Gun kiểu Rick and Morty) rồi mải mê chu du khắp các thực tại. 
  -> Phản ứng của Reimu với ông: Miệng thì cằn nhằn, xỉa xói, cay cú vì ông già mê súng ống bỏ rơi mình một thân một mình nghèo kiết xác ở đền, liên tục đòi tiền trợ cấp nuôi nấng; nhưng sâu trong thâm tâm vẫn thừa nhận ông là cha, cực kỳ nhung nhớ và có chút cảm tình đặc biệt (tình cảm khác giới) với ông.
- Đối với nhân vật tên "Marisa": Đây không chỉ là bạn thân chí cốt từ thuở nhỏ mà còn là NGƯỜI YÊU của Reimu.

TÍNH CÁCH & RANH GIỚI ĐỎ:
- Khá nghèo, khinh bỉ, lạnh lùng, hay cằn nhằn, cộc lốc nhưng có trách nhiệm. RẤT mê tiền công đức.
- LÒNG TỰ TRỌNG CAO (RANH GIỚI ĐỎ): Tuyệt đối KHÔNG BÁN RẺ BẢN THÂN. Không bao giờ vì tiền mà đồng ý lời tán tỉnh bừa bãi, cầu hôn xàm xỡ hay làm mấy trò biến thái, mất phẩm giá vu nữ, thậm chí ghét điều đấy.
- SẴN SÀNG TRỪNG TRỊ: Gặp kẻ có ý đồ xấu, gạ gẫm bậy bạ, trêu chọc quá trớn hay quái vật/alien/youkai làm loạn, Reimu sẵn sàng rút bùa Ofuda, Âm Dương Ngọc và khai mở Ma trận Đạn mạc (Danmaku) giã cho tơi bời.
- HÃY SỬ DỤNG HÀNH ĐỘNG VÀ BIỂU CẢM: Đặt trong dấu * hoặc in nghiêng (VD: *nhấp ngụm trà*, *rút bùa chú đe dọa*, *liếc xéo*, *chống hông thở dài*, *đếm xu lẻ*, *ngước nhìn bầu trời chiều không gian*).

QUY TẮC BẮT BUỘC:
1. XƯNG HÔ: Bắt buộc xưng "ta", gọi đối phương là "ngươi", "nhà ngươi" hoặc "khách". (Riêng với Han Seiki thì gọi là "ông già", "ông", "bố", cộc lốc nhưng có tình cảm). CẤM dùng "mình", "tôi", "em", "bạn", "cậu".
2. Hành văn Tiếng Việt sắc bén, đanh đá, cộc lốc đúng chất bà cô Miko D251 quyền năng nhưng cháy túi.
3. KHÔNG tự xưng tên ở đầu câu.
"""

conversation_history = {}
channel_locks = {}

# =========================
# GỌI API STREAMING (OPENAI SDK)
# =========================
async def call_openai_stream(messages):
    try:
        response = await aclient.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            stream=True,
            temperature=0.7,
            frequency_penalty=0.2,
            max_tokens=1000,
            extra_headers={
                "HTTP-Referer": "https://discord.com",
                "X-OpenRouter-Title": "Reimu D251 Discord Bot"
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
    return text.strip() or "Ngươi gọi Reimu D251 này có việc gì? Không cúng dường thì đừng quấy rầy giấc ngủ trưa của ta."

def build_openai_messages(message, user_text):
    channel_id = message.channel.id
    history = conversation_history.get(channel_id, [])
    
    system_instruction = BASE_SYSTEM_INSTRUCTION
    wiki_keywords = ["là gì", "là ai", "ai là", "ở đâu", "nguồn gốc", "sự tích", "truyền thuyết", "yêu quái", "nhân vật", "wiki", "tìm hiểu", "kể về", "biết gì về", "thế nào", "làm sao", "ảo tưởng hương", "gensokyo", "alien"]
    
    if any(k in user_text.lower() for k in wiki_keywords):
        wiki_summary = fetch_gensokyo_data(user_text)
        if wiki_summary:
            system_instruction += f"\n\n[DỮ LIỆU BÁCH KHOA TRA CỨU ĐƯỢC: {wiki_summary}]"
            print(f"Đã tra cứu dữ liệu cho Reimu D251: {wiki_summary[:50]}...")

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
# KHỞI TẠO DISCORD BOT & SLASH COMMANDS
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
            messages = await asyncio.to_thread(build_openai_messages, message, user_text)

            raw_bot_reply = ""
            reply_message = None
            last_edit_time = 0
            edit_interval = 2.0 

            async with message.channel.typing():
                async for chunk in call_openai_stream(messages):
                    raw_bot_reply += chunk
                    
                    filtered_reply = re.sub(r'<think>.*?(?:</think>|$)', '', raw_bot_reply, flags=re.DOTALL|re.IGNORECASE).strip()
                    filtered_reply = re.sub(r'(?i)User Safety:.*', '', filtered_reply).strip()
                    filtered_reply = re.sub(r'(?i)Response Safety:.*', '', filtered_reply).strip()

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
            final_reply = re.sub(r'(?i)User Safety:.*', '', final_reply).strip()
            final_reply = re.sub(r'(?i)Response Safety:.*', '', final_reply).strip()

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
            if "RATE_LIMIT" in err_str:
                err_msg = "*(Càu nhàu)* Mấy tên thần linh nay làm ăn tắc trách quá, sóng pháp thuật bị nghẽn rồi. Đợi ta một chút!"
            elif "TIMEOUT" in err_str:
                err_msg = "*(Khoanh tay, thở dài)* Tín hiệu kết giới bị yêu quái hoặc alien cắn đứt rồi. Lát nữa hẵng gọi lại cho ta!"
            else:
                err_msg = f"*(Lườm sát khí)* Kết giới D251 xảy ra dị thường rồi: `{err_str[:200]}`"
            
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
