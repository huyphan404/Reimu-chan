import asyncio
import os
import re
from threading import Thread

import discord
import requests
from flask import Flask


# =========================
# WEBSERVER GIỮ BOT ONLINE
# =========================

app = Flask(__name__)


@app.route("/")
def home():
    return "Miko Reimu đang trực đền miễn phí!"


def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    thread = Thread(target=run, daemon=True)
    thread.start()


# =========================
# CẤU HÌNH
# =========================

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Model Gemini mới
GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_API_VERSION = "v1beta"

# Số tin nhắn gần nhất Reimu ghi nhớ
MAX_HISTORY_MESSAGES = 12

# Nếu Gemini không chọn GIF thì dùng GIF mặc định này
DEFAULT_GIF_ACTION = "smile"

# Để 0 nếu chỉ muốn gọi bằng @mention hoặc chữ "Reimu".
# Nếu đặt Channel ID, bot sẽ tự trả lời mọi tin nhắn trong kênh đó.
CHAT_CHANNEL_ID = int(
    os.environ.get("CHAT_CHANNEL_ID", "0") or "0"
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

Chỉ thêm tối đa 1 GIF tag khi cảm xúc hoặc hành động thật sự phù hợp.
Nếu không phù hợp thì không thêm GIF.

Các GIF tag hợp lệ là:
[GIF: bite], [GIF: blush], [GIF: bored], [GIF: cry],
[GIF: dance], [GIF: facepalm], [GIF: happy], [GIF: laugh],
[GIF: pat], [GIF: pout], [GIF: punch], [GIF: slap],
[GIF: sleep], [GIF: smile], [GIF: think], [GIF: wave],
[GIF: wink].
"""


# Lịch sử lưu trong RAM.
# Khi Render restart hoặc deploy lại thì lịch sử sẽ reset.
conversation_history = {}


# =========================
# GỌI GEMINI API
# =========================

def call_gemini(contents):
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Thiếu biến môi trường GEMINI_API_KEY"
        )

    url = (
        f"https://generativelanguage.googleapis.com/"
        f"{GEMINI_API_VERSION}/models/{GEMINI_MODEL}:generateContent"
    )

    payload = {
        "system_instruction": {
            "parts": [
                {
                    "text": SYSTEM_INSTRUCTION
                }
            ]
        },
        "contents": contents
    }

    response = requests.post(
        url,
        params={
            "key": GEMINI_API_KEY
        },
        headers={
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=30
    )

    try:
        data = response.json()
    except ValueError:
        data = {}

    if not response.ok:
        error = data.get("error", {})
        error_message = error.get(
            "message",
            response.text
        )

        raise RuntimeError(
            f"Gemini HTTP {response.status_code} "
            f"với model {GEMINI_MODEL}: {error_message}"
        )

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (
        KeyError,
        IndexError,
        TypeError
    ) as error:
        raise RuntimeError(
            f"Gemini trả về dữ liệu không hợp lệ: {data}"
        ) from error


# =========================
# LẤY GIF
# =========================

def get_anime_gif(action):
    try:
        response = requests.get(
            f"https://nekos.best/api/v2/{action}",
            timeout=10
        )

        response.raise_for_status()

        return response.json()["results"][0]["url"]

    except (
        requests.RequestException,
        KeyError,
        IndexError,
        TypeError,
        ValueError
    ):
        return None


# =========================
# TÁCH TIN NHẮN DISCORD
# =========================

def split_discord_message(text, limit=2000):
    if not text:
        return [""]

    return [
        text[index:index + limit]
        for index in range(0, len(text), limit)
    ]


# =========================
# KIỂM TRA CÁCH GỌI BOT
# =========================

def is_triggered(message):
    """
    Bot phản hồi khi:

    1. Được @mention.
    2. Tin nhắn bắt đầu bằng Reimu hoặc Reimu ơi.
    3. Tin nhắn nằm trong CHAT_CHANNEL_ID nếu đã cài đặt.
    """

    if client.user and client.user.mentioned_in(message):
        return True

    if (
        CHAT_CHANNEL_ID
        and message.channel.id == CHAT_CHANNEL_ID
    ):
        return True

    return bool(
        re.match(
            r"^\s*reimu(?:\s+ơi)?"
            r"(?:\s*[,!:：-])?(?:\s|$)",
            message.content,
            flags=re.IGNORECASE
        )
    )


def extract_user_text(message):
    """
    Xóa @mention hoặc chữ Reimu ở đầu tin nhắn.
    """

    text = message.content

    if client.user:
        text = re.sub(
            rf"<@!?{client.user.id}>",
            "",
            text
        )

    text = re.sub(
        r"^\s*reimu(?:\s+ơi)?"
        r"(?:\s*[,!:：-])?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    if not text.strip():
        return "Ngươi vừa gọi ta đấy à?"

    return text.strip()


# =========================
# TẠO NGỮ CẢNH HỘI THOẠI
# =========================

def build_contents(message, user_text):
    channel_id = message.channel.id

    history = conversation_history.get(
        channel_id,
        []
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
            ]
        }
    )

    return contents


def save_conversation(
    message,
    user_text,
    bot_reply
):
    channel_id = message.channel.id

    history = conversation_history.setdefault(
        channel_id,
        []
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
                ]
            },
            {
                "role": "model",
                "parts": [
                    {
                        "text": bot_reply
                    }
                ]
            }
        ]
    )

    conversation_history[channel_id] = (
        history[-MAX_HISTORY_MESSAGES:]
    )


# =========================
# KIỂM TRA TOKEN
# =========================

if not DISCORD_TOKEN:
    raise RuntimeError(
        "Thiếu biến môi trường DISCORD_TOKEN"
    )


# =========================
# KHỞI TẠO DISCORD BOT
# =========================

intents = discord.Intents.default()

# Bắt buộc để bot đọc nội dung tin nhắn
intents.message_content = True

client = discord.Client(
    intents=intents
)


@client.event
async def on_ready():
    print(
        f"Miko {client.user} đã sẵn sàng nhận tiền công đức!"
    )

    print(
        f"Đang dùng Gemini model: {GEMINI_MODEL}"
    )

    print(
        "Có thể gọi bot bằng @mention "
        "hoặc bắt đầu tin nhắn bằng 'Reimu'."
    )

    print(
        "Bot sẽ tự gửi GIF sau mỗi câu trả lời."
    )

    if CHAT_CHANNEL_ID:
        print(
            f"Tự động trả lời trong channel ID: "
            f"{CHAT_CHANNEL_ID}"
        )


# =========================
# XỬ LÝ TIN NHẮN
# =========================

@client.event
async def on_message(message):
    # Không trả lời chính mình
    if message.author == client.user:
        return

    # Không đúng điều kiện gọi bot thì bỏ qua
    if not is_triggered(message):
        return

    user_text = extract_user_text(message)

    contents = build_contents(
        message,
        user_text
    )

    async with message.channel.typing():
        try:
            # Gọi Gemini ngoài event loop
            # để Discord không bị đứng nếu API phản hồi chậm.
            bot_reply = await asyncio.to_thread(
                call_gemini,
                contents
            )

            save_conversation(
                message,
                user_text,
                bot_reply
            )

            gif_match = re.search(
                r"\[GIF:(.*?)\]",
                bot_reply
            )

            if gif_match:
                # Dùng GIF do Gemini lựa chọn
                action = gif_match.group(
                    1
                ).strip().lower()

                bot_reply = bot_reply.replace(
                    gif_match.group(0),
                    ""
                ).strip()
            else:
                # Nếu Gemini không chọn GIF,
                # dùng GIF mặc định là smile.
                action = DEFAULT_GIF_ACTION

            gif_url = await asyncio.to_thread(
                get_anime_gif,
                action
            )

            # Gửi câu trả lời
            for chunk in split_discord_message(
                bot_reply
            ):
                await message.reply(chunk)

            # Gửi GIF sau câu trả lời
            if gif_url:
                await message.channel.send(
                    gif_url
                )

        except Exception as error:
            print(
                f"Lỗi: {error}"
            )

            await message.reply(
                "Đang bận quét lá ở đền! "
                f"Mã lỗi: `{error}`"
            )


# =========================
# CHẠY BOT
# =========================

keep_alive()
client.run(DISCORD_TOKEN)
