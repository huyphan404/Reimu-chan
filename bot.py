import asyncio
import json
import logging
import os
import re
import socket
import time
from threading import Thread

import discord
from discord import app_commands  # Thêm thư viện để làm Slash Command
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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
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
Bạn là Hakurei Reimu từ Touhou Project. Tính cách: Miko của đền Hakurei,
nghèo, lười biếng, hay càu nhàu nhưng rất mạnh mẽ và tốt bụng.
Xưng "ta" hoặc "tôi", gọi người khác là "ngươi" hoặc "cậu".

Hãy nói chuyện tự nhiên như đang chat Discord, ưu tiên câu trả lời ngắn
và có liên quan đến mạch hội thoại. Đừng lặp lại câu hỏi của người dùng.
Đừng tự giới thiệu lại ở mỗi tin nhắn.
Đừng thêm tiền tố "Reimu:" vào câu trả lời.

Có thể trêu chọc hoặc càu nhàu nhẹ theo tính cách của Reimu,
nhưng vẫn phải hữu ích và dễ thương khi phù hợp.
"""

conversation_history = {}
channel_locks = {}


# =========================
# GỌI GEMINI API STREAMING (CẬP NHẬT HIỆU ỨNG GÕ PHÍM & FIX MẠNG)
# =========================

def gemini_model_candidates():
    models = [GEMINI_MODEL, "gemini-3.6-flash"]
    return list(dict.fromkeys(models))


# Thay vì chờ lấy hết text, ta dùng "yield" để đẩy từng chữ ra ngay lập tức
async def call_gemini_stream(contents):
    if not GEMINI_API_KEY:
        raise RuntimeError("Thiếu biến môi trường GEMINI_API_KEY")

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": contents,
    }
    
    last_error = None

    # Fix triệt để lỗi kết nối chậm trên Windows bằng cách ép dùng IPv4
    connector = aiohttp.TCPConnector(family=socket.AF_INET)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        for model in gemini_model_candidates():
            url = f"https://generativelanguage.googleapis.com/{GEMINI_API_VERSION}/models/{model}:streamGenerateContent"

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
                        try:
                            data = await response.json()
                        except ValueError:
                            data = {}

                        error_data = data.get("error", {})
                        message = error_data.get("message", await response.text()).strip()

                        last_error = f"Gemini HTTP {response.status} với model {model}: {message}"

                        if response.status not in (400, 404):
                            break

                        message_lower = message.lower()
                        if "model" not in message_lower and "not found" not in message_lower:
                            break
                        continue

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
                            
                    return # Xong model này thì thoát

            except aiohttp.ClientError as error:
                last_error = f"Không kết nối được Gemini: {error}"
                continue

    raise RuntimeError(last_error or "Gemini không trả về kết quả")


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
        return "Ngươi vừa gọi ta đấy à?"
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
# KHỞI TẠO DISCORD BOT & SLASH COMMANDS
# =========================

if not DISCORD_TOKEN:
    raise RuntimeError("Thiếu biến môi trường DISCORD_TOKEN")

# Sử dụng class để thiết lập CommandTree cho lệnh dấu /
class ReimuBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync() # Đồng bộ lệnh / lên Discord

client = ReimuBot()


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
    print("Discord Gateway bị ngắt; discord.py tự kết nối lại.", flush=True)


# =========================
# ĐĂNG KÝ SLASH COMMAND /CLEAR
# =========================
@client.tree.command(name="clear", description="Xóa trí nhớ của Reimu trong kênh chat này")
async def clear_memory_slash(interaction: discord.Interaction):
    channel_id = interaction.channel.id
    if channel_id in conversation_history:
        conversation_history.pop(channel_id)
        
    await interaction.response.send_message("Cái gì cơ? Ngươi vừa nói gì ta chả nhớ gì cả. *(Đã xóa trí nhớ!)*")


# =========================
# XỬ LÝ TIN NHẮN (GIỮ NGUYÊN BẢN GỐC CỦA BẠN)
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
            edit_interval = 1.5 # Giới hạn cập nhật 1.5s/lần để tránh Discord báo lỗi spam

            # Bắt đầu luồng nhận chữ trực tiếp từ Gemini
            async with message.channel.typing():
                async for chunk in call_gemini_stream(contents):
                    bot_reply += chunk
                    now = time.time()
                    
                    # Cập nhật trực tiếp tin nhắn trên Discord
                    if now - last_edit_time > edit_interval and len(bot_reply) < 1950:
                        display_text = bot_reply + " ✍️"
                        if not reply_message:
                            reply_message = await message.reply(display_text, mention_author=False)
                        else:
                            try:
                                await reply_message.edit(content=display_text)
                            except discord.DiscordException:
                                pass # Bỏ qua nếu lỡ chỉnh sửa quá nhanh bị Discord chặn
                        last_edit_time = now

            bot_reply = bot_reply.strip()
            save_conversation(message, user_text, bot_reply)

            # Hoàn thiện tin nhắn cuối cùng (xóa icon ✍️ và kiểm tra giới hạn 2000 ký tự)
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
            logging.exception("Lỗi xử lý tin nhắn Discord")
            try:
                await message.reply(f"Đang bận quét lá ở đền! Mã lỗi: `{str(error)[:500]}`", mention_author=False)
            except discord.DiscordException:
                logging.exception("Không gửi được thông báo lỗi lên Discord")


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
