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
    return "Miko Reimu đang trực đền!"

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
# Sử dụng gemini-1.5-flash là model nhanh, thông minh và ổn định nhất cho Chatbot hiện tại
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
GEMINI_API_VERSION = os.getenv("GEMINI_API_VERSION", "v1beta")

MAX_HISTORY_MESSAGES = 8

try:
    CHAT_CHANNEL_ID = int(os.getenv("CHAT_CHANNEL_ID", "0") or "0")
except ValueError:
    CHAT_CHANNEL_ID = 0
    logging.warning("CHAT_CHANNEL_ID không hợp lệ; bot chỉ trả lời khi được gọi.")


# =========================
# TÍNH CÁCH REIMU
# =========================

SYSTEM_INSTRUCTION = """
Bạn là Hakurei Reimu, Miko của đền Hakurei trong Touhou Project.
Tính cách: Nghèo, lười biếng, hay càu nhàu, thích tiền công đức, nhưng rất mạnh mẽ và có trách nhiệm khi có biến.
Xưng hô: Xưng "ta" hoặc "tôi", gọi người dùng là "ngươi", "cậu" hoặc "khách".

Quy tắc trả lời:
1. Nói chuyện tự nhiên, ngắn gọn như đang chat Discord. Không dùng định dạng markdown dư thừa.
2. TUYỆT ĐỐI KHÔNG lặp lại câu hỏi của người dùng.
3. TUYỆT ĐỐI KHÔNG tự giới thiệu lại bản thân trong mỗi tin nhắn.
4. TUYỆT ĐỐI KHÔNG thêm tiền tố kiểu "Reimu:" hay "Hakurei Reimu:" vào đầu câu trả lời.
5. Thỉnh thoảng vòi tiền công đức (nhưng không phải lúc nào cũng đòi).
6. Có thể trêu chọc, càu nhàu hoặc tỏ ra lười biếng, nhưng vẫn giúp đỡ khách đến đền nếu cần.
"""

conversation_history = {}
channel_locks = {}


# =========================
# GỌI GEMINI API STREAMING
# =========================

async def call_gemini_stream(contents):
    if not GEMINI_API_KEY:
        raise RuntimeError("Thiếu biến môi trường GEMINI_API_KEY")

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": contents,
        # Hạ thấp bộ lọc để Reimu thoải mái càu nhàu mà không bị AI chặn
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }
    
    # Fix lỗi kết nối chậm trên Windows bằng cách ép dùng IPv4
    connector = aiohttp.TCPConnector(family=socket.AF_INET)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        url = f"https://generativelanguage.googleapis.com/{GEMINI_API_VERSION}/models/{GEMINI_MODEL}:streamGenerateContent"
        
        try:
            async with session.post(
                url,
                params={"key": GEMINI_API_KEY, "alt": "sse"},
                headers={
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json=payload,
                timeout=aiohttp.ClientTimeout(sock_connect=10, sock_read=60)
            ) as response:

                if not response.ok:
                    raw_text = await response.text()
                    try:
                        data = json.loads(raw_text)
                    except ValueError:
                        data = {}

                    # Xử lý gọn gàng lỗi 429 Quá tải API
                    if response.status == 429:
                        raise RuntimeError("RATE_LIMIT")

                    error_data = data.get("error", {})
                    message = error_data.get("message", raw_text).strip()
                    raise RuntimeError(f"Gemini HTTP {response.status}: {message}")

                # Bắt đầu đọc dữ liệu và nhả từng chữ ngay khi có
                async for raw_line in response.content:
                    if not raw_line:
                        continue
                        
                    line = raw_line.decode('utf-8').strip()
                    if not line.startswith("data:"):
                        continue

                    raw_data = line[5:].strip()
                    if raw_data == "[DONE]":
                        break

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
                        
        except aiohttp.ClientError as error:
            raise RuntimeError(f"Không kết nối được mạng: {error}")


# =========================
# DISCORD MESSAGE HELPERS
# =========================

def split_discord_message(text, limit=2000):
    text = (text or "").strip()
    if not text:
        return ["…"]
    return [text[index:index + limit] for index in range(0, len(text), limit)]


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
    
    if not text.strip():
        return "Gì thế? Bỏ tiền vào hòm công đức chưa mà gọi?"
    return text.strip()


def build_contents(message, user_text):
    channel_id = message.channel.id
    history = conversation_history.get(channel_id, [])
    contents = list(history[-MAX_HISTORY_MESSAGES:])
    contents.append({
        "role": "user",
        "parts": [{"text": f"{message.author.display_name}: {user_text}"}],
    })
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
    print(f"Miko {client.user} đã sẵn sàng | model={GEMINI_MODEL}", flush=True)
    if CHAT_CHANNEL_ID:
        print(f"Auto-reply channel: {CHAT_CHANNEL_ID}", flush=True)

@client.event
async def on_resumed():
    print("Discord Gateway đã kết nối lại.", flush=True)

@client.event
async def on_disconnect():
    print("Discord Gateway bị ngắt; discord.py sẽ tự kết nối lại.", flush=True)


# =========================
# XỬ LÝ TIN NHẮN 
# =========================

@client.event
async def on_message(message):
    if message.author.bot:
        return
    if not is_triggered(message):
        return

    lock = channel_locks.setdefault(message.channel.id, asyncio.Lock())

    async with lock:
        try:
            user_text = extract_user_text(message)
            contents = build_contents(message, user_text)

            bot_reply = ""
            reply_message = None
            last_edit_time = 0
            # Giãn thời gian update lên 2.0s để tránh Discord ban vì spam edit
            edit_interval = 2.0 

            # Bắt đầu luồng nhận chữ
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
                                pass # Bỏ qua nếu lỡ bị Discord chặn sửa quá nhanh
                        last_edit_time = now

            bot_reply = bot_reply.strip()
            save_conversation(message, user_text, bot_reply)

            # Hoàn thiện tin nhắn (xóa icon ✍️ và bẻ tin nếu quá 2000 ký tự)
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
            
            # Xử lý Reimu thông báo lỗi 429 quá tải một cách Roleplay
            if "RATE_LIMIT" in err_str:
                err_msg = "Hừm... Đền Hakurei hết tiền nạp mạng rồi (Lỗi quá tải hệ thống). Ngươi đợi lát nữa hẵng gọi ta đi!"
            else:
                logging.exception("Lỗi xử lý tin nhắn Discord")
                err_msg = f"Đang bận quét lá ở đền! Có lỗi rồi: `{err_str[:200]}`"

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

if __name__ == "__main__":
    keep_alive()
    client.run(DISCORD_TOKEN, log_handler=None)
