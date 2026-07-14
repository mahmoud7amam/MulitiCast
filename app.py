import asyncio
import threading
import json
import os
from flask import Flask, render_template, request, jsonify
import discord

app = Flask(__name__)

CONFIG_FILE = "bots_config.json"
# قاموس لتخزين كائنات البوتات النشطة لسهولة التحكم بها {token: client_object}
active_bots = {}
# قاموس لتخزين حالة كل بوت لعرضها في الـ Dashboard
bots_status = {}

# تحميل التوكنات المحفوظة عند بدء التشغيل
def load_tokens():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

# حفظ التوكنات
def save_token(token):
    tokens = load_tokens()
    if token not in tokens:
        tokens.append(token)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(tokens, f, indent=4)
        return True
    return False

# كلاس مخصص لكل بوت ديسكورد لإدارة اتصاله وعملية النشر المخصصة له
class BroadcastBot(discord.Client):
    def __init__(self, token):
        intents = discord.Intents.default()
        intents.members = True
        intents.presences = True  # مهمة جداً لمعرفة حالة اتصال الأعضاء (أونلاين/أوفلاين)
        super().__init__(intents=intents)
        self.token = token
        bots_status[token] = "جاري الاتصال..."

    async def on_ready(self):
        bots_status[self.token] = "متصل 🟢"
        active_bots[self.token] = self
        print(f"🚀 البوت {self.user.name} جاهز للعمل وتحت السيطرة!")

    async def run_broadcast(self, message, online_only=False):
        """دالة النشر مع المنشن التلقائي والتأخير لتجنب الـ Rate Limit"""
        bots_status[self.token] = "جاري النشر... 🔄"
        success = 0
        failed = 0
        
        for guild in self.guilds:
            # جلب قائمة الأعضاء بالكامل من السيرفر
            async for member in guild.fetch_members(limit=None):
                if member.bot:
                    continue
                
                # فلترة الحالات لو المطلوب أونلاين فقط (+obc)
                if online_only and member.status == discord.Status.offline:
                    continue
                
                try:
                    # إضافة منشن العضو في أول الرسالة
                    mention_text = f"<@{member.id}> {message}"
                    await member.send(mention_text)
                    success += 1
                    await asyncio.sleep(1.5)  # تأخير آمن لتجنب الباند
                except discord.Forbidden:
                    failed += 1
                except Exception:
                    failed += 1
        
        bots_status[self.token] = f"مكتمل (نجح: {success} | فشل: {failed}) ✅"

# دالة لتشغيل البوت في Thread منفصل حتى لا يتعطل سيرفر الويب
def start_bot_thread(token):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = BroadcastBot(token)
    try:
        loop.run_until_complete(bot.start(token))
    except Exception as e:
        bots_status[token] = "خطأ في التوكن ❌"
        print(f"خطأ في البوت {token[:10]}...: {e}")

# عند تشغيل السكربت، نقوم بمحاولة تشغيل كافة البوتات المحفوظة تلقائياً
def init_all_saved_bots():
    tokens = load_tokens()
    for token in tokens:
        t = threading.Thread(target=start_bot_thread, args=(token,))
        t.daemon = True
        t.start()

# --- مسارات الـ API ولوحة التحكم (Flask Routes) ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/bots', methods=['GET'])
def get_bots():
    """أمر +bots: لعرض التوكنات وحالة تشغيل كل بوت"""
    tokens = load_tokens()
    result = []
    for token in tokens:
        status = bots_status.get(token, "غير متصل 🔴")
        # نخفي جزء من التوكن للأمان عند العرض
        masked_token = token[:15] + "..." + token[-10:] if len(token) > 25 else token
        result.append({
            "token": token,
            "masked_token": masked_token,
            "status": status
        })
    return jsonify(result)

@app.route('/api/add-bot', methods=['POST'])
def add_bot():
    """أمر +addb: لإضافة بوت جديد وتشغيله فوراً"""
    data = request.json
    token = data.get('token', '').strip()
    if not token:
        return jsonify({"status": "error", "message": "التوكن فارغ!"}), 400
    
    if save_token(token):
        # تشغيل البوت فوراً في الخلفية
        t = threading.Thread(target=start_bot_thread, args=(token,))
        t.daemon = True
        t.start()
        return jsonify({"status": "success", "message": "تم حفظ البوت وجاري تشغيله..."})
    else:
        return jsonify({"status": "error", "message": "التوكن مضاف بالفعل مسبقاً!"})

@app.route('/api/broadcast', methods=['POST'])
def execute_broadcast():
    """أمر +bc و +obc للتحكم بعدد محدد من البوتات وإرسال الرسائل"""
    data = request.json
    message = data.get('message', '')
    bot_count = int(data.get('bot_count', 1))
    online_only = data.get('online_only', False) # True لـ +obc و False لـ +bc

    if not message:
        return jsonify({"status": "error", "message": "الرسالة فارغة!"}), 400

    # تصفية البوتات المتصلة حالياً والجاهزة للعمل فقط
    ready_bots = [bot for token, bot in active_bots.items() if bots_status.get(token) == "متصل 🟢"]
    
    if not ready_bots:
        return jsonify({"status": "error", "message": "لا يوجد أي بوت جاهز ومتصل حالياً!"}), 400

    # تحديد البوتات اللي هنستخدمها بناءً على العدد المطلوب
    selected_bots = ready_bots[:bot_count]
    
    # تشغيل مهام الإرسال بالتوازي لكل بوت متاح دون تعطيل الـ Flask
    for bot in selected_bots:
        loop = bot.loop
        asyncio.run_coroutine_threadsafe(bot.run_broadcast(message, online_only), loop)

    return jsonify({
        "status": "success", 
        "message": f"تم توجيه الأوامر لـ ({len(selected_bots)}) بوت لبدء الحملة بنجاح!"
    })

if __name__ == '__main__':
    # تشغيل البوتات المحفوظة مسبقاً في الخلفية
    init_all_saved_bots()
    # تشغيل تطبيق الويب على الموبايل بورت 5000
    app.run(debug=False, port=5000, host='0.0.0.0')
