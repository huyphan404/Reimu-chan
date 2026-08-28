import asyncio
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
    # Render cung cấp PORT qua biến môi trường.
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

# Model hiện tại mà API của bạn yêu cầu
GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash",
)

GEMINI_API_VERSION = os.getenv(
    "GEMINI_API_VERSION",
    "v1beta",
)

MAX_HISTORY_MESSAGES = 12
DEFAULT_GIF_ACTION = "smile"

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


VALID_GIF_ACTIONS = {
    "bite",
    "blush",
    "bored",
    "cry",
    "dance",
    "facepalm",
    "happy",
    "laugh",
    "pat",
    "pout",
    "punch",
    "slap",
    "sleep",
    "smile",
    "think",
    "wave",
    "wink",
}


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


conversation_history = {}
channel_locks = {}


# =========================
# GỌI GEMINI API
# =========================

def gemini_model_candidates():
    """
    Thử model đang cấu hình trước.
    Nếu biến môi trường đang còn model cũ,
    sẽ chuyển sang gemini-3.6-flash.
    """

    models = [
        GEMINI_MODEL,
        "gemini-3.6-flash",
    ]

    # Xóa model bị trùng
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
            f"{model}:generateContent"
        )

        try:
            response = requests.post(
                url,
                params={
                    "key": GEMINI_API_KEY
                },
                headers={
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=45,
            )

        except requests.RequestException as error:
            raise RuntimeError(
                f"Không kết nối được Gemini: {error}"
            ) from error

        try:
            data = response.json()

        except ValueError:
            data = {}

        if response.ok:
            try:
                return data[
                    "candidates"
                ][0][
                    "content"
                ][
                    "parts"
                ][0]["text"]

            except (
                KeyError,
                IndexError,
                TypeError,
            ) as error:
                feedback = data.get(
                    "promptFeedback",
                    data,
                )

                raise RuntimeError(
                    "Gemini trả về dữ liệu không hợp lệ: "
                    f"{feedback}"
                ) from error

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

        # Nếu model không tồn tại thì thử model 3.6
        if response.status_code not in (400, 404):
            break

        message_lower = message.lower()

        if (
            "model" not in message_lower
            and "not found" not in message_lower
        ):
            break

    raise RuntimeError(
        last_error or "Gemini không trả về kết quả"
    )


# =========================
# LẤY GIF
# =========================

def get_anime_gif(action):
    if action not in VALID_GIF_ACTIONS:
        action = DEFAULT_GIF_ACTION

    try:
        response = requests.get(
            f"https://nekos.best/api/v2/{action}",
            timeout=10,
        )

        response.raise_for_status()

        return response.json()[
            "results"
        ][0]["url"]

    except (
        requests.RequestException,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
    ):
        # GIF lỗi thì bot vẫn trả lời bình thường
        return None


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

    # Khi tin nhắn bắt đầu bằng "Reimu"
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


def split_reply_and_gif(reply):
    gif_match = re.search(
        r"\[GIF:\s*([a-zA-Z]+)\s*\]",
        reply or "",
    )

    action = DEFAULT_GIF_ACTION

    if gif_match:
        requested_action = (
            gif_match.group(1).lower()
        )

        if requested_action in VALID_GIF_ACTIONS:
            action = requested_action

        reply = reply.replace(
            gif_match.group(0),
            "",
            1,
        ).strip()

    return reply, action


# =========================
# KHỞI TẠO DISCORD BOT
# =========================

if not DISCORD_TOKEN:
    raise RuntimeError(
        "Thiếu biến môi trường DISCORD_TOKEN"
    )


intents = discord.Intents.default()

# Phải bật thêm Message Content Intent
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

            async with message.channel.typing():
                raw_reply = await asyncio.to_thread(
                    call_gemini,
                    contents,
                )

                bot_reply, gif_action = (
                    split_reply_and_gif(
                        raw_reply
                    )
                )

                save_conversation(
                    message,
                    user_text,
                    bot_reply,
                )

                # Gửi nội dung trả lời
                for chunk in split_discord_message(
                    bot_reply
                ):
                    await message.reply(
                        chunk,
                        mention_author=False,
                    )

                # Lấy và gửi GIF
                gif_url = await asyncio.to_thread(
                    get_anime_gif,
                    gif_action,
                )

                if gif_url:
                    await message.channel.send(
                        gif_url
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
