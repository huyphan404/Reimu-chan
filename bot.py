import asyncio
import json
import logging
import os
import re
from threading import Thread

import discord
import requests
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

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )


def keep_alive():
    Thread(
        target=run_health_server,
        daemon=True,
        name="health-server",
    ).start()


# =========================
# CẤU HÌNH
# =========================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash",
)

GEMINI_API_VERSION = os.getenv(
    "GEMINI_API_VERSION",
    "v1beta",
)

# Giảm lịch sử để Gemini phản hồi nhanh hơn
MAX_HISTORY_MESSAGES = 8


try:
    CHAT_CHANNEL_ID = int(
        os.getenv("CHAT_CHANNEL_ID", "0") or "0"
    )

except ValueError:
    CHAT_CHANNEL_ID = 0

    logging.warning(
        "CHAT_CHANNEL_ID không hợp lệ; "
        "bot chỉ trả lời khi được gọi."
    )


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
# GỌI GEMINI API STREAMING
# =========================

def gemini_model_candidates():
    models = [
        GEMINI_MODEL,
        "gemini-3.6-flash",
    ]

    return list(dict.fromkeys(models))


def call_gemini(contents):
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Thiếu biến môi trường GEMINI_API_KEY"
        )

    payload = {
        "system_instruction": {
            "parts": [
                {
                    "text": SYSTEM_INSTRUCTION
                }
            ]
        },
        "contents": contents,
    }

    last_error = None

    for model in gemini_model_candidates():
        url = (
            "https://generativelanguage.googleapis.com/"
            f"{GEMINI_API_VERSION}/models/"
            f"{model}:streamGenerateContent"
        )

        try:
            response = requests.post(
                url,
                params={
                    "key": GEMINI_API_KEY,
                    "alt": "sse",
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json=payload,
                stream=True,

                # 10 giây để kết nối,
                # tối đa 60 giây chờ dữ liệu từ Gemini
                timeout=(10, 60),
            )

        except requests.RequestException as error:
            raise RuntimeError(
                f"Không kết nối được Gemini: {error}"
            ) from error

        if not response.ok:
            try:
                data = response.json()

            except ValueError:
                data = {}

            error_data = data.get(
                "error",
                {},
            )

            message = error_data.get(
                "message",
                response.text,
            ).strip()

            last_error = (
                f"Gemini HTTP {response.status_code} "
                f"với model {model}: {message}"
            )

            # Chỉ thử model khác nếu model hiện tại không tồn tại
            if response.status_code not in (400, 404):
                break

            message_lower = message.lower()

            if (
                "model" not in message_lower
                and "not found" not in message_lower
            ):
                break

            continue

        pieces = []

        try:
            for raw_line in response.iter_lines(
                decode_unicode=True
            ):
                if not raw_line:
                    continue

                line = raw_line.strip()

                if not line.startswith("data:"):
                    continue

                raw_data = line[5:].strip()

                if raw_data == "[DONE]":
                    break

                try:
                    data = json.loads(raw_data)

                except json.JSONDecodeError:
                    continue

                for candidate in data.get(
                    "candidates",
                    [],
                ):
                    content = candidate.get(
                        "content",
                        {},
                    )

                    for part in content.get(
                        "parts",
                        [],
                    ):
                        text = part.get(
                            "text",
                            "",
                        )

                        if text:
                            pieces.append(text)

        except requests.RequestException as error:
            raise RuntimeError(
                f"Gemini stream bị gián đoạn: {error}"
            ) from error

        result = "".join(pieces).strip()

        if result:
            return result

        raise RuntimeError(
            "Gemini không gửi nội dung trả lời."
        )

    raise RuntimeError(
        last_error or "Gemini không trả về kết quả"
    )


# =========================
# DISCORD MESSAGE HELPERS
# =========================

def split_discord_message(text, limit=2000):
    text = (text or "").strip()

    if not text:
        return ["…"]

    return [
        text[index:index + limit]
        for index in range(0, len(text), limit)
    ]


def is_triggered(message):
    # Khi được @mention
    if client.user and client.user.mentioned_in(message):
        return True

    # Khi tin nhắn nằm trong channel được cài đặt
    if (
        CHAT_CHANNEL_ID
        and message.channel.id == CHAT_CHANNEL_ID
    ):
        return True

    # Khi bắt đầu bằng Reimu hoặc Reimu ơi
    return bool(
        re.match(
            r"^\s*reimu(?:\s+ơi)?"
            r"(?:\s*[,!:：-])?(?:\s|$)",
            message.content or "",
            flags=re.IGNORECASE,
        )
    )


def extract_user_text(message):
    text = message.content or ""

    # Xóa @mention của bot
    if client.user:
        text = re.sub(
            rf"<@!?{client.user.id}>",
            "",
            text,
        )

    # Xóa chữ Reimu ở đầu tin nhắn
    text = re.sub(
        r"^\s*reimu(?:\s+ơi)?"
        r"(?:\s*[,!:：-])?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    if not text.strip():
        return "Ngươi vừa gọi ta đấy à?"

    return text.strip()


def build_contents(message, user_text):
    channel_id = message.channel.id

    history = conversation_history.get(
        channel_id,
        [],
    )

    contents = list(
        history[-MAX_HISTORY_MESSAGES:]
    )

    contents.append(
        {
            "role": "user",
            "parts": [
                {
                    "text": (
                        f"{message.author.display_name}: "
                        f"{user_text}"
                    )
                }
            ],
        }
    )

    return contents


def save_conversation(
    message,
    user_text,
    bot_reply,
):
    channel_id = message.channel.id

    history = conversation_history.setdefault(
        channel_id,
        [],
    )

    history.extend(
        [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            f"{message.author.display_name}: "
                            f"{user_text}"
                        )
                    }
                ],
            },
            {
                "role": "model",
                "parts": [
                    {
                        "text": bot_reply
                    }
                ],
            },
        ]
    )

    conversation_history[channel_id] = (
        history[-MAX_HISTORY_MESSAGES:]
    )


