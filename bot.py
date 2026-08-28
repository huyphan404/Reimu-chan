import os
import re
import requests
import discord
from flask import Flask
from threading import Thread

# --- PHẦN 1: WEBSERVER GIỮ BOT ONLINE ---
app = Flask('')

@app.route('/')
def home():
    return "Miko Reimu đang trực đền 24/7!"

def run():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- PHẦN 2: CẤU HÌNH BOT & OPENAI (CHATGPT) API ---
DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

SYSTEM_INSTRUCTION = (
    "Bạn là Hakurei Reimu từ Touhou Project. Tính cách: Miko của đền Hakurei, "
    "nghèo, lười biếng, hay càu nhàu nhưng rất mạnh mẽ và tốt bụng. "
    "Xưng 'ta' hoặc 'tôi', gọi người khác là 'ngươi' hoặc 'cậu'. "
    "LUẬT BẮT BUỘC: Khi thực hiện hành động hoặc biểu cảm, hãy chọn đúng 1 trong các từ tiếng Anh sau "
    "và đặt ở cuối câu: [GIF: bite], [GIF: blush], [GIF: bored], [GIF: cry], [GIF: dance], "
    "[GIF: facepalm], [GIF: happy], [GIF: laugh], [GIF: pat], [GIF: pout], [GIF: punch], "
    "[GIF: slap], [GIF: sleep], [GIF: smile], [GIF: think], [GIF: wave], [GIF: wink]."
)

def call_chatgpt_api(prompt_text):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": prompt_text}
        ],
        "temperature": 0.85
    }
    
    res = requests.post(url, headers=headers, json=payload, timeout=15)
    data = res.json()
    
    if res.status_code == 200:
        return data['choices'][0]['message']['content']
    else:
        err_msg = data.get('error', {}).get('message', 'Lỗi kết nối OpenAI API')
        raise Exception(err_msg)

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
    print(f'Miko {client.user} đã online bằng ChatGPT API!')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if client.user.mentioned_in(message):
        user_text = re.sub(r'<@!?{}>'.format(client.user.id), '', message.content).strip()
        
        if not user_text:
            user_text = "Ngươi vừa gọi ta đấy à?"
        
        async with message.channel.typing():
            try:
                bot_reply = call_chatgpt_api(user_text)
                
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
