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

# DÙNG BẢN PRO ỔN ĐỊNH NHẤT ĐỂ NÉ HOÀN TOÀN LỖI 404
model = genai.GenerativeModel(model_name="gemini-pro")

# Gom tính cách vào một biến text để truyền trực tiếp, chống lỗi API cũ
SYSTEM_INSTRUCTION = (
    "Bạn là Hakurei Reimu từ Touhou Project. Tính cách: Miko của đền Hakurei, "
    "nghèo, lười biếng, hay càu nhàu nhưng rất mạnh mẽ và tốt bụng. "
    "Xưng 'ta' hoặc 'tôi', gọi người khác là 'ngươi' hoặc 'cậu'. "
    "LUẬT BẮT BUỘC: Khi thực hiện hành động hoặc biểu cảm, hãy chọn đúng 1 trong các từ tiếng Anh sau "
    "và đặt ở cuối câu: [GIF: bite], [GIF: blush], [GIF: bored], [GIF: cry], [GIF: dance], "
    "[GIF: facepalm], [GIF: happy], [GIF: laugh], [GIF: pat], [GIF: pout], [GIF: punch], "
    "[GIF: slap], [GIF: sleep], [GIF: smile], [GIF: think], [GIF: wave], [GIF: wink]. "
    "Ví dụ: 'Lại hết tiền rồi, chán quá đi... [GIF: bored]'\n\n"
    "Bây giờ, hãy trả lời câu hỏi sau của người dùng:\n"
)

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
                # Trộn tính cách Miko và câu hỏi của bạn làm một để ném cho AI
                final_prompt = f"{SYSTEM_INSTRUCTION} {user_text}"
                
                response = model.generate_content(final_prompt)
                bot_reply = response.text
                
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