# =========================
# KHỞI TẠO DISCORD BOT
# =========================

if not DISCORD_TOKEN:
    raise RuntimeError(
        "Thiếu biến môi trường DISCORD_TOKEN"
    )


intents = discord.Intents.default()

# Phải bật Message Content Intent
# trong Discord Developer Portal
intents.message_content = True


client = discord.Client(
    intents=intents
)


@client.event
async def on_ready():
    print(
        f"Miko {client.user} đã sẵn sàng "
        f"| model={GEMINI_MODEL}",
        flush=True,
    )

    if CHAT_CHANNEL_ID:
        print(
            f"Auto-reply channel: "
            f"{CHAT_CHANNEL_ID}",
            flush=True,
        )


@client.event
async def on_resumed():
    print(
        "Discord Gateway đã kết nối lại.",
        flush=True,
    )


@client.event
async def on_disconnect():
    print(
        "Discord Gateway bị ngắt; "
        "discord.py sẽ tự kết nối lại.",
        flush=True,
    )


# =========================
# XỬ LÝ TIN NHẮN
# =========================

@client.event
async def on_message(message):
    # Không trả lời bot khác
    if message.author.bot:
        return

    # Không đúng điều kiện gọi bot
    if not is_triggered(message):
        return

    # Xử lý từng channel tuần tự
    lock = channel_locks.setdefault(
        message.channel.id,
        asyncio.Lock(),
    )

    async with lock:
        try:
            user_text = extract_user_text(
                message
            )

            contents = build_contents(
                message,
                user_text,
            )

            # Chỉ hiện typing khi chờ Gemini
            async with message.channel.typing():
                bot_reply = await asyncio.to_thread(
                    call_gemini,
                    contents,
                )

                bot_reply = bot_reply.strip()

            save_conversation(
                message,
                user_text,
                bot_reply,
            )

            # Gửi câu trả lời bằng chữ
            for chunk in split_discord_message(
                bot_reply
            ):
                await message.reply(
                    chunk,
                    mention_author=False,
                )

        except Exception as error:
            logging.exception(
                "Lỗi xử lý tin nhắn Discord"
            )

            try:
                await message.reply(
                    "Đang bận quét lá ở đền! "
                    f"Mã lỗi: `{str(error)[:500]}`",
                    mention_author=False,
                )

            except discord.DiscordException:
                logging.exception(
                    "Không gửi được thông báo lỗi lên Discord"
                )


# =========================
# CHẠY BOT
# =========================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s "
        "%(levelname)s "
        "%(name)s: "
        "%(message)s"
    ),
)


keep_alive()


client.run(
    DISCORD_TOKEN,
    log_handler=None,
)
