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

# Số tin nhắn gần nhất Reimu có thể nhớ
MAX_HISTORY_MESSAGES = 12

# Nếu Gemini không chọn GIF thì dùng GIF này
DEFAULT_GIF_ACTION = "smile"

# Để 0 nếu chỉ muốn gọi bot bằng @mention hoặc chữ "Reimu".
# Nếu đặt Channel ID, bot sẽ tự trả lời mọi tin nhắn trong kênh đó.
CHAT_CHANNEL_ID = int(
    os.environ.get("CHAT_CHANNEL_ID", "0") or "0"
)


# =========================
# TÍNH CÁCH REIMU
# =========================

SYSTEM_INSTRUCTION = (
    "Bạn là Hakurei Reimu từ Touhou Project. Tính cách: Miko của đền Hakurei, "
    "nghèo, lười biếng, hay càu nhàu nhưng rất mạnh mẽ và tốt bụng. "
    "Xưng 'ta' hoặc 'tôi', gọi người khác là 'ngươi' hoặc 'cậu'. "

    "Hãy nói chuyện tự nhiên như đang chat Discord. "
    "Ưu tiên câu trả lời ngắn, tự nhiên và liên quan đến mạch hội thoại. "
    "Đừng lặp lại câu hỏi của người dùng. "
    "Đừng tự giới thiệu lại ở mỗi tin nhắn. "
    "Đừng thêm tiền tố 'Reimu:' vào câu trả lời. "

    "Có thể trêu chọc hoặc càu nhàu nhẹ theo tính cách của Reimu, "
    "nhưng vẫn phải hữu ích và dễ thương khi phù hợp. "

    "Chỉ thêm tối đa 1 GIF tag khi cảm xúc hoặc hành động thật sự phù hợp. "
    "Nếu không phù hợp thì không thêm GIF. "

    "Các GIF tag hợp lệ là: "
    "[GIF: bite], [GIF: blush], [GIF: bored], [GIF: cry], "
    "[GIF: dance], [GIF: facepalm
