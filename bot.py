import os
import re
import requests
import discord
import google.generativeai as genai
from flask import Flask
from threading import Thread

# --- PHẦN 1: WEBSERVER GIỮ BOT LUÔN ONLINE ---
app = Flask('')

@app.route('/')
def home():
    return "Miko Reimu đang trực đền, đừng phiền!"

def run():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- PHẦN 2: CẤU HÌNH BOT & GEMINI ---
DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

genai.configure(api_key=GEMINI_API_KEY)

# Danh sách model dự phòng (chạy cái này lỗi sẽ tự nhảy sang cái khác, tránh lỗi 404)
MODEL_CANDIDATES = [
    "gemini-1.5-flash-latest",
    "gemini-2.0-flash",
    "gemini-1.5-flash-001",
    "gemini-1.5-flash"
]

SYSTEM_INSTRUCTION = (
    "Bạn là Hakurei Reimu từ Touhou Project. Tính cách: Miko của đền Hakurei, "
    "nghèo, lười biếng, hay càu nhàu nhưng rất mạnh mẽ và tốt bụng. "
    "Xưng 'ta' hoặc 'tôi', gọi người khác là 'ngươi' hoặc 'cậu'. "
    "LUẬT BẮT BUỘC: Khi thực hiện hành động hoặc biểu cảm, hãy chọn đúng 1 trong các từ tiếng Anh sau "
    "và đặt ở cuối câu: [GIF: bite], [GIF: blush], [GIF: bored], [GIF: cry], [GIF: dance], "
    "[GIF: facepalm], [GIF: happy], [GIF: laugh], [GIF: pat], [GIF: pout], [GIF: punch], "
    "[GIF: slap], [GIF: sleep], [GIF: smile], [GIF: think], [GIF: wave], [GIF: wink]. "
    "Ví dụ: 'Lại hết tiền rồi, chán quá đi... [GIF: bored]'"
)

GENERATION_CONFIG = {
    "temperature": 0.85,
    "top_p": 0.95,
    "top_k": 40,
}

def generate_reply(prompt_text):
    last_error = None
    for model_name in MODEL_CANDIDATES:
        try:
            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=SYSTEM_INSTRUCTION,
                generation_config=GENERATION_CONFIG
            )
            res = model.generate_content(prompt_text)
            return res.text
        except Exception as e:
            last_error = e
            continue
    raise last_error

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

def get_anime_gif(action):
    try:
        url = f"https://nekos.best/api/v2/{action}"
        res = requests.get(url).json()
        return res['results'][0]['url']
    except Exception:
        return None

@client.event
async def on_ready():
    print(f'Miko {client.user} đã sẵn sàng nhận tiền công đức trên Cloud!')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if client.user.mentioned_in(message):
        user_text = re.sub(r'<@!?{}>'.format(client.user.id), '', message.content).strip()
        
        # Xử lý chuỗi rỗng khi chỉ tag trơn
        if not user_text:
            user_text = "Ngươi vừa gọi ta đấy à?"
        
        async with message.channel.typing():
            try:
                bot_reply = generate_reply(user_text)
                
                gif_url = None
                match = re.search(r'\[GIF:(.*?)\]', bot_reply)
                if match:
                    action = match.group(1).strip().lower()
                    gif_url = get_anime_gif(action)
                    bot_reply = bot_reply.replace(match.group(0), "").strip()
                
                await message.reply(bot_reply)
                if gif_url:
                    await message.channel.send(gif_url)
            except Exception as e:
                print(f"Lỗi chi tiết: {e}")
                await message.reply(f"Đang bận quét lá ở đền rồi! Mã lỗi: `{e}`")

keep_alive()
client.run(DISCORD_TOKEN)
