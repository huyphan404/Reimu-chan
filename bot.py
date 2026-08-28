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
# CẤU HÌNH BOT
# =========================

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# gemini-1.5-flash đã bị ngừng hỗ trợ.
# Có thể đổi model bằng biến môi trường GEMINI_MODEL.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_VERSION = "v1beta"


SYSTEM_INSTRUCTION = (
    "Bạn là Hakurei Reimu từ Touhou Project. Tính cách: Miko của đền Hakurei, "
    "nghèo, lười biếng, hay càu nhàu nhưng rất mạnh mẽ và tốt bụng. "
    "Xưng 'ta' hoặc 'tôi', gọi người khác là 'ngươi' hoặc 'cậu'. "
    "LUẬT BẮT BUỘC: Khi thực hiện hành động hoặc biểu cảm, hãy chọn đúng 1 "
    "trong các từ tiếng Anh sau và đặt ở cuối câu: "
    "[GIF: bite], [GIF: blush], [GIF: bored], [GIF: cry], [GIF: dance], "
    "[GIF: facepalm], [GIF: happy], [GIF: laugh], [GIF: pat], [GIF: pout], "
    "[GIF: punch], [GIF: slap], [GIF: sleep], [GIF: smile], [GIF: think], "
    "[GIF: wave], [GIF: wink]."
)


# =========================
# GỌI GEMINI API
# =========================

def call_gemini(prompt_text):
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
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": prompt_text
                    }
                ]
            }
        ]
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
        error_message = error.get("message", response.text)

        raise RuntimeError(
            f"Gemini HTTP {response.status_code} "
            f"với model {GEMINI_MODEL}: {error_message}"
        )

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as error:
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
    """
    Discord giới hạn mỗi tin nhắn tối đa 2000 ký tự.
    """
    if not text:
        return [""]

    return [
        text[index:index + limit]
        for index in range(0, len(text), limit)
    ]


# =========================
# KIỂM TRA BIẾN MÔI TRƯỜNG
# =========================

if not DISCORD_TOKEN:
    raise RuntimeError(
        "Thiếu biến môi trường DISCORD_TOKEN"
    )


# =========================
# KHỞI TẠO DISCORD BOT
# =========================

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(
        f"Miko {client.user} đã sẵn sàng nhận tiền công đức!"
    )

    print(
        f"Đang sử dụng Gemini model: {GEMINI_MODEL}"
    )


@client.event
async def on_message(message):
    # Không trả lời chính mình
    if message.author == client.user:
        return

    # Chỉ phản hồi khi được mention
    if client.user.mentioned_in(message):
        user_text = re.sub(
            rf"<@!?{client.user.id}>",
            "",
            message.content
        ).strip()

        if not user_text:
            user_text = "Ngươi vừa gọi ta đấy à?"

        async with message.channel.typing():
            try:
                # requests là hàm đồng bộ.
                # Chạy trong thread để không làm Discord bot bị treo.
                bot_reply = await asyncio.to_thread(
                    call_gemini,
                    user_text
                )

                gif_url = None

                gif_match = re.search(
                    r"\[GIF:(.*?)\]",
                    bot_reply
                )

                if gif_match:
                    action = gif_match.group(1).strip().lower()

                    gif_url = await asyncio.to_thread(
                        get_anime_gif,
                        action
                    )

                    bot_reply = bot_reply.replace(
                        gif_match.group(0),
                        ""
                    ).strip()

                # Gửi từng phần nếu câu trả lời dài hơn 2000 ký tự
                for chunk in split_discord_message(bot_reply):
                    await message.reply(chunk)

                if gif_url:
                    await message.channel.send(gif_url)

            except Exception as error:
                print(f"Lỗi: {error}")

                await message.reply(
                    f"Đang bận quét lá ở đền! "
                    f"Mã lỗi: `{error}`"
                )


# =========================
# CHẠY BOT
# =========================

keep_alive()
client.run(DISCORD_TOKEN)
