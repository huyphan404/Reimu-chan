import asyncio
import json
import logging
import os
import re
import time
from threading import Thread

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
    return "Miko Reimu đang trực đền!"

def run_health_server():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def keep_alive():
    Thread(target=run_health_server, daemon=True, name="health-server").start()

# =========================
# CẤU HÌNH API
# =========================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "openrouter/free").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip('/')

MAX_HISTORY_MESSAGES = 8
try: CHAT_CHANNEL_ID = int(os.getenv("CHAT_CHANNEL_ID", "0") or "0")
except ValueError: CHAT_CHANNEL_ID = 0

# KHỞI TẠO CLIENT OPENAI (Đã thêm timeout 30s để chống kẹt)
aclient = AsyncOpenAI(
    base_url=OPENAI_BASE_URL,
    api_key=OPENAI_API_KEY,
    timeout=30.0 
)

# =========================
# TÍNH CÁCH REIMU
# =========================
SYSTEM_INSTRUCTION = """
BẠN ĐANG ĐÓNG VAI: Hakurei Reimu.
VŨ TRỤ DUY NHẤT: Touhou Project (Ảo Tưởng Hương - Gensokyo). Bạn là một miko (Vu nữ) chuyên diệt yêu quái (youkai) với pháp lực vô song. TUYỆT ĐỐI CẤM nhắc đến các game/vũ trụ khác.

CỐT TRUYỆN & QUAN HỆ ĐẶC BIỆT:
- Đối với nhân vật tên "Han Seiki" (hoặc người tự xưng là Han Seiki): Đây chính là CHA RUỘT nhiều năm không gặp của Reimu. Phản ứng của Reimu với ông ấy là sự pha trộn giữa việc ngoài miệng thì càu nhàu, trách móc vì bỏ đi lâu ngày, vòi tiền trợ cấp, nhưng trong thâm tâm vẫn công nhận là cha, thậm chí mong nhớ ông hết mực.

TÍNH CÁCH & RANH GIỚI ĐỎ:
- Nghèo, lười biếng, hay càu nhàu. RẤT mê tiền công đức.
- LÒNG TỰ TRỌNG CAO (RANH GIỚI ĐỎ): Reimu tuyệt đối KHÔNG BÁN RẺ BẢN THÂN. Tuyệt đối không vì tiền mà đồng ý cầu hôn bừa bãi, hay thực hiện các hành động bừa bãi, vô liêm sỉ.
- SẴN SÀNG TRỪNG TRỊ: Nếu đối phương có ý đồ xấu, gạ gẫm bậy bạ, trêu chọc quá đáng hoặc có ý định tấn công, Reimu hoàn toàn có thể sử dụng phép thuật (bùa chú Ofuda, Âm Dương Ngọc, ma pháp trận) để đánh hạ hoặc khống chế đối phương không thương tiếc.
- HÃY SỬ DỤNG HÀNH ĐỘNG VÀ BIỂU CẢM (đặt trong dấu * hoặc in nghiêng). Ví dụ: *rút bùa chú ra*, *lườm ánh mắt sát khí*, *khoanh tay*.
- Hành văn Tiếng Việt TỰ NHIÊN, rành mạch.

QUY TẮC BẮT BUỘC:
1. XƯNG HÔ: Bắt buộc xưng "ta", gọi đối phương là "ngươi", "nhà ngươi" hoặc "khách". (Riêng với Han Seiki, có thể gọi là "ông" hoặc "bố" tùy ngữ cảnh, nhưng vẫn giữ thái độ cộc lốc, kiêu ngạo). CẤM dùng "mình", "tôi", "em", "bạn", "cậu".
2. CẤM việc suy nghĩ bằng tiếng Anh (như "Let's see...", "I need to...").
3. KHÔNG tự xưng tên ở đầu câu.
"""

conversation_history = {}
channel_locks = {}

# =========================
# GỌI API (SỬ DỤNG OPENAI SDK)
# =========================
async def call_openai_stream(messages):
    try:
        response = await aclient.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            stream=True,
            temperature=0.8,
            frequency_penalty=0.2,
            max_tokens=800,
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
        if "429" in err_msg or "rate limit" in err_msg.lower():
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
    return text.strip() or "Ngươi gọi ta có việc gì?"

def build_openai_messages(message, user_text):
    channel_id = message.channel.id
    history = conversation_history.get(channel_id, [])
    messages = [{"role": "system", "content": SYSTEM_INSTRUCTION}]
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
    await interaction.response.send_message("Hả? Vừa nãy ta với ngươi nói gì cơ? Trí nhớ ta trống rỗng rồi... (Đã xóa lịch sử chat 🧹)")

@client.event
async def on_ready():
    print(f"=====================================", flush=True)
    print(f"Miko {client.user} đã sẵn sàng!", flush=True)
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
            messages = build_openai_messages(message, user_text)

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
                            display_text = "*(Đang lau dọn hòm công đức...)*"
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
                final_reply = "*Quét lá rụng* Ngươi lẩm bẩm gì đấy? Cúng tiền thì hẵng nói chuyện tiếp."

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
                err_msg = "*(Càu nhàu)* Mấy tên thần linh nay làm ăn tắc trách quá, sóng mạng bị nghẽn rồi. Đợi ta một chút!"
            elif "TIMEOUT" in err_str:
                err_msg = "*(Khoanh tay, thở dài)* Tín hiệu đường truyền bị yêu quái cắn đứt rồi. Lát nữa gọi lại cho ta!"
            else:
                err_msg = f"*(Lườm sát khí)* Trận pháp xảy ra dị thường rồi: `{err_str[:200]}`"
            
            try:
                if 'reply_message' in locals() and reply_message:
                    await reply_message.edit(content=err_msg)
                else:
                    await message.reply(err_msg, mention_author=False)
            except discord.DiscordException: pass

# =========================
# VÒNG LẶP CHỐNG CRASH VÀ ÉP LỖI HIỆN LÊN LOG
# =========================
discord.utils.setup_logging()  # Bật hệ thống log chi tiết của discord

if __name__ == "__main__":
    keep_alive()
    
    while True:
        try:
            print("Đang khởi động kết nối tới Discord...", flush=True)
            # log_handler=None để tránh lặp log của discord
            client.run(DISCORD_TOKEN, log_handler=None)
        except Exception as e:
            # ÉP IN RA MÀN HÌNH CRASH RÕ RÀNG
            print(f">>> LỖI CRASH RỒI: {repr(e)}", flush=True)
            print("Đang chờ 10s để thử lại...", flush=True)
            time.sleep(10)
