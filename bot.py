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
    return "Bot đang hoạt động bình thường!"

def run_health_server():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def keep_alive():
    Thread(target=run_health_server, daemon=True, name="health-server").start()

# =========================
# CẤU HÌNH
# =========================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
GEMINI_API_VERSION = os.getenv("GEMINI_API_VERSION", "v1beta")

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
# GỌI GEMINI API (CƠ CHẾ AUTO-RETRY CHUYÊN NGHIỆP)
# =========================

async def call_gemini_stream(contents):
    if not GEMINI_API_KEY:
        raise RuntimeError("Thiếu biến môi trường GEMINI_API_KEY")

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": contents,
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }
    
    # Danh sách model dự phòng. Nếu model đầu bị lỗi 404, bot sẽ tự động lùi xuống dùng model tiếp theo.
    models_to_try = list(dict.fromkeys([GEMINI_MODEL, "gemini-1.5-flash", "gemini-2.0-flash", "gemini-pro"]))
    
    connector = aiohttp.TCPConnector(family=socket.AF_INET)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/{GEMINI_API_VERSION}/models/{model}:streamGenerateContent"
            
            # Thử lại tối đa 3 lần nếu gặp lỗi mạng hoặc 429 (Quá tải)
            for attempt in range(3):
                try:
                    async with session.post(
                        url,
                        params={"key": GEMINI_API_KEY, "alt": "sse"},
                        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
                        json=payload,
                        timeout=aiohttp.ClientTimeout(sock_connect=10, sock_read=60)
                    ) as response:

                        if response.status == 429:
                            # Lỗi quá tải (Rate Limit): Im lặng chờ 2s -> 4s -> 6s rồi thử lại ngầm
                            await asyncio.sleep(2 * (attempt + 1))
                            continue 
                            
                        if not response.ok:
                            # Nếu 404 (sai tên model) hoặc 400 (lỗi data), bỏ qua model này để thử model tiếp theo trong danh sách
                            if response.status in (404, 400):
                                break 
                            # Các lỗi server khác (500, 502), chờ 2s rồi thử lại
                            await asyncio.sleep(2)
                            continue

                        # Kết nối thành công, bắt đầu nhận chữ
                        async for raw_line in response.content:
                            if not raw_line: continue
                                
                            line = raw_line.decode('utf-8').strip()
                            if not line.startswith("data:"): continue

                            raw_data = line[5:].strip()
                            if raw_data == "[DONE]": break

                            try:
                                data = json.loads(raw_data)
                                for candidate in data.get("candidates", []):
                                    content = candidate.get("content", {})
                                    for part in content.get("parts", []):
                                        text = part.get("text", "")
                                        if text:
                                            yield text
                            except json.JSONDecodeError:
                                continue
                                
                        return # Lấy xong câu trả lời, kết thúc hàm thành công!
                        
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    # Lỗi rớt mạng cục bộ, đợi ngầm 2s rồi thử lại
                    await asyncio.sleep(2)
                    continue

    # Chỉ khi thử tất cả các cách trên mà vẫn không được thì mới báo lỗi mộc mạc
    yield "Xin lỗi, đường truyền tín hiệu của ta đang gặp vấn đề. Ngươi chờ một lát rồi nhắn lại nhé."

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

def build_contents(message, user_text):
    channel_id = message.channel.id
    history = conversation_history.get(channel_id, [])
    contents = list(history[-MAX_HISTORY_MESSAGES:])
    contents.append({"role": "user", "parts": [{"text": f"{message.author.display_name}: {user_text}"}]})
    return contents

def save_conversation(message, user_text, bot_reply):
    channel_id = message.channel.id
    history = conversation_history.setdefault(channel_id, [])
    history.extend([
        {"role": "user", "parts": [{"text": f"{message.author.display_name}: {user_text}"}]},
        {"role": "model", "parts": [{"text": bot_reply}]},
    ])
    conversation_history[channel_id] = history[-MAX_HISTORY_MESSAGES:]

# =========================
# KHỞI TẠO DISCORD BOT
# =========================

if not DISCORD_TOKEN:
    raise RuntimeError("Thiếu biến môi trường DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Bot {client.user} đã hoạt động!", flush=True)

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
            contents = build_contents(message, user_text)

            bot_reply = ""
            reply_message = None
            last_edit_time = 0
            edit_interval = 2.0 

            async with message.channel.typing():
                async for chunk in call_gemini_stream(contents):
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
                    await reply_message.edit(content=bot_reply[:2000])
                    for chunk_str in split_discord_message(bot_reply[2000:]):
                        await message.reply(chunk_str, mention_author=False)
                else:
                    for chunk_str in split_discord_message(bot_reply):
                        await message.reply(chunk_str, mention_author=False)

        except Exception as error:
            logging.error(f"Lỗi hệ thống: {error}")

# =========================
# CHẠY BOT
# =========================

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

if __name__ == "__main__":
    keep_alive()
    client.run(DISCORD_TOKEN, log_handler=None)
