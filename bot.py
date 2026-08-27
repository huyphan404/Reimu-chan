import discord
import google.generativeai as genai
import requests
import re
import os
from flask import Flask
from threading import Thread

# --- PHẦN 1: TẠO WEB SERVER ẢO ĐỂ GIỮ BOT LUÔN THỨC ---
app = Flask('')

@app.route('/')
def home():
    return "Miko Reimu đang trực đền, đừng phiền!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- PHẦN 2: CẤU HÌNH BOT NHƯ CŨ ---
DISCORD_TOKEN = 'YOUR_DISCORD_TOKEN'
GEMINI_API_KEY = 'YOUR_GEMINI_API_KEY'

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    system_instruction=(
        "Bạn là Hakurei Reimu từ Touhou Project. Tính cách: Miko của đền Hakurei, "
        "nghèo, lười biếng, hay càu nhàu nhưng rất mạnh mẽ và tốt bụng. "
        "Xưng 'ta' hoặc 'tôi', gọi người khác là 'ngươi' hoặc 'cậu'. "
        "LUẬT BẮT BUỘC: Khi thực hiện hành động hoặc biểu cảm, hãy chọn đúng 1 trong các từ tiếng Anh sau "
        "và đặt ở cuối câu: [GIF: bite], [GIF: blush], [GIF: bored], [GIF: cry], [GIF: dance], "
        "[GIF: facepalm], [GIF: happy], [GIF: laugh], [GIF: pat], [GIF: pout], [GIF: punch], "
        "[GIF: slap], [GIF: sleep], [GIF: smile], [GIF: think], [GIF: wave], [GIF: wink]. "
        "Ví dụ: 'Lại hết tiền rồi, chán quá đi... [GIF: bored]'"
    )
)
chat_session = model.start_chat(history=[])

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
        user_text = message.content.replace(f'<@{client.user.id}>', '').strip()
        
        async with message.channel.typing():
            try:
                bot_reply = chat_session.send_message(user_text).text
                
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
                await message.reply("Đang bận quét lá ở đền rồi! (Lỗi hệ thống)")
                print(e)

# Chạy web server ngầm rồi bật bot Discord
keep_alive()
client.run(DISCORD_TOKEN)