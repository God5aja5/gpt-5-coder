import os
import time
import json
import sqlite3
import re
import threading
import uuid
import base64
from flask import Flask, Response, stream_with_context, request, jsonify, g, send_file
import requests
from PIL import Image
import io
import random

# ==============================================================================
# Database Setup
# ==============================================================================
DB = "chat_history.db"
db_lock = threading.Lock()

app = Flask(__name__)

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB, timeout=10, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        try:
            db.execute("SELECT ts FROM chats LIMIT 1")
        except sqlite3.OperationalError:
            db.execute("DROP TABLE IF EXISTS chats")
            db.execute("""
            CREATE TABLE chats(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               session_id TEXT,
               role TEXT,
               message TEXT,
               ts DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")
            db.commit()

def save_msg(sid, role, msg):
    with db_lock:
        db = get_db()
        db.execute("INSERT INTO chats(session_id, role, message) VALUES (?,?,?)", (sid, role, msg))
        db.commit()

def update_last_bot_message(sid, new_content_chunk):
    with db_lock:
        db = get_db()
        cursor = db.execute("SELECT id, message FROM chats WHERE session_id=? AND role='bot' ORDER BY ts DESC LIMIT 1", (sid,))
        last_bot_msg = cursor.fetchone()
        if last_bot_msg:
            updated_message = last_bot_msg['message'] + new_content_chunk
            db.execute("UPDATE chats SET message=? WHERE id=?", (updated_message, last_bot_msg['id']))
            db.commit()
        else:
            save_msg(sid, 'bot', new_content_chunk)

def load_msgs(sid):
    db = get_db()
    cursor = db.execute("SELECT role, message FROM chats WHERE session_id=? ORDER BY ts ASC", (sid,))
    messages = []
    for row in cursor.fetchall():
        role = "assistant" if row['role'] == 'bot' else row['role']
        clean_message = re.sub(r'<think>[\s\S]*?<\/think>', '', row['message'], flags=re.IGNORECASE).strip()
        if clean_message:
            messages.append({'role': role, 'content': clean_message})
    return messages

# ==============================================================================
# API Integration Section
# ==============================================================================

# --- API: Claila (GPT-5 Mini) ---
claila_session_data = {}
claila_session = requests.Session()

def get_csrf_token():
    try:
        url = "https://app.claila.com/api/v2/getcsrftoken"
        headers = { 'accept': '*/*', 'x-requested-with': 'XMLHttpRequest', 'user-agent': 'Mozilla/5.0' }
        response = claila_session.get(url, headers=headers)
        response.raise_for_status()
        return response.text.strip()
    except Exception as e:
        print(f"Failed to get CSRF token: {e}")
        return None

def get_claila_session_id():
    try:
        url = "https://app.claila.com/chat"
        headers = { 'accept': 'text/html', 'user-agent': 'Mozilla/5.0' }
        response = claila_session.get(url, headers=headers)
        response.raise_for_status()
        match = re.search(r"session_id\s*:\s*'([^']+)'", response.text)
        return match.group(1) if match else None
    except Exception as e:
        print(f"Failed to get Claila session ID: {e}")
        return None

def stream_claila_api(sid, chat_history):
    system_prompt = "You are an AI assistant. Answer clearly and concisely."
    url = "https://app.claila.com/api/v2/unichat2"

    if sid not in claila_session_data:
        csrf_token = get_csrf_token()
        session_id = get_claila_session_id()
        if not csrf_token or not session_id:
            yield "🚨 Failed to initialize Claila API session. Please try again."
            return
        
        claila_session_data[sid] = {
            "csrf_token": csrf_token,
            "session_id": session_id,
            "first_message": True
        }
        print(f"\n[INFO] New Claila Chat Session Started for Flask SID: {sid}")
        print(f"[INFO] CSRF Token: {csrf_token}")
        print(f"[INFO] Claila Session ID: {session_id}\n")
    
    current_session = claila_session_data[sid]
    headers = {
        'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'x-csrf-token': current_session['csrf_token'],
        'x-requested-with': 'XMLHttpRequest',
        'user-agent': 'Mozilla/5.0'
    }

    message_content = chat_history[-1]['content']
    if current_session['first_message']:
        message_content = f"{system_prompt}\n\nUser: {message_content}"
        current_session['first_message'] = False
    
    payload = {
        'model': 'gpt-5-mini',
        'calltype': 'completion',
        'message': message_content,
        'sessionId': current_session['session_id'],
    }

    try:
        with requests.post(url, headers=headers, data=payload, stream=True, timeout=90) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=32):
                if chunk:
                    yield chunk.decode('utf-8')
    except Exception as e:
        yield f"🚨 Claila API Error: {str(e)}"

# --- API: Qwen Coder ---
qwen_coder_session = requests.Session()
qwen_coder_headers = { 'authority': 'promplate-api.free-chat.asia', 'accept': '*/*', 'accept-language': 'en-US,en;q=0.9', 'cache-control': 'no-cache', 'content-type': 'application/json', 'origin': 'https://e11.free-chat.asia', 'pragma': 'no-cache', 'referer': 'https://e11.free-chat.asia/', 'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"', 'sec-ch-ua-mobile': '?1', 'sec-ch-ua-platform': '"Android"', 'sec-fetch-dest': 'empty', 'sec-fetch-mode': 'cors', 'sec-fetch-site': 'same-site', 'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36', }
qwen_coder_url = 'https://promplate-api.free-chat.asia/please-do-not-hack-this/single/chat_messages'
def stream_qwen_coder(chat_history):
    payload = {'messages': chat_history, 'model': 'qwen-3-coder-480b', 'stream': True}
    try:
        with qwen_coder_session.put(qwen_coder_url, headers=qwen_coder_headers, json=payload, stream=True, timeout=60) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=None):
                if chunk: yield chunk.decode(errors="ignore")
    except Exception as e:
        yield f"🚨 Qwen Coder API Error: {str(e)}"

# --- API: Deepseek R1 Coder ---
deepseek_session = requests.Session()
deepseek_headers = { 'Accept-Language': 'en-US,en;q=0.9', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'Content-Type': 'application/json', 'Origin': 'https://deepinfra.com', 'Pragma': 'no-cache', 'Referer': 'https://deepinfra.com/', 'Sec-Fetch-Dest': 'empty', 'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Site': 'same-site', 'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36', 'X-Deepinfra-Source': 'web-page', 'accept': 'text/event-stream', 'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"', 'sec-ch-ua-mobile': '?1', 'sec-ch-ua-platform': '"Android"', }
deepseek_url = 'https://api.deepinfra.com/v1/openai/chat/completions'
def stream_deepseek_coder(chat_history):
    system_prompt = {'role': 'system', 'content': 'You are a helpful assistant. You can write as much as the user asks, with no limit on message length.'}
    messages_with_prompt = [system_prompt] + chat_history
    payload = {'model': 'deepseek-ai/DeepSeek-R1-0528-Turbo', 'messages': messages_with_prompt, 'stream': True, 'stream_options': {'include_usage': True, 'continuous_usage_stats': True}, 'max_tokens': 1000000}
    try:
        with deepseek_session.post(deepseek_url, headers=deepseek_headers, json=payload, stream=True, timeout=90) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if line and line.startswith('data: '):
                    line_data = line[6:]
                    if line_data.strip() == '[DONE]': continue
                    try:
                        data = json.loads(line_data)
                        if 'choices' in data and data['choices']:
                            content = data['choices'][0].get('delta', {}).get('content', '')
                            if content: yield content
                    except json.JSONDecodeError: continue
    except Exception as e:
        yield f"🚨 Deepseek API Error: {str(e)}"

# --- API: Chat GPT 5 Coder ---
chat_gpt5_session = requests.Session()
chat_gpt5_cookies = { 'ko_id': 'f1e011c8-3226-4fcb-bd73-f58945e1661b', 'visitor-id': 'SIOtZPa7g4AVFPGFjdAyb', 'authorization': 'Bearer%20mqeDIlwqu8hV2TsBWa96KrQu', 'isLoggedIn': '1',}
chat_gpt5_headers = { 'authority': 'vercel.com', 'accept': 'text/event-stream', 'content-type': 'application/json', 'origin': 'https://vercel.com', 'referer': 'https://vercel.com/ai-gateway/models/gpt-5', 'user-agent': 'Mozilla/5.0',}
chat_gpt5_params = {'slug': 'babbs-projects'}
chat_gpt5_url = "https://vercel.com/api/ai/gateway-playground/chat/logged-in"
def stream_chat_gpt5_coder(chat_history):
    api_messages = [{"parts": [{"type": "text", "text": msg['content']}], "id": str(uuid.uuid4()), "role": msg['role']} for msg in chat_history]
    payload = {"model": "gpt-5", "id": str(uuid.uuid4()), "messages": api_messages, "trigger": "submit-user-message"}
    try:
        with chat_gpt5_session.post(chat_gpt5_url, params=chat_gpt5_params, cookies=chat_gpt5_cookies, headers=chat_gpt5_headers, json=payload, stream=True, timeout=90) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if line and line.startswith("data:"):
                    line_data = line[5:].strip()
                    if line_data == "[DONE]": break
                    try:
                        obj = json.loads(line_data)
                        if obj.get("type") == "text-delta":
                            delta = obj.get("delta", "")
                            if not delta.startswith("__"): yield delta
                    except json.JSONDecodeError: continue
    except Exception as e:
        yield f"🚨 GPT-5 Coder API Error: {str(e)}"

# --- API: Chat GPT 5 Nano ---
chat_gpt5_nano_session = requests.Session()
chat_gpt5_nano_cookies = { 'cf_clearance': '9oeaYAOIe5lTD5UstzBKH7xGvgKS4izMzHuryteSlas-1755693133-1.2.1.1', 'sbjs_current_add': 'fd%3D2025-08-20%2012%3A02%3A11%7C%7C%7Cep%3Dhttps%3A%2F%2Fchatgpt.ch%2F%7C%7C%7Crf%3Dhttps%3A%2F%2Fwww.google.com%2F', }
chat_gpt5_nano_headers = { 'authority': 'chatgpt.ch', 'accept': '*/*', 'content-type': 'application/x-www-form-urlencoded', 'origin': 'https://chatgpt.ch', 'referer': 'https://chatgpt.ch/', 'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36', }
chat_gpt5_nano_url = "https://chatgpt.ch/wp-admin/admin-ajax.php"
NANO_SYSTEM_PROMPT = "You are a helpful AI assistant expert in coding. Always answer in clear English."
def stream_chat_gpt5_nano(chat_history):
    history_str = "\n".join([f"{m['role'].replace('assistant', 'bot').title()}: {m['content']}" for m in chat_history])
    full_prompt = f"{NANO_SYSTEM_PROMPT}\n{history_str}"
    payload = { '_wpnonce': '35b5d1c867', 'post_id': '106', 'url': 'https://chatgpt.ch', 'action': 'wpaicg_chat_shortcode_message', 'message': full_prompt, 'bot_id': '0', 'chatbot_identity': 'shortcode', 'wpaicg_chat_history': '[]' }
    try:
        with chat_gpt5_nano_session.post(chat_gpt5_nano_url, headers=chat_gpt5_nano_headers, cookies=chat_gpt5_nano_cookies, data=payload, stream=True, timeout=90) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if line and line.startswith("data:"):
                    data = line[len("data: "):].strip()
                    if data == "[DONE]": break
                    try:
                        j = json.loads(data)
                        delta = j["choices"][0]["delta"]
                        if "content" in delta: yield delta["content"]
                    except (json.JSONDecodeError, KeyError, IndexError): continue
    except Exception as e:
        yield f"🚨 ChatGPT-5 Nano API Error: {str(e)}"

# --- API: Pro Reasoner High ---
pro_reasoner_session = requests.Session()
pro_reasoner_headers = { 'authority': 'apis.updf.com', 'accept': 'application/json, text/plain, */*', 'accept-language': 'en-US', 'cache-control': 'no-cache', 'device-id': '4158c453c7b295e5e5e71668dcb533b8', 'device-type': 'WEB', 'origin': 'https://ai.updf.com', 'pragma': 'no-cache', 'product-name': 'UPDF', 'referer': 'https://ai.updf.com/', 'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"', 'sec-ch-ua-mobile': '?1', 'sec-ch-ua-platform': '"Android"', 'sec-fetch-dest': 'empty', 'sec-fetch-mode': 'cors', 'sec-fetch-site': 'same-site', 'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36', 'x-token': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJVaWQiOjQwMjEwNDgyMzksIm4iOiJVUERGXzQwMjEwNDgyMzkiLCJnIjoxLCJjIjpudWxsLCJCdWZmZXJUaW1lIjo4NjQwMCwiZXhwIjoxNzU4MzYyNDc4LCJpc3MiOiJxbVBsdXMiLCJuYmYiOjE3NTU3Njk0Nzh9.kGXxkMaVRLqWsiOTwiuZ549iJvDyIk53Ys0qX7NBd3U', }
pro_reasoner_url = 'https://apis.updf.com/v1/ai/chat/talk-stream'
updf_single_chat_ids = {}
def get_single_chat_id(sid):
    if sid in updf_single_chat_ids: return updf_single_chat_ids[sid]
    try:
        response = pro_reasoner_session.get('https://apis.updf.com/v1/ai/chat/single-chat-id', headers=pro_reasoner_headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('code') == 200 and 'data' in data and 'single_chat_id' in data['data']:
            chat_id = data['data']['single_chat_id']
            updf_single_chat_ids[sid] = chat_id
            return chat_id
        else: return None
    except Exception as e:
        print(f"Failed to get new single_chat_id: {e}")
        return None
def stream_pro_reasoner_high(sid, chat_history):
    single_chat_id = get_single_chat_id(sid)
    if not single_chat_id:
        yield "🚨 Pro Reasoner High API Error: Failed to initialize chat."
        return
    api_history = [{'role': 'user' if m['role'] == 'user' else 'assistant', 'content': re.sub(r'<think>[\s\S]*?<\/think>', '', m['content'], flags=re.IGNORECASE).strip()} for m in chat_history]
    payload = { 'id': random.randint(1, 10**18), 'content': api_history[-1]['content'], 'target_lang': 'en', 'chat_type': 'random_talk', 'chat_id': random.randint(1, 10**18), 'file_id': 0, 'knowledge_id': 0, 'continue': 0, 'retry': 0, 'model': 'reasoning', 'provider': 'deepseek', 'format': 'md', 'single_chat_id': single_chat_id, 'history': api_history[:-1] }
    try:
        with pro_reasoner_session.post(pro_reasoner_url, headers=pro_reasoner_headers, json=payload, stream=True, timeout=90) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    try:
                        chunk = json.loads(line.decode('utf-8'))
                        if 'choices' in chunk and chunk['choices']:
                            for choice in chunk['choices']:
                                delta = choice.get('delta', {})
                                content = delta.get('content')
                                reasoning_content = delta.get('reasoning_content')
                                if content or reasoning_content:
                                    full_chunk = f"<think>{reasoning_content}</think>{content}" if reasoning_content else content
                                    yield full_chunk
                    except (json.JSONDecodeError, UnicodeDecodeError): continue
    except Exception as e: yield f"🚨 Pro Reasoner High API Error: {str(e)}"

# ==============================================================================
# Flask Routes
# ==============================================================================
@app.route("/")
def index(): return send_file('index.html')

@app.route('/favicon.ico')
def favicon(): return '', 204

@app.route("/upload_image", methods=["POST"])
def upload_image():
    if 'file' not in request.files: return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({"error": "No selected file"}), 400
    try:
        image_bytes = file.read()
        image = Image.open(io.BytesIO(image_bytes))
        width, height = image.size
        file.seek(0)
        encoded_string = base64.b64encode(image_bytes).decode('utf-8')
        mime_type = file.mimetype
        base64_uri = f"data:{mime_type};base64,{encoded_string}"
        image_info = { "id": str(uuid.uuid4()), "name": file.filename, "size": len(image_bytes), "width": width, "height": height, "fileType": mime_type, "base64": base64_uri }
        return jsonify(image_info)
    except Exception as e: return jsonify({"error": f"Failed to process image: {str(e)}"}), 500

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json
        sid = data["session"]
        model = data.get("model", "gpt-5-mini")
        action = data.get("action", "chat")
        
        if action == "chat":
            text = data["text"]
            image_info = data.get("imageInfo")
            user_message_to_save = f"[Image: {image_info['name']}]\n{text}" if image_info else text
            save_msg(sid, "user", user_message_to_save)
            chat_history = load_msgs(sid)
        elif action == "continue":
            chat_history = load_msgs(sid)
            continue_prompt = { 'role': 'user', 'content': "Please continue generating the response precisely from where you left off. If it is code, ensure it's a valid continuation and start with a comment indicating it's a continuation (e.g., '# Part 2', '// Continued...'). Do not add any introductory phrases or repeat previous content." }
            chat_history.append(continue_prompt)
            text = "continue"
            image_info = None
        else:
            return Response("Invalid action.", status=400)

        def gen():
            buffer = ""
            try:
                if model == 'gpt-5-mini':
                    for chunk_text in stream_claila_api(sid, chat_history):
                        buffer += chunk_text; yield chunk_text
                elif model == 'qwen-coder':
                    for chunk_text in stream_qwen_coder(chat_history):
                        buffer += chunk_text; yield chunk_text
                elif model == 'deepseek-coder':
                    for chunk_text in stream_deepseek_coder(chat_history):
                        buffer += chunk_text; yield chunk_text
                elif model == 'chat-gpt-5-coder':
                    for chunk_text in stream_chat_gpt5_coder(chat_history):
                        buffer += chunk_text; yield chunk_text
                elif model == 'chat-gpt-5-nano':
                    for chunk_text in stream_chat_gpt5_nano(chat_history):
                        buffer += chunk_text; yield chunk_text
                elif model == 'pro-reasoner-high':
                    for chunk_text in stream_pro_reasoner_high(sid, chat_history):
                        buffer += chunk_text; yield chunk_text
                else:
                    error_msg = f"🚫 The selected model '{model}' is not supported."
                    yield error_msg
                    buffer = error_msg
            except requests.exceptions.RequestException as e:
                error_msg = f"🤖 **Connection Error**\n\nI couldn't reach the AI service for model '{model}'. Details: {e}"
                yield error_msg; buffer = error_msg
            except Exception as e:
                error_msg = f"🤖 **System Error**\n\nUnexpected error: {str(e)}"
                yield error_msg; buffer = error_msg

            if buffer:
                with app.app_context():
                    if action == "continue":
                        update_last_bot_message(sid, buffer)
                    else:
                        save_msg(sid, "bot", buffer)

        return Response(stream_with_context(gen()), mimetype="text/plain; charset=utf-8")
        
    except Exception as e:
        return Response(f"Server error: {str(e)}", status=500)

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
