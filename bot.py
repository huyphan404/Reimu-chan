import asyncio
import json
import logging
import os
import re
import socket
import time
from threading import Thread

import discord
import aiohttp
from flask import Flask

# =========================
# HEALTH CHECK CHO DEPLOY
# =========================
app = Flask(__name__)

@app.get("/")
def home():
    return "Miko Reimu đang trực đền (Powered by OpenAI/Groq/OpenRouter)!"

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

# Lấy cấu hình bạn vừa nhập
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
# Bỏ dấu gạch chéo ở cuối URL (nếu có lỡ nhập thừa) để tránh lỗi API
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip('/')

MAX_HISTORY_MESSAGES = 8

try:
    CHAT_CHANNEL_ID = int(os.getenv("CHAT_CHANNEL_ID", "0") or "0")
except ValueError:
    CHAT_CHANNEL_ID = 0

# =========================
# TÍNH CÁCH REIMU
# =========================
SYSTEM_INSTRUCTION = """
Bạn là Hakurei Reimu, Miko của đền Hakurei trong Touhou Project.
Tính cách: Nghèo, lười biếng, hay càu nhàu, nhưng rất mạnh mẽ và tốt bụng.
Xưng "ta" hoặc "tôi", gọi người khác là "ngươi" hoặc "cậu".

Hãy nói chuyện tự nhiên như đang chat Discord, ưu tiên câu trả lời ngắn gọn.
Đừng lặp lại câu hỏi. Đừng tự giới thiệu lại ở mỗi tin nhắn. 
KHÔNG thêm tiền tố "Reimu:" vào đầu câu trả lời.
"""

conversation_history = {}
channel_locks = {}

# =========================
# GỌI API (STREAMING CHỮ TỪNG DÒNG)
# =========================
async def call_openai_stream(messages):
    if not OPENAI_API_KEY:
        raise RuntimeError("Thiếu biến môi trường OPENAI_API_KEY!")

    url = f"{OPENAI_BASE_URL}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }
    
    # Ở OpenRouter, bắt buộc phải có mục này nếu dùng bản free
    if "openrouter" in OPENAI_BASE_URL:
        headers["HTTP-Referer"] = "https://discord.com"
        headers["X-Title"] = "Reimu Discord Bot"

    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "stream": True
    }

    connector = aiohttp.TCPConnector(family=socket.AF_INET)
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            async with session.post(
                url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(sock_connect=10, sock_read=60)
            ) as response:
                
                if response.status == 429:
                    raise RuntimeError("RATE_LIMIT")
                    
                if not response.ok:
                    raw_text = await response.text()
                    raise RuntimeError(f"Lỗi hệ thống ({response.status}): {raw_text}")

                # Nhận dữ liệu stream
                async for raw_line in response.content:
                    if not raw_line: continue
                    
                    line = raw_line.decode('utf-8').strip()
                    if not line.startswith("data:"): continue
                    
                    raw_data = line[5:].strip()
                    if raw_data == "[DONE]": break

                    try:
                        data = json.loads(raw_data)
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            text = delta.get("content", "")
                            if text:
                                yield text
                    except json.JSONDecodeError:
                        continue

        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            raise RuntimeError(f"Lỗi mạng: {error}")

# =========================
# DISCORD MESSAGE HELPERS
# =========================
def split_discord_message(text, limit=2000):
    text = (text or "").strip()
    return [text[i:i + limit] for i in range(0, max(1, len(text)), limit)]

def is_triggered(message):
    if client.user and client.user.mentioned_in(message):
        return True
    if CHAT_CHANNEL_ID and message.channel.id == CHAT_CHANNEL_ID:
        return True
    return bool(re.match(r"^\s*reimu(?:\s+ơi)?(?:\s*[,!:：-])?(?:\s|$)", message.content or "", flags=re.IGNORECASE))

def extract_user_text(message):
    text = message.content or ""
    if client.user:
        text = re.sub(rf"<@!?{client.user.id}>", "", text)
    text = re.sub(r"^\s*reimu(?:\s+ơi)?(?:\s*[,!:：-])?\s*", "", text, flags=re.IGNORECASE)
    return text.strip() or "Ngươi gọi ta có việc gì?"

def build_openai_messages(message, user_text):
    channel_id = message.channel.id
    history = conversation_history.get(channel_id, [])
    
    messages = [{"role": "system", "content": SYSTEM_INSTRUCTION}]
    
    for msg in history[-MAX_HISTORY_MESSAGES:]:
        messages.append(msg)
        
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

@client.event
async def on_ready():
    print(f"Miko {client.user} đã sẵn sàng (Model: {OPENAI_MODEL})!", flush=True)

# =========================
# XỬ LÝ TIN NHẮN 
# =========================
@client.event
async def on_message(message):
    if message.author.bot or not is_triggered(message):
        return

    lock = channel_locks.setdefault(message.channel.id, asyncio.Lock())
    async with lock:
        try:
            user_text = extract_user_text(message)
            messages = build_openai_messages(message, user_text)

            bot_reply = ""
            reply_message = None
            last_edit_time = 0
            edit_interval = 2.0 

            async with message.channel.typing():
                async for chunk in call_openai_stream(messages):
                    bot_reply += chunk
                    now = time.time()
                    
                    if now - last_edit_time > edit_interval and len(bot_reply) < 1950:
                        display_text = bot_reply + " ✍️"
                        if not reply_message:
                            reply_message = await message.reply(display_text, mention_author=False)
                        else:
                            try:
                                await reply_message.edit(content=display_text)
                            except discord.DiscordException:
                                pass
                        last_edit_time = now

            bot_reply = bot_reply.strip()
            if bot_reply:
                save_conversation(message, user_text, bot_reply)
                if reply_message:
                    if len(bot_reply) <= 2000:
                        await reply_message.edit(content=bot_reply)
                    else:
                        await reply_message.edit(content=bot_reply[:2000])
                        for chunk_str in split_discord_message(bot_reply[2000:]):
                            await message.reply(chunk_str, mention_author=False)
                else:
                    for chunk_str in split_discord_message(bot_reply):
                        await message.reply(chunk_str, mention_author=False)

        except Exception as error:
            err_str = str(error)
            if "RATE_LIMIT" in err_str:
                err_msg = "*(Quá tải mạng lưới một chút, đợi ta vài giây rồi gọi lại nhé!)*"
            else:
                logging.error(f"Lỗi: {err_str}")
                err_msg = f"*(Lỗi hệ thống, kiểm tra lại API Key hoặc Model)*: `{err_str[:200]}`"

            try:
                if 'reply_message' in locals() and reply_message:
                    await reply_message.edit(content=err_msg)
                else:
                    await message.reply(err_msg, mention_author=False)
            except discord.DiscordException:
                pass

# =========================
# CHẠY BOT
# =========================
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

if __name__ == "__main__":
    keep_alive()
    client.run(DISCORD_TOKEN, log_handler=None)
